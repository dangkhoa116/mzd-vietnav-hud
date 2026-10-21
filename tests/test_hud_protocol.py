"""Synthetic wire tests. These are not captures from a phone or a real HUD."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hud_emulator.protocol import (MAX_FRAME, StreamDecoder, crc16, decode, encode,
                                   event)

ROOT = Path(__file__).resolve().parents[1]


def navigation(protocol='new', direction=8, next_road='Đường Nguyễn Huệ', current='Lê Lợi'):
    first, second = next_road.encode(), current.encode()
    if protocol == 'legacy':
        roads = first.ljust(80, b'\0') + second.ljust(80, b'\0')
    else:
        roads = bytes([len(first)]) + first + bytes([len(second)]) + second
    # Independently specified field values, not emitted by the production codec.
    payload = bytes([direction]) + bytes.fromhex('0000012c') + roads
    payload += bytes.fromhex('00010203000030390032')
    return encode(0, payload, protocol=protocol, timestamp=1234)


class ProtocolTests(unittest.TestCase):
    def test_standard_crc_vector(self):
        self.assertEqual(crc16(b'123456789'), 0x4b37)

    def test_fixed_legacy_vector(self):
        raw = bytes.fromhex('a55a37c50000000602ff3aa1')
        self.assertEqual(decode(raw).payload, b'\xff')
        self.assertEqual(encode(2, b'\xff', protocol='legacy'), raw)

    def test_fixed_new_vector(self):
        # Frozen synthetic request; two checksums are sums of big-endian MD5 words.
        raw = bytes.fromhex('a55a37c30000000e000000000e004dc64215c1c48da3')
        f = decode(raw, uid=bytes(16))
        self.assertEqual((f.command, f.payload, f.uid_valid), (14, b'\0', True))
        self.assertEqual(encode(14, b'\0'), raw)

    def test_new_navigation_fields_and_utf8(self):
        e = event(decode(navigation()))
        self.assertEqual(e['next_road'], 'Đường Nguyễn Huệ')
        self.assertEqual(e['current_road'], 'Lê Lợi')
        self.assertEqual(e['turn_distance_m'], 300)
        self.assertEqual(e['remaining_distance_m'], 12345)
        self.assertEqual(e['speed_raw'], 50)
        self.assertEqual(e['direction_raw'], 8)
        self.assertEqual(e['remaining_time_third_raw'], 3)
        self.assertNotIn('remaining_seconds', e)
        self.assertIsNone(e['uid_valid'])

    def test_legacy_navigation(self):
        e = event(decode(navigation('legacy')))
        self.assertEqual(e['next_road'], 'Đường Nguyễn Huệ')
        self.assertEqual(e['current_road'], 'Lê Lợi')
        self.assertEqual(e['remaining_seconds'], 3723)

    def test_end_navigation(self):
        for protocol in ('new', 'legacy'):
            self.assertFalse(event(decode(navigation(protocol, 255)))['active'])

    def test_camera_and_heartbeat(self):
        for protocol in ('new', 'legacy'):
            e = event(decode(encode(1, bytes.fromhex('02012c3c'), protocol=protocol)))
            self.assertEqual((e['camera_type_raw'], e['distance_m'], e['speed_limit_raw']), (2, 300, 60))
            self.assertEqual(event(decode(encode(2, b'\xff\xff', protocol=protocol)))['speed_raw'], 65535)

    def test_every_fragment_boundary_and_coalesced_frames(self):
        first, second = navigation(), navigation('legacy')
        for boundary in range(len(first) + 1):
            s = StreamDecoder()
            frames = s.feed(first[:boundary]) + s.feed(first[boundary:] + second)
            self.assertEqual([f.protocol for f in frames], ['new', 'legacy'])
            self.assertFalse(s.buffer)

    def test_one_byte_fragments(self):
        s = StreamDecoder()
        frames = [f for byte in navigation() for f in s.feed(bytes([byte]))]
        self.assertEqual(len(frames), 1)

    def test_corruption_rejected_then_resync(self):
        for protocol in ('new', 'legacy'):
            bad = bytearray(navigation(protocol))
            bad[15] ^= 1
            s = StreamDecoder()
            frames = s.feed(bytes(bad) + encode(14, b'\0'))
            self.assertEqual([f.command for f in frames], [14])
            self.assertEqual(s.errors, 1)

    def test_runtime_uid_is_optional_but_never_claimed_verified(self):
        raw = encode(2, b'\0\x32', uid=b'A' * 16)
        self.assertIsNone(decode(raw).uid_valid)
        self.assertTrue(decode(raw, uid=b'A' * 16).uid_valid)
        with self.assertRaisesRegex(ValueError, 'runtime UID'):
            decode(raw, uid=bytes(16))

    def test_bounded_invalid_lengths(self):
        s = StreamDecoder()
        for n in (0, 1, 12, 0xffffffff):
            self.assertEqual(s.feed(bytes.fromhex('a55a37c3') + struct.pack('>I', n)), [])
        self.assertEqual(len(s.feed(encode(14, b'\0'))), 1)
        self.assertLess(len(s.buffer), 4)
        self.assertEqual(s.feed(b'X' * (MAX_FRAME + 1)), [])
        self.assertFalse(s.buffer)

    def test_malformed_road_lengths(self):
        for payload in (b'\0' * 16, b'\0' * 5 + b'\xff' + b'\0' * 11,
                        b'\0' * 6 + b'\xff' + b'\0' * 10):
            with self.assertRaises(ValueError):
                event(decode(encode(0, payload)))
        with self.assertRaises(ValueError):
            event(decode(encode(0, b'\0' * 174, protocol='legacy')))

    def test_truncated_legacy_utf8_is_explicit(self):
        f = decode(navigation('legacy'))
        p = f.payload[:5] + (b'a' * 79 + b'\xe1') + f.payload[85:]
        self.assertTrue(event(decode(encode(0, p, protocol='legacy')))['next_road'].endswith('\ufffd'))

    def test_unknown_command_preserved(self):
        e = event(decode(encode(0xee, b'\x01\xab')))
        self.assertEqual((e['type'], e['payload_hex']), ('unknown', '01ab'))

    def test_bad_frame_lengths_and_magic(self):
        raw = encode(14, b'\0')
        for bad in (b'', raw[:-1], raw + b'\0', b'XXXX' + raw[4:]):
            with self.assertRaises(ValueError):
                decode(bad)

    def test_cli_hex_replay(self):
        raw = navigation()
        r = subprocess.run([sys.executable, '-m', 'hud_emulator', 'decode'], cwd=ROOT,
                           input=raw[:7].hex() + '\n' + raw[7:].hex() + '\n',
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['next_road'], 'Đường Nguyễn Huệ')
        r = subprocess.run([sys.executable, '-m', 'hud_emulator', 'decode'], cwd=ROOT,
                           input=raw[:-1].hex(), capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
