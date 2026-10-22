# vmlhud_nav_test.py - test cho bo giai ma payload dan duong.
# Chay:  python3 vmlhud_nav_test.py
#
# Test round-trip cua ba layout da chot tu disassembly vietmap_hud_sdk
# (docs/vmlhud-nav-payloads.md) + mot vai frame "tay" theo byte that cua
# cac nhanh code da doc. Neu app gui khac di, se thay ngay o capture runtime.

import struct
import sys

import vmlhud_frame as F
import vmlhud_nav as N

ok = 0
fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("FAIL:", name)


nav = N.NavInfo(direction=12, distance_m=350,
                current_road="Nguyen Van Linh", next_road="Le Dai Hanh",
                remain_time_s=1234, remain_dist_m=5678, speed_kmh=61)

# --- builder ra dung byte theo offset da doc trong disassembly ---
v1 = N.build_nav_variable(nav)
check("v1 [0] direction", v1[0] == 12)
check("v1 [1..4] distance BE", v1[1:5] == (350).to_bytes(4, "big"))
check("v1 [5] len next", v1[5] == len(b"Le Dai Hanh"))
check("v1 next tai [6]", v1[6:6 + v1[5]] == b"Le Dai Hanh")
o = 6 + v1[5]
ln_cur = v1[o]
check("v1 len cur", ln_cur == len(b"Nguyen Van Linh"))
o += 1 + ln_cur
check("v1 hours BE u16", v1[o:o + 2] == (1234 // 3600).to_bytes(2, "big"))
check("v1 phut", v1[o + 2] == 20)
check("v1 giay", v1[o + 3] == 34)

v2 = N.build_nav_variable2(nav)
check("v2 header 00000001", v2[1:5] == b"\x00\x00\x00\x01")
check("v2 [5] = 1", v2[5] == 1)
check("v2 dist tai [6..9]", v2[6:10] == (350).to_bytes(4, "big"))

fx = N.build_nav_fixed(nav)
check("fixed dai 0xAF", len(fx) == 0xAF)
check("fixed road pad 0x50", fx[5:0x55] == b"Le Dai Hanh".ljust(0x50, b"\x00"))
check("fixed cur tai 0x55", fx[0x55:0xA5] == b"Nguyen Van Linh".ljust(0x50, b"\x00"))

# --- round-trip ca ba layout ---
for name, body in [("fixed", fx), ("variable1", v1), ("variable2", v2)]:
    info = N.decode_nav(body)
    check("%s direction" % name, info.direction == 12)
    check("%s distance" % name, info.distance_m == 350)
    check("%s next_road" % name, info.next_road == "Le Dai Hanh")
    check("%s current_road" % name, info.current_road == "Nguyen Van Linh")
    check("%s remain_time" % name, info.remain_time_s == 1234)
    check("%s raw time" % name, (info.remain_hours, info.remain_minutes, info.remain_time_third_raw) == (0,20,34))
    check("%s remain_dist" % name, info.remain_dist_m == 5678)
    check("%s speed" % name, info.speed_kmh == 61)
    check("%s layout nhan dang" % name, info.layout == name)

# --- ten duong tieng Viet co dau (UTF-8 nhieu byte) ---
nav_vn = N.NavInfo(direction=3, distance_m=1200,
                   current_road="Đường Nguyễn Huệ", next_road="Phố đi bộ",
                   remain_time_s=3661, remain_dist_m=9000, speed_kmh=0)
for name, body in [("fixed", N.build_nav_fixed(nav_vn)),
                   ("variable1", N.build_nav_variable(nav_vn)),
                   ("variable2", N.build_nav_variable2(nav_vn))]:
    info = N.decode_nav(body)
    check("%s VN next_road" % name, info.next_road == "Phố đi bộ")
    check("%s VN current_road" % name, info.current_road == "Đường Nguyễn Huệ")
    check("%s VN remain_time" % name, info.remain_time_s == 3661)

# --- ten duong qua dai: fixed cat 0x50, variable cat 255 ---
long_road = "X" * 300
nav_long = N.NavInfo(direction=1, distance_m=5, current_road=long_road,
                     next_road=long_road, remain_time_s=0, remain_dist_m=0, speed_kmh=0)
info = N.decode_nav(N.build_nav_fixed(nav_long))
check("fixed cat 0x50", info.current_road == "X" * 0x50)
info = N.decode_nav(N.build_nav_variable(nav_long))
check("variable1 cat 255", info.current_road == "X" * 255)

# --- variable2 voi ANH mui ten custom (u32 = do dai JPEG, anh noi ngay sau) ---
img = bytes(range(200))  # gia lap JPEG
v2img = bytes((nav.direction,)) + struct.pack(">I", len(img)) + img         + struct.pack(">I", nav.distance_m)         + bytes((len(b"Le Dai Hanh"),)) + b"Le Dai Hanh"         + bytes((len(b"Nguyen Van Linh"),)) + b"Nguyen Van Linh"         + struct.pack(">H", 0) + bytes((20, 34))         + struct.pack(">I", 5678) + struct.pack(">H", 61)
info = N.decode_nav_variable2(v2img)
check("v2+anh direction", info.direction == 12)
check("v2+anh distance", info.distance_m == 350)
check("v2+anh next_road", info.next_road == "Le Dai Hanh")
check("v2+anh current_road", info.current_road == "Nguyen Van Linh")
check("v2+anh remain", info.remain_time_s == 1234 and info.remain_time_third_raw == 34 and info.remain_dist_m == 5678)
check("v2+anh speed", info.speed_kmh == 61)
info = N.decode_nav(v2img)
check("v2+anh auto-detect", info.layout == "variable2")

# --- trong khung: frame CMD 0x40 (variable2) va CMD 0x00 (variable1/fixed) ---
fr40 = F.build(0x40, v2)
p = F.parse(fr40)
check("frame 0x40 payload", p["payload"] == v2)
info = N.decode_nav(p["payload"], cmd=p["cmd"])
check("frame 0x40 layout variable2", info.layout == "variable2")

fr00 = F.build(F.CMD_NAV, fx)
p = F.parse(fr00)
info = N.decode_nav(p["payload"], cmd=p["cmd"])
check("frame 0x00 fixed", info.layout == "fixed")

# --- payload rac -> loi ro rang ---
for bad in (b"", b"\x01", b"\x00" * 3):
    try:
        N.decode_nav(bad)
        check("payload rac %r tu choi" % bad, False)
    except ValueError:
        check("payload rac %r tu choi" % bad, True)

# ---------------------------------------------------------------------------
# Fixture THAT: payload CMD 0x00 do VIETMAP LIVE 3.4.3 (iOS) gui cho emulator
# ESP32-C3 ngay 22-10-2026, doc tu out/cycle-trial-3.log. Moi mau da doi chieu
# voi man hinh app tai thoi diem bat (xem docs/vmlhud-nav-payloads.md muc 10).
# ---------------------------------------------------------------------------
LIVE = [
    # (hex payload, dist_m, next_road, h, m, s, remain_m, ghi chu man hinh app)
    ("FE000000960E5175E1BB9163204CE1BB9920313300000019260000203D0000",
     150, "Quốc Lộ 13", 0, 25, 38, 8253, "re phai vao QL13; app hien 25p / 8.3km"),
    ("FE000000960E5175E1BB9163204CE1BB9920313300000025340000376D0000",
     150, "Quốc Lộ 13", 0, 37, 52, 14189, "cung khung re phai; app hien 37p / 14.2km"),
    ("FE0000001E10C490C6B0E1BB9D6E672053E1BB9120370000000100000003E80000",
     30, "Đường Số 7", 0, 1, 0, 1000, "diem den 47m, icon la co dich khong phai mui ten"),
    ("FEFFFFFFFF143331C2B0206DC3A27920C491656E207520C3A16D0000000000000000000000",
     0xFFFFFFFF, "31° mây đen u ám", 0, 0, 0, 0, "khung nhan roi: dist=-1, duoi toan 0"),
]
for hexs, dist, nxt, h, m, s, rem, note in LIVE:
    info = N.decode_nav(bytes.fromhex(hexs))
    check("live %s layout" % note, info.layout == "variable1")
    check("live %s dist" % note, info.distance_m == dist)
    check("live %s next_road" % note, info.next_road == nxt)
    check("live %s current_road rong" % note, info.current_road == "")
    check("live %s time" % note,
          (info.remain_hours, info.remain_minutes, info.remain_time_third_raw) == (h, m, s))
    check("live %s remain_time_s" % note, info.remain_time_s == h * 3600 + m * 60 + s)
    check("live %s remain_dist" % note, info.remain_dist_m == rem)
    check("live %s speed" % note, info.speed_kmh == 0)
    # Moi khung thuc te deu co direction = 0xFE, ke ca khi mui ten tren app
    # khac nhau (re phai / co dich) va ca khi khong dan duong.
    check("live %s direction 0xFE" % note, info.direction == 0xFE)


# --- Fixture that: CMD 0x40 variable2 sau khi emulator tra PROTOCOL:2.2.2 ---
# App gui anh mui ten JPEG MOT lan (image_len = do dai JPEG), roi cac khung sau
# dung image_len=1 + flag=1 = "giu anh cu". Xem docs/vmlhud-nav-payloads.md muc 10.7.
LIVE_V2 = [
    ("FE0000000101000000960E5175E1BB9163204CE1BB99203133000000191B0000203D0000",
     150, "Quốc Lộ 13", 0, 25, 27, 8253, 0, "giu anh cu, dang dan duong"),
    ("FE0000000101FFFFFFFF0F3330C2B0206DC6B0612076E1BBAB610000000000000000000028",
     0xFFFFFFFF, "30° mưa vừa", 0, 0, 0, 0, 40, "nhan roi, speed 40 tu GPS"),
]
for hexs, dist, nxt, h, m, sec, rem, spd, note in LIVE_V2:
    info = N.decode_nav(bytes.fromhex(hexs))
    check("live v2 %s layout" % note, info.layout == "variable2")
    check("live v2 %s dist" % note, info.distance_m == dist)
    check("live v2 %s next_road" % note, info.next_road == nxt)
    check("live v2 %s time" % note,
          (info.remain_hours, info.remain_minutes, info.remain_time_third_raw) == (h, m, sec))
    check("live v2 %s remain_dist" % note, info.remain_dist_m == rem)
    check("live v2 %s speed" % note, info.speed_kmh == spd)
    check("live v2 %s direction 0xFE" % note, info.direction == 0xFE)

print("RESULT: %d ok, %d fail" % (ok, fail))
sys.exit(1 if fail else 0)
