"""Guidance pipeline tests: nav decode parity against the Python bridge, the
GuidanceBuilder port, Vietnamese HUD-font normalization, the vn_vbs sender
against a capturing fake backend, and the full wire path (ATT writes ->
framed nav -> guidance callback). All fixtures synthetic; no D-Bus, no radio."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'bridge'))
from hud_emulator.protocol import DEFAULT_UID, encode
import vmlhud_nav as py_nav
import vmlhud_vbs as py_vbs


class GuidanceStruct(C.Structure):
    _fields_ = [('icon', C.c_uint32), ('distance', C.c_uint32), ('unit', C.c_uint32),
                ('speed_limit', C.c_uint32), ('sync', C.c_uint32),
                ('clear', C.c_uint8), ('road', C.c_char * 256)]


def _compile(name, sources):
    work = tempfile.mkdtemp(prefix='vietnav-guide-')
    lib = Path(work) / name
    cc = ['gcc'] if shutil.which('gcc') else [sys.executable, '-m', 'ziglang', 'cc']
    subprocess.run(cc + ['-std=c99', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                         '-fsanitize=undefined', '-fno-sanitize-recover=all', '-shared', '-fPIC',
                         '-I', str(ROOT / 'native')] +
                   [str(ROOT / 'native' / src) for src in sources] + ['-o', str(lib)], check=True)
    return lib, work


def _unload(lib, work):
    try:
        import ctypes.wintypes
        C.WinDLL('kernel32').FreeLibrary(lib._handle)
    except Exception:
        pass
    try:
        shutil.rmtree(work)
    except OSError:
        pass


class GuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native = ROOT / 'native'
        cls.vbs_lib, cls.vbs_work = _compile(
            'vbs.so', ['hud_guidance.c', 'vn_vbs.c', '../tests/guidance_driver.c'])
        cls.lib = C.CDLL(str(cls.vbs_lib))
        lib = cls.lib
        lib.gd_decode.argtypes = [C.c_char_p, C.c_uint]
        for getter in ('gd_distance', 'gd_remain_time', 'gd_remain_dist', 'gd_speed',
                       'gd_limit', 'gd_direction', 'gd_layout'):
            getattr(lib, getter).restype = C.c_uint
        lib.gd_road.argtypes = [C.c_int, C.c_char_p, C.c_uint]
        lib.gd_feed.argtypes = [C.c_uint, C.c_char_p, C.c_char_p, C.c_uint, C.c_uint,
                                C.POINTER(GuidanceStruct)]
        lib.gd_normalize.argtypes = [C.c_char_p, C.c_char_p, C.c_uint]
        lib.gd_normalize.restype = C.c_uint
        lib.vn_vbs_guide.argtypes = [C.POINTER(GuidanceStruct)]
        lib.vn_vbs_guide.restype = C.c_int
        for getter in ('gd_vbs_created', 'gd_vbs_connected', 'gd_vbs_started',
                       'gd_vbs_worker_stopped', 'gd_vbs_disconnected', 'gd_vbs_freed',
                       'gd_vbs_bus', 'gd_vbs_msg_calls', 'gd_vbs_msg2_calls',
                       'gd_vbs_disp_icon', 'gd_vbs_disp_distance', 'gd_vbs_disp_unit',
                       'gd_vbs_disp_limit', 'gd_vbs_disp_limit_unit', 'gd_vbs_disp_sync',
                       'gd_vbs_msg2_sync'):
            getattr(lib, getter).restype = C.c_int
        lib.gd_vbs_name.argtypes = [C.c_char_p, C.c_uint]
        lib.gd_vbs_road.argtypes = [C.c_char_p, C.c_uint]
        lib.gd_vbs_last_log.argtypes = [C.c_char_p, C.c_uint]
        lib.gd_vbs_set_fail.argtypes = [C.c_int, C.c_int]
        lib.gd_vbs_set_status.argtypes = [C.c_ubyte]

    @classmethod
    def tearDownClass(cls):
        _unload(cls.lib, cls.vbs_work)

    def setUp(self):
        self.lib.gd_vbs_reset()

    # -- decode parity -------------------------------------------------

    def _assert_decode_parity(self, cmd, payload):
        expected = py_nav.decode_nav(payload, cmd)
        self.assertEqual(self.lib.gd_decode(bytes([cmd]) + payload, len(payload) + 1), 1)
        self.assertEqual(self.lib.gd_distance(), expected.distance_m)
        self.assertEqual(self.lib.gd_remain_time(), expected.remain_time_s)
        self.assertEqual(self.lib.gd_remain_dist(), expected.remain_dist_m)
        self.assertEqual(self.lib.gd_speed(), expected.speed_kmh)
        self.assertEqual(self.lib.gd_direction(), expected.direction)
        out = C.create_string_buffer(300)
        self.lib.gd_road(0, out, 300)
        self.assertEqual(out.value.decode(), expected.next_road)
        self.lib.gd_road(1, out, 300)
        self.assertEqual(out.value.decode(), expected.current_road)

    def test_decode_parity_variable2(self):
        for distance, nxt, cur in ((150, 'Nguyễn Văn Linh', 'Quốc Lộ 13'),
                                   (8300, 'Xa lộ Hà Nội', 'Đường số 5'),
                                   (0, '', '')):
            nav = py_nav.NavInfo(direction=0xfe, distance_m=distance,
                                 next_road=nxt, current_road=cur,
                                 remain_hours=0, remain_minutes=12,
                                 remain_time_third_raw=34,
                                 remain_dist_m=distance + 900, speed_kmh=42)
            self._assert_decode_parity(0x40, py_nav.build_nav_variable2(nav))

    def test_decode_parity_variable2_with_image(self):
        # variable v2 carrying a custom JPEG: distance follows the image block
        jpeg = bytes(range(256))
        payload = bytes([0xfe]) + struct.pack('>I', len(jpeg)) + jpeg + \
            struct.pack('>I', 150) + bytes([13]) + ' Lê Văn Việt '.encode() + \
            bytes([10]) + 'Võ Văn Tần'.encode() + struct.pack('>HBB', 1, 2, 3) + \
            struct.pack('>IH', 4242, 55)
        self._assert_decode_parity(0x40, payload)

    def test_decode_parity_fixed_and_variable1(self):
        for nav in (py_nav.NavInfo(direction=0xfe, distance_m=450,
                                   next_road='Lý Thường Kiệt', current_road='Hai Bà Trưng',
                                   remain_hours=1, remain_minutes=5,
                                   remain_time_third_raw=0, remain_dist_m=9000,
                                   speed_kmh=33),
                    py_nav.NavInfo(direction=0xfe, distance_m=0xffffffff,
                                   next_road='', current_road='',
                                   remain_hours=0, remain_minutes=0,
                                   remain_time_third_raw=0, remain_dist_m=0,
                                   speed_kmh=0)):
            self._assert_decode_parity(0x00, py_nav.build_nav_fixed(nav))
            self._assert_decode_parity(0x00, py_nav.build_nav_variable(nav))

    def test_decode_rejects_garbage(self):
        self.assertEqual(self.lib.gd_decode(b'\x00\x01', 2), 0)
        self.assertEqual(self.lib.gd_decode(b'\x0e\x00' + b'\x00' * 4, 6), 0)
        self.assertEqual(self.lib.gd_decode(b'\x00' * 10, 10), 0)

    # -- guidance builder parity ----------------------------------------

    def _c_feed(self, distance, nxt, cur='', limit=0, icon_hint=0):
        out = GuidanceStruct()
        emitted = self.lib.gd_feed(distance, nxt.encode(), cur.encode(), limit,
                                   icon_hint, C.byref(out))
        return emitted, out

    def test_guide_sequence_matches_python(self):
        builder = py_vbs.GuidanceBuilder()
        self.lib.gd_feed_reset()
        seq = [
            (150, '', '', 0),
            (150, 'Nguyen Van Linh', 'Le Dai Hanh', 0),
            (150, 'Nguyen Van Linh', 'Le Dai Hanh', 0),
            (100, 'Nguyen Van Linh', 'Le Dai Hanh', 0),
            (8300, 'Xa lo Ha Noi', 'Le Dai Hanh', 0),
            (0xffffffff, '', '', 0),
            (0xffffffff, '', '', 0),
            (120, 'Quốc Lộ 13', '', 0),
        ]
        for distance, nxt, cur, limit in seq:
            nav = py_nav.NavInfo(direction=0xfe, distance_m=distance,
                                 next_road=nxt, current_road=cur)
            want = builder.feed(nav)
            emitted, got = self._c_feed(distance, nxt, cur, limit)
            self.assertEqual(bool(emitted), want is not None, (distance, nxt))
            if want is None:
                continue
            self.assertEqual(got.icon, want.icon)
            self.assertEqual(got.distance, want.distance)
            self.assertEqual(got.unit, want.unit)
            self.assertEqual(got.sync, want.sync)
            self.assertEqual(bool(got.clear), want.clear)
            if not want.clear and nxt.isascii():
                self.assertEqual(got.road.decode(), want.road)
        # The Vietnamese case keeps the same maneuver fields but the road is
        # normalized for the cluster font (tone marks dropped): ố -> ô.
        emitted, got = self._c_feed(120, 'Quốc Lộ 13', '')
        self.assertEqual(emitted, 0)  # deduped against the normalized key
        self.lib.gd_feed_reset()
        emitted, got = self._c_feed(120, 'Quốc Lộ 13', '')
        self.assertEqual(emitted, 1)
        self.assertEqual(got.road.decode(), 'Quôc Lô 13')

    def test_guide_icon_hint_and_hold_last(self):
        self.lib.gd_feed_reset()
        emitted, got = self._c_feed(200, 'Trần Hưng Đạo', icon_hint=3)
        self.assertTrue(emitted)
        self.assertEqual(got.icon, 3)
        # No hint on the next push: hold the last icon, not straight.
        emitted, got = self._c_feed(100, 'Trần Hưng Đạo', icon_hint=0)
        self.assertTrue(emitted)
        self.assertEqual(got.icon, 3)
        self.assertEqual(got.distance, 100)

    def test_map_distance_rounds_half_to_even_like_python(self):
        self.lib.vn_map_distance.argtypes = [C.c_uint32, C.POINTER(C.c_uint32)]
        self.lib.vn_map_distance.restype = C.c_uint32
        unit = C.c_uint32()
        for meters in (0, 999, 1000, 1004, 1049, 1050, 1150, 1250, 8300, 9999, 100000):
            want_value, want_unit = py_vbs.map_distance(meters)
            self.assertEqual(self.lib.vn_map_distance(meters, C.byref(unit)), want_value,
                             meters)
            self.assertEqual(unit.value, want_unit, meters)

    # -- Vietnamese normalization ----------------------------------------

    def test_normalize_vietnamese_for_hud_font(self):
        cases = {
            'về hướng Gia Mô': 'vê hương Gia Mô',
            'Đường ống': 'Đương ông',
            'Quốc Lộ 13': 'Quôc Lô 13',
            'ascii only 123': 'ascii only 123',
            'ô â ă đ ư ơ': 'ô â ă đ ư ơ',
            '中': '?',
            'hàng 中 kết': 'hàng ? kêt',
        }
        for src, want in cases.items():
            out = C.create_string_buffer(300)
            self.lib.gd_normalize(src.encode(), out, 300)
            self.assertEqual(out.value.decode(), want, src)

    def test_normalize_never_splits_a_sequence(self):
        src = 'a' * 250 + 'ề'
        out = C.create_string_buffer(256)
        written = self.lib.gd_normalize(src.encode(), out, 256)
        # the 3-byte tone char maps to 2-byte ê, so the buffer holds 252 bytes
        self.assertEqual(written, 252)
        self.assertEqual(out.value.decode(), 'a' * 250 + 'ê')

    # -- vn_vbs sender against the fake backend --------------------------

    def _guide(self, **kwargs):
        defaults = dict(icon=1, distance=150, unit=1, speed_limit=0, sync=0, clear=0,
                        road=b'Le Dai Hanh')
        defaults.update(kwargs)
        rec = GuidanceStruct(**defaults)
        return self.lib.vn_vbs_guide(C.byref(rec))

    def test_sender_lazy_connect_and_pairing(self):
        self.assertEqual(self.lib.vn_vbs_guide.restype, C.c_int)
        self.assertEqual(self._guide(), 0)
        self.assertEqual(self.lib.gd_vbs_created(), 1)
        self.assertEqual(self.lib.gd_vbs_connected(), 1)
        name = C.create_string_buffer(80)
        self.lib.gd_vbs_name(name, 80)
        self.assertEqual(name.value.decode(), 'com.jci.vietnav.hud')
        self.assertEqual(self.lib.gd_vbs_bus(), 0)
        self.assertEqual(self.lib.gd_vbs_started(), 1)
        # Msg1 and Msg2 always go out together, in that order.
        self.assertEqual(self.lib.gd_vbs_msg_calls(), 1)
        self.assertEqual(self.lib.gd_vbs_msg2_calls(), 1)
        self.assertEqual(self.lib.gd_vbs_disp_icon(), 1)
        self.assertEqual(self.lib.gd_vbs_disp_distance(), 150)
        self.assertEqual(self.lib.gd_vbs_disp_unit(), 1)
        self.assertEqual(self.lib.gd_vbs_disp_limit(), 0)
        self.assertEqual(self.lib.gd_vbs_disp_limit_unit(), 0)
        self.assertEqual(self.lib.gd_vbs_disp_sync(), self.lib.gd_vbs_msg2_sync())
        road = C.create_string_buffer(320)
        self.lib.gd_vbs_road(road, 320)
        self.assertEqual(road.value.decode(), 'Le Dai Hanh')

    def test_sender_speed_limit_roundel(self):
        self.assertEqual(self._guide(speed_limit=3, sync=2), 0)
        self.assertEqual(self.lib.gd_vbs_disp_limit(), 3)
        self.assertEqual(self.lib.gd_vbs_disp_limit_unit(), 1)

    def test_sender_blank_road_becomes_single_space(self):
        self._guide(road=b'')
        road = C.create_string_buffer(320)
        self.lib.gd_vbs_road(road, 320)
        self.assertEqual(road.value, b' ')

    def test_sender_clear_blanks_every_field(self):
        self._guide()
        before = self.lib.gd_vbs_msg_calls()
        self._guide(clear=1, road=b'')
        self.assertEqual(self.lib.gd_vbs_msg_calls(), before + 1)
        self.assertEqual(self.lib.gd_vbs_disp_icon(), 0)
        self.assertEqual(self.lib.gd_vbs_disp_distance(), 0)
        self.assertEqual(self.lib.gd_vbs_disp_unit(), 0)
        road = C.create_string_buffer(320)
        self.lib.gd_vbs_road(road, 320)
        self.assertEqual(road.value, b' ')

    def test_sender_stop_wipes_and_releases_then_reconnects(self):
        self._guide()
        self.lib.vn_vbs_stop()
        self.assertEqual(self.lib.gd_vbs_worker_stopped(), 1)
        self.assertEqual(self.lib.gd_vbs_disconnected(), 1)
        self.assertEqual(self.lib.gd_vbs_freed(), 1)
        self.assertEqual(self.lib.vn_vbs_active(), 0)
        self.assertEqual(self._guide(), 0)
        self.assertEqual(self.lib.gd_vbs_created(), 2)

    def test_sender_hud_absent_gate_is_fail_open(self):
        self._guide()
        self.lib.gd_vbs_set_status(0)
        self.lib.vn_vbs_stop()
        held = self.lib.gd_vbs_msg_calls()
        self.assertEqual(self._guide(), 0)
        self.assertEqual(self.lib.gd_vbs_msg_calls(), held)

    def test_sender_transport_failures(self):
        # A failed create latches for the session (no retry storm); a fresh
        # bind re-arms it, like a restarted trial.
        self.lib.gd_vbs_set_fail(0, 1)
        self.assertEqual(self._guide(), -1)
        self.assertEqual(self.lib.gd_vbs_msg_calls(), 0)
        self.lib.gd_vbs_reset()
        self.lib.gd_vbs_set_fail(2, 1)
        self.assertEqual(self._guide(), -1)
        self.assertEqual(self.lib.gd_vbs_msg_calls(), 0)
        self.assertEqual(self.lib.gd_vbs_msg2_calls(), 0)
        self.lib.gd_vbs_reset()
        self.assertEqual(self._guide(), 0)

    def test_sender_unbound_is_inert(self):
        self.lib.gd_vbs_unbind()
        self.assertEqual(self._guide(), -1)
        self.assertEqual(self.lib.gd_vbs_created(), 0)


class WireGuidanceTests(unittest.TestCase):
    """Full stack: ATT writes -> frame reassembly -> decode -> guide callback."""

    @classmethod
    def setUpClass(cls):
        cls.core_lib, cls.core_work = _compile(
            'core.so', ['hud_native.c', 'hud_guidance.c', '../tests/native_driver.c'])
        cls.lib = C.CDLL(str(cls.core_lib))
        lib = cls.lib
        lib.test_caps.argtypes = [C.c_char_p, C.c_char_p, C.c_uint, C.c_uint, C.c_uint]
        lib.test_start.argtypes = [C.c_int, C.c_ulonglong, C.c_uint]
        lib.test_tick.argtypes = [C.c_ulonglong, C.c_int]
        lib.test_reply.argtypes = [C.c_uint, C.c_uint, C.c_ulonglong]
        lib.test_connect.argtypes = [C.c_uint, C.c_uint, C.c_uint, C.c_ulonglong]
        lib.test_att.argtypes = [C.c_char_p, C.c_uint]
        lib.test_completed.argtypes = [C.c_uint, C.c_uint]
        lib.test_pop.argtypes = [C.c_char_p]
        lib.test_guide_at.restype = C.POINTER(GuidanceStruct)

    @classmethod
    def tearDownClass(cls):
        try:
            import ctypes.wintypes
            C.WinDLL('kernel32').FreeLibrary(cls.lib._handle)
        except Exception:
            pass
        try:
            shutil.rmtree(cls.core_work)
        except OSError:
            pass

    def setUp(self):
        self.lib.test_reset()
        commands = bytearray(64)
        for bit in (205, 207, 208, 209):
            commands[bit // 8] |= 1 << (bit % 8)
        self.lib.test_caps(bytes(commands), bytes.fromhex('ff0f000000000000'), 27, 15, 7)
        self.now = 1000
        self.assertTrue(self.lib.test_start(1, self.now, 60000))
        for op in (0x2006, 0x2008, 0x2009, 0x200a):
            self.now += 200
            self.lib.test_tick(self.now, 1)
            self.lib.test_reply(op, 0, self.now)
        self.lib.test_connect(0, 0x41, 1, self.now)
        self.assertEqual(self.lib.test_state(), 3)

    def _write_handle(self, handle, data):
        for off in range(0, len(data), 20):
            chunk = data[off:off + 20]
            self.lib.test_att(b'\x12' + struct.pack('<H', handle) + chunk, 3 + len(chunk))
            self.now += 1
            self.lib.test_tick(self.now, 1)
            # drain the ATT response and its ACL completion
            buf = C.create_string_buffer(40)
            while self.lib.test_pop(buf):
                self.lib.test_completed(0x41, 1)

    def _nav_frame(self, cmd, distance, nxt, cur=''):
        nav = py_nav.NavInfo(direction=0xfe, distance_m=distance,
                             next_road=nxt, current_road=cur,
                             remain_hours=0, remain_minutes=1,
                             remain_time_third_raw=2,
                             remain_dist_m=distance, speed_kmh=30)
        payload = (py_nav.build_nav_variable2(nav) if cmd == 0x40
                   else py_nav.build_nav_variable(nav))
        return encode(cmd, payload, uid=DEFAULT_UID)

    def test_navigation_push_reaches_guide_callback(self):
        self._write_handle(14, self._nav_frame(0x40, 150, 'Nguyen Van Linh', 'Le Dai Hanh'))
        self.assertEqual(self.lib.test_guide_count(), 1)
        got = self.lib.test_guide_at(0).contents
        self.assertEqual(got.icon, 1)
        self.assertEqual(got.distance, 150)
        self.assertEqual(got.unit, 1)
        self.assertEqual(got.road.decode(), 'Nguyen Van Linh')
        self.assertEqual(got.sync, 1)
        self.assertFalse(got.clear)
        # dedup: same content again emits nothing
        self._write_handle(14, self._nav_frame(0x40, 150, 'Nguyen Van Linh', 'Le Dai Hanh'))
        self.assertEqual(self.lib.test_guide_count(), 1)
        # distance change re-emits with a bumped sync bit
        self._write_handle(14, self._nav_frame(0x40, 90, 'Nguyen Van Linh', 'Le Dai Hanh'))
        self.assertEqual(self.lib.test_guide_count(), 2)
        self.assertEqual(self.lib.test_guide_at(1).contents.sync, 2)
        # idle frame wipes once
        self._write_handle(14, self._nav_frame(0x40, 0xffffffff, '', ''))
        self.assertEqual(self.lib.test_guide_count(), 3)
        clear = self.lib.test_guide_at(2).contents
        self.assertTrue(clear.clear)
        self.assertEqual(clear.icon, 0)
        self.assertEqual(clear.road, b'')
        self._write_handle(14, self._nav_frame(0x40, 0xffffffff, '', ''))
        self.assertEqual(self.lib.test_guide_count(), 3)

    def test_bad_checksum_frame_never_guides(self):
        frame = bytearray(self._nav_frame(0x40, 150, 'Nguyen Van Linh'))
        frame[-1] ^= 0xff
        self._write_handle(14, bytes(frame))
        self.assertEqual(self.lib.test_guide_count(), 0)


if __name__ == '__main__':
    unittest.main()
