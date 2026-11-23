#!/usr/bin/env python3
"""Replay HUD input through the native C engine, without Bluetooth or vehicle I/O.

Linux/WSL needs gcc. --compiler/--qemu can run the identical engine as ARM.
--render selects mzd-connect-emu/scripts/hud-render.py for an offline preview.
"""
import argparse
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hud_emulator.protocol import StreamDecoder,encode
from bridge import vmlhud_nav as nav
from build_arrow_model import assets,compile_model,native_library


def picture(raw):
    from PIL import Image
    image=Image.open(io.BytesIO(raw)).convert('RGBA')
    image=Image.alpha_composite(Image.new('RGBA',image.size,(0,0,0,255)),image).convert('RGB')
    output=io.BytesIO();image.save(output,'JPEG',quality=95)
    return output.getvalue()


def navigation(distance,road='Nguyễn Huệ',jpeg=None):
    payload=nav.build_nav_variable2(nav.NavInfo(direction=0xfe,distance_m=distance,next_road=road))
    if jpeg:
        payload=payload[:1]+struct.pack('>I',len(jpeg))+jpeg+payload[6:]
    return encode(0x40,payload,timestamp=0)


def demo(app):
    icons={}
    for path,name,raw in assets(app):
        if '/dark/' in path: icons[name]=raw
    frames=[]
    for modifier,distance in (('right',150),('left',90),('straight',60)):
        raw=icons.get('direction_turn_'+modifier)
        if raw is None: raise ValueError('Missing demo asset: '+modifier)
        frames.append(navigation(distance,jpeg=picture(raw)))
        if modifier=='right':
            frames.append(encode(1,bytes.fromhex('0100643c'),timestamp=0))
            frames.append(navigation(120))  # retain image, no JPEG retransmission
    frames.append(navigation(0xffffffff,''))
    return b''.join(frames)


def from_log(path,family):
    stream=StreamDecoder();frames=[];stats={'frames':0,'errors':0,'incomplete_sessions':0}
    pattern=re.compile(r'\[W:(FFF2|FFF3|9ABC)\]\s+(\d+) byte:\s*([0-9A-Fa-f]+)\s*$')
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
        if ('[BLE] connected' in line or '[BLE] disconnected' in line or
                'VML connected' in line or 'VML disconnected' in line):
            stats['errors']+=stream.errors
            stats['incomplete_sessions']+=bool(stream.buffer)
            stream=StreamDecoder();frames.append(navigation(0xffffffff,''));continue
        match=pattern.search(line)
        if match:
            if (match[1]=='9ABC') != (family=='H50'): continue
            chunk=bytes.fromhex(match[3])
            if len(chunk)!=int(match[2]): raise ValueError('Serial length mismatch')
        elif 'VML RX ' in line: chunk=bytes.fromhex(line.split('VML RX ',1)[1])
        else: continue
        for frame in stream.feed(chunk):
            if frame.protocol!='new': continue
            # Preserve the verified header/payload. Runtime UID is unknown;
            # the replay re-signs with zero UID and validates the default sum.
            frames.append(encode(frame.command,frame.payload,timestamp=frame.timestamp))
            stats['frames']+=1
    stats['errors']+=stream.errors;stats['incomplete_sessions']+=bool(stream.buffer)
    if not stats['frames']: raise ValueError('No verified new-protocol frames in capture')
    return b''.join(frames),stats


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    model=parser.add_mutually_exclusive_group(required=True)
    model.add_argument('--app',type=Path);model.add_argument('--model',type=Path)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--demo',action='store_true');source.add_argument('--frames',type=Path)
    source.add_argument('--log',type=Path)
    parser.add_argument('--family',choices=('H1','H50'),default='H1')
    parser.add_argument('--out',type=Path,default=ROOT/'out/hud-emu')
    parser.add_argument('--compiler',default='gcc');parser.add_argument('--qemu',type=Path)
    parser.add_argument('--render',type=Path,help='mzd-connect-emu/scripts/hud-render.py')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.demo and not args.app: parser.error('--demo needs --app for owner-supplied arrow assets')
    if args.app:
        with tempfile.TemporaryDirectory(prefix='hud-model-') as temporary:
            blob,metadata=compile_model(args.app,native_library(temporary))
        (out/'arrows.vna').write_bytes(blob)
        (out/'arrows.json').write_text(json.dumps({'format':'VNA1','records':metadata},ensure_ascii=False,indent=2)+'\n')
    elif args.model.resolve()!=(out/'arrows.vna'):
        shutil.copyfile(args.model,out/'arrows.vna')
    statistics={}
    if args.demo: data=demo(args.app)
    elif args.log: data,statistics=from_log(args.log,args.family)
    else: data=args.frames.read_bytes()
    (out/'frames.bin').write_bytes(data)
    binary=out/('hud-replay-arm' if args.qemu else 'hud-replay')
    sources=('hud_replay.c','hud_native.c','hud_guidance.c','hud_arrow.c','vn_vbs.c','vendor/picojpeg/picojpeg.c')
    build=[args.compiler,'-std=gnu99','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'native')]
    if args.qemu: build+=['-static']
    subprocess.run(build+[str(ROOT/'native'/p) for p in sources]+['-o',str(binary)],check=True)
    command=([str(args.qemu)] if args.qemu else [])+[str(binary),str(out/'arrows.vna'),str(out/'frames.bin')]
    run=subprocess.run(command,capture_output=True,text=True,check=True,timeout=60)
    (out/'hud-raw.jsonl').write_text(run.stdout)
    events=[]
    for line in run.stdout.splitlines():
        row=json.loads(line)
        if row.get('type')!='hud': continue
        events.append(dict(type='guidance',schema=2,distance_encoding='display',icon=row['icon'],
                           distance=row['distanceValue']/10,unit=row['distanceUnit'],road=row['road'],
                           speed_limit=row['speedLimit'],speed_unit=row['speedUnit'],sync=row['sync'],
                           clear=not(row['icon'] or row['distanceValue'] or row['speedLimit'] or row['road'].strip()),
                           wire=row,source='native-replay-fake-oem-bus',physical_hud_verified=False))
    (out/'hud-events.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events))
    report=dict(mode='demo-from-owner-app-assets' if args.demo else 'replay',input_stats=statistics,
                messages=len(events),radio_tested=False,original_oem_bus_tested=False,physical_hud_verified=False,
                target='ARM/QEMU' if args.qemu else 'host')
    (out/'REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.render:
        subprocess.run([sys.executable,str(args.render),str(out/'hud-events.jsonl'),
                        '--out',str(out/'preview'),'--sheet'],check=True)
    print(json.dumps(report));print(out)


if __name__=='__main__': main()
