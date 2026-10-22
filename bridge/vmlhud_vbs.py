# SPDX-License-Identifier: AGPL-3.0-or-later
"""Anh xa nav VIETMAP (BLE gia HUD) -> khung com.jci.vbs.navi cua CMU150.

Dau vao la ``NavInfo`` (bridge/vmlhud_nav.py) + ket qua doi chieu anh mui ten
(``ArrowMatch`` cua bridge/vmlhud_arrow.py, co the None). Dau ra la ban ghi
``Guidance`` chinh xac cac truong cua ``VbsNaviHudDisplay`` +
``VbsNaviHudMsg2`` (xem oem/libjcivbsnaviclient.h trong checkout
mazda-carplay-hud: u32 maneuver, u16 distance, u8 unit, u16 speed limit,
u8 unit, u8 sync; Msg2 = ten duong UTF-8 + sync bit).

Nguon cac con so:
- Ma mui ten Mazda: hud_send.cpp enum MazdaIcon (goctu AA table da kiem tren
  xe that). Ban dan: reference hud.cpp NaviTurns.
- Don vi khoang cach Mazda: 1=MET, 2=MILE, 3=KM, 4=YARD, 5=FEET
  (map_distance_unit trong hud_send.cpp).
- Sync bit quay vong 1..7, Msg2 luon gui kem Msg1 (mirror native hud_send).
- Xoa guidance: khung nhan roi (distance 0xFFFFFFFF + duoi toan 0) - da thay
  tren capture that 22-10-2026 (docs/vmlhud-nav-payloads.md section 10).
"""
from dataclasses import dataclass

# Ma mui ten Mazda HUD (subset dung cho anh xa Mapbox asset).
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

HUD_UNIT_METERS = 1
HUD_UNIT_KM = 3
# Nguong doi sang km: app hien "8.3 km" tu khoang 1 km; duoi do hien met.
KM_THRESHOLD_M = 1000

_IDLE_DISTANCE = 0xFFFFFFFF

# (kind, modifier) cua ten asset Mapbox -> ma Mazda.
# kind/modifier la dau ra parse_asset_name() cua vmlhud_arrow.
_ASSET_ICON = {
    ("turn", "left"): HUD_LEFT,
    ("turn", "right"): HUD_RIGHT,
    ("turn", "sharp left"): HUD_SHARP_LEFT,
    ("turn", "sharp right"): HUD_SHARP_RIGHT,
    ("turn", "slight left"): HUD_SLIGHT_LEFT,
    ("turn", "slight right"): HUD_SLIGHT_RIGHT,
    ("turn", "uturn"): HUD_U_TURN_LEFT,
    ("end_of_road", "left"): HUD_LEFT,
    ("end_of_road", "right"): HUD_RIGHT,
    ("on_ramp", "left"): HUD_LEFT,
    ("on_ramp", "right"): HUD_RIGHT,
    ("off_ramp", "left"): HUD_OFF_RAMP_LEFT,
    ("off_ramp", "right"): HUD_OFF_RAMP_RIGHT,
    ("fork", "left"): HUD_FORK_LEFT,
    ("fork", "right"): HUD_FORK_RIGHT,
    ("merge", "left"): HUD_MERGE_LEFT,
    ("merge", "right"): HUD_MERGE_RIGHT,
    ("continue", "left"): HUD_SLIGHT_LEFT,
    ("continue", "right"): HUD_SLIGHT_RIGHT,
    ("continue", "slight left"): HUD_SLIGHT_LEFT,
    ("continue", "slight right"): HUD_SLIGHT_RIGHT,
    ("new_name", "left"): HUD_LEFT,
    ("new_name", "right"): HUD_RIGHT,
    ("depart", "left"): HUD_FLAG_LEFT,
    ("depart", "right"): HUD_FLAG_RIGHT,
    ("depart", "straight"): HUD_FLAG,
    ("arrive", "left"): HUD_DESTINATION_LEFT,
    ("arrive", "right"): HUD_DESTINATION_RIGHT,
    ("arrive", "straight"): HUD_DESTINATION,
    # Roundabout: AA table de 0 (trang) vi phu thuoc goc ra; asset Mapbox co
    # modifier nen dung mui ten co ban tuong ung thay vi trang.
    ("roundabout", "left"): HUD_LEFT,
    ("roundabout", "right"): HUD_RIGHT,
    ("roundabout", "slight left"): HUD_SLIGHT_LEFT,
    ("roundabout", "slight right"): HUD_SLIGHT_RIGHT,
    ("roundabout", "straight"): HUD_STRAIGHT,
    ("exit_roundabout", "left"): HUD_LEFT,
    ("exit_roundabout", "right"): HUD_RIGHT,
    ("exit_roundabout", "slight left"): HUD_SLIGHT_LEFT,
    ("exit_roundabout", "slight right"): HUD_SLIGHT_RIGHT,
    ("exit_roundabout", "straight"): HUD_STRAIGHT,
}
# Tat ca kind/modifier con lai (continue straight, turn straight...) -> thang.
_DEFAULT_ICON = HUD_STRAIGHT


def icon_for(maneuver, modifier):
    """Ma Mazda cho (kind, modifier) cua asset; modifier None -> straight."""
    key = (maneuver, (modifier or "straight").strip().lower())
    return _ASSET_ICON.get(key, _DEFAULT_ICON)


@dataclass
class Guidance:
    """Mot lan can day len com.jci.vbs.navi; ``None`` = khong gi thay doi."""
    icon: int = 0            # nextManeuverInfo; 0 = xoa guidance
    distance: int = 0        # u16 sau khi chon don vi
    unit: int = 0            # 1=met, 3=km
    road: str = ""           # guidancePointName (Msg2), UTF-8
    speed_limit: int = 0     # km/h; 0 = khong hien
    sync: int = 0            # text_ID3 / syncBit quay 1..7
    clear: bool = False      # day la tin hieu het dan duong


def map_distance(distance_m):
    """(gia tri u16, ma don vi) cho khoang cach met."""
    if distance_m >= KM_THRESHOLD_M:
        # km mot chu so thap phan (83 -> "8.3 km"), kieu app hien thi.
        return min(round(distance_m / 100.0), 0xFFFF), HUD_UNIT_KM
    return min(distance_m, 0xFFFF), HUD_UNIT_METERS


def is_idle(nav):
    """Khung nhan roi: het dan duong (distance ve 0xFFFFFFFF)."""
    return nav.distance_m == _IDLE_DISTANCE or nav.distance_m >= _IDLE_DISTANCE


class GuidanceBuilder:
    """Gop nav + mui ten thanh Guidance, chi phat khi thay doi.

    sync bit quay vong 1..7 tren moi lan phat lai (giong hud_send.cpp),
    de HUD phan biet cap nhat moi vs cap nhat lap.
    """

    def __init__(self):
        self._last = None
        self._sync = 0

    def _next_sync(self):
        self._sync = self._sync % 7 + 1
        return self._sync

    def feed(self, nav, arrow=None):
        """nav: NavInfo; arrow: ArrowMatch hoac None. Tra Guidance hoac None."""
        if is_idle(nav):
            if self._last is None:
                return None  # da o trang thai xoa
            self._last = None
            return Guidance(icon=0, sync=self._next_sync(), clear=True)
        # Ten duong: HUD hien ten duong sap re vao (= next_road cua app).
        road = (nav.next_road or nav.current_road).strip()
        if not road and not arrow:
            return None  # chua co du lieu chi dan
        if arrow is not None and arrow.confident():
            icon = icon_for(arrow.maneuver, arrow.modifier)
        else:
            icon = self._last[0] if self._last else _DEFAULT_ICON
        distance, unit = map_distance(nav.distance_m)
        limit = nav.speed_limit_kmh
        key = (icon, distance, unit, road, limit)
        if self._last is not None and self._last == key:
            return None  # khong thay doi gi
        self._last = key
        return Guidance(icon=icon, distance=distance, unit=unit, road=road,
                        speed_limit=limit, sync=self._next_sync())
