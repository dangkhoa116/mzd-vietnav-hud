#!/usr/bin/env python3
"""Exercise a HUD board over real BLE from a PC, standing in for VIETMAP LIVE.

Connects as the GATT central, subscribes to the notify characteristic, requests
HUDInfo and pushes navigation/heartbeat frames built by this repo's codec. Each
frame is written in 20-byte chunks so the board's reassembly path is exercised
as it would be at the default ATT MTU of 23. With --port the board's Serial log
is captured at the same time and shown per step.

This validates the board, the GATT layout and the wire format. It does NOT
validate that the phone app discovers or accepts the device: only a session
with VIETMAP LIVE itself can show that.

Needs bleak (`python -m pip install bleak`); pyserial only for --port.
"""
import argparse
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bridge import vmlhud_frame as wire  # noqa: E402
from bridge import vmlhud_nav as nav  # noqa: E402

FAMILIES = {
    'h1': dict(service='fff0', notify='fff1', write='fff2'),
    'h50': dict(service='ffff', notify='1234', write='9abc'),
}
FROZEN = 'a55a37c30000000e000000000e004dc64215c1c48da3'


def uuid128(short):
    return f'0000{short}-0000-1000-8000-00805f9b34fb'


class SerialWatch:
    """Collect the board's Serial lines with timestamps, or nothing if absent."""

    def __init__(self, port):
        self.lines, self.port, self._stop = [], port, threading.Event()
        self.error = None
        if port:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            import serial
            handle = serial.Serial()
            handle.port, handle.baudrate, handle.timeout = self.port, 115200, 0.2
            handle.dtr = handle.rts = False
            handle.open()
        except Exception as exc:
            self.error = str(exc)
            return
        pending = b''
        while not self._stop.is_set():
            chunk = handle.read(4096)
            if not chunk:
                continue
            pending += chunk
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                text = line.decode('utf-8', 'replace').rstrip('\r')
                if text:
                    self.lines.append((time.time(), text))
        handle.close()

    def since(self, mark, label):
        rows = [text for stamp, text in self.lines if stamp >= mark]
        if self.port:
            print(f'    serial during {label}: {len(rows)} line(s)')
            for text in rows:
                print(f'      | {text}')
        return rows

    def stop(self):
        self._stop.set()


class Probe:
    def __init__(self):
        self.results = []

    def check(self, name, ok, detail=''):
        self.results.append((name, bool(ok)))
        print(f'  [{"PASS" if ok else "FAIL"}] {name}' + (f' - {detail}' if detail else ''))
        return bool(ok)

    def report(self):
        failed = [name for name, ok in self.results if not ok]
        print(f'\n{len(self.results) - len(failed)}/{len(self.results)} checks passed')
        for name in failed:
            print(f'  FAILED: {name}')
        return 0 if not failed else 1


async def write_frame(client, char, frame):
    for offset in range(0, len(frame), 20):
        await client.write_gatt_char(char, frame[offset:offset + 20], response=True)
    await asyncio.sleep(1.2)


async def run(args):
    from bleak import BleakClient, BleakScanner

    probe = Probe()
    print('# codec cross-check against the firmware PING vector')
    probe.check('python codec reproduces frozen SDK vector',
                wire.build(0x0E, b'\x00', 0).hex() == FROZEN)

    watch = SerialWatch(args.port)
    await asyncio.sleep(1.0)
    if args.port and watch.error:
        print(f'  note: serial {args.port} unavailable ({watch.error}); BLE checks still run')

    print(f'\n# discovering (name must contain {args.name!r})')
    device = None
    if args.address:
        device = await BleakScanner.find_device_by_address(args.address, timeout=args.timeout)
    else:
        found = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
        for candidate, adv in found.values():
            if adv.local_name and args.name in adv.local_name:
                device = candidate
                print(f'  {candidate.address}  name={adv.local_name!r}  rssi={adv.rssi}  '
                      f'uuids={sorted(adv.service_uuids)}')
                probe.check('name present in advertisement', True, adv.local_name)
                probe.check('FFF0 in advertisement', uuid128('fff0') in adv.service_uuids)
                probe.check('FFFF in advertisement', uuid128('ffff') in adv.service_uuids)
                break
    if not probe.check('board found by scan', device is not None):
        watch.stop()
        return probe.report()

    async with BleakClient(device, timeout=args.timeout) as client:
        probe.check('connected', client.is_connected, f'mtu={getattr(client, "mtu_size", "?")}')
        watch.since(0, 'connect')

        present = {char.uuid for service in client.services for char in service.characteristics}
        for family, uuids in FAMILIES.items():
            for role in ('notify', 'write'):
                probe.check(f'{family}: {uuids[role].upper()} present',
                            uuid128(uuids[role]) in present)

        for family in args.families:
            uuids = FAMILIES[family]
            notify_uuid, write_uuid = uuid128(uuids['notify']), uuid128(uuids['write'])
            buffer, frames = bytearray(), []

            def handler(_, data, buffer=buffer, frames=frames):
                buffer.extend(data)
                got, rest = wire.split_stream(bytes(buffer))
                buffer[:] = rest
                frames.extend(got)

            print(f'\n# === family {family}: {uuids["service"].upper()} ===')
            mark = time.time()
            await client.start_notify(notify_uuid, handler)
            await asyncio.sleep(0.6)
            watch.since(mark, 'subscribe')

            # HUDInfo: the only request the sketch answers, so it proves the
            # notify path and the 8-byte trailer end to end.
            mark = time.time()
            await write_frame(client, write_uuid, wire.build(0x0E, b'\x00'))
            watch.since(mark, 'getHUDInfo')
            info = [f for f in frames if f['cmd'] == 0x0E]
            if probe.check(f'{family}: HUDInfo frame reassembled and checksum-verified', info):
                text = info[0]['payload'].decode('utf-8', 'replace')
                print(f'      HUDInfo = {text}')
                probe.check(f'{family}: HUDInfo carries MODEL and SID',
                            'MODEL:' in text and 'SID:' in text)

            # Navigation with Vietnamese road names: the case the project exists
            # for, and the one that breaks if UTF-8 is mishandled anywhere.
            mark = time.time()
            guidance = nav.NavInfo(direction=3, distance_m=250,
                                   current_road=args.current_road, next_road=args.next_road,
                                   remain_time_s=None, remain_hours=0, remain_minutes=12,
                                   remain_time_third_raw=30, remain_dist_m=5400, speed_kmh=48)
            await write_frame(client, write_uuid, wire.build(0x00, nav.build_nav_variable(guidance)))
            lines = watch.since(mark, 'navigation')
            if args.port and not watch.error:
                decoded = [l for l in lines if '[NAV]' in l and 'rejected' not in l]
                probe.check(f'{family}: board decoded navigation', decoded)
                probe.check(f'{family}: Vietnamese road names intact in board log',
                            any(args.current_road in l and args.next_road in l for l in decoded))

            # Legacy CRC16 branch: the SDK uses it before hudInfo is known.
            mark = time.time()
            await write_frame(client, write_uuid, wire.build(0x02, b'\xff', protocol='legacy'))
            lines = watch.since(mark, 'legacy heartbeat')
            if args.port and not watch.error:
                probe.check(f'{family}: legacy CRC16 heartbeat accepted',
                            any('[HB ]' in l for l in lines))

            # End of guidance, so a bridge knows when to clear the HUD.
            mark = time.time()
            done = nav.NavInfo(direction=0xFF, remain_time_s=None)
            await write_frame(client, write_uuid, wire.build(0x00, nav.build_nav_variable(done)))
            lines = watch.since(mark, 'end of guidance')
            if args.port and not watch.error:
                probe.check(f'{family}: end-of-guidance (direction 0xFF) decoded',
                            any('dir=255' in l for l in lines))

            try:
                await client.stop_notify(notify_uuid)
            except Exception:
                pass

    watch.stop()
    if args.log:
        Path(args.log).write_text(json.dumps(
            dict(address=device.address, checks=[dict(name=n, passed=o) for n, o in probe.results],
                 serial=[dict(at=t, line=s) for t, s in watch.lines]),
            indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'\ntranscript written to {args.log}')
    return probe.report()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--address', help='BLE address; default is to scan for --name')
    parser.add_argument('--name', default='VMHUD-EMU', help='advertised name substring to match')
    parser.add_argument('--port', help='serial port of the board, to capture its log alongside')
    parser.add_argument('--family', dest='families', action='append', choices=sorted(FAMILIES),
                        help='device family to exercise; repeatable, default both')
    parser.add_argument('--timeout', type=float, default=20.0)
    parser.add_argument('--log', help='write a JSON transcript here')
    parser.add_argument('--current-road', default='Đường Nguyễn Văn Linh')
    parser.add_argument('--next-road', default='Đại lộ Võ Nguyên Giáp')
    args = parser.parse_args()
    args.families = args.families or sorted(FAMILIES)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(asyncio.run(run(args)))


if __name__ == '__main__':
    main()
