"""ESP32 portable code exercised against frozen SDK-format bytes, with ASan/UBSan."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hud_emulator.protocol import encode


class Esp32CodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='esp32-hud-test-')
        cls.binary=Path(cls.temp.name)/'codec'
        subprocess.run(['g++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror',
                        '-fsanitize=address,undefined','-fno-sanitize-recover=all',
                        '-I',str(ROOT/'emu/esp32-hud-emu/vmhud_emu'),
                        str(ROOT/'tests/esp32_hud_driver.cpp'),'-lcrypto','-o',str(cls.binary)],check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_codec(self,*args):
        result=subprocess.run([str(self.binary),*map(str,args)],text=True,capture_output=True,timeout=45,
                              env={**os.environ,'ASAN_OPTIONS':'detect_leaks=1'})
        self.assertEqual(result.returncode,0,result.stderr)
        return result.stdout.strip()

    def test_frozen_new_and_legacy_wire_vectors(self):
        self.assertEqual(self.run_codec('build',14,'new',0,'00'),
                         'a55a37c30000000e000000000e004dc64215c1c48da3')
        self.assertEqual(self.run_codec('build',2,'legacy',0,'ff'),'a55a37c50000000602ff3aa1')

    def test_cpp_wire_matches_independent_python_for_various_lengths(self):
        for legacy in (False,True):
            for size in (0,1,19,20,63,64,255,511):
                data=bytes(i%256 for i in range(size));protocol='legacy' if legacy else 'new'
                self.assertEqual(bytes.fromhex(self.run_codec('build',64,protocol,1234,data.hex())),
                                 encode(64,data,protocol=protocol,timestamp=1234))

    def test_every_split_boundary_and_two_families_of_frame(self):
        a=bytes.fromhex('a55a37c30000000e000000000e004dc64215c1c48da3')
        b=bytes.fromhex('a55a37c50000000602ff3aa1')
        for split in range(len(a)+1):
            output=self.run_codec('feed',a[:split].hex()+','+(a[split:]+b).hex())
            frames=[json.loads(line) for line in output.splitlines()]
            self.assertEqual([f['cmd'] for f in frames],[14,2])
            self.assertEqual([f['payload'] for f in frames],['00','ff'])

    def test_reject_corruption_and_hostile_lengths_then_resync(self):
        good=encode(14,b'\0');bad=bytearray(good);bad[-1]^=1
        prefix=bytes.fromhex('a55a37c3ffffffff')+bytes.fromhex('a55a37c30000000c')+bytes(bad)
        output=self.run_codec('feed',(prefix+good).hex())
        self.assertEqual(json.loads(output)['cmd'],14)

    @staticmethod
    def variable(second=False,image=None):
        # Direct fixture, not encoded by the C++ implementation under test.
        nxt='Nguyễn Huệ'.encode();cur='Lê Lợi'.encode()
        prefix=b'\x08'
        if second:
            prefix+=struct.pack('>I',len(image)) + image if image is not None else b'\0\0\0\x01\x01'
        return prefix+struct.pack('>I',300)+bytes([len(nxt)])+nxt+bytes([len(cur)])+cur+bytes.fromhex('0001023d000030390032')

    def test_utf8_variable_and_custom_arrow_keep_raw_time(self):
        for second,image in ((False,None),(True,None),(True,b'\xff\xd8JPEG\xff\xd9')):
            payload=self.variable(second,image)
            nav=json.loads(self.run_codec('nav',64 if second else 0,'new',payload.hex()))
            self.assertEqual(nav['distance'],300)
            self.assertEqual(bytes.fromhex(nav['next_hex']).decode(),'Nguyễn Huệ')
            self.assertEqual(nav['third_raw'],61)
            self.assertEqual(nav['layout'],'variable2' if second else 'variable1')

    def test_all_truncated_navigation_and_huge_image_rejected(self):
        for second in (False,True):
            payload=self.variable(second)
            for size in range(len(payload)):
                self.assertEqual(self.run_codec('nav',64 if second else 0,'new',payload[:size].hex()),'null')
        hostile=b'\x08'+bytes.fromhex('ffffffff')+bytes(32)
        self.assertEqual(self.run_codec('nav',64,'new',hostile.hex()),'null')

    def test_fixed_navigation_only_on_legacy_path(self):
        payload=b'\x08'+struct.pack('>I',300)+b'next'.ljust(80,b'\0')+b'current'.ljust(80,b'\0')+bytes.fromhex('00010203000030390032')
        nav=json.loads(self.run_codec('nav',0,'legacy',payload.hex()))
        self.assertEqual(nav['layout'],'fixed')
        self.assertEqual(nav['speed_raw'],50)
        self.assertEqual(self.run_codec('nav',64,'new',payload.hex()),'null')

    def test_fifty_thousand_malformed_inputs_under_sanitizers(self):
        self.assertIn('50000 malformed inputs PASS',self.run_codec('fuzz'))


if __name__=='__main__':
    unittest.main()
