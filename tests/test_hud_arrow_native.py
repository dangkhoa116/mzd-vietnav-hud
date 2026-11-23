"""Native JPEG classifier and complete ATT -> arrow/nav -> OEM VBS ABI pipeline.

Synthetic shapes avoid redistributing application assets. The release build
also checks owner-supplied app assets locally via native/validate_arrow_model.py.
"""
import ctypes as C
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import subprocess
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'native'))
sys.path.insert(0,str(ROOT/'tests'))
from build_arrow_model import compile_model, fnv
from test_hud_guidance import _compile, _unload
import test_hud_guidance as guidance_tests
from hud_emulator.protocol import encode
from bridge import vmlhud_nav as nav
try:
    from PIL import Image, ImageDraw
except ImportError:
    def setUpModule():
        raise unittest.SkipTest('Pillow is required for native image tests')


class Result(C.Structure):
    _fields_=[(name,C.c_uint) for name in ('icon','group','score','margin')]


def image(kind):
    im=Image.new('RGB',(60,60),'black');d=ImageDraw.Draw(im)
    if kind=='right':
        d.line((10,53,10,30,48,30),fill='white',width=7)
        d.polygon(((43,17),(57,30),(43,43)),fill='white')
    elif kind=='left':
        d.line((50,53,50,30,12,30),fill='white',width=7)
        d.polygon(((17,17),(3,30),(17,43)),fill='white')
    elif kind=='straight':
        d.line((30,55,30,15),fill='white',width=7)
        d.polygon(((17,20),(30,3),(43,20)),fill='white')
    else:
        d.ellipse((12,12,48,48),fill='gray')  # weather/non-direction input
    return im


def encoded_image(kind,quality=90,progressive=False,size=None):
    im=image(kind)
    if size: im=im.resize(size)
    out=io.BytesIO();im.save(out,'JPEG',quality=quality,progressive=progressive)
    return out.getvalue()


def synthetic_model(lib,folder):
    app=Path(folder)/'synthetic.apk'
    with zipfile.ZipFile(app,'w') as z:
        for kind in ('left','right','straight'):
            out=io.BytesIO();image(kind).save(out,'PNG')
            z.writestr(f'assets/flutter_assets/lib/assets/hud/directions/dark/direction_turn_{kind}.png',out.getvalue())
    return compile_model(app,lib)[0]


class ArrowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path,cls.work=_compile('arrow.so',['hud_arrow.c','vendor/picojpeg/picojpeg.c'])
        cls.lib=C.CDLL(str(cls.path))
        cls.lib.vn_arrow_vector_gray.argtypes=[C.c_char_p,C.c_uint,C.c_uint,C.c_void_p]
        cls.lib.vn_arrow_model_valid.argtypes=[C.c_char_p,C.c_uint]
        cls.lib.vn_arrow_match.argtypes=[C.c_char_p,C.c_uint,C.c_char_p,C.c_uint,C.c_void_p]
        cls.model=synthetic_model(cls.lib,cls.work)

    @classmethod
    def tearDownClass(cls): _unload(cls.lib,cls.work)

    def match(self,jpeg,model=None):
        model=self.model if model is None else model
        result=Result()
        found=self.lib.vn_arrow_match(model,len(model),jpeg,len(jpeg),C.byref(result))
        return found,result

    def test_directions_survive_jpeg_reencoding_and_resize(self):
        for kind,icon in (('left',2),('right',3),('straight',1)):
            for quality in (60,80,95,100):
                for size in (None,(64,64)):
                    with self.subTest(kind=kind,quality=quality,size=size):
                        found,result=self.match(encoded_image(kind,quality,size=size))
                        self.assertEqual((found,result.icon),(1,icon))

    def test_weather_flat_progressive_oversize_and_truncated_images_are_rejected(self):
        jpeg=encoded_image('right')
        flat=io.BytesIO();Image.new('RGB',(60,60),'black').save(flat,'JPEG')
        invalid=[encoded_image('weather'),flat.getvalue(),jpeg[:-2],jpeg[:50],
                 encoded_image('right',progressive=True),encoded_image('right',size=(129,129)),
                 b'\xff\xd8'+bytes(8192)+b'\xff\xd9']
        for value in invalid:
            self.assertEqual(self.match(value)[0],0)

    def test_model_bounds_checksum_and_ambiguous_direction_fail_closed(self):
        for size in range(12):
            self.assertEqual(self.lib.vn_arrow_model_valid(self.model[:size],size),0)
        bad=bytearray(self.model);bad[-1]^=1
        self.assertEqual(self.match(encoded_image('right'),bytes(bad))[0],0)
        # Identical template assigned to two opposing direction groups must
        # be rejected rather than selected arbitrarily by iteration order.
        record=self.model[12:1040];other=bytes([3,2])+record[2:]
        body=record+other
        ambiguous=b'VNA1\x20\x01'+struct.pack('>HI',2,fnv(body))+body
        self.assertEqual(self.match(encoded_image('left'),ambiguous)[0],0)

    def test_mutated_jpegs_under_address_and_undefined_sanitizers(self):
        folder=Path(self.work)
        binary=folder/'jpeg-fuzz'
        subprocess.run(['gcc','-std=c99','-O1','-g','-Wall','-Wextra','-Werror',
                        '-fsanitize=address,undefined','-fno-sanitize-recover=all',
                        '-I',str(ROOT/'native'),str(ROOT/'native/arrow_fuzz.c'),
                        str(ROOT/'native/hud_arrow.c'),str(ROOT/'native/vendor/picojpeg/picojpeg.c'),
                        '-o',str(binary)],check=True)
        (folder/'model.vna').write_bytes(self.model)
        (folder/'seed.jpg').write_bytes(encoded_image('right'))
        result=subprocess.run([str(binary),str(folder/'model.vna'),str(folder/'seed.jpg')],
                              capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('20000 malformed/mutated JPEGs PASS',result.stdout)


class FullPipelineTests(guidance_tests.WireGuidanceTests):
    extra_sources=['hud_arrow.c','vendor/picojpeg/picojpeg.c','vn_vbs.c','../tests/guidance_driver.c']
    extra_flags=('-DVN_TEST_ARROWS',)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lib.vn_arrow_vector_gray.argtypes=[C.c_char_p,C.c_uint,C.c_uint,C.c_void_p]
        cls.lib.test_bind_arrow_model.argtypes=[C.c_char_p,C.c_uint]
        cls.model=synthetic_model(cls.lib,cls.core_work)
        cls.lib.gd_vbs_road.argtypes=[C.c_char_p,C.c_uint]

    def setUp(self):
        self.lib.gd_vbs_reset()
        super().setUp()
        self.lib.test_bind_arrow_model(self.model,len(self.model))

    def arrow(self,kind,distance=150,flag=1,direction=0xfe):
        value=nav.NavInfo(direction=direction,distance_m=distance,next_road='Nguyễn Huệ')
        payload=nav.build_nav_variable2(value)
        if kind:
            jpeg=encoded_image(kind)
            payload=payload[:1]+struct.pack('>I',len(jpeg))+jpeg+payload[6:]
        else: payload=payload[:5]+bytes([flag])+payload[6:]
        self._write_handle(14,encode(0x40,payload))

    def test_full_sequence_sends_correct_arrow_road_distance_camera_and_clear(self):
        self.arrow('right')
        self.assertEqual(self.lib.gd_vbs_disp_icon(),3)
        self.assertEqual(self.lib.gd_vbs_disp_distance(),1500)
        road=C.create_string_buffer(300);self.lib.gd_vbs_road(road,len(road))
        self.assertEqual(road.value.decode(),'Nguyên Huê')
        self._write_handle(14,encode(1,bytes.fromhex('0101903c01006428')))
        self.assertEqual(self.lib.gd_vbs_disp_limit(),40)
        self.arrow(None,120)
        self.assertEqual((self.lib.gd_vbs_disp_icon(),self.lib.gd_vbs_disp_distance()),(3,1200))
        self.arrow('left',90)
        self.assertEqual(self.lib.gd_vbs_disp_icon(),2)
        self._write_handle(14,encode(1,bytes.fromhex('0186a00000000000')))
        self.assertEqual(self.lib.gd_vbs_disp_limit(),0)
        self.arrow(None,0xffffffff)
        self.assertEqual((self.lib.gd_vbs_disp_icon(),self.lib.gd_vbs_disp_distance()),(0,0))
        self.assertEqual(self.lib.gd_vbs_disp_sync(),self.lib.gd_vbs_msg2_sync())
        count=self.lib.test_guide_count();self.arrow(None,0xffffffff)
        self.assertEqual(self.lib.test_guide_count(),count)

    def test_unknown_image_and_explicit_clear_never_keep_an_old_turn(self):
        self.arrow('left');self.arrow('weather')
        self.assertEqual(self.lib.gd_vbs_disp_icon(),0)
        self.arrow('right');self.arrow(None,flag=0)
        self.assertEqual(self.lib.gd_vbs_disp_icon(),0)

    def test_sdk_end_direction_and_stale_navigation_clear_once(self):
        self.arrow('right');self.arrow(None,distance=0,direction=0xff)
        self.assertEqual(self.lib.gd_vbs_disp_icon(),0)
        self.arrow('left');count=self.lib.test_guide_count()
        # Heartbeats do not keep stale navigation alive.
        self._write_handle(14,encode(2,b'\0\x28'))
        self.now+=10001;self.lib.test_tick(self.now,1)
        self.assertEqual(self.lib.test_guide_count(),count+1)
        self.assertEqual(self.lib.gd_vbs_disp_icon(),0)
        self.lib.test_tick(self.now+1,1)
        self.assertEqual(self.lib.test_guide_count(),count+1)
        self.arrow('right')
        self.assertEqual(self.lib.gd_vbs_disp_icon(),3)


if __name__=='__main__': unittest.main()
