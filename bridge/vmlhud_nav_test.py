# vmlhud_nav_test.py - test cho bo giai ma payload dan duong.
# Chay:  python3 vmlhud_nav_test.py
#
# Test round-trip cua ba layout da chot tu disassembly vietmap_hud_sdk
# (docs/vmlhud-nav-payloads.md) + mot vai frame "tay" theo byte that cua
# cac nhanh code da doc. Neu app gui khac di, se thay ngay o capture runtime.

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
    check("%s VN remain_time 3661s" % name, info.remain_time_s == 3661)

# --- ten duong qua dai: fixed cat 0x50, variable cat 255 ---
long_road = "X" * 300
nav_long = N.NavInfo(direction=1, distance_m=5, current_road=long_road,
                     next_road=long_road, remain_time_s=0, remain_dist_m=0, speed_kmh=0)
info = N.decode_nav(N.build_nav_fixed(nav_long))
check("fixed cat 0x50", info.current_road == "X" * 0x50)
info = N.decode_nav(N.build_nav_variable(nav_long))
check("variable1 cat 255", info.current_road == "X" * 255)

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

print("RESULT: %d ok, %d fail" % (ok, fail))
sys.exit(1 if fail else 0)
