#!/usr/bin/env python3
"""Prepare an isolated HUD-only build from a verified TPMS source revision.

Does not alter TPMS, installers, the car, or a USB stick. Outputs are experiments,
not release binaries. Keep the full TPMS MIT notice in generated/distributed code.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess

SOURCE_SHA256 = '39ea9a0d9ff6c942b2798bb45c96cb222bb2bc8729c4ed938b065bf475c8cdd4'
HERE = Path(__file__).resolve().parent
NATIVE_FILES = ('hud_native.h', 'hud_native.c', 'hud_guidance.h', 'hud_guidance.c',
                'vn_vbs.h', 'vn_vbs.c', 'vn_vbs_dl.c', 'tpms_adapter.inc',
                'hud_arrow.h', 'hud_arrow.c', 'arrow_model.c',
                'vendor/picojpeg/picojpeg.h', 'vendor/picojpeg/picojpeg.c')
C_SOURCES = ('v3.c', 'hud_native.c', 'hud_guidance.c', 'vn_vbs.c', 'vn_vbs_dl.c',
             'hud_arrow.c', 'arrow_model.c', 'vendor/picojpeg/picojpeg.c')


def load_arrow_model(path):
    import struct
    raw = path.read_bytes()
    if len(raw)<12 or raw[:6]!=b'VNA1\x20\x01':
        raise ValueError('invalid native arrow model header')
    count,expected=struct.unpack('>HI',raw[6:12])
    if not 1<=count<=256 or len(raw)!=12+count*1028:
        raise ValueError('invalid native arrow model length')
    checksum=2166136261
    for byte in raw[12:]: checksum=((checksum^byte)*16777619)&0xffffffff
    if checksum!=expected: raise ValueError('native arrow model checksum mismatch')
    return raw,count


def prepare(source, output, arrow_model=None):
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('TPMS v3.c differs from the reviewed revision; review/update the patch first')
    for parent in source.parents:
        if (parent / '.git').exists() and (output == parent or parent in output.parents):
            raise ValueError('output must be outside the TPMS source checkout')
    # Never overwrite a source checkout, including a checkout passed as output.
    if (output / 'v3.c').resolve() == source.resolve():
        raise ValueError('output must be separate from the TPMS source directory')
    if output == HERE:
        raise ValueError('output must be separate from native sources')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'v3.c').write_bytes(raw)
    for name in NATIVE_FILES:
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / name, output / name)
    if arrow_model:
        model,count=load_arrow_model(arrow_model)
        (output/'arrow_model.c').write_text(
            '/* Generated from the owner-supplied arrow model; do not commit. */\n'
            'const unsigned char vn_arrow_model[] = {\n'+
            '\n'.join(','.join(str(x) for x in model[i:i+32])+',' for i in range(0,len(model),32))+
            '\n};\nconst unsigned vn_arrow_model_size = '+str(len(model))+';\n')
    subprocess.run(['patch', '--batch', '--forward', '-p1', '-i', str(HERE / 'tpms-v3-hud.patch')],
                   cwd=output, check=True, capture_output=True, text=True)
    (output / 'PROVENANCE.txt').write_text(
        f'TPMS source sha256: {SOURCE_SHA256}\n'
        'Base: mzd-connect-tpms tpms/v3/v3.c; MIT, copyright Dang Khoa.\n'
        'Native additions: mzd-vietnav-hud/native; AGPL-3.0-or-later.\n'
        'HUD-only experimental build. No TPMS concurrently. No car validation.\n'
        'Reversible USB trial launcher is built separately with native/usb/build_kit.py.\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tpms', type=Path, default=HERE.parents[1] / 'mzd-connect-tpms/tpms/v3/v3.c')
    parser.add_argument('--out', type=Path, default=HERE.parent / 'out/native-build')
    parser.add_argument('--host-build', action='store_true')
    parser.add_argument('--arrow-model', type=Path)
    args = parser.parse_args()
    try:
        prepare(args.tpms.resolve(), args.out.resolve(), args.arrow_model)
        if args.host_build:
            subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-fno-builtin', '-DVN_VBS_HAVE_UNISTD',
                            '-o', str(args.out / 'libvietnav-native-host.so'),
                            *(str(args.out / name) for name in C_SOURCES), '-ldl'], check=True)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'prepare: {exc}\n')
    print(f'Prepared experimental source in {args.out}')


if __name__ == '__main__':
    main()
