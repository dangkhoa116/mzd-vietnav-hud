#!/usr/bin/env python3
"""Decode the C3 sketch's Serial [W:FFF2/FFF3/9ABC] records to JSON Lines."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from bridge import vmlhud_frame as wire
from bridge import vmlhud_nav as nav

WRITE=re.compile(r'\[W:(FFF2|FFF3|9ABC)\]\s+(\d+) byte:\s*([0-9a-fA-F]*)\s*$')


def decode_lines(lines):
    buffers={'H1':b'','H50':b''}
    session=None
    for number,line in enumerate(lines,1):
        if line.startswith(('[BLE] connected','[BLE] disconnected')):
            for stream,remaining in buffers.items():
                if remaining:
                    yield dict(type='incomplete_frame',session=session,stream=stream,buffered_bytes=len(remaining),line=number)
            buffers={'H1':b'','H50':b''}
            if line.startswith('[BLE] connected'):
                session=1 if session is None else session+1
            continue
        match=WRITE.search(line)
        if not match:
            continue
        stream='H50' if match[1]=='9ABC' else 'H1'
        try:
            chunk=bytes.fromhex(match[3])
            if len(chunk)!=int(match[2]) or len(chunk)>wire.MAX_FRAME:
                raise ValueError('serial write length mismatch or oversize')
        except ValueError as exc:
            buffers[stream]=b''
            yield dict(type='capture_error',line=number,stream=stream,error=str(exc))
            continue
        frames,buffers[stream]=wire.split_stream(buffers[stream]+chunk)
        for frame in frames:
            event=dict(session=session,stream=stream,command=frame['cmd'],protocol=frame['protocol'],
                       timestamp=frame['timestamp'],uid_valid=frame['uid_valid'])
            payload=frame['payload']
            try:
                if frame['cmd'] in (0,0x40):
                    value=nav.decode_nav(payload,cmd=frame['cmd'],protocol=frame['protocol'])
                    event.update(type='navigation',layout=value.layout,direction_raw=value.direction,
                                 turn_distance_m=value.distance_m,current_road=value.current_road,next_road=value.next_road,
                                 remaining_distance_m=value.remain_dist_m,remaining_seconds=value.remain_time_s,
                                 remaining_hours=value.remain_hours,remaining_minutes=value.remain_minutes,
                                 remaining_time_third_raw=value.remain_time_third_raw,speed_raw=value.speed_kmh)
                elif frame['cmd']==14:
                    event.update(type='hud_info_request' if payload==b'\0' else 'hud_info',text=payload.decode('utf-8','replace'))
                elif frame['cmd']==1 and len(payload)==4:
                    event.update(type='camera',camera_type_raw=payload[0],distance_m=int.from_bytes(payload[1:3],'big'),speed_limit_raw=payload[3])
                elif frame['cmd']==2 and len(payload) in (1,2):
                    event.update(type='heartbeat',speed_raw=int.from_bytes(payload,'big'))
                else:
                    event.update(type='unknown',payload_hex=payload.hex())
            except ValueError as exc:
                event.update(type='payload_error',error=str(exc),payload_hex=payload.hex())
            yield event
    for stream,remaining in buffers.items():
        if remaining:
            yield dict(type='incomplete_frame',session=session,stream=stream,buffered_bytes=len(remaining))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    args=parser.parse_args()
    with args.capture.open(encoding='utf-8',errors='replace') as lines:
        for event in decode_lines(lines):
            print(json.dumps(event,ensure_ascii=False))


if __name__=='__main__':
    main()
