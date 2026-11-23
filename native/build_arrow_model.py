#!/usr/bin/env python3
"""Compile a bounded native arrow model from the owner's IPA/APK; no asset upload."""
import argparse
import ctypes as C
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'bridge'))
from vmlhud_arrow import ASSET_RE, parse_asset_name
from vmlhud_hud_out import icon_for

SIDE = 32
GROUPS = {'left':1, 'right':2, 'straight':3, 'slight_left':4, 'slight_right':5,
          'sharp_left':6, 'sharp_right':7, 'uturn':8}
KINDS = {'turn','end_of_road','continue','new_name','on_ramp','off_ramp',
         'fork','merge','arrive','depart','roundabout','rotary'}


def fnv(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def native_library(directory):
    output = Path(directory)/'arrows.so'
    subprocess.run(['gcc','-shared','-fPIC','-O2','-std=c99','-I',str(ROOT/'native'),
                    str(ROOT/'native/hud_arrow.c'), str(ROOT/'native/vendor/picojpeg/picojpeg.c'),
                    '-o',str(output)],check=True)
    lib = C.CDLL(str(output))
    lib.vn_arrow_vector_gray.argtypes = [C.c_char_p,C.c_uint,C.c_uint,C.c_void_p]
    lib.vn_arrow_match.argtypes = [C.c_char_p,C.c_uint,C.c_char_p,C.c_uint,C.c_void_p]
    return lib


def assets(app):
    if Path(app).is_dir():
        for path in sorted(Path(app).rglob('*.png')):
            match = ASSET_RE.search(path.as_posix())
            if match:
                yield path.as_posix(), match[2], path.read_bytes()
    else:
        with zipfile.ZipFile(app) as archive:
            for path in sorted(archive.namelist()):
                match = ASSET_RE.search(path)
                if match:
                    yield path, match[2], archive.read(path)


def compile_model(app, lib, fixtures=None):
    from PIL import Image
    records, metadata, unique = [], [], set()
    for path, name, raw in assets(app):
        kind, modifier = parse_asset_name(name)
        if not kind and modifier == 'uturn': kind = 'turn'
        if kind not in KINDS: continue
        if not modifier and kind not in {'arrive','depart','continue'}: continue
        modifier = modifier or 'straight'
        image = Image.open(io.BytesIO(raw)).convert('RGBA')
        if max(image.size)>128: raise ValueError('Arrow exceeds native 128px limit: '+path)
        flat = Image.alpha_composite(Image.new('RGBA',image.size,(0,0,0,255)),image)
        grayscale = flat.convert('L')
        vector = C.create_string_buffer(SIDE*SIDE)
        if not lib.vn_arrow_vector_gray(grayscale.tobytes(),*image.size,vector):
            raise ValueError('Cannot vectorize '+path)
        icon = icon_for(kind,modifier)
        group = GROUPS[modifier]
        # The same bitmap can occur in light/dark and several synonymous assets.
        key = (vector.raw,group)
        if key in unique: continue
        unique.add(key)
        records.append(bytes([icon,group,0,0])+vector.raw)
        row = dict(asset=name,path=path,icon=icon,group=group,png_sha256=hashlib.sha256(raw).hexdigest())
        if fixtures:
            filename = f'{len(records):03d}-{name}.jpg'
            flat.convert('RGB').save(Path(fixtures)/filename,'JPEG',quality=95,subsampling=0)
            row['fixture']=filename
        metadata.append(row)
    if not 1<=len(records)<=256: raise ValueError('Expected 1..256 arrow templates')
    body=b''.join(records)
    model=b'VNA1'+bytes([SIDE,1])+struct.pack('>HI',len(records),fnv(body))+body
    return model,metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--fixtures',type=Path,help='Local-only JPEG validation images')
    args=parser.parse_args()
    if args.fixtures: args.fixtures.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vietnav-model-') as folder:
        model,metadata=compile_model(args.app,native_library(folder),args.fixtures)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_bytes(model)
    report=dict(format='VNA1',side=SIDE,records=metadata,sha256=hashlib.sha256(model).hexdigest(),
                app=str(args.app),bytes=len(model))
    args.out.with_suffix('.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(f'{args.out}: {len(metadata)} templates, {len(model)} bytes; SHA256 {report["sha256"]}')


if __name__=='__main__': main()
