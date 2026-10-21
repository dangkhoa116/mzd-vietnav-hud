# vmlhud_nav.py - giai ma payload dan duong (CMD 0x00 / 0x40) va camera/bien bao
# (sendCameraInformation) tu khung VIETMAP LIVE -> HUD.
#
# OFFSET DA CHOT TU STATIC ANALYSIS (21-10-2026) - disassembly day du
# vietmap_hud_sdk.framework 3.4.3 (xem docs/vmlhud-nav-payloads.md):
#   - DJBTManager.insideSendNavigationInformation... (0x460c): payload variable v1
#     (CMD 0x00) va payload fixed 0xAF (CMD 0x00, nhanh protocol 1.6 khi hudInfo nil)
#   - DJBTManager.SimplifyNavigationInformationData... (0x5348): payload variable v2
#     (CMD 0x40, header 00 00 00 01 01)
# Moi layout deu ket thuc bang: gio u16be + phut u8 + giay u8 + quang u32be + toc do u16be.
#
# Con phai doi chieu RUNTIME (ESP32 emu hoac btsnoop voi HUD that):
#   - bang ma huong re (direction byte -> ten); hien chi in gia tri goc
#   - 2 byte cuoi payload fixed [0xAD..0xAE] (dau la speed u16be theo doi xung)

from dataclasses import dataclass, field
import struct


@dataclass
class NavInfo:
    direction: int = 0          # ma huong re (byte dau tien cua payload)
    distance_m: int = 0         # khoang cach toi diem re, met
    current_road: str = ""      # ten duong hien tai (UTF-8)
    next_road: str = ""         # ten duong tiep theo
    remain_time_s: int | None = 0  # None for variable layouts: iOS third time byte is not seconds
    remain_hours: int = 0
    remain_minutes: int = 0
    remain_time_third_raw: int = 0
    remain_dist_m: int = 0      # quang con lai, met
    speed_kmh: int = 0          # toc do hien tai
    speed_limit_kmh: int = 0    # bien bao toc do (tu sendCameraInformation)
    layout: str = ""            # "fixed" / "variable1" / "variable2"
    raw: bytes = field(default=b"", repr=False)

    def is_valid(self):
        return bool(self.current_road or self.next_road) or self.distance_m > 0


def _utf8(b):
    return b.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _hms_to_s(h, m, s):
    return h * 3600 + m * 60 + s


# ---------------------------------------------------------------------------
# Layout "fixed" (0xAF byte) - nhanh protocol 1.6 (hudInfo == nil), CMD 0x00,
# gui bang sendParamDataProtocol_1_6WithData:andCMD:.
#
#   [0]      u8    direction
#   [1..4]   u32be distance_m
#   [5..0x54]   80B next_road    UTF-8, cat 0x50, chen 0x00
#   [0x55..0xA4] 80B current_road UTF-8, cat 0x50, chen 0x00
#   [0xA5..0xA6] u16be remain_hours
#   [0xA7]   u8    remain_minutes
#   [0xA8]   u8    remain_seconds
#   [0xA9..0xAC] u32be remain_dist_m
#   [0xAD..0xAE] u16be speed_kmh (suy doan - chua doi chieu runtime)
# ---------------------------------------------------------------------------
FIXED_LEN = 0xAF
ROAD_FIELD_MAX = 0x4F           # ten duong cat con 0x50 byte khi qua 0x4F


def decode_nav_fixed(payload):
    if len(payload) < FIXED_LEN:
        raise ValueError("payload fixed ngan hon 0xAF: %d" % len(payload))
    direction = payload[0]
    (distance_m,) = struct.unpack_from(">I", payload, 1)
    next_road = _utf8(payload[5:0x55])
    current_road = _utf8(payload[0x55:0xA5])
    hours, = struct.unpack_from(">H", payload, 0xA5)
    minutes = payload[0xA7]
    seconds = payload[0xA8]
    (remain_dist_m,) = struct.unpack_from(">I", payload, 0xA9)
    (speed_kmh,) = struct.unpack_from(">H", payload, 0xAD)
    return NavInfo(
        direction=direction, distance_m=distance_m,
        current_road=current_road, next_road=next_road,
        remain_time_s=_hms_to_s(hours, minutes, seconds),
        remain_hours=hours, remain_minutes=minutes, remain_time_third_raw=seconds,
        remain_dist_m=remain_dist_m, speed_kmh=speed_kmh,
        layout="fixed", raw=payload[:FIXED_LEN])


# ---------------------------------------------------------------------------
# Layout "variable v1" - inline trong insideSendNavigationInformation, CMD 0x00,
# gui bang sendParamData:andCMD: (khi hudInfo != nil).
#
#   [0]    u8    direction
#   [1..4] u32be distance_m
#   [5]    u8    len(next_road)
#   [6..]  next_road UTF-8
#   [+1]   u8    len(current_road)
#   [+..]  current_road UTF-8
#   u16be remain_hours; u8 remain_minutes; u8 remain_seconds
#   u32be remain_dist_m; u16be speed_kmh
# ---------------------------------------------------------------------------
def decode_nav_variable(payload):
    """Dinh dang variable v1 (CMD 0x00). Do dai moi ten duong la byte dan dau."""
    if len(payload) < 17:
        raise ValueError("payload variable qua ngan: %d" % len(payload))
    o = 0
    direction = payload[o]; o += 1
    (distance_m,) = struct.unpack_from(">I", payload, o); o += 4
    ln_next = payload[o]; o += 1
    if o + ln_next >= len(payload):
        raise ValueError("next road exceeds payload")
    next_road = payload[o:o + ln_next]; o += ln_next
    ln_cur = payload[o]; o += 1
    if o + ln_cur + 10 > len(payload):
        raise ValueError("current road/tail exceeds payload")
    current_road = payload[o:o + ln_cur]; o += ln_cur
    hours, = struct.unpack_from(">H", payload, o)
    minutes = payload[o + 2]
    seconds = payload[o + 3]
    (remain_dist_m,) = struct.unpack_from(">I", payload, o + 4)
    (speed_kmh,) = struct.unpack_from(">H", payload, o + 8)
    end = o + 10
    if end > len(payload):
        raise ValueError("payload variable bi thieu duoi: can %d, co %d" % (end, len(payload)))
    return NavInfo(
        direction=direction, distance_m=distance_m,
        current_road=_utf8(current_road), next_road=_utf8(next_road),
        remain_time_s=None, remain_hours=hours, remain_minutes=minutes,
        remain_time_third_raw=seconds,
        remain_dist_m=remain_dist_m, speed_kmh=speed_kmh,
        layout="variable1", raw=payload[:end])


# ---------------------------------------------------------------------------
# Layout "variable v2" (SimplifyNavigationInformationData; SDK DJ Android
# W7/c.java, W7/e.java), CMD 0x40, gui bang sendParamData:andCMD:0x40.
#
# Semantics tu Android: sau direction la khoi "anh mui ten custom":
#   u32be image_len  = 1 -> KHONG co anh (hai byte than tro thanh hang so
#                      00 00 00 01 + flag 0); > 1 -> do dai JPEG custom
#   neu image_len == 1: u8 image_flag (0 = khong anh, 1 = giu anh cu)
#   neu image_len > 1 : <image_len byte JPEG> (bo qua khi giai ma nav)
# roi moi toi distance.
#
#   [0]     u8    direction
#   [1..4]  u32be image_len (=1 khi khong anh)
#   [5]     u8    image_flag  (hoac JPEG dai image_len neu >1)
#   [6..9]  u32be distance_m
#   [10]    u8    len(next_road)
#   [11..]  next_road UTF-8
#   [+1]    u8    len(current_road)
#   [+..]   current_road UTF-8
#   u16be remain_hours; u8 remain_minutes; u8 remain_seconds
#   u32be remain_dist_m; u16be speed_kmh
# ---------------------------------------------------------------------------
def decode_nav_variable2(payload):
    if len(payload) < 22:
        raise ValueError("payload variable2 qua ngan: %d" % len(payload))
    (image_len,) = struct.unpack_from(">I", payload, 1)
    if image_len == 1:
        if payload[5] not in (0, 1):
            raise ValueError("image_flag la: %d" % payload[5])
        dist_off = 6
    elif image_len > 1:
        if len(payload) < 5 + image_len + 4:
            raise ValueError("thieu byte anh custom: %d" % len(payload))
        dist_off = 5 + image_len
    else:
        raise ValueError("image_len=%d vo ly" % image_len)
    direction = payload[0]
    (distance_m,) = struct.unpack_from(">I", payload, dist_off)
    o = dist_off + 4
    if o >= len(payload):
        raise ValueError("missing next road length")
    ln_next = payload[o]; o += 1
    if o + ln_next >= len(payload):
        raise ValueError("next road exceeds payload")
    next_road = payload[o:o + ln_next]; o += ln_next
    ln_cur = payload[o]; o += 1
    if o + ln_cur + 10 > len(payload):
        raise ValueError("current road/tail exceeds payload")
    current_road = payload[o:o + ln_cur]; o += ln_cur
    hours, = struct.unpack_from(">H", payload, o)
    minutes = payload[o + 2]
    seconds = payload[o + 3]
    (remain_dist_m,) = struct.unpack_from(">I", payload, o + 4)
    (speed_kmh,) = struct.unpack_from(">H", payload, o + 8)
    end = o + 10
    if end > len(payload):
        raise ValueError("payload variable2 bi thieu duoi: can %d, co %d" % (end, len(payload)))
    return NavInfo(
        direction=direction, distance_m=distance_m,
        current_road=_utf8(current_road), next_road=_utf8(next_road),
        remain_time_s=None, remain_hours=hours, remain_minutes=minutes,
        remain_time_third_raw=seconds,
        remain_dist_m=remain_dist_m, speed_kmh=speed_kmh,
        layout="variable2", raw=payload[:end])


# ---------------------------------------------------------------------------
# Builder (de test round-trip va de emu ESP32 tham chieu; C port trong emu).
# ---------------------------------------------------------------------------
def _build_time(nav):
    if nav.remain_time_s is None:
        return nav.remain_hours, nav.remain_minutes, nav.remain_time_third_raw
    h, rem = divmod(max(0, nav.remain_time_s), 3600)
    m, s = divmod(rem, 60)
    return h, m, s


def build_nav_variable(nav):
    n = nav.next_road.encode("utf-8")[:255]
    c = nav.current_road.encode("utf-8")[:255]
    h, m, s = _build_time(nav)
    body = struct.pack(">B", nav.direction & 0xFF) + struct.pack(">I", nav.distance_m)
    body += bytes((len(n),)) + n + bytes((len(c),)) + c
    body += struct.pack(">H", h) + bytes((m, s))
    body += struct.pack(">I", nav.remain_dist_m) + struct.pack(">H", nav.speed_kmh)
    return body


def build_nav_fixed(nav):
    n = nav.next_road.encode("utf-8")[:0x50].ljust(0x50, b"\x00")
    c = nav.current_road.encode("utf-8")[:0x50].ljust(0x50, b"\x00")
    h, m, s = _build_time(nav)
    body = struct.pack(">B", nav.direction & 0xFF) + struct.pack(">I", nav.distance_m) + n + c
    body += struct.pack(">H", h) + bytes((m, s))
    body += struct.pack(">I", nav.remain_dist_m) + struct.pack(">H", nav.speed_kmh)
    assert len(body) == FIXED_LEN, len(body)
    return body


def build_nav_variable2(nav):
    n = nav.next_road.encode("utf-8")[:255]
    c = nav.current_road.encode("utf-8")[:255]
    h, m, s = _build_time(nav)
    body = struct.pack(">B", nav.direction & 0xFF) + b"\x00\x00\x00\x01\x01"
    body += struct.pack(">I", nav.distance_m)
    body += bytes((len(n),)) + n + bytes((len(c),)) + c
    body += struct.pack(">H", h) + bytes((m, s))
    body += struct.pack(">I", nav.remain_dist_m) + struct.pack(">H", nav.speed_kmh)
    return body


def decode_nav(payload, cmd=None, protocol=None):
    """Tu dong nhan dang layout. cmd (0x00/0x40) neu biet de uu tien.

    Uu tien parse "an khop" toan bo payload (end == len); neu khong layout nao
    an khop (vd payload co pad), lay parse dau tien khong loi."""
    if protocol is not None:
        if protocol == 'legacy' and cmd in (None, 0):
            info = decode_nav_fixed(payload)
        elif protocol == 'new' and cmd == 0:
            info = decode_nav_variable(payload)
        elif protocol == 'new' and cmd == 0x40:
            info = decode_nav_variable2(payload)
        else:
            raise ValueError('unsupported protocol/navigation command')
        if len(info.raw) != len(payload):
            raise ValueError('unexpected navigation trailing data')
        return info
    order = []
    if cmd == 0x40:
        order = [decode_nav_variable2, decode_nav_variable, decode_nav_fixed]
    elif cmd == 0x00:
        order = [decode_nav_fixed, decode_nav_variable, decode_nav_variable2]
    else:
        if len(payload) >= FIXED_LEN:
            order = [decode_nav_fixed, decode_nav_variable, decode_nav_variable2]
        elif len(payload) > 5 and payload[1:5] >= b"\x00\x00\x00\x01":
            # [1..5] la u32 image_len (>=1) cua variable2 (khoang bien thi = 1)
            order = [decode_nav_variable2, decode_nav_variable, decode_nav_fixed]
        else:
            order = [decode_nav_variable, decode_nav_variable2, decode_nav_fixed]
    first_ok = None
    for fn in order:
        try:
            info = fn(payload)
        except (ValueError, struct.error):
            continue
        if len(info.raw) == len(payload):
            return info
        if first_ok is None:
            first_ok = info
    if first_ok is not None:
        return first_ok
    raise ValueError("khong giai ma duoc payload (%d byte)" % len(payload))
