# vmlhud_frame_test.py - test cho bo codec khung. Chay:  python3 vmlhud_frame_test.py
#
# Day la test TU NHAT QUAN cua lop khung (round-trip, checksum, tach stream). No
# KHONG chung minh offset payload dan duong dung - cai do can capture that.

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


# --- round-trip cac CMD ---
for cmd, pl in [(F.CMD_HUD_INFO, b"\x01"),
                (F.CMD_HEARTBEAT, bytes((50,))),
                (F.CMD_NAV, b"hello road"),
                (0x00, b"")]:
    fr = F.build(cmd, pl, timestamp=0x11223344)
    p = F.parse(fr)
    check("roundtrip cmd=%#x payload" % cmd, p["payload"] == pl)
    check("roundtrip cmd=%#x cmd" % cmd, p["cmd"] == cmd)
    check("roundtrip cmd=%#x ts" % cmd, p["timestamp"] == 0x11223344)
    check("roundtrip cmd=%#x length" % cmd, p["length"] == len(pl) + F.LEN_ADDEND)

# --- layout byte dung spec ---
fr = F.build(0x0E, b"\x01", timestamp=0x11223344)
check("magic", fr[:4] == bytes((0xA5, 0x5A, 0x37, 0xC3)))
check("length BE", fr[4:8] == struct.pack(">I", 1 + F.LEN_ADDEND))
check("ts BE", fr[8:12] == struct.pack(">I", 0x11223344))
check("cmd byte", fr[12] == 0x0E)
check("trailer 8 byte checksum", len(fr) == F.HEADER_LEN + 1 + F.TRAILER_LEN)

# --- MD5 hong thi bi tu choi ---
bad = bytearray(F.build(0x00, b"abc"))
bad[-1] ^= 0xFF
try:
    F.parse(bytes(bad))
    check("MD5 hong -> loi", False)
except F.FrameError:
    check("MD5 hong -> loi", True)
# ... nhung verify_md5=False thi van doc duoc
check("bo qua md5 doc duoc", F.parse(bytes(bad), verify_md5=False)["payload"] == b"abc")

# --- magic sai ---
try:
    F.parse(b"\x00" * 40)
    check("magic sai -> loi", False)
except F.FrameError:
    check("magic sai -> loi", True)

# --- tach nhieu khung + rac dan xen ---
a = F.build(F.CMD_HEARTBEAT, bytes((40,)), timestamp=1)
b = F.build(F.CMD_NAV, b"Nguyen Van Linh", timestamp=2)
frames, rest = F.split_stream(b"\xde\xad" + a + b[:-3])   # khung b bi cat dang do
check("stream tach dung 1 khung tron", len(frames) == 1)
check("stream khung dau la heartbeat", frames[0]["cmd"] == F.CMD_HEARTBEAT)
check("stream giu phan du", rest.endswith(b[:-3][-5:]))
frames2, rest2 = F.split_stream(a + b)
check("stream tach 2 khung", len(frames2) == 2 and rest2 == b"")

# --- nav variable v1 round-trip (layout DA CHOT tu disassembly; builder chinh la spec) ---
nav_in = N.NavInfo(direction=3, distance_m=120, current_road="Vo Van Kiet",
                   next_road="Nguyen Van Linh", remain_time_s=540,
                   remain_dist_m=2300, speed_kmh=48)
pl = N.build_nav_variable(nav_in)
nav = N.decode_nav_variable(pl)
check("nav dir", nav.direction == 3)
check("nav distance", nav.distance_m == 120)
check("nav remain_time raw", nav.remain_time_s == 540 and nav.remain_minutes == 9)
check("nav remain_dist", nav.remain_dist_m == 2300)
check("nav speed", nav.speed_kmh == 48)
check("nav current_road", nav.current_road == "Vo Van Kiet")
check("nav next_road", nav.next_road == "Nguyen Van Linh")
check("nav is_valid", nav.is_valid())

print("\n%d pass, %d fail" % (ok, fail))
sys.exit(1 if fail else 0)
