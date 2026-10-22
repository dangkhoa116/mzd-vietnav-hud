"""Kiem bo nhan dang anh mui ten (bridge/vmlhud_arrow.py).

Bo asset cua app khong nam trong repo, nen test tu dung mot bo asset gia bang
PIL roi kiem toan bo duong di: tao van tay -> luu/doc cache -> phan loai ->
tach ten asset thanh (maneuver, modifier) -> doc anh tu capture CMD 0x40.
"""
import io
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bridge'))

try:
    from PIL import Image, ImageDraw
    import numpy  # noqa: F401  (vmlhud_arrow can numpy)
    import vmlhud_arrow as arrow
except ImportError as exc:  # pragma: no cover
    # Skip qua setUpModule: SkipTest ngay luc import lam unittest loader
    # nem exception thay voi bao skip (thay tren CI).
    def setUpModule():
        raise unittest.SkipTest('can Pillow va numpy: %s' % exc)


def icon(kind):
    """Ve mot icon 60x60 don gian, moi 'kind' mot hinh ro rang khac nhau."""
    image = Image.new('RGBA', (60, 60), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    white = (255, 255, 255, 255)
    if kind == 'right':
        draw.line((10, 50, 10, 30), fill=white, width=8)
        draw.line((10, 30, 50, 30), fill=white, width=8)
        draw.polygon([(44, 16), (58, 30), (44, 44)], fill=white)
    elif kind == 'left':
        draw.line((50, 50, 50, 30), fill=white, width=8)
        draw.line((50, 30, 10, 30), fill=white, width=8)
        draw.polygon([(16, 16), (2, 30), (16, 44)], fill=white)
    elif kind == 'straight':
        draw.line((30, 56, 30, 16), fill=white, width=8)
        draw.polygon([(16, 20), (30, 4), (44, 20)], fill=white)
    else:  # uturn
        draw.arc((12, 10, 48, 46), start=180, end=360, fill=white, width=8)
        draw.line((48, 28, 48, 54), fill=white, width=8)
    return image


def png_bytes(image):
    buf = io.BytesIO()
    image.save(buf, 'PNG')
    return buf.getvalue()


def jpeg_bytes(image):
    """Giong app: det len nen den roi ma hoa JPEG (co mat mat)."""
    flat = Image.alpha_composite(Image.new('RGBA', image.size, (0, 0, 0, 255)), image)
    buf = io.BytesIO()
    flat.convert('RGB').save(buf, 'JPEG', quality=80)
    return buf.getvalue()


SHAPES = {'direction_turn_right': 'right',
          'direction_end_of_road_right': 'right',
          'direction_turn_left': 'left',
          'direction_turn_straight': 'straight',
          'direction_uturn': 'uturn'}


def fake_prints():
    return {name: [arrow._vector(icon(shape))] for name, shape in SHAPES.items()}


class AssetNameTests(unittest.TestCase):
    def test_splits_type_and_modifier(self):
        cases = {
            'direction_end_of_road_right': ('end_of_road', 'right'),
            'direction_turn_slight_left': ('turn', 'slight_left'),
            'direction_roundabout_sharp_right': ('roundabout', 'sharp_right'),
            'direction_continue_uturn': ('continue', 'uturn'),
            'direction_arrive': ('arrive', ''),
            'direction_uturn': ('', 'uturn'),
        }
        for name, expected in cases.items():
            self.assertEqual(arrow.parse_asset_name(name), expected, name)

    def test_misspelled_asset_folds_onto_the_correct_type(self):
        # Bo asset that co ca "notification" lan "notificaiton".
        self.assertEqual(arrow.parse_asset_name('direction_notificaiton_right'),
                         ('notification', 'right'))
        self.assertEqual(arrow.parse_asset_name('direction_notification_right'),
                         ('notification', 'right'))

    def test_longer_modifier_wins_over_its_suffix(self):
        # "slight_right" khong duoc rut gon thanh "right".
        self.assertEqual(arrow.parse_asset_name('direction_turn_slight_right')[1],
                         'slight_right')


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.prints = fake_prints()

    def test_jpeg_round_trip_recovers_the_modifier(self):
        for name, shape in SHAPES.items():
            match = arrow.classify(jpeg_bytes(icon(shape)), self.prints)
            self.assertTrue(match.confident, '%s: %r' % (name, match))
            self.assertEqual(match.modifier, arrow.parse_asset_name(name)[1],
                             '%s -> %s' % (name, match.asset))

    def test_assets_sharing_a_shape_do_not_shrink_the_margin(self):
        # turn_right va end_of_road_right ve giong het nhau; margin phai do voi
        # huong re KHAC, neu khong se luon bao "yeu".
        match = arrow.classify(jpeg_bytes(icon('right')), self.prints)
        self.assertIn(match.asset,
                      ('direction_turn_right', 'direction_end_of_road_right'))
        self.assertGreater(match.margin, 0.05)

    def test_unrelated_image_is_reported_as_not_confident(self):
        # Icon thoi tiet/nhan roi cung di qua cung mot o anh nhu mui ten.
        blob = Image.new('RGBA', (60, 60), (0, 0, 0, 255))
        draw = ImageDraw.Draw(blob)
        draw.ellipse((8, 20, 52, 48), fill=(255, 255, 255, 255))
        match = arrow.classify(jpeg_bytes(blob), self.prints)
        self.assertFalse(match.confident, repr(match))


class CacheTests(unittest.TestCase):
    def test_cache_survives_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'nested', 'prints.json')
            arrow.save_fingerprints(fake_prints(), path)
            loaded = arrow.load_fingerprints(path)
            self.assertEqual(sorted(loaded), sorted(SHAPES))
            match = arrow.classify(jpeg_bytes(icon('left')), loaded)
            self.assertEqual(match.modifier, 'left')

    def test_cache_with_a_different_size_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'prints.json')
            arrow.save_fingerprints(fake_prints(), path)
            with open(path, encoding='utf-8') as handle:
                payload = json.load(handle)
            payload['size'] = arrow.SIZE + 8
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle)
            with self.assertRaises(SystemExit):
                arrow.load_fingerprints(path)


class CaptureTests(unittest.TestCase):
    def test_reads_images_and_skips_keep_previous_frames(self):
        image = jpeg_bytes(icon('right'))
        with_image = b'\xfe' + struct.pack('>I', len(image)) + image + b'\x00' * 16
        keep = bytes.fromhex('FE0000000101000000960E00' + '00' * 10)
        lines = [
            '[RX ] new CMD 0x40 ts=1 plen=%d : %s\n' % (len(keep), keep.hex()),
            '[RX ] new CMD 0x40 ts=2 plen=%d : %s\n' % (len(with_image), with_image.hex()),
            '[RX ] new CMD 0x40 ts=3 plen=%d : %s\n' % (len(with_image), with_image.hex()),
            '[RX ] new CMD 0x00 ts=4 plen=2 : 0000\n',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'capture.log')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.writelines(lines)
            found = list(arrow.images_in_capture(path))
        # Chi mot anh: khung "giu anh cu" bi bo, khung trung lap bi gom.
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][:2], b'\xff\xd8')


if __name__ == '__main__':
    unittest.main()
