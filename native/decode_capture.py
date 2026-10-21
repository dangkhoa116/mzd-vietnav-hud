#!/usr/bin/env python3
"""Decode only VML RX write fragments from the native preload's own log."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hud_emulator.protocol import StreamDecoder, event


def records(lines):
    stream = StreamDecoder()
    connected = False
    for number, line in enumerate(lines, 1):
        if 'VML connected' in line:
            stream = StreamDecoder()
            connected = True
        if 'VML disconnected' in line:
            if stream.buffer:
                yield dict(type='incomplete_frame', line=number, bytes=len(stream.buffer))
            stream = StreamDecoder()
            connected = False
        if 'VML RX ' not in line:
            continue
        try:
            chunk = bytes.fromhex(line.split('VML RX ', 1)[1])
        except ValueError:
            yield dict(type='invalid_log_hex', line=number)
            continue
        old = stream.errors
        for frame in stream.feed(chunk):
            try:
                yield dict(line=number, session_seen=connected, **event(frame))
            except ValueError as exc:
                yield dict(type='payload_error', line=number, error=str(exc))
        if stream.errors != old:
            yield dict(type='frame_error', line=number, count=stream.errors-old)
    if stream.buffer:
        yield dict(type='incomplete_frame', bytes=len(stream.buffer))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('log', type=Path)
    args = p.parse_args()
    with args.log.open(encoding='utf-8') as f:
        for record in records(f):
            print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
