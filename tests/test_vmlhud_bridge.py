import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bridge import vmlhud_frame as wire, vmlhud_nav as nav
from hud_emulator.protocol import encode,decode

spec=importlib.util.spec_from_file_location('esp_log',ROOT/'emu/esp32-hud-emu/decode_log.py')
capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)


class BridgeRegressionTests(unittest.TestCase):
    def test_frozen_sdk_wire_vectors(self):
        new=bytes.fromhex('a55a37c30000000e000000000e004dc64215c1c48da3')
        legacy=bytes.fromhex('a55a37c50000000602ff3aa1')
        self.assertEqual(wire.build(14,b'\0',timestamp=0),new)
        self.assertEqual(wire.build(2,b'\xff',protocol='legacy'),legacy)
        self.assertEqual(wire.parse(new)['payload'],b'\0')
        self.assertEqual(wire.parse(legacy)['cmd'],2)

    def test_bridge_matches_native_python_and_runtime_uid_optional(self):
        for protocol in ('legacy','new'):
            for size in (0,1,19,64,255,511):
                payload=bytes(i%256 for i in range(size))
                frame=wire.build(64,payload,timestamp=123,protocol=protocol)
                self.assertEqual(frame,encode(64,payload,timestamp=123,protocol=protocol))
                self.assertEqual(decode(frame).payload,payload)
        frame=wire.build(2,b'\0\x32',uid=b'A'*16)
        self.assertIsNone(wire.parse(frame)['uid_valid'])
        self.assertTrue(wire.parse(frame,uid=b'A'*16)['uid_valid'])
        with self.assertRaises(wire.FrameError):wire.parse(frame,uid=bytes(16))

    def test_hostile_lengths_and_bad_checksum_resync(self):
        good=encode(14,b'\0');bad=bytearray(good);bad[-1]^=1
        frames,rest=wire.split_stream(bytes.fromhex('a55a37c3ffffffff')+bad+good)
        self.assertEqual([f['cmd'] for f in frames],[14]);self.assertEqual(rest,b'')
        with self.assertRaises(wire.FrameError):wire.parse(good+b'EXTRA')

    def test_navigation_truncation_and_road_lengths_have_value_errors(self):
        value=nav.NavInfo(direction=8,current_road='Lê Lợi',next_road='Nguyễn Huệ',remain_time_s=1234)
        for builder,decoder in ((nav.build_nav_variable,nav.decode_nav_variable),(nav.build_nav_variable2,nav.decode_nav_variable2)):
            payload=builder(value)
            for size in range(len(payload)):
                with self.assertRaises(ValueError):decoder(payload[:size])
        with self.assertRaises(ValueError):nav.decode_nav_variable(b'\0'*5+b'\xff'+b'\0'*20)
        with self.assertRaises(ValueError):nav.decode_nav_variable2(b'\0'+b'\xff'*4+b'\0'*20)

    def test_variable_time_third_byte_is_seconds_and_round_trips(self):
        # Byte thu ba cua duoi variable la GIAY: builder Android W7/e tag 5 ghi
        # total % 60, va hai mau that tu iOS 3.4.3 khop ETA tren man hinh app
        # (25p38s va 37p52s). Xem docs/vmlhud-nav-payloads.md muc 10.
        payload=b'\x08'+struct.pack('>I',300)+b'\0\0'+bytes.fromhex('000102250000303900 32'.replace(' ',''))
        value=nav.decode_nav(payload,cmd=0,protocol='new')
        self.assertEqual((value.remain_hours,value.remain_minutes,value.remain_time_third_raw),(1,2,37))
        self.assertEqual(value.remain_time_s,1*3600+2*60+37)
        self.assertEqual(nav.build_nav_variable(value),payload)

    def test_variable_time_out_of_range_third_byte_round_trips_unchanged(self):
        # Byte thu ba >59 chua tung thay tren song; builder van phai tra lai
        # dung byte goc thay vi chuan hoa sang 1h03m01s.
        payload=b'\x08'+struct.pack('>I',300)+b'\0\0'+bytes.fromhex('0001023d000030390032')
        value=nav.decode_nav(payload,cmd=0,protocol='new')
        self.assertEqual(value.remain_time_third_raw,61)
        self.assertEqual(nav.build_nav_variable(value),payload)

    def test_capture_reassembly_and_family_routes(self):
        first=encode(14,b'\0');second=encode(2,b'\0\x32')
        lines=['[BLE] connected\n',f'[W:FFF2] 10 byte: {first[:10].hex()}\n',
               f'[W:9ABC] {len(second)} byte: {second.hex()}\n',f'[W:FFF2] {len(first)-10} byte: {first[10:].hex()}\n']
        events=list(capture.decode_lines(lines))
        self.assertEqual([(e['stream'],e['type']) for e in events],[('H50','heartbeat'),('H1','hud_info_request')])
        self.assertTrue(all(e['session']==1 for e in events))

    def test_capture_does_not_join_across_connections_or_hide_truncation(self):
        frame=encode(14,b'\0')
        events=list(capture.decode_lines(['[BLE] connected\n',f'[W:FFF2] 10 byte: {frame[:10].hex()}\n',
                                         '[BLE] disconnected\n','[BLE] connected\n',
                                         f'[W:FFF2] 22 byte: {frame.hex()}\n']))
        self.assertEqual([e['type'] for e in events],['incomplete_frame','hud_info_request'])
        self.assertEqual(events[-1]['session'],2)
        self.assertEqual(list(capture.decode_lines(['[W:FFF2] 99 byte: 00\n']))[0]['type'],'capture_error')


if __name__=='__main__':unittest.main()
