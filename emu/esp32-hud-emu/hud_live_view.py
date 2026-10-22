#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Doc capture.jsonl cua board va in ra "HUD Mazda se ve gi" qua GuidanceBuilder.

Cach dung: python hud_live_view.py <capture.jsonl>
Mo tung dong Guidance nhu lenh VBS tuong ung (icon/duong/khoang cach/sync).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bridge"))
sys.path.insert(0, str(ROOT / "tests"))

import vmlhud_vbs as vbs  # noqa: E402
from vmlhud_nav import NavInfo  # noqa: E402

# Chi ten icon (bo don vi: HUD_UNIT_* cung la so 1/3 nhu HUD_STRAIGHT/HUD_LEFT...).
ICON_NAMES = {v: k for k, v in
              ((n, getattr(vbs, n)) for n in dir(vbs)
               if n.startswith("HUD_") and not n.startswith("HUD_UNIT_"))}


def nav_from_event(d):
    return NavInfo(direction=d.get("direction_raw", 0),
                   distance_m=d.get("turn_distance_m", 0),
                   current_road=d.get("current_road", ""),
                   next_road=d.get("next_road", ""),
                   remain_dist_m=d.get("remaining_distance_m", 0),
                   remain_time_s=d.get("remaining_seconds", 0),
                   speed_limit_kmh=d.get("speed_limit_kmh", 0),
                   layout=d.get("layout", ""))


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "out/live-check2.jsonl")
    builder = vbs.GuidanceBuilder()
    nav_frames = guidance_out = 0
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "navigation":
            continue
        nav_frames += 1
        g = builder.feed(nav_from_event(d))
        if g is None:
            continue
        guidance_out += 1
        if g.clear:
            print(f"[{d['timestamp']}] CLEAR - xoa guidance khoi HUD")
        else:
            icon = ICON_NAMES.get(g.icon, f"code {g.icon}")
            unit = "km" if g.unit == vbs.HUD_UNIT_KM else "m"
            print(f"[{d['timestamp']}] HUD: {icon} | {g.distance} {unit} | duong: {g.road!r} | sync={g.sync}")
    print(f"-- {nav_frames} khung nav -> {guidance_out} lenh VBS")


if __name__ == "__main__":
    main()
