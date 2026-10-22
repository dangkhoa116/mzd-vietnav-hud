import argparse
import asyncio
import json
import sys
from contextlib import nullcontext
from .protocol import StreamDecoder, event


def main():
    # JSONL carries Vietnamese road names. A legacy console codepage (cp1252 on
    # Windows) cannot encode them and would abort a redirected capture, so pin
    # UTF-8 instead of inheriting the locale.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Vietnav experimental HUD BLE peripheral / offline decoder')
    sub = parser.add_subparsers(dest='mode', required=True)
    replay = sub.add_parser('decode', help='decode binary BLE write stream or hex lines from stdin')
    replay.add_argument('input', nargs='?', default='-', help='raw binary file; stdin uses one hex chunk per line')
    ble = sub.add_parser('ble', help='advertise on Linux BlueZ; requires dbus-next and BLE hardware')
    ble.add_argument('--adapter', default='hci0')
    ble.add_argument('--name', default='VIETNAV HUD')
    ble.add_argument('--output', default='-', help='JSONL capture, default stdout')
    ble.add_argument('--hud-info', default='MODEL:VIETNAV,HW:0,FW:0,PROTOCOL:2.0',
                     help='experimental HUDInfo payload; no real device identity by default')
    ble.add_argument('--no-info-reply', action='store_true', help='receive/log only')
    args = parser.parse_args()
    if args.mode == 'decode':
        stream = StreamDecoder()
        if args.input == '-':
            chunks = (bytes.fromhex(line.strip()) for line in sys.stdin if line.strip())
            source = nullcontext(chunks)
        try:
            if args.input != '-':
                source = open(args.input, 'rb')
            with source as handle:
                chunks = iter(lambda: handle.read(4096), b'') if args.input != '-' else handle
                for chunk in chunks:
                    for frame in stream.feed(chunk):
                        print(json.dumps(event(frame), ensure_ascii=False))
            if stream.errors or stream.buffer:
                raise ValueError(f'{stream.errors} corrupt frame(s), {len(stream.buffer)} trailing byte(s)')
        except (ValueError, OSError) as exc:
            parser.exit(1, f'decode: {exc}\n')
        return
    if 'HUD' not in args.name or 'TPMS' in args.name or len(args.name.encode('utf-8')) > 20:
        parser.error('BLE name must contain HUD, exclude TPMS, and fit 20 UTF-8 bytes')
    if args.no_info_reply:
        args.hud_info = None
    elif len(args.hud_info.encode('utf-8')) > 1024:
        parser.error('HUDInfo text too long')
    try:
        from .bluez import run
        from dbus_next import DBusError
    except ImportError:
        parser.exit(1, 'BLE mode needs dbus-next: pip install -r hud_emulator/requirements.txt\n')
    try:
        with (nullcontext(sys.stdout) if args.output == '-' else open(args.output, 'a', encoding='utf-8')) as output:
            asyncio.run(run(args, output))
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, DBusError) as exc:
        parser.exit(1, f'BLE: {exc}\n')


if __name__ == '__main__':
    main()
