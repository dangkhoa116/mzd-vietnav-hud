"""Offline replay CLI and capture session handling, without radio/OEM services."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'native'))
sys.path.insert(0,str(ROOT/'tests'))
import hud_emu
from hud_emulator.protocol import encode,StreamDecoder
from build_arrow_model import native_library
from test_hud_arrow_native import synthetic_model,encoded_image


class ReplayTests(unittest.TestCase):
    def test_log_routes_family_resets_sessions_and_reports_incomplete_input(self):
        frame=encode(14,b'\0')
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'capture.txt'
            log.write_text('[BLE] connected\n'+
                           f'[W:FFF2] 10 byte: {frame[:10].hex()}\n'+
                           '[BLE] disconnected\n[BLE] connected\n'+
                           f'[W:9ABC] {len(frame)} byte: {frame.hex()}\n'+
                           f'[W:FFF2] {len(frame)} byte: {frame.hex()}\n')
            raw,stats=hud_emu.from_log(log,'H1')
            self.assertEqual(stats['frames'],1)
            self.assertEqual(stats['incomplete_sessions'],1)
            self.assertEqual(StreamDecoder().feed(raw)[-1].command,14)

    def test_cli_uses_actual_native_pipeline_and_emits_explicit_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);lib=native_library(folder)
            model=folder/'arrows.vna';model.write_bytes(synthetic_model(lib,folder))
            frames=folder/'input.bin'
            frames.write_bytes(hud_emu.navigation(150,jpeg=encoded_image('right'))+
                               encode(1,bytes.fromhex('0100643c'))+hud_emu.navigation(0xffffffff,''))
            out=folder/'out'
            subprocess.run([sys.executable,str(ROOT/'native/hud_emu.py'),'--model',str(model),
                            '--frames',str(frames),'--out',str(out)],check=True,
                           capture_output=True,text=True,timeout=30)
            report=json.loads((out/'REPORT.json').read_text())
            self.assertFalse(report['radio_tested']);self.assertFalse(report['original_oem_bus_tested'])
            rows=[json.loads(x) for x in (out/'hud-events.jsonl').read_text().splitlines()]
            self.assertEqual((rows[0]['icon'],rows[0]['distance']),(3,150))
            self.assertEqual(rows[1]['speed_limit'],60)
            self.assertTrue(rows[2]['clear'])
            self.assertTrue(all(x['wire']['sync']==x['wire']['streetSync'] for x in rows))

    def test_replay_continues_past_the_physical_trial_time_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);lib=native_library(folder)
            model=folder/'arrows.vna';model.write_bytes(synthetic_model(lib,folder))
            frames=folder/'long.bin'
            frames.write_bytes(b''.join(hud_emu.navigation(100+i) for i in range(1801)))
            out=folder/'out'
            subprocess.run([sys.executable,str(ROOT/'native/hud_emu.py'),'--model',str(model),
                            '--frames',str(frames),'--out',str(out)],check=True,
                           capture_output=True,text=True,timeout=30)
            rows=[json.loads(x) for x in (out/'hud-events.jsonl').read_text().splitlines()]
            last=[row for row in rows if not row['clear']][-1]
            self.assertEqual((last['wire']['distanceValue'],last['unit']),(19,3))


if __name__=='__main__': unittest.main()
