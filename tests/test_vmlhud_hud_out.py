"""Kiem bo doi dan duong VietMap -> khung com.jci.vbs.navi (bridge/vmlhud_hud_out.py).

Bang ma mui ten va cach tinh icon vong xuyen duoc soi guong tu hud_send.cpp cua
ban CarPlay da chay that tren HUD; test o day chot lai cac gia tri do de mot lan
sua tay khong lam lech am tham.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bridge'))

import vmlhud_hud_out as H
import vmlhud_nav as N


class IconTests(unittest.TestCase):
    def test_plain_turns_use_the_reference_codes(self):
        cases = {
            ('turn', 'left'): H.HUD_LEFT,
            ('turn', 'right'): H.HUD_RIGHT,
            ('turn', 'slight_left'): H.HUD_SLIGHT_LEFT,
            ('turn', 'slight_right'): H.HUD_SLIGHT_RIGHT,
            ('turn', 'sharp_left'): H.HUD_SHARP_LEFT,
            ('turn', 'sharp_right'): H.HUD_SHARP_RIGHT,
            ('turn', 'straight'): H.HUD_STRAIGHT,
        }
        for (maneuver, modifier), expected in cases.items():
            self.assertEqual(H.icon_for(maneuver, modifier), expected,
                             '%s/%s' % (maneuver, modifier))

    def test_end_of_road_is_treated_as_a_normal_turn(self):
        # Truong hop bat duoc that: Duong So 7 het duong, re phai vao QL13.
        self.assertEqual(H.icon_for('end_of_road', 'right'), H.HUD_RIGHT)
        self.assertEqual(H.icon_for('end_of_road', 'left'), H.HUD_LEFT)

    def test_ramps_forks_and_merges_have_their_own_glyphs(self):
        self.assertEqual(H.icon_for('off_ramp', 'right'), H.HUD_OFF_RAMP_RIGHT)
        self.assertEqual(H.icon_for('off_ramp', 'left'), H.HUD_OFF_RAMP_LEFT)
        self.assertEqual(H.icon_for('fork', 'left'), H.HUD_FORK_LEFT)
        self.assertEqual(H.icon_for('fork', 'right'), H.HUD_FORK_RIGHT)
        self.assertEqual(H.icon_for('merge', 'left'), H.HUD_MERGE_LEFT)
        self.assertEqual(H.icon_for('merge', 'right'), H.HUD_MERGE_RIGHT)
        # on_ramp dung chung icon re thuong, giong kTurnIcons cua ban tham chieu.
        self.assertEqual(H.icon_for('on_ramp', 'right'), H.HUD_RIGHT)

    def test_arrive_and_depart(self):
        self.assertEqual(H.icon_for('arrive', ''), H.HUD_DESTINATION)
        self.assertEqual(H.icon_for('arrive', 'left'), H.HUD_DESTINATION_LEFT)
        self.assertEqual(H.icon_for('arrive', 'right'), H.HUD_DESTINATION_RIGHT)
        self.assertEqual(H.icon_for('depart', ''), H.HUD_FLAG)
        self.assertEqual(H.icon_for('depart', 'right'), H.HUD_FLAG_RIGHT)

    def test_uturn_follows_the_side_of_the_road(self):
        self.assertEqual(H.icon_for('turn', 'uturn'), H.HUD_U_TURN_LEFT)
        self.assertEqual(H.icon_for('turn', 'uturn', left_hand_traffic=True),
                         H.HUD_U_TURN_RIGHT)

    def test_unknown_maneuver_falls_back_to_the_turn_table(self):
        self.assertEqual(H.icon_for('ten_la', 'right'), H.HUD_RIGHT)
        self.assertEqual(H.icon_for('', ''), H.HUD_STRAIGHT)


class RoundaboutTests(unittest.TestCase):
    def test_matches_the_angles_verified_on_the_real_hud(self):
        # Tu comment [BUILD-20] cua hud_send.cpp, da kiem truc tiep tren HUD:
        # straight(0)->43, right(+90)->40, left(270)->46, behind(180)->37.
        self.assertEqual(H.roundabout_icon(0), 43)
        self.assertEqual(H.roundabout_icon(90), 40)
        self.assertEqual(H.roundabout_icon(270), 46)
        self.assertEqual(H.roundabout_icon(180), 37)

    def test_left_hand_traffic_uses_the_other_bank(self):
        self.assertEqual(H.roundabout_icon(0, left_hand_traffic=True), 55)

    def test_every_angle_lands_inside_the_glyph_bank(self):
        for degrees in range(-720, 721, 7):
            self.assertIn(H.roundabout_icon(degrees), range(37, 49), degrees)

    def test_roundabout_maneuvers_route_through_the_angle_table(self):
        self.assertEqual(H.icon_for('roundabout', 'right'), H.roundabout_icon(90))
        self.assertEqual(H.icon_for('rotary', 'straight'), H.roundabout_icon(0))


class DistanceTests(unittest.TestCase):
    def test_metres_below_a_kilometre(self):
        self.assertEqual(H.distance_fields(150), (1500, H.UNIT_METERS))
        self.assertEqual(H.distance_fields(30), (300, H.UNIT_METERS))
        self.assertEqual(H.distance_fields(999), (9990, H.UNIT_METERS))

    def test_kilometres_from_one_kilometre_up(self):
        # 8253 m -> 8.2 km, dung nhu con so app hien ("8.3km" la lam tron len).
        self.assertEqual(H.distance_fields(1000), (10, H.UNIT_KILOMETERS))
        self.assertEqual(H.distance_fields(8253), (82, H.UNIT_KILOMETERS))
        self.assertEqual(H.distance_fields(14189), (141, H.UNIT_KILOMETERS))

    def test_value_never_overflows_the_u16_field(self):
        value, unit = H.distance_fields(99_999_999)
        self.assertLessEqual(value, 0xFFFF)
        self.assertEqual(unit, H.UNIT_KILOMETERS)

    def test_negative_or_missing_distance_yields_no_unit(self):
        self.assertEqual(H.distance_fields(-1), (0, H.UNIT_NONE))
        self.assertEqual(H.distance_fields(None), (0, H.UNIT_NONE))


class FakeArrow:
    def __init__(self, maneuver, modifier, confident=True):
        self.maneuver, self.modifier, self.confident = maneuver, modifier, confident


# Khung that bat duoc 22-10-2026 sau khi emulator tra PROTOCOL:2.2.2.
LIVE_GUIDING = bytes.fromhex(
    "FE0000000101000000960E5175E1BB9163204CE1BB99203133000000191B0000203D0000")
LIVE_IDLE = bytes.fromhex(
    "FE0000000101FFFFFFFF0F3330C2B0206DC6B0612076E1BBAB610000000000000000000000")


class FrameTests(unittest.TestCase):
    def test_real_guiding_frame_becomes_the_expected_hud_content(self):
        nav = N.decode_nav(LIVE_GUIDING)
        frame = H.frame_for(nav, FakeArrow('end_of_road', 'right'),
                            speed_limit_kmh=50)
        self.assertTrue(frame.guiding)
        self.assertEqual(frame.as_display(), {
            'nextManeuverInfo': H.HUD_RIGHT,
            'distanceValue': 1500, 'distanceUnit': H.UNIT_METERS,
            'displaySpeedLimit': 50, 'displaySpeedUnit': 1, 'text_ID3': 1})
        self.assertEqual(frame.as_msg2(),
                         {'guidancePointName': 'Quốc Lộ 13', 'syncBit': 1})

    def test_real_idle_frame_clears_the_hud(self):
        nav = N.decode_nav(LIVE_IDLE)
        frame = H.frame_for(nav, FakeArrow('end_of_road', 'right'))
        self.assertFalse(frame.guiding)
        self.assertEqual(frame.next_maneuver_info, H.HUD_NONE)
        self.assertEqual(frame.distance_unit, H.UNIT_NONE)
        # Chuoi thoi tiet trong next_road KHONG duoc dua len HUD nhu ten duong.
        self.assertEqual(frame.guidance_point_name, '')

    def test_weak_arrow_match_falls_back_instead_of_guessing(self):
        nav = N.decode_nav(LIVE_GUIDING)
        frame = H.frame_for(nav, FakeArrow('merge', 'left', confident=False))
        self.assertEqual(frame.next_maneuver_info, H.HUD_STRAIGHT)

    def test_missing_arrow_keeps_distance_and_road_name(self):
        # Khung "giu anh cu" khong kem anh; van phai cap nhat khoang cach.
        nav = N.decode_nav(LIVE_GUIDING)
        frame = H.frame_for(nav, None)
        self.assertEqual(frame.distance_value, 1500)
        self.assertEqual(frame.guidance_point_name, 'Quốc Lộ 13')

    def test_speed_limit_unit_is_off_when_there_is_no_limit(self):
        nav = N.decode_nav(LIVE_GUIDING)
        self.assertEqual(H.frame_for(nav, None, speed_limit_kmh=0).display_speed_unit, 0)
        self.assertEqual(H.frame_for(nav, None, speed_limit_kmh=60).display_speed_unit, 1)


class SyncBitTests(unittest.TestCase):
    def test_cycles_one_to_seven_when_the_maneuver_is_unchanged(self):
        seen, bit = [], 1
        for _ in range(9):
            bit = H.next_sync_bit(bit, maneuver_changed=False)
            seen.append(bit)
        self.assertEqual(seen, [2, 3, 4, 5, 6, 7, 1, 2, 3])

    def test_holds_still_when_the_maneuver_changes(self):
        self.assertEqual(H.next_sync_bit(4, maneuver_changed=True), 4)

    def test_frame_rejects_an_out_of_range_sync_bit(self):
        nav = N.decode_nav(LIVE_GUIDING)
        self.assertEqual(H.frame_for(nav, None, sync_bit=0).text_id3, 1)
        self.assertEqual(H.frame_for(nav, None, sync_bit=9).text_id3, 1)


if __name__ == '__main__':
    unittest.main()
