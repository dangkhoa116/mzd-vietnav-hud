#!/usr/bin/env python3
"""Record a VIETMAP LIVE trial against the board and name the rung that failed.

Captures the board's Serial log with host timestamps while optionally scanning
from the PC to confirm the board is still advertising. On exit it reports how
far the app got, because "no navigation" has several very different causes:

  advertising -> connected -> subscribed -> HUDInfo asked -> HUDInfo answered
              -> writes arriving -> navigation decoded

The board stops advertising once a central connects, so scan results are only
meaningful while no connection is up; the recorder accounts for that.

Needs pyserial. --scan additionally needs bleak.
"""
import argparse
import asyncio
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RUNGS = [
    ('advertising', 'board advertising seen'),
    ('connected', 'a central connected'),
    ('subscribed', 'central enabled notify'),
    ('hudinfo_request', 'central asked for HUDInfo (CMD 0x0E)'),
    ('hudinfo_answer', 'board answered HUDInfo'),
    ('writes', 'further writes arrived after HUDInfo'),
    ('navigation', 'navigation payload decoded'),
]

ADVICE = {
    'advertising': (
        'The board was never seen advertising. Check it is powered and the '
        'sketch is running (send STATUS on the serial port); re-flash if the '
        'banner is missing.'),
    'connected': (
        'The board advertised but nothing connected, so this is a discovery '
        'problem on the phone rather than a protocol one. On VIETMAP LIVE 3.4.3 '
        'for Android this is expected and is not a fault of the board: its HUD '
        'screen calls BluetoothAdapter.startDiscovery(), a Bluetooth Classic '
        'inquiry, and does not list an LE-only peripheral even after Android '
        'has discovered and named it. An ESP32-C3 has no Bluetooth Classic, so '
        'it cannot appear there; see docs/hud-dart-layer-analysis.vi.md. The '
        'iOS SDK takes a CoreBluetooth/FFF0 route instead, so an iPhone is the '
        'branch worth trying with this board. Permissions are worth a glance '
        'only if Android itself never reports the device.'),
    'subscribed': (
        'Connected but notify was never enabled. The central connected without '
        'driving the HUD profile. Check whether the phone OS connected on its '
        'own (Bluetooth settings) rather than the app, and keep the app on its '
        'HUD screen.'),
    'hudinfo_request': (
        'Subscribed but no getHUDInfo request. The app opened the GATT link but '
        'did not start the HUD handshake; capture which device family it chose '
        'and whether it expected a different service.'),
    'hudinfo_answer': (
        'The request arrived but the board did not answer. This is a board-side '
        'fault: run ble_central_probe.py to reproduce it without the phone.'),
    'writes': (
        'HUDInfo was answered but nothing followed. The app likely rejected the '
        'reply. The PROTOCOL value decides the Android branch: 2.2.2S drives the '
        'full nav builder, while any other value (including 1.6) selects the '
        'minimal branch that sends no navigation. Keep PROTOCOL:2.2.2S and note '
        'any app message about the device; permission/serial checks live here.'),
    'navigation': (
        'Writes arrived but no navigation decoded. Start a route with a turn and '
        'a named road; if writes are heartbeats only (CMD 0x02), the app is in '
        'its minimal branch - recheck the HUDInfo PROTOCOL value. Keep every '
        '[W:...] hex line: decode_log.py can replay them offline.'),
}

PATTERNS = [
    ('advertising', re.compile(r'\[ADV\] connectable start OK')),
    ('connected', re.compile(r'\[BLE\] connected')),
    ('subscribed', re.compile(r'\[BLE\] notify \S+ sub=0x0001')),
    ('hudinfo_request', re.compile(r'\[RX \] \S+ CMD 0x0E')),
    ('hudinfo_answer', re.compile(r'\[EMU\] HUDInfo via')),
    ('navigation', re.compile(r'\[NAV\] (?!rejected)\S+ dir=')),
]
WRITE_LINE = re.compile(r'\[W:(?:FFF2|FFF3|9ABC)\]')


class Trial:
    def __init__(self):
        self.reached = {}
        self.lock = threading.Lock()
        self.connected = False
        self.writes_after_info = 0
        self.lines = 0

    def stamp(self):
        return datetime.now(timezone.utc).astimezone().strftime('%H:%M:%S')

    def mark(self, rung, how):
        with self.lock:
            if rung not in self.reached:
                self.reached[rung] = (time.time(), how)
                print(f'  {self.stamp()}  ++ {dict(RUNGS)[rung]}')

    def feed(self, line):
        with self.lock:
            self.lines += 1
            if '[BLE] connected' in line:
                self.connected = True
            if '[BLE] disconnected' in line:
                self.connected = False
        for rung, pattern in PATTERNS:
            if pattern.search(line):
                self.mark(rung, 'serial')
        if WRITE_LINE.search(line):
            with self.lock:
                if 'hudinfo_answer' in self.reached:
                    self.writes_after_info += 1
                    writes = self.writes_after_info
                else:
                    writes = 0
            if writes == 1:
                self.mark('writes', 'serial')

    def report(self):
        print('\n' + '=' * 68)
        print(f'serial lines captured: {self.lines}')
        for rung, label in RUNGS:
            hit = self.reached.get(rung)
            print(f'  [{"YES" if hit else " no"}] {label}' + (f'  (via {hit[1]})' if hit else ''))
        missing = [rung for rung, _ in RUNGS if rung not in self.reached]
        if not missing:
            print('\nAll rungs reached: the app connected and sent navigation.')
            print('Next: compare direction byte, road names and distances against '
                  'the app screen, and keep this log as a codec fixture.')
            return 0
        rung = missing[0]
        print(f'\nFirst rung not reached: {rung}\n')
        print(ADVICE[rung])
        print('\nKeep this log either way; absence of navigation does not by '
              'itself prove the server or the serial number refused the device.')
        return 1


def serial_reader(port, out_path, trial, stop):
    import serial
    handle = serial.Serial()
    handle.port, handle.baudrate, handle.timeout = port, 115200, 0.2
    handle.dtr = handle.rts = False
    handle.open()
    print(f'# holding {port}; press RESET on the board now, then use the app')
    pending = b''
    with open(out_path, 'a', encoding='utf-8') as log:
        while not stop.is_set():
            chunk = handle.read(4096)
            if not chunk:
                continue
            pending += chunk
            while b'\n' in pending:
                raw, pending = pending.split(b'\n', 1)
                line = raw.decode('utf-8', 'replace').rstrip('\r')
                if not line:
                    continue
                log.write(f'{datetime.now(timezone.utc).astimezone().isoformat()}\t{line}\n')
                log.flush()
                print(f'  {trial.stamp()}  | {line}')
                trial.feed(line)
    handle.close()


async def scan_loop(name, trial, stop, every):
    from bleak import BleakScanner
    while not stop.is_set():
        if trial.connected:
            # Advertising legitimately stops while a central is connected.
            await asyncio.sleep(every)
            continue
        try:
            found = await BleakScanner.discover(timeout=4.0, return_adv=True)
        except Exception as exc:
            print(f'  {trial.stamp()}  # scan failed: {exc}')
            await asyncio.sleep(every)
            continue
        for _, adv in found.values():
            if adv.local_name and name in adv.local_name:
                trial.mark('advertising', 'PC scan')
                print(f'  {trial.stamp()}  # PC still sees {adv.local_name!r} '
                      f'(rssi={adv.rssi}) - so the board is advertising')
                break
        else:
            if not trial.connected:
                print(f'  {trial.stamp()}  # PC scan did NOT see {name!r}')
        await asyncio.sleep(every)


async def main_async(args):
    trial = Trial()
    stop = threading.Event()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    reader = threading.Thread(target=serial_reader, args=(args.port, out_path, trial, stop),
                             daemon=True)
    reader.start()
    print('# ladder: advertising -> connected -> subscribed -> HUDInfo -> writes -> navigation')
    print('# in VIETMAP LIVE: open HUD/Bluetooth, scan, connect, then start a route')
    print('# press Ctrl+C when done\n')
    try:
        work = (scan_loop(args.name, trial, stop, args.scan_every) if args.scan
                else asyncio.Event().wait())
        if args.seconds:
            await asyncio.wait_for(work, timeout=args.seconds)
        else:
            await work
    except (KeyboardInterrupt, asyncio.CancelledError, asyncio.TimeoutError):
        pass
    finally:
        stop.set()
    print(f'\nlog written to {out_path}')
    return trial.report()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', required=True, help='board serial port, e.g. COM3')
    parser.add_argument('--out', default='out/app-trial.log', help='timestamped capture path')
    parser.add_argument('--name', default='VMHUD-EMU', help='advertised name to look for')
    parser.add_argument('--scan', action='store_true', default=True,
                        help='confirm advertising from this PC (default)')
    parser.add_argument('--no-scan', dest='scan', action='store_false')
    parser.add_argument('--scan-every', type=float, default=20.0)
    parser.add_argument('--seconds', type=float, default=0,
                        help='stop after this many seconds; default is to wait for Ctrl+C')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(asyncio.run(main_async(args)))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == '__main__':
    main()
