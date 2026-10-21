"""Linux BlueZ GATT peripheral. Optional dependency: dbus-next==0.2.3."""
import asyncio
import contextlib
import json
import time

from dbus_next import Variant, DBusError, BusType
from dbus_next.aio import MessageBus
from dbus_next.constants import PropertyAccess
from dbus_next.service import ServiceInterface, method, dbus_property

from .protocol import StreamDecoder, encode, event

ROOT = '/vn/vietnav/hud'
SERVICE = ROOT + '/service0'
ADVERTISEMENT = '/vn/vietnav/advertisement0'
GATT = 'org.bluez.GattCharacteristic1'


def uuid(short):
    return f'0000{short}-0000-1000-8000-00805f9b34fb'


class Application(ServiceInterface):
    def __init__(self, objects):
        super().__init__('org.freedesktop.DBus.ObjectManager')
        self.objects = objects

    @method()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        return {path: {obj.name: obj.properties()} for path, obj in self.objects}


class Service(ServiceInterface):
    def __init__(self):
        super().__init__('org.bluez.GattService1')

    def properties(self):
        return {'UUID': Variant('s', self.UUID), 'Primary': Variant('b', True),
                'Includes': Variant('ao', [])}

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's':
        return uuid('fff0')

    @dbus_property(access=PropertyAccess.READ)
    def Primary(self) -> 'b':
        return True

    @dbus_property(access=PropertyAccess.READ)
    def Includes(self) -> 'ao':
        return []


class Characteristic(ServiceInterface):
    def __init__(self, short, flags, receiver=None):
        super().__init__(GATT)
        self.short, self.flags, self.receiver = short, flags, receiver
        self.value = b''
        self.notifying = False

    def properties(self):
        return {'UUID': Variant('s', self.UUID), 'Service': Variant('o', SERVICE),
                'Flags': Variant('as', self.flags), 'Value': Variant('ay', self.value),
                'Notifying': Variant('b', self.notifying)}

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's':
        return uuid(self.short)

    @dbus_property(access=PropertyAccess.READ)
    def Service(self) -> 'o':
        return SERVICE

    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> 'as':
        return self.flags

    @dbus_property(access=PropertyAccess.READ)
    def Value(self) -> 'ay':
        return self.value

    @dbus_property(access=PropertyAccess.READ)
    def Notifying(self) -> 'b':
        return self.notifying

    @method()
    def ReadValue(self, options: 'a{sv}') -> 'ay':
        if 'read' not in self.flags:
            raise DBusError('org.bluez.Error.NotPermitted', 'not readable')
        offset = options.get('offset', Variant('q', 0)).value
        if offset > len(self.value):
            raise DBusError('org.bluez.Error.InvalidOffset', 'offset outside value')
        return self.value[offset:]

    @method()
    def WriteValue(self, value: 'ay', options: 'a{sv}'):
        if self.receiver is None:
            raise DBusError('org.bluez.Error.NotPermitted', 'not writable')
        if options.get('offset', Variant('q', 0)).value != 0:
            raise DBusError('org.bluez.Error.NotSupported', 'prepared writes unsupported')
        if options.get('prepare-authorize', Variant('b', False)).value:
            raise DBusError('org.bluez.Error.NotSupported', 'prepared writes unsupported')
        self.receiver(bytes(value), options)

    @method()
    def StartNotify(self):
        if 'notify' not in self.flags:
            raise DBusError('org.bluez.Error.NotSupported', 'notifications unsupported')
        self.notifying = True
        self.emit_properties_changed({'Notifying': True})

    @method()
    def StopNotify(self):
        self.notifying = False
        self.emit_properties_changed({'Notifying': False})


class Advertisement(ServiceInterface):
    def __init__(self, name):
        super().__init__('org.bluez.LEAdvertisement1')
        self.local_name = name

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> 's':
        return 'peripheral'

    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> 'as':
        return [uuid('fff0')]

    @dbus_property(access=PropertyAccess.READ)
    def LocalName(self) -> 's':
        return self.local_name

    @method()
    def Release(self):
        pass


class Session:
    """One phone at a time; capture writes even before a handshake succeeds."""
    def __init__(self, output, info_text):
        self.output, self.info_text = output, info_text
        self.device = None
        self.generation = 0
        self.streams = {}
        self.replies = asyncio.Queue(maxsize=16)

    def log(self, item):
        print(json.dumps(dict(received_at=time.time(), **item), ensure_ascii=False),
              file=self.output, flush=True)

    def receive(self, data, options):
        device = options.get('device', Variant('o', '/')).value
        if self.device is not None and device != self.device:
            raise DBusError('org.bluez.Error.NotPermitted', 'one phone per session')
        self.device = device
        # FFF2 and FFF3 carry the same byte stream, but never mix two phones.
        stream = self.streams.setdefault(device, StreamDecoder())
        self.log(dict(type='ble_write', device=device, data_hex=data.hex()))
        errors = stream.errors
        for frame in stream.feed(data):
            try:
                item = event(frame)
            except ValueError as exc:
                self.log(dict(type='payload_error', error=str(exc), command=frame.command,
                              payload_hex=frame.payload.hex()))
                continue
            self.log(item)
            if item['type'] == 'hud_info_request' and self.info_text is not None:
                reply = encode(14, self.info_text.encode('utf-8'), timestamp=int(time.time()))
                try:
                    self.replies.put_nowait((device, self.generation, reply))
                except asyncio.QueueFull:
                    self.log(dict(type='reply_dropped', reason='notification queue full'))
        if stream.errors != errors:
            self.log(dict(type='frame_error', count=stream.errors - errors))

    def disconnected(self, device):
        if self.device == device:
            self.log(dict(type='disconnected', device=device))
            self.device = None
            self.generation += 1
            self.streams.clear()
            while not self.replies.empty():
                self.replies.get_nowait()

    async def notify_loop(self, characteristic):
        while True:
            device, generation, reply = await self.replies.get()
            # Wait briefly for the CCC subscription; do not invent keepalive ACKs.
            for _ in range(100):
                if characteristic.notifying or device != self.device or generation != self.generation:
                    break
                await asyncio.sleep(0.05)
            if not characteristic.notifying or device != self.device or generation != self.generation:
                self.log(dict(type='reply_dropped', reason='no active subscriber'))
                continue
            complete = True
            for offset in range(0, len(reply), 20):
                if not characteristic.notifying or device != self.device or generation != self.generation:
                    complete = False
                    break
                characteristic.value = reply[offset:offset + 20]
                characteristic.emit_properties_changed({'Value': characteristic.value})
                await asyncio.sleep(0.02)
            self.log(dict(type='ble_notify' if complete else 'reply_interrupted',
                          data_hex=reply.hex()))


async def run(args, output):
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    manager = gatt_manager = adv_manager = None
    registered_app = registered_adv = False
    notify_task = None
    try:
        intro = await bus.introspect('org.bluez', '/')
        manager = bus.get_proxy_object('org.bluez', '/', intro).get_interface(
            'org.freedesktop.DBus.ObjectManager')
        objects = await manager.call_get_managed_objects()
        adapter = '/org/bluez/' + args.adapter
        interfaces = objects.get(adapter, {})
        if not all(x in interfaces for x in ('org.bluez.GattManager1', 'org.bluez.LEAdvertisingManager1')):
            raise RuntimeError(f'{adapter}: need a powered BLE adapter with GATT server/advertising support')
        if not interfaces.get('org.bluez.Adapter1', {}).get('Powered', Variant('b', False)).value:
            raise RuntimeError(f'{adapter}: adapter is off; power it on first')
        session = Session(output, args.hud_info)
        service = Service()
        notify = Characteristic('fff1', ['read', 'notify'])
        chars = [notify, Characteristic('fff2', ['write', 'write-without-response'], session.receive),
                 Characteristic('fff3', ['write', 'write-without-response'], session.receive),
                 Characteristic('fff4', ['notify'])]
        exported = [(SERVICE, service)] + [(SERVICE + f'/char{i}', c) for i, c in enumerate(chars)]
        app = Application(exported)
        bus.export(ROOT, app)
        for path, obj in exported:
            bus.export(path, obj)
        adv_path = ADVERTISEMENT
        bus.export(adv_path, Advertisement(args.name))
        intro = await bus.introspect('org.bluez', adapter)
        proxy = bus.get_proxy_object('org.bluez', adapter, intro)
        gatt_manager = proxy.get_interface('org.bluez.GattManager1')
        adv_manager = proxy.get_interface('org.bluez.LEAdvertisingManager1')

        def watch(message):
            if (message.interface == 'org.freedesktop.DBus.Properties'
                    and message.member == 'PropertiesChanged' and len(message.body) >= 2
                    and message.body[0] == 'org.bluez.Device1'):
                connected = message.body[1].get('Connected')
                if connected is not None and not connected.value:
                    if session.device == message.path:
                        notify.notifying = False
                    session.disconnected(message.path)

        bus.add_message_handler(watch)
        # Subscribe to BlueZ connection changes so fragments cannot cross sessions.
        intro = await bus.introspect('org.freedesktop.DBus', '/org/freedesktop/DBus')
        dbus = bus.get_proxy_object('org.freedesktop.DBus', '/org/freedesktop/DBus', intro)
        await dbus.get_interface('org.freedesktop.DBus').call_add_match(
            "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'")
        await gatt_manager.call_register_application(ROOT, {})
        registered_app = True
        await adv_manager.call_register_advertisement(adv_path, {})
        registered_adv = True
        session.log(dict(type='advertising', name=args.name, adapter=args.adapter,
                         hud_info=args.hud_info, note='experimental; phone acceptance unverified'))
        notify_task = asyncio.create_task(session.notify_loop(notify))
        await bus.wait_for_disconnect()
    finally:
        if notify_task:
            notify_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await notify_task
        if bus.connected:
            if registered_adv:
                with contextlib.suppress(Exception):
                    await adv_manager.call_unregister_advertisement(ADVERTISEMENT)
            if registered_app:
                with contextlib.suppress(Exception):
                    await gatt_manager.call_unregister_application(ROOT)
            bus.disconnect()
