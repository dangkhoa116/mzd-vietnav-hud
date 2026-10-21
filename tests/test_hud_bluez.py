"""BlueZ D-Bus contract test using a private bus; no Bluetooth hardware needed.

Exercises actual registration, introspection, BLE write callbacks and notify
signals via a fake org.bluez. This cannot verify over-the-air/app acceptance.
"""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dbus_next import Variant, Message, MessageType
    from dbus_next.aio import MessageBus
    from dbus_next.constants import PropertyAccess
    from dbus_next.service import ServiceInterface, method, dbus_property
    from hud_emulator.bluez import ROOT, SERVICE, GATT, Session, run
except ImportError:
    raise unittest.SkipTest('install hud_emulator/requirements.txt for BlueZ contract tests')
from hud_emulator.protocol import StreamDecoder, decode, encode


class FakeRoot(ServiceInterface):
    def __init__(self):
        super().__init__('org.freedesktop.DBus.ObjectManager')

    @method()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        return {'/org/bluez/hci0': {
            'org.bluez.Adapter1': {'Powered': Variant('b', True)},
            'org.bluez.GattManager1': {}, 'org.bluez.LEAdvertisingManager1': {}}}


class FakeGatt(ServiceInterface):
    def __init__(self, bus):
        super().__init__('org.bluez.GattManager1')
        self.bus = bus
        self.objects = None
        self.unregistered = False

    @method()
    async def RegisterApplication(self, app: 'o', options: 'a{sv}'):
        # Registration identifies the peer through the unique name of its export.
        # The test sets peer once run() has connected, before this is processed.
        names = await self.bus.call(Message(destination='org.freedesktop.DBus',
            path='/org/freedesktop/DBus', interface='org.freedesktop.DBus', member='ListNames'))
        for name in names.body[0]:
            if not name.startswith(':') or name == self.bus.unique_name:
                continue
            intro = await self.bus.introspect(name, app)
            if any(i.name == 'org.freedesktop.DBus.ObjectManager' for i in intro.interfaces):
                self.peer = name
                proxy = self.bus.get_proxy_object(name, app, intro)
                self.objects = await proxy.get_interface('org.freedesktop.DBus.ObjectManager').call_get_managed_objects()
                return
        raise RuntimeError('application export missing')

    @method()
    def UnregisterApplication(self, app: 'o'):
        self.unregistered = True


class FakeAdvertising(ServiceInterface):
    def __init__(self):
        super().__init__('org.bluez.LEAdvertisingManager1')
        self.ready = asyncio.Event()
        self.unregistered = False

    @method()
    def RegisterAdvertisement(self, app: 'o', options: 'a{sv}'):
        self.ready.set()

    @method()
    def UnregisterAdvertisement(self, app: 'o'):
        self.unregistered = True


class FakeAdapter(ServiceInterface):
    def __init__(self):
        super().__init__('org.bluez.Adapter1')

    @dbus_property(access=PropertyAccess.READ)
    def Powered(self) -> 'b':
        return True


class BluezTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_write_notify_disconnect_cleanup(self):
        if not shutil.which('dbus-daemon'):
            self.skipTest('dbus-daemon required')
        daemon = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = daemon.stdout.readline().strip()
        old_address = os.environ.get('DBUS_SYSTEM_BUS_ADDRESS')
        os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = address
        bus = task = None
        try:
            bus = await MessageBus(bus_address=address).connect()
            await bus.request_name('org.bluez')
            bus.export('/', FakeRoot())
            gatt, adv = FakeGatt(bus), FakeAdvertising()
            bus.export('/org/bluez/hci0', gatt)
            bus.export('/org/bluez/hci0', adv)
            bus.export('/org/bluez/hci0', FakeAdapter())
            out = io.StringIO()
            args = SimpleNamespace(adapter='hci0', name='VIETNAV HUD',
                                   hud_info='MODEL:VIETNAV,HW:0,FW:0,PROTOCOL:2.0')
            task = asyncio.create_task(run(args, out))
            await asyncio.wait_for(adv.ready.wait(), timeout=4)
            self.assertEqual(len(gatt.objects), 5)
            props = gatt.objects[SERVICE]['org.bluez.GattService1']
            self.assertEqual(props['UUID'].value, '0000fff0-0000-1000-8000-00805f9b34fb')
            self.assertEqual(gatt.objects[SERVICE + '/char1'][GATT]['Flags'].value,
                             ['write', 'write-without-response'])
            intro = await bus.introspect(gatt.peer, SERVICE + '/char1')
            writer = bus.get_proxy_object(gatt.peer, SERVICE + '/char1', intro).get_interface(GATT)
            intro = await bus.introspect(gatt.peer, SERVICE + '/char0')
            notify_proxy = bus.get_proxy_object(gatt.peer, SERVICE + '/char0', intro)
            notify = notify_proxy.get_interface(GATT)
            fragments = []
            def changed(interface, changed, invalidated):
                if interface == GATT and 'Value' in changed:
                    fragments.append(changed['Value'].value)
            notify_proxy.get_interface('org.freedesktop.DBus.Properties').on_properties_changed(changed)
            await notify.call_start_notify()
            raw = encode(14, b'\0')
            options = {'device': Variant('o', '/org/bluez/hci0/dev_TEST')}
            await writer.call_write_value(raw[:7], options)
            await writer.call_write_value(raw[7:], options)
            for _ in range(100):
                if 'ble_notify' in out.getvalue():
                    break
                await asyncio.sleep(0.01)
            reply = decode(b''.join(fragments), uid=bytes(16))
            self.assertEqual(reply.payload.decode(), args.hud_info)
            self.assertTrue(all(len(f) <= 20 for f in fragments))
            await writer.call_write_value(encode(1, bytes.fromhex('02012c3c')), options)
            records = [json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual(next(x for x in records if x['type'] == 'camera')['speed_limit_raw'], 60)
            # BlueZ emits a disconnect: ensure the actual match rule resets session.
            bus.send(Message.new_signal('/org/bluez/hci0/dev_TEST',
                'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                'sa{sv}as', ['org.bluez.Device1', {'Connected': Variant('b', False)}, []]))
            for _ in range(100):
                if 'disconnected' in out.getvalue():
                    break
                await asyncio.sleep(0.01)
            self.assertIn('disconnected', out.getvalue())
            await writer.call_write_value(encode(2, b'\x00\x32'),
                {'device': Variant('o', '/org/bluez/hci0/dev_OTHER')})
            self.assertIn('heartbeat', out.getvalue())
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            self.assertTrue(gatt.unregistered)
            self.assertTrue(adv.unregistered)
        finally:
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if bus:
                bus.disconnect()
                await bus.wait_for_disconnect()
            if old_address is None:
                os.environ.pop('DBUS_SYSTEM_BUS_ADDRESS', None)
            else:
                os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = old_address
            daemon.terminate()
            daemon.communicate(timeout=3)

    async def test_session_reconnect_discards_partial_frame(self):
        s = Session(io.StringIO(), None)
        a = {'device': Variant('o', '/phone_a')}
        b = {'device': Variant('o', '/phone_b')}
        raw = encode(14, b'\0')
        s.receive(raw[:9], a)
        with self.assertRaises(Exception):
            s.receive(raw, b)
        s.disconnected('/phone_a')
        s.receive(raw, b)
        self.assertEqual(s.device, '/phone_b')
        self.assertTrue(s.replies.empty())
        self.assertEqual(s.streams['/phone_b'].buffer, b'')

    async def test_bad_navigation_logged_without_crash(self):
        out = io.StringIO()
        s = Session(out, None)
        s.receive(encode(0, b'\0'), {})
        self.assertIn('payload_error', out.getvalue())

    async def test_old_reply_cannot_cross_reconnect(self):
        out = io.StringIO()
        s = Session(out, 'MODEL:VIETNAV')
        options = {'device': Variant('o', '/phone')}
        s.receive(encode(14, b'\0'), options)
        old = await s.replies.get()
        s.disconnected('/phone')
        s.receive(encode(2, b'\0\x32'), options)
        s.replies.put_nowait(old)
        class NeverNotify:
            notifying = True
            def emit_properties_changed(self, _):
                raise AssertionError('old reply leaked to new session')
        task = asyncio.create_task(s.notify_loop(NeverNotify()))
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self.assertIn('reply_dropped', out.getvalue())


if __name__ == '__main__':
    unittest.main()
