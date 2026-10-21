#!/usr/bin/env python3
"""Recheck selected OTA strings and adjacent ARM64 pool loads for one known IPA.

This is a build-specific evidence extractor, not a general Dart snapshot parser.
Requires the operator's App.framework/App and DAE 0.1.13 text/strings.txt.
It never executes the target or reads device credentials.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

SHA256 = '83d39fa1f3067fd408a3b928a9d1e8cee4559a62b4b9b248178aa7b17e09223f'
POOL_START, POOL_END, COUNT = 0x1dd1c9f, 0x1e620d2, 160386
SELECT = re.compile(r'updatefirmware|fwnew|Firmware.GetFirmwares|UpdatePermission|'
                    r'remoteFirmwareInfo|localFirmwareInfo|lastedFirmwareInfo', re.I)


def inspect(binary, string_table):
    data = binary.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise ValueError('Unsupported binary SHA256; offsets apply only to the documented iOS build')
    strings = {}
    for line in string_table.read_text(encoding='utf-8').splitlines():
        parts = line.split('\t', 1)
        if len(parts) == 2:
            try:
                strings[int(parts[0], 16)] = parts[1]
            except ValueError:
                pass
    position = POOL_START

    def read(ref=False):
        nonlocal position
        value, shift = 0, 0
        for _ in range(10):
            if position >= POOL_END:
                raise ValueError('Pool entry exceeds documented boundary')
            byte = data[position]
            position += 1
            if ref:
                signed = byte - 256 if byte & 128 else byte
                value = (value << 7) + signed
                if signed < 0:
                    return value + 128
            else:
                if byte & 128:
                    return value + ((byte - 192) << shift)
                value |= byte << shift
                shift += 7
        raise ValueError('Oversize varint')

    selected = {}
    for index in range(COUNT):
        bits = data[position]
        position += 1
        kind = bits & 127
        if kind == 0:
            read()
        elif kind == 1:
            reference = read(ref=True)
            text = strings.get(reference)
            if text and SELECT.search(text):
                selected[16 + index * 8] = dict(ref=hex(reference), text=text)
    if position != POOL_END:
        raise ValueError('Pool end does not match the next DAE cluster')
    if not any(x['text'] == '/v20/hud/updatefirmware' for x in selected.values()):
        raise ValueError('DAE string table does not resolve the expected endpoint')

    # Only adjacent ADD-from-PP / LDR pairs are admitted. No dataflow or inferred
    # function boundary is claimed. Other instruction sequences are not covered.
    references = []
    for address in range(0xe340, 0x1990380 - 8, 4):
        add, load = struct.unpack_from('<II', data, address)
        if add & 0xff000000 != 0x91000000 or (add >> 5) & 31 != 27:
            continue
        register = add & 31
        if load & 0xffc00000 != 0xf9400000 or (load >> 5) & 31 != register:
            continue
        base = ((add >> 10) & 4095) << (12 if add & (1 << 22) else 0)
        offset = base + ((load >> 10) & 4095) * 8
        if offset in selected:
            references.append(dict(address=hex(address), load=hex(address + 4),
                                   pool_offset=hex(offset), **selected[offset]))
    return dict(binary_sha256=digest, pool_start=hex(POOL_START), pool_end=hex(position),
                pool_entries=COUNT, selected_pool={hex(k): v for k, v in selected.items()},
                adjacent_loads=references, coverage='selected strings and adjacent loads only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('strings', type=Path, help='DAE text/strings.txt for that binary')
    parser.add_argument('--out', required=True, type=Path, help='New JSON evidence file')
    args = parser.parse_args()
    try:
        result = inspect(args.binary, args.strings)
        with args.out.open('x', encoding='utf-8') as output:
            json.dump(result, output, indent=2, ensure_ascii=True)
            output.write('\n')
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    print(f'Validated {COUNT} entries; found {len(result["adjacent_loads"])} adjacent loads')


if __name__ == '__main__':
    main()
