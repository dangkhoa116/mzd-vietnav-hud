"""Native C peripheral tests against a fake controller; all wire fixtures synthetic."""
import ctypes as C
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hud_emulator.protocol import DEFAULT_UID, decode, encode, md5_sum


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='vietnav-native-')
        lib = Path(cls.work.name) / 'core.so'
        subprocess.run(['gcc', '-std=c99', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', '-fno-sanitize-recover=all', '-shared', '-fPIC',
                        '-I', str(ROOT / 'native'), str(ROOT / 'native/hud_native.c'),
                        str(ROOT / 'tests/native_driver.c'), '-o', str(lib)], check=True)
        cls.lib = C.CDLL(str(lib))
        cls.lib.test_caps.argtypes = [C.c_char_p, C.c_char_p, C.c_uint, C.c_uint, C.c_uint]
        cls.lib.test_start.argtypes = [C.c_int, C.c_ulonglong, C.c_uint]
        cls.lib.test_tick.argtypes = [C.c_ulonglong, C.c_int]
        cls.lib.test_reply.argtypes = [C.c_uint, C.c_uint, C.c_ulonglong]
        cls.lib.test_connect.argtypes = [C.c_uint, C.c_uint, C.c_uint, C.c_ulonglong]
        cls.lib.test_att.argtypes = [C.c_char_p, C.c_uint]
        cls.lib.vn_checksum.argtypes = [C.c_char_p, C.c_uint, C.c_char_p, C.c_void_p]

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def setUp(self):
        self.lib.test_reset()
        self.commands = bytearray(64)
        for bit in (205, 207, 208, 209):
            self.commands[bit // 8] |= 1 << (bit % 8)
        self.states = bytes.fromhex('ff0f000000000000')
        self.caps()
        self.now = 1000

    def caps(self, *, size=27, count=15, seen=7, states=None):
        self.lib.test_caps(bytes(self.commands), states or self.states, size, count, seen)

    def pop(self):
        b = C.create_string_buffer(40)
        n = self.lib.test_pop(b)
        return b.raw[:n]

    def tick(self, advance=200, allow=1):
        self.now += advance
        self.lib.test_tick(self.now, allow)

    def advertise(self):
        self.assertTrue(self.lib.test_start(1, self.now, 60000))
        commands = []
        for op in (0x2006, 0x2008, 0x2009, 0x200a):
            self.tick()
            packet = self.pop()
            self.assertEqual(int.from_bytes(packet[1:3], 'little'), op)
            commands.append(packet)
            self.lib.test_reply(op, 0, self.now)
        self.assertEqual(self.lib.test_state(), 2)
        return commands

    def connect(self):
        self.advertise()
        self.lib.test_connect(0, 0x41, 1, self.now)
        self.assertEqual(self.lib.test_state(), 3)

    def request(self, raw):
        self.lib.test_att(raw, len(raw))
        self.tick(1)
        packet = self.pop()
        if packet:
            self.assertEqual(packet[0], 2)
            self.assertLessEqual(len(packet), 32)
            self.assertEqual(packet[7:9], b'\x04\0')
            self.lib.test_completed(0x41, 1)
            return packet[9:]
        return b''

    def test_checksum_matches_python_at_md5_padding_boundaries(self):
        rng = random.Random(213)
        for length in (0, 1, 13, 39, 40, 47, 48, 63, 64, 65, 120, 175, 2040):
            data = rng.randbytes(length)
            for uid in (bytes(16), DEFAULT_UID, rng.randbytes(16)):
                out = C.create_string_buffer(4)
                self.lib.vn_checksum(data, len(data), uid, out)
                self.assertEqual(out.raw, md5_sum(data, uid))

    def test_query_does_not_transmit(self):
        self.assertTrue(self.lib.test_start(0, self.now, 60000))
        self.tick()
        self.assertFalse(self.pop())
        self.assertEqual(self.lib.test_state(), 5)

    def test_each_missing_capability_blocks_advertising(self):
        for bit in (205, 207, 208, 209):
            self.commands[bit // 8] ^= 1 << (bit % 8)
            self.caps()
            self.assertFalse(self.lib.test_ready())
            self.commands[bit // 8] ^= 1 << (bit % 8)
        for seen in (0, 1, 3, 5, 6):
            self.caps(seen=seen)
            self.assertFalse(self.lib.test_ready())
        for states in (bytes(8), b'\x04' + bytes(7), b'\x80' + bytes(7)):
            self.caps(states=states)
            self.assertFalse(self.lib.test_ready())
        for size, count in ((0, 0), (27, 0), (26, 1)):
            self.caps(size=size, count=count)
            self.assertFalse(self.lib.test_ready())

    def test_unsupported_does_not_transmit(self):
        self.caps(states=bytes(8))
        self.assertFalse(self.lib.test_start(1, self.now, 60000))
        self.tick()
        self.assertFalse(self.pop())

    def test_advertising_parameters_payload_and_name(self):
        params, ad, scan, enable = self.advertise()
        self.assertEqual(params[4:8], bytes.fromhex('a000f000'))
        self.assertEqual(params[8], 0)  # ADV_IND connectable undirected
        self.assertEqual(params[-2:], b'\x07\0')
        self.assertEqual(ad[4], 20)
        self.assertEqual(ad[5:12], bytes.fromhex('0201060303f0ff'))
        self.assertIn(b'VIETNAV HUD', ad)
        self.assertEqual(len(ad), 36)
        self.assertEqual(scan[4:], bytes(32))
        self.assertEqual(enable[4:], b'\1')

    def test_wait_for_command_reply_and_idle_gate(self):
        self.lib.test_start(1, self.now, 60000)
        self.tick(200, allow=0)
        self.assertFalse(self.pop())
        self.tick()
        self.assertTrue(self.pop())
        self.tick()
        self.assertFalse(self.pop())
        self.lib.test_reply(0x1234, 0, self.now)
        self.tick()
        self.assertFalse(self.pop())

    def test_controller_refusal_prevents_enable(self):
        self.lib.test_start(1, self.now, 60000)
        self.tick()
        self.pop()
        self.lib.test_reply(0x2006, 0x11, self.now)
        self.tick()
        self.assertFalse(self.pop())
        self.assertEqual(self.lib.test_state(), 6)

    def test_unanswered_enable_gets_explicit_cleanup(self):
        self.lib.test_start(1, self.now, 60000)
        for op in (0x2006, 0x2008, 0x2009):
            self.tick(); self.pop(); self.lib.test_reply(op, 0, self.now)
        self.tick(); self.pop()
        self.tick(3001)
        self.assertEqual(self.pop(), bytes.fromhex('010a200100'))
        self.lib.test_reply(0x200a, 0, self.now)
        self.tick()
        self.assertEqual(self.lib.test_state(), 6)

    def test_expiration_disables_advertising(self):
        self.advertise()
        self.tick(60000)
        self.assertEqual(self.pop(), bytes.fromhex('010a200100'))
        self.lib.test_reply(0x200a, 0, self.now)
        self.tick()
        self.assertEqual(self.lib.test_state(), 5)

    def test_stop_while_enable_reply_pending_still_disables_advertising(self):
        self.lib.test_start(1, self.now, 60000)
        for op in (0x2006, 0x2008, 0x2009):
            self.tick(); self.pop(); self.lib.test_reply(op, 0, self.now)
        self.tick(); self.pop()
        self.lib.test_stop()
        self.lib.test_reply(0x200a, 0, self.now)
        self.tick()
        self.assertEqual(self.pop(), bytes.fromhex('010a200100'))

    def test_connection_before_enable_ack_keeps_connected_state(self):
        self.lib.test_start(1, self.now, 60000)
        for op in (0x2006, 0x2008, 0x2009):
            self.tick(); self.pop(); self.lib.test_reply(op, 0, self.now)
        self.tick(); self.pop()
        self.lib.test_connect(0, 0x41, 1, self.now)
        self.lib.test_reply(0x200a, 0, self.now)
        self.assertEqual(self.lib.test_state(), 3)

    def test_wrong_role_is_claimed_for_disconnect_cleanup(self):
        self.advertise()
        self.lib.test_connect(0, 0x41, 0, self.now)
        self.assertEqual(self.lib.test_handle(), 0x41)
        self.tick()
        self.assertEqual(self.pop(), bytes.fromhex('01060403410013'))

    def test_cleanup_waits_for_disconnect_event(self):
        self.connect()
        self.lib.test_stop()
        self.tick()
        self.assertEqual(self.pop(), bytes.fromhex('01060403410013'))
        self.lib.test_reply(0x0406, 0, self.now)
        self.tick()
        self.assertEqual(self.lib.test_state(), 4)
        self.lib.test_disconnect(0x41)
        self.tick()
        self.assertEqual(self.lib.test_state(), 5)

    def test_service_and_characteristic_discovery(self):
        self.connect()
        self.assertEqual(self.request(bytes.fromhex('100100ffff0028')),
                         bytes.fromhex('110601000500001806000600011807001100f0ff'))
        self.assertEqual(self.request(bytes.fromhex('060100ffff0028f0ff')),
                         bytes.fromhex('0707001100'))
        self.assertEqual(self.request(bytes.fromhex('08070011000328')),
                         bytes.fromhex('09070800120900f1ff0b000c0c00f2ff0d000c0e00f3ff'))
        self.assertEqual(self.request(bytes.fromhex('080e0011000328')),
                         bytes.fromhex('09070f00101000f4ff'))
        self.assertEqual(self.request(bytes.fromhex('0409001100')),
                         bytes.fromhex('05010900f1ff0a0002290b0003280c00f2ff0d000328'))

    def test_mtu_read_blob_and_att_errors(self):
        self.connect()
        self.assertEqual(self.request(bytes.fromhex('020002')), bytes.fromhex('031700'))
        self.assertEqual(self.request(bytes.fromhex('0a0300')), b'\x0bVIETNAV HUD')
        self.assertEqual(self.request(bytes.fromhex('0c03000800')), b'\x0dHUD')
        for raw, err in (('0c03000c00', '010c030007'), ('0a0c00', '010a0c0002'),
                         ('0a0000', '010a000001'), ('040000ffff', '0104000001'),
                         ('100100ffff0228', '0110010010'), ('120a000200', '01120a0013'),
                         ('120a0001', '01120a000d'), ('1612000000', '0116000006')):
            self.assertEqual(self.request(bytes.fromhex(raw)), bytes.fromhex(err))

    def test_info_handshake_fragments_cccd_and_checksum(self):
        self.connect()
        raw = encode(14, b'\0', timestamp=1792584000)
        self.assertFalse(self.request(b'\x52\x0c\0' + raw[:20]))
        self.assertFalse(self.request(b'\x52\x0c\0' + raw[20:]))
        self.assertEqual(self.request(bytes.fromhex('120a000100')), b'\x13')
        data = b''
        for _ in range(10):
            self.tick(1)
            packet = self.pop()
            if not packet:
                break
            self.assertEqual(packet[9:12], b'\x1b\x09\0')
            data += packet[12:]
            self.lib.test_completed(0x41, 1)
        frame = decode(data, uid=bytes(16))
        self.assertEqual(frame.command, 14)
        self.assertEqual(frame.timestamp, 1792584000)
        self.assertEqual(frame.payload, b'MODEL:VIETNAV,HW:0,FW:0,PROTOCOL:2.0')

    def test_acl_credit_is_required_and_wrong_handle_cannot_release_it(self):
        self.connect()
        self.lib.test_att(bytes.fromhex('0a0300'), 3)
        self.tick(1)
        self.assertTrue(self.pop())
        self.lib.test_att(bytes.fromhex('0a0500'), 3)
        self.tick(1)
        self.assertFalse(self.pop())
        self.lib.test_completed(0x42, 99)
        self.tick(1)
        self.assertFalse(self.pop())
        self.lib.test_completed(0x41, 1)
        self.tick(1)
        self.assertEqual(self.pop()[9:], bytes.fromhex('0b0000'))

    def test_disconnect_discards_fragments_and_pending_notifications(self):
        self.connect()
        raw = encode(14, b'\0')
        self.request(b'\x52\x0c\0' + raw[:10])
        self.lib.test_disconnect(0x42)
        self.assertEqual(self.lib.test_handle(), 0x41)
        self.lib.test_disconnect(0x41)
        self.assertEqual(self.lib.test_handle(), -1)
        self.tick()
        self.assertFalse(self.pop())

    def test_bad_checksum_and_unknown_command_do_not_generate_info(self):
        self.connect()
        self.request(bytes.fromhex('120a000100'))
        for raw in (encode(0xee, b'\0'), encode(14, b'\0')[:-1] + b'\xaa'):
            for off in range(0, len(raw), 20):
                self.assertFalse(self.request(b'\x52\x0c\0' + raw[off:off + 20]))
        self.tick()
        self.assertFalse(self.pop())

    def test_queue_overflow_and_uart_failure_stop(self):
        self.connect()
        for _ in range(17):
            self.lib.test_att(b'\x0a\x03\0', 3)
        self.assertEqual(self.lib.test_state(), 4)
        self.setUp(); self.connect()
        self.lib.test_reject_send(1)
        self.lib.test_att(b'\x0a\x03\0', 3)
        self.tick()
        self.assertEqual(self.lib.test_state(), 4)

    def test_malformed_att_fuzz(self):
        rng = random.Random(45)
        for _ in range(1000):
            self.setUp(); self.connect()
            raw = rng.randbytes(rng.randrange(40))
            self.request(raw)


if __name__ == '__main__':
    unittest.main()
