# vmlhud_nav.py - giai ma payload dan duong (CMD 0x00) va camera/bien bao
# (sendCameraInformation) tu khung VIETMAP LIVE -> HUD.
#
# ====================================================================
#  CANH BAO: OFFSET CAC TRUONG DUOI DAY CHUA DUOC XAC NHAN.
#  Chung suy ra tu danh sach method ObjC + doc disassembly, CHUA doi chieu
#  voi mot phien BLE that. Truoc khi dua len xe khach, PHAI bat mot phien
#  VIETMAP LIVE <-> HUD Vietmap that (HCI snoop log Android) va chot lai
#  tung offset o day. Xem docs/vietmap-hud-bridge.md muc "Bat phien that".
# ====================================================================
#
# Tu sendNavigationInformationWithDirection:andDistance:andNextRoad:
#   andCurrentRoad:andRemainTime:andRemainDistance:andCurrentSpeed:
# -> 7 truong: huong re, khoang cach toi diem re, ten duong hien tai,
#    ten duong tiep theo, thoi gian con lai, quang con lai, toc do.
#
# Co HAI dinh dang payload (chon theo hudInfo doc luc bat tay):
#   - "fixed"    : ~0xAF byte, truong o vi tri co dinh, ten duong dem ve ~0x4F
#   - "variable" : header + ten duong theo do dai that + cac truong so
#
# Dau ra la mot dict trung lap (neutral) de ben inject dich sang com.jci.vbs.navi.

from dataclasses import dataclass, field


@dataclass
class NavInfo:
    direction: int = 0          # ma huong re (bang anh xa sang icon HUD, TODO)
    distance_m: int = 0         # khoang cach toi diem re, met
    current_road: str = ""      # ten duong hien tai (UTF-8)
    next_road: str = ""         # ten duong tiep theo
    remain_time_s: int = 0      # thoi gian con lai, giay
    remain_dist_m: int = 0      # quang con lai, met
    speed_kmh: int = 0          # toc do hien tai
    speed_limit_kmh: int = 0    # bien bao toc do (tu sendCameraInformation)
    raw: bytes = field(default=b"", repr=False)

    def is_valid(self):
        # mot khung dan duong hop le toi thieu phai co huong + mot ten duong
        return bool(self.current_road or self.next_road) or self.distance_m > 0


def _utf8(b):
    return b.split(b"\x00", 1)[0].decode("utf-8", "replace")


def decode_nav_variable(payload):
    """Dinh dang bien doi: [dir u8][dist u32be][remain_time u32be]
    [remain_dist u32be][speed u8][len_cur u8][cur...][len_next u8][next...].

    DAY LA GIA THUYET LAYOUT - phai doi chieu capture that truoc khi dung."""
    if len(payload) < 15:
        raise ValueError("payload variable qua ngan: %d" % len(payload))
    import struct
    o = 0
    direction = payload[o]; o += 1
    (distance_m,) = struct.unpack_from(">I", payload, o); o += 4
    (remain_time_s,) = struct.unpack_from(">I", payload, o); o += 4
    (remain_dist_m,) = struct.unpack_from(">I", payload, o); o += 4
    speed_kmh = payload[o]; o += 1
    cur = nxt = b""
    if o < len(payload):
        ln = payload[o]; o += 1
        cur = payload[o:o + ln]; o += ln
    if o < len(payload):
        ln = payload[o]; o += 1
        nxt = payload[o:o + ln]; o += ln
    return NavInfo(
        direction=direction, distance_m=distance_m, remain_time_s=remain_time_s,
        remain_dist_m=remain_dist_m, speed_kmh=speed_kmh,
        current_road=_utf8(cur), next_road=_utf8(nxt), raw=payload)


# Dinh dang "fixed" (~0xAF byte): offset tung truong CHUA biet chac. De trong
# cho den khi co capture; khi do dien ROAD1_OFF/ROAD2_OFF/... vao day.
FIXED_LEN = 0xAF
ROAD_FIELD_MAX = 0x4F


def decode_nav_fixed(payload):
    raise NotImplementedError(
        "dinh dang fixed can offset tu capture that - xem docs/vietmap-hud-bridge.md")


def decode_nav(payload):
    """Chon dinh dang theo do dai payload (heuristic tam thoi)."""
    if len(payload) >= FIXED_LEN - 4:
        try:
            return decode_nav_fixed(payload)
        except NotImplementedError:
            pass
    return decode_nav_variable(payload)
