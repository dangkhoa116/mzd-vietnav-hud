#!/usr/bin/env python3
"""Doi dan duong VIETMAP LIVE thanh dung hai khung ma HUD zin Mazda doc.

Dau ra cua HUD zin (Active Driving Display) la hai struct cua
`com.jci.vbs.navi`, lay tu ban CarPlay->HUD da chay that tren CMU150
(`repos/mazda-carplay-hud`, `oem/libjcivbsnaviclient.h`):

    VbsNaviHudDisplay { u32 nextManeuverInfo; u16 distanceValue; u8 distanceUnit;
                        u16 displaySpeedLimit; u8 displaySpeedUnit; u8 text_ID3 }
    VbsNaviHudMsg2    { const char *guidancePointName; u8 syncBit }

Module nay chi lo phan **noi dung** hai struct do. Phan goi
`VBS_NAVI_SetHUDDisplayMsgReq` / `VBS_NAVI_TMC_SetHUD_Display_Msg2` nam trong
daemon C tren CMU - xem docs/hud-native-cmu.md.

Bang ma mui ten (`MazdaIcon`) va cach tinh icon vong xuyen duoc **soi guong
nguyen ven** tu `hud_send.cpp` cua ban CarPlay, vi bang do da duoc kiem truc
tiep tren HUD that. Khong tu dat lai so.

Dau vao phia VietMap:
  - `NavInfo` tu `vmlhud_nav.decode_nav` (ten duong, khoang cach, thoi gian...)
  - `ArrowMatch` tu `vmlhud_arrow.classify` (huong re suy tu anh JPEG, vi byte
    `direction` tren song luon 0xFE va vo nghia)
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Ma mui ten cua HUD ECU (soi guong tu hud_send.cpp: enum MazdaIcon) ---
HUD_NONE = 0
HUD_STRAIGHT = 1
HUD_LEFT = 2
HUD_RIGHT = 3
HUD_SLIGHT_LEFT = 4
HUD_SLIGHT_RIGHT = 5
HUD_OFF_RAMP_RIGHT = 7
HUD_DESTINATION = 8
HUD_SHARP_RIGHT = 9
HUD_U_TURN_RIGHT = 10
HUD_SHARP_LEFT = 11
HUD_FLAG = 12
HUD_U_TURN_LEFT = 13
HUD_FORK_RIGHT = 14
HUD_FORK_LEFT = 15
HUD_MERGE_LEFT = 16
HUD_MERGE_RIGHT = 17
HUD_OFF_RAMP_LEFT = 30
HUD_DESTINATION_LEFT = 33
HUD_DESTINATION_RIGHT = 34
HUD_FLAG_LEFT = 35
HUD_FLAG_RIGHT = 36

# Don vi khoang cach cua HUD (HudDistanceUnit trong hud.h tham chieu).
UNIT_NONE = 0
UNIT_METERS = 1
UNIT_MILES = 2
UNIT_KILOMETERS = 3

# Goc re uoc luong cho tung modifier, do, duong = re phai (chieu kim dong ho).
# Chi dung cho vong xuyen: VietMap khong gui goc thoat, chi gui mot trong cac
# hinh roundabout_* nen day la do phan giai toi da lay duoc.
MODIFIER_DEGREES = {
    "straight": 0,
    "slight_right": 45,
    "right": 90,
    "sharp_right": 135,
    "uturn": 180,
    "sharp_left": 225,
    "left": 270,
    "slight_left": 315,
}

# (maneuver, modifier) -> ma mui ten. Tra cuu theo maneuver truoc, roi modifier.
# Cac maneuver khong co trong bang se roi ve _TURN_LIKE (coi nhu mot cu re).
_TURN_LIKE = {
    "left": HUD_LEFT,
    "right": HUD_RIGHT,
    "slight_left": HUD_SLIGHT_LEFT,
    "slight_right": HUD_SLIGHT_RIGHT,
    "sharp_left": HUD_SHARP_LEFT,
    "sharp_right": HUD_SHARP_RIGHT,
    "uturn": HUD_U_TURN_LEFT,   # Viet Nam di ben phai: quay dau la vong trai
    "straight": HUD_STRAIGHT,
    "": HUD_STRAIGHT,
}
_BY_MANEUVER = {
    # Giong bang kTurnIcons cua hud_send.cpp: TURN_TURN / TURN_ON_RAMP dung
    # chung bo icon re thuong.
    "turn": _TURN_LIKE,
    "end_of_road": _TURN_LIKE,
    "on_ramp": _TURN_LIKE,
    "continue": _TURN_LIKE,
    "notification": _TURN_LIKE,
    "invalid": _TURN_LIKE,
    # TURN_NAME_CHANGE -> STRAIGHT o moi huong.
    "new_name": dict(_TURN_LIKE, **{"": HUD_STRAIGHT}),
    "merge": {"left": HUD_MERGE_LEFT, "slight_left": HUD_MERGE_LEFT,
              "right": HUD_MERGE_RIGHT, "slight_right": HUD_MERGE_RIGHT,
              "straight": HUD_STRAIGHT, "": HUD_STRAIGHT},
    "fork": {"left": HUD_FORK_LEFT, "slight_left": HUD_FORK_LEFT,
             "right": HUD_FORK_RIGHT, "slight_right": HUD_FORK_RIGHT,
             "straight": HUD_STRAIGHT, "": HUD_STRAIGHT},
    "off_ramp": {"left": HUD_OFF_RAMP_LEFT, "slight_left": HUD_OFF_RAMP_LEFT,
                 "right": HUD_OFF_RAMP_RIGHT, "slight_right": HUD_OFF_RAMP_RIGHT,
                 "straight": HUD_STRAIGHT, "": HUD_OFF_RAMP_RIGHT},
    "arrive": {"left": HUD_DESTINATION_LEFT, "right": HUD_DESTINATION_RIGHT,
               "straight": HUD_DESTINATION, "": HUD_DESTINATION},
    "depart": {"left": HUD_FLAG_LEFT, "right": HUD_FLAG_RIGHT,
               "straight": HUD_FLAG, "": HUD_FLAG},
    "flag": {"": HUD_FLAG},
    "close": {"": HUD_FLAG},
    "updown": {"": HUD_STRAIGHT},
}
ROUNDABOUT_MANEUVERS = ("roundabout", "rotary")


def roundabout_icon(degrees: int, left_hand_traffic: bool = False) -> int:
    """Icon vong xuyen theo goc thoat; soi guong roundabout_icon() cua hud_send.cpp.

    HUD co 12 glyph moi ben, sector 0 chi XUONG (chan vao) va chay nguoc chieu
    kim dong ho, nen phai lay `180 - goc` truoc khi chia 30 do.
    """
    d = (180 - int(degrees)) % 360
    nearest = ((d + 15) // 30) % 12
    return nearest + (49 if left_hand_traffic else 37)


def icon_for(maneuver: str, modifier: str, left_hand_traffic: bool = False) -> int:
    """(maneuver, modifier) tu ten asset VietMap -> ma mui ten HUD."""
    maneuver = (maneuver or "").strip()
    modifier = (modifier or "").strip()
    if maneuver in ROUNDABOUT_MANEUVERS:
        # Khong co goc thoat that; uoc luong tu modifier.
        return roundabout_icon(MODIFIER_DEGREES.get(modifier, 0), left_hand_traffic)
    if modifier == "uturn" and left_hand_traffic:
        return HUD_U_TURN_RIGHT
    table = _BY_MANEUVER.get(maneuver, _TURN_LIKE)
    if modifier in table:
        return table[modifier]
    if modifier in _TURN_LIKE:
        return _TURN_LIKE[modifier]
    return table.get("", HUD_STRAIGHT)


def distance_fields(meters: int) -> tuple[int, int]:
    """Met -> (distanceValue, distanceUnit) dung quy uoc cua HUD.

    `distanceValue` la gia tri **nhan 10** (mot chu so thap phan) theo don vi da
    chon, giong `distance_dec` trong hud_send.cpp; HUD tu dat dau phay. Duoi
    1 km dung met, tu 1 km tro len dung kilomet - giong cach Google Maps hien.
    """
    if meters is None or meters < 0:
        return 0, UNIT_NONE
    if meters < 1000:
        value, unit = meters * 10, UNIT_METERS
    else:
        value, unit = meters // 100, UNIT_KILOMETERS
    return min(value, 0xFFFF), unit


@dataclass
class HudFrame:
    """Noi dung hai struct com.jci.vbs.navi, da san sang ghi ra."""
    next_maneuver_info: int = HUD_NONE
    distance_value: int = 0
    distance_unit: int = UNIT_NONE
    display_speed_limit: int = 0
    display_speed_unit: int = 0      # 1 = km/h, 0 = khong hien
    text_id3: int = 1                # sync bit, dung chung voi Msg2.syncBit
    guidance_point_name: str = ""
    guiding: bool = True             # False = xoa guidance khoi HUD

    def as_display(self) -> dict:
        return {"nextManeuverInfo": self.next_maneuver_info,
                "distanceValue": self.distance_value,
                "distanceUnit": self.distance_unit,
                "displaySpeedLimit": self.display_speed_limit,
                "displaySpeedUnit": self.display_speed_unit,
                "text_ID3": self.text_id3}

    def as_msg2(self) -> dict:
        return {"guidancePointName": self.guidance_point_name,
                "syncBit": self.text_id3}


# VietMap bao "het dan duong" bang distance = 0xFFFFFFFF kem duoi toan 0; luc do
# truong next_road mang chuoi thong tin (thoi tiet) chu khong phai ten duong.
NO_GUIDANCE_DISTANCE = 0xFFFFFFFF


def frame_for(nav, arrow=None, speed_limit_kmh: int = 0, sync_bit: int = 1,
              left_hand_traffic: bool = False) -> HudFrame:
    """Dung HudFrame tu mot khung dan duong da giai ma.

    `nav`   - NavInfo cua vmlhud_nav.decode_nav
    `arrow` - ArrowMatch cua vmlhud_arrow.classify, hoac None khi khung do dung
              "giu anh cu" (image_len == 1). Goi phai tu nho mui ten gan nhat.
    """
    sync_bit = sync_bit if 1 <= sync_bit <= 7 else 1
    if nav.distance_m == NO_GUIDANCE_DISTANCE:
        # Khong con dan duong: xoa icon, khoang cach va ten duong khoi HUD.
        return HudFrame(next_maneuver_info=HUD_NONE, distance_value=0,
                        distance_unit=UNIT_NONE,
                        display_speed_limit=speed_limit_kmh,
                        display_speed_unit=1 if speed_limit_kmh else 0,
                        text_id3=sync_bit, guidance_point_name="", guiding=False)
    value, unit = distance_fields(nav.distance_m)
    icon = (icon_for(arrow.maneuver, arrow.modifier, left_hand_traffic)
            if arrow is not None and arrow.confident else HUD_STRAIGHT)
    return HudFrame(next_maneuver_info=icon, distance_value=value,
                    distance_unit=unit,
                    display_speed_limit=speed_limit_kmh,
                    display_speed_unit=1 if speed_limit_kmh else 0,
                    text_id3=sync_bit,
                    guidance_point_name=nav.next_road or "", guiding=True)


def next_sync_bit(previous: int, maneuver_changed: bool) -> int:
    """HUD can sync bit doi thi moi ve lai ten duong khi mui ten khong doi."""
    if maneuver_changed:
        return previous
    return (previous % 7) + 1


# --- Cong cu doi chieu: capture serial -> chuoi khung HUD -------------------
def _frames_from_capture(log_path, prints=None):
    """Doc capture cua emulator, tra ve lan luot (nav, arrow, frame).

    Giu lai mui ten gan nhat de cac khung "giu anh cu" (image_len == 1) van co
    icon dung - app chi gui anh MOT lan moi khi doi.
    """
    import re
    import sys
    sys.path.insert(0, __import__('os').path.dirname(__file__))
    import vmlhud_nav as nav_mod

    pattern = re.compile(r"new CMD 0x(00|40) .*plen=(\d+) : ([0-9A-Fa-f]+)")
    arrow = None
    sync = 1
    previous_icon = None
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = pattern.search(line)
            if not match:
                continue
            command = int(match.group(1), 16)
            payload = bytes.fromhex(match.group(3))
            try:
                nav = nav_mod.decode_nav(payload, cmd=command, protocol="new")
            except ValueError:
                continue
            if command == 0x40 and prints is not None:
                length = int.from_bytes(payload[1:5], "big")
                if length > 1 and len(payload) >= 5 + length:
                    import vmlhud_arrow
                    found = vmlhud_arrow.classify(payload[5:5 + length], prints)
                    arrow = found if found.confident else None
            frame = frame_for(nav, arrow, sync_bit=sync)
            sync = next_sync_bit(sync, frame.next_maneuver_info != previous_icon)
            previous_icon = frame.next_maneuver_info
            yield nav, arrow, frame


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Doi capture dan duong VietMap thanh chuoi khung HUD Mazda.")
    parser.add_argument("log", help="capture serial cua emulator")
    parser.add_argument("--prints", default="out/arrow-fingerprints.json",
                        help="cache van tay mui ten (tao bang vmlhud_arrow.py --app)")
    parser.add_argument("--all", action="store_true",
                        help="in moi khung thay vi chi in khi noi dung HUD doi")
    args = parser.parse_args()

    prints = None
    try:
        import vmlhud_arrow
        prints = vmlhud_arrow.load_fingerprints(args.prints)
    except (OSError, SystemExit):
        print("(khong co %s - se khong nhan dang duoc mui ten)" % args.prints)

    previous = None
    for _nav, arrow, frame in _frames_from_capture(args.log, prints):
        key = (frame.next_maneuver_info, frame.distance_value, frame.distance_unit,
               frame.guidance_point_name)
        if not args.all and key == previous:
            continue
        previous = key
        if not frame.guiding:
            print("HUD: (xoa guidance)")
            continue
        unit = {UNIT_METERS: "m", UNIT_KILOMETERS: "km"}.get(frame.distance_unit, "?")
        print("HUD: icon=%-2d %6.1f %-2s  %-28s %s"
              % (frame.next_maneuver_info, frame.distance_value / 10.0, unit,
                 frame.guidance_point_name,
                 ("[%s/%s]" % (arrow.maneuver, arrow.modifier)) if arrow else ""))


if __name__ == "__main__":
    main()
