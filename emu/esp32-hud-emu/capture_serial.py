#!/usr/bin/env python3
"""Save raw ESP32 USB Serial to a file and echo it; Ctrl+C stops capture."""
import argparse
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', help='COM7 on Windows, /dev/ttyACM0 on Linux')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        import serial
    except ImportError:
        parser.exit(1, 'Install first: python -m pip install pyserial==3.5\n')
    # Exclusive creation preserves previous captures; write bytes without decoding.
    with args.output.open('xb') as output, serial.Serial(args.port, 115200, timeout=1) as port:
        print('Capturing; reset board now, then connect in VietMap. Ctrl+C stops.', file=sys.stderr)
        try:
            while True:
                data = port.read(port.in_waiting or 1)
                if data:
                    output.write(data)
                    output.flush()
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
