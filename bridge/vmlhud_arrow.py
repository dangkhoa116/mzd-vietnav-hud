#!/usr/bin/env python3
"""Nhan dang anh mui ten VIETMAP LIVE gui kem khung CMD 0x40.

Van de: byte `direction` trong moi layout dan duong cua app iOS 3.4.3 luon la
0xFE, khong mang y nghia (xem docs/vmlhud-nav-payloads.md muc 10.3). Huong re
that nam trong **anh JPEG** di kem khung variable2. HUD zin Mazda lai tu ve mui
ten theo MA huong re chu khong nhan anh, nen phai doi anh -> ma.

Cach lam: anh app gui chi la ban ma hoa lai cua mot asset co san trong chinh
app (`lib/assets/hud/directions/{dark,light}/direction_*.png`). So anh nhan duoc
voi bo asset do bang tuong quan chuan hoa se ra dung ten asset.

Khong keo asset vao repo: nguoi dung tro toi ban APK/IPA cua minh, module tu
trich va cache van tay ra file JSON (mac dinh trong `out/`, da bi git ignore).

Dung:
    python bridge/vmlhud_arrow.py --app vietmap.apk --image out/arrow-2.jpg
    python bridge/vmlhud_arrow.py --app vietmap.apk --log out/capture.log
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field

SIZE = 48  # canh anh sau khi chuan hoa; 32..96 cho ket qua nhu nhau
ASSET_RE = re.compile(r"/hud/directions/(dark|light)/(direction_[a-z_]+)\.png$")

# Thu tu quan trong: hau to dai kiem truoc de "slight_right" khong khop "right".
MODIFIERS = ("slight_left", "slight_right", "sharp_left", "sharp_right",
             "uturn", "straight", "left", "right")
# Cac "type" trong bo asset, theo cach dat ten kieu Mapbox/Valhalla.
TYPES = ("end_of_road", "new_name", "on_ramp", "off_ramp", "roundabout",
         "notificaiton", "notification", "continue", "depart", "arrive",
         "invalid", "rotary", "merge", "turn", "fork", "flag", "close",
         "updown")


def parse_asset_name(name: str) -> tuple[str, str]:
    """"direction_end_of_road_right" -> ("end_of_road", "right")."""
    body = name[len("direction_"):] if name.startswith("direction_") else name
    modifier = ""
    for mod in MODIFIERS:
        if body == mod:
            return "", mod
        if body.endswith("_" + mod):
            modifier = mod
            body = body[: -len(mod) - 1]
            break
    kind = body if body in TYPES else body
    # "notificaiton" la loi chinh ta co that trong bo asset; gom ve mot ten.
    if kind == "notificaiton":
        kind = "notification"
    return kind, modifier


@dataclass
class ArrowMatch:
    asset: str                  # ten asset khop nhat, vd "direction_end_of_road_right"
    maneuver: str               # "end_of_road"
    modifier: str               # "right"
    score: float                # tuong quan 0..1 voi asset khop nhat
    margin: float               # cach biet so voi asset dau tien co MODIFIER khac
    runners_up: list = field(default_factory=list)

    @property
    def confident(self) -> bool:
        """Du tin de dung lam ma huong re cho HUD."""
        return self.score >= 0.90 and self.margin >= 0.01


def _vector(image):
    """Anh -> vector da tru trung binh va chia do lech chuan (de so tuong quan)."""
    from PIL import Image
    import numpy as np

    image = image.convert("RGBA")
    # Anh app gui da duoc det len nen den khi ma hoa JPEG; lam y het de so sanh.
    flat = Image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 255)), image)
    data = np.asarray(flat.convert("L").resize((SIZE, SIZE), Image.BILINEAR),
                      dtype="float32")
    data -= data.mean()
    deviation = data.std()
    return (data / deviation if deviation > 1e-6 else data).reshape(-1)


def build_fingerprints(app_path: str) -> dict:
    """Trich bo asset mui ten tu APK (hoac thu muc IPA da giai nen)."""
    from PIL import Image

    prints: dict[str, list] = {}
    if os.path.isdir(app_path):
        for root, _dirs, files in os.walk(app_path):
            for entry in files:
                full = os.path.join(root, entry).replace("\\", "/")
                match = ASSET_RE.search(full)
                if match:
                    with open(full, "rb") as handle:
                        prints.setdefault(match.group(2), []).append(
                            _vector(Image.open(io.BytesIO(handle.read()))))
    else:
        with zipfile.ZipFile(app_path) as archive:
            for entry in archive.namelist():
                match = ASSET_RE.search(entry)
                if match:
                    prints.setdefault(match.group(2), []).append(
                        _vector(Image.open(io.BytesIO(archive.read(entry)))))
    if not prints:
        raise SystemExit("khong thay asset direction_*.png nao trong " + app_path)
    return prints


def save_fingerprints(prints: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"size": SIZE,
               "assets": {k: [[round(float(x), 4) for x in v] for v in vs]
                          for k, vs in prints.items()}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def load_fingerprints(path: str) -> dict:
    import numpy as np

    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("size") != SIZE:
        raise SystemExit("cache dung SIZE khac; xoa %s roi tao lai" % path)
    return {k: [np.asarray(v, dtype="float32") for v in vs]
            for k, vs in payload["assets"].items()}


def classify(image_bytes: bytes, prints: dict) -> ArrowMatch:
    """So anh nhan duoc voi bo asset; tra ve asset khop nhat va do tin cay."""
    from PIL import Image
    import numpy as np

    query = _vector(Image.open(io.BytesIO(image_bytes)))
    scored = sorted(((max(float((query * ref).mean()) for ref in refs), name)
                     for name, refs in prints.items()), reverse=True)
    best_score, best = scored[0]
    _kind, best_modifier = parse_asset_name(best)
    # Cac asset cung mot huong re thuong giong het nhau (vd on_ramp_right va
    # continue_right), nen cach biet chi co y nghia khi so voi HUONG RE khac.
    margin = best_score
    for score, name in scored[1:]:
        if parse_asset_name(name)[1] != best_modifier:
            margin = best_score - score
            break
    kind, modifier = parse_asset_name(best)
    return ArrowMatch(asset=best, maneuver=kind, modifier=modifier,
                      score=best_score, margin=margin,
                      runners_up=[(round(s, 4), n) for s, n in scored[1:4]])


def images_in_capture(log_path: str):
    """Lay cac anh mui ten tu capture serial cua emulator (khung CMD 0x40)."""
    pattern = re.compile(r"new CMD 0x40 .*plen=(\d+) : ([0-9A-Fa-f]+)")
    seen = set()
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = pattern.search(line)
            if not match:
                continue
            payload = bytes.fromhex(match.group(2))
            length = int.from_bytes(payload[1:5], "big")
            if length <= 1 or len(payload) < 5 + length:
                continue  # image_len==1 nghia la "giu anh cu", khong co anh moi
            image = payload[5:5 + length]
            digest = hash(image)
            if digest not in seen:
                seen.add(digest)
                yield image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", help="APK, hoac thu muc Payload/ cua IPA da giai nen")
    parser.add_argument("--cache", default=os.path.join("out", "arrow-fingerprints.json"))
    parser.add_argument("--image", action="append", default=[],
                        help="file anh can nhan dang (lap lai duoc)")
    parser.add_argument("--log", help="capture serial: nhan dang moi anh trong khung 0x40")
    args = parser.parse_args()

    if args.app:
        prints = build_fingerprints(args.app)
        save_fingerprints(prints, args.cache)
        print("da tao van tay cho %d asset -> %s" % (len(prints), args.cache))
    elif os.path.exists(args.cache):
        prints = load_fingerprints(args.cache)
    else:
        parser.exit(2, "chua co cache %s; chay lai kem --app duong/dan/vietmap.apk\n"
                    % args.cache)

    blobs = []
    for path in args.image:
        with open(path, "rb") as handle:
            blobs.append((path, handle.read()))
    if args.log:
        for index, image in enumerate(images_in_capture(args.log)):
            blobs.append(("%s[anh %d]" % (args.log, index), image))

    for label, blob in blobs:
        match = classify(blob, prints)
        flag = "OK " if match.confident else "YEU"
        print("%s %-28s score=%.4f margin=%.4f  %s / %s" %
              (flag, label, match.score, match.margin,
               match.maneuver or "-", match.modifier or "-"))
        if not match.confident:
            print("      gan nhat: %s" % match.runners_up)


if __name__ == "__main__":
    main()
