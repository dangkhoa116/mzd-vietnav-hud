#!/usr/bin/env python3
"""Build the experimental ARM preload with the CMU-period m3 toolchain."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from prepare import HERE, SOURCE_SHA256, prepare


def inspect_elf(readelf, path):
    def read(flag):
        return subprocess.check_output([str(readelf), flag, '-W', str(path)], text=True)
    header, symbols, versions, relocs, attributes = [read(flag) for flag in
        ('-h', '--dyn-syms', '-V', '-r', '-A')]
    flags = int(re.search(r'Flags:\s+(0x[0-9a-f]+)', header)[1], 16)
    required = set()
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[6] == 'UND' and fields[4] != 'WEAK':
            required.add(fields[7].split('@')[0])
    glibc = sorted(set(re.findall(r'GLIBC_[0-9.]+', versions)))
    if 'ELF32' not in header or not re.search(r'Machine:\s+ARM\b', header) or 'little endian' not in header:
        raise ValueError('expected 32-bit little-endian ARM ELF')
    if flags & 0xff000000 != 0x05000000 or flags & 0x400:
        raise ValueError('expected EABI5 with base/soft-float calling convention')
    if 'Tag_ABI_VFP_args: VFP registers' in attributes:
        raise ValueError('hard-float argument ABI is incompatible with the CMU')
    if any(tuple(map(int, ver[6:].split('.'))) > (2, 11) for ver in glibc):
        raise ValueError('GLIBC dependency exceeds the CMU glibc 2.11')
    return dict(flags=flags, required_symbols=sorted(required), glibc=glibc,
                relocations=sorted(set(re.findall(r'R_ARM_\w+', relocs))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=HERE.parent / 'out/native-build')
    parser.add_argument('--tpms', type=Path, default=HERE.parents[1] / 'mzd-connect-tpms')
    args = parser.parse_args()
    toolchain, output, tpms = args.toolchain.resolve(), args.out.resolve(), args.tpms.resolve()
    prefix = toolchain / 'bin/arm-cortexa9_neon-linux-gnueabi-'
    cc, readelf = str(prefix) + 'gcc', str(prefix) + 'readelf'
    sysroot = toolchain / 'arm-cortexa9_neon-linux-gnueabi/sysroot'
    try:
        if not (sysroot / 'lib/libc-2.11.so').exists():
            raise ValueError('toolchain must include the CMU glibc 2.11 sysroot')
        prepare(tpms / 'tpms/v3/v3.c', output)
        library = output / 'libvietnav-native-arm.so'
        subprocess.run([cc, '-std=gnu99', '--sysroot=' + str(sysroot), '-shared', '-fPIC', '-O2',
                        '-Wall', '-Wextra', '-Werror', '-fno-builtin', '-fno-stack-protector', '-s',
                        '-o', str(library), str(output / 'v3.c'), str(output / 'hud_native.c'), '-ldl'], check=True)
        report = inspect_elf(readelf, library)
        baseline = inspect_elf(readelf, tpms / 'tpms/v1/libtpms-v1.so')
        if set(report['required_symbols']) - set(baseline['required_symbols']):
            raise ValueError('new required loader symbols compared with the on-car v1 baseline')
        if set(report['relocations']) - set(baseline['relocations']):
            raise ValueError('new relocation types compared with the on-car v1 baseline')
        # GNU m3 ld and the baseline linker set optional legacy flags differently.
        # Both use base AAPCS. Do not rewrite ELF headers just to match those bits.
        flag_difference = report['flags'] ^ baseline['flags']
        if flag_difference & ~0x202:
            raise ValueError('unexpected ELF flag difference from the baseline')
        report.update(sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                      compiled_sources={name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                                        for name in ('v3.c', 'hud_native.c', 'hud_native.h', 'tpms_adapter.inc')},
                      tpms_source_sha256=SOURCE_SHA256,
                      compiler=subprocess.check_output([cc, '--version'], text=True).splitlines()[0],
                      baseline_flags=baseline['flags'], optional_flag_difference=flag_difference,
                      baseline='mzd-connect-tpms/tpms/v1/libtpms-v1.so',
                      status='experimental HUD-only; not tested on car')
        (output / 'ARM-CHECKS.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(f'ARM loader checks PASS: {library}; {", ".join(report["glibc"])}')
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'ARM build/check: {exc}\n')


if __name__ == '__main__':
    main()
