# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test vmlhud_vbs: nav that -> guidance VBS, dung fixture tu capture that."""
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))

from vmlhud_nav import NavInfo  # noqa: E402
import vmlhud_vbs as vbs  # noqa: E402


@dataclass
class FakeArrow:
    maneuver: str
    modifier: str
    score: float = 1.0
    margin: float = 0.9

    def confident(self):
        return self.score >= 0.9 and self.margin >= 0.05


def nav(**kw):
    base = dict(direction=0xFE, distance_m=150, current_road="", next_road="Quốc Lộ 13",
                remain_time_s=1527, remain_dist_m=8253, speed_kmh=0, speed_limit_kmh=0,
                layout="variable2", raw=b"")
    base.update(kw)
    return NavInfo(**base)


class IconMapTests(unittest.TestCase):
    def test_capture_case_end_of_road_right(self):
        # Capture that 22-10: end_of_road/right o Dut Duong So 7, re phai vao QL13.
        self.assertEqual(vbs.icon_for("end_of_road", "right"), vbs.HUD_RIGHT)

    def test_all_modifier_variants(self):
        cases = {
            ("turn", "left"): vbs.HUD_LEFT,
            ("turn", "sharp right"): vbs.HUD_SHARP_RIGHT,
            ("turn", "slight left"): vbs.HUD_SLIGHT_LEFT,
            ("turn", "uturn"): vbs.HUD_U_TURN_LEFT,
            ("fork", "right"): vbs.HUD_FORK_RIGHT,
            ("merge", "left"): vbs.HUD_MERGE_LEFT,
            ("off_ramp", "right"): vbs.HUD_OFF_RAMP_RIGHT,
            ("off_ramp", "left"): vbs.HUD_OFF_RAMP_LEFT,
            ("depart", None): vbs.HUD_FLAG,
            ("arrive", "straight"): vbs.HUD_DESTINATION,
            ("continue", "straight"): vbs.HUD_STRAIGHT,
            ("notification", "left"): vbs.HUD_STRAIGHT,  # mac dinh
        }
        for key, want in cases.items():
            self.assertEqual(vbs.icon_for(*key), want, key)

    def test_modifier_is_normalised(self):
        self.assertEqual(vbs.icon_for("turn", " Sharp Right "), vbs.HUD_SHARP_RIGHT)


class DistanceTests(unittest.TestCase):
    def test_meters_under_1km(self):
        self.assertEqual(vbs.map_distance(150), (150, vbs.HUD_UNIT_METERS))

    def test_km_over_1km(self):
        # 8253 m -> 83 (x100 m) hien "8.3 km" nhu man hinh app.
        self.assertEqual(vbs.map_distance(8253), (83, vbs.HUD_UNIT_KM))

    def test_clamp_u16(self):
        # 200 km -> 2000 (x 100 m); khong bao gio tran u16 voi khoang cach
        # duong bo thuc te; tran chi xay ra voi so phi le.
        self.assertEqual(vbs.map_distance(200_000), (2000, vbs.HUD_UNIT_KM))
        self.assertEqual(vbs.map_distance(0xFFFFFFFF)[0], 0xFFFF)


class GuidanceBuilderTests(unittest.TestCase):
    def test_first_guidance_with_arrow(self):
        b = vbs.GuidanceBuilder()
        g = b.feed(nav(), FakeArrow("end_of_road", "right"))
        self.assertEqual((g.icon, g.distance, g.unit, g.road), (vbs.HUD_RIGHT, 150, 1, "Quốc Lộ 13"))
        self.assertEqual(g.sync, 1)
        self.assertFalse(g.clear)

    def test_duplicate_suppressed_then_sync_rotates(self):
        b = vbs.GuidanceBuilder()
        g1 = b.feed(nav(), FakeArrow("end_of_road", "right"))
        self.assertIsNone(b.feed(nav(), FakeArrow("end_of_road", "right")))
        g2 = b.feed(nav(distance_m=100), FakeArrow("end_of_road", "right"))
        self.assertEqual(g2.distance, 100)
        self.assertEqual(g2.sync, g1.sync + 1)

    def test_distance_shrinks_without_new_arrow(self):
        # Anh mui ten chi gui khi doi; cac khung sau arrow=None phai giu icon.
        b = vbs.GuidanceBuilder()
        g1 = b.feed(nav(), FakeArrow("turn", "left"))
        g2 = b.feed(nav(distance_m=80), None)
        self.assertEqual(g2.icon, vbs.HUD_LEFT)
        self.assertEqual(g2.distance, 80)

    def test_idle_frame_emits_clear_once(self):
        b = vbs.GuidanceBuilder()
        b.feed(nav(), FakeArrow("turn", "left"))
        clear = b.feed(nav(distance_m=0xFFFFFFFF, next_road="", remain_dist_m=0))
        self.assertTrue(clear.clear)
        self.assertEqual(clear.icon, 0)
        # Nhan roi tiep theo khong phat lai.
        self.assertIsNone(b.feed(nav(distance_m=0xFFFFFFFF, next_road="", remain_dist_m=0)))

    def test_no_road_no_arrow_is_skipped(self):
        b = vbs.GuidanceBuilder()
        self.assertIsNone(b.feed(nav(next_road="", current_road=""), None))

    def test_after_clear_guidance_resumes(self):
        b = vbs.GuidanceBuilder()
        b.feed(nav(), FakeArrow("turn", "left"))
        b.feed(nav(distance_m=0xFFFFFFFF, next_road=""))
        g = b.feed(nav(distance_m=300), FakeArrow("turn", "right"))
        self.assertEqual(g.icon, vbs.HUD_RIGHT)
        self.assertEqual(g.distance, 300)


class RealCaptureTests(unittest.TestCase):
    """Chay tren capture that 22-10-2026 neu con file: khung nhan roi phai
    tao dung 1 tin hieu clear, khung dan duong phai co ten duong QL13."""

    CAPTURE = ROOT / "out" / "cycle-trial-3.jsonl"

    def test_idle_and_guidance_from_capture(self):
        if not self.CAPTURE.exists():
            self.skipTest("capture fixture not present")
        cleared = guided = 0
        builder = vbs.GuidanceBuilder()
        for line in self.CAPTURE.open(encoding="utf-8"):
            d = json.loads(line)
            if d.get("type") != "navigation":
                continue
            info = NavInfo(direction=d.get("direction_raw", 0),
                           distance_m=d.get("turn_distance_m", 0),
                           current_road=d.get("current_road", ""),
                           next_road=d.get("next_road", ""),
                           remain_dist_m=d.get("remaining_distance_m", 0),
                           layout=d.get("layout", ""))
            out = builder.feed(info)
            if out is None:
                continue
            if out.clear:
                cleared += 1
            else:
                guided += 1
                self.assertTrue(out.road, "guidance phai co ten duong")
        self.assertGreaterEqual(guided, 1)
        # Capture gom nhieu tuyen: moi lan thoat tuyen phat 1 lenh clear,
        # nhung khong the nhieu hon so lan bat dau lai dan duong.
        self.assertGreaterEqual(cleared, 1)
        self.assertLessEqual(cleared, 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
