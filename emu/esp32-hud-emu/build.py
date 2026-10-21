#!/usr/bin/env python3
"""Build pinned C3 firmware and a reviewable trial ZIP; never flashes hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FQBN = 'esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashMode=dio'
CORE = '3.3.2'
LIBRARY = '2.3.7'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', default='arduino-cli')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT/'out/esp32-c3-kit-build')
    parser.add_argument('--extended', action='store_true', help='Also build optional scan diagnostic')
    args = parser.parse_args()
    out = args.out.resolve()
    kit = out/'vietnav-esp32c3-hud-trial'
    archive = out/'vietnav-esp32c3-hud-trial.zip'
    if kit.exists() or archive.exists():
        parser.error('Kit/archive already exists; choose a new --out directory')
    command = [args.cli]
    if args.config:
        command += ['--config-file', str(args.config.resolve())]

    def run_json(*arguments):
        return json.loads(subprocess.check_output(command+list(arguments)+['--format', 'json']))

    cores = run_json('core', 'list')
    platforms = cores.get('platforms', []) if isinstance(cores, dict) else cores
    if not any(x.get('id') == 'esp32:esp32' and str(x.get('installed_version')) == CORE for x in platforms):
        parser.error(f'Install esp32:esp32@{CORE} before building')
    libraries = run_json('lib', 'list')
    entries = libraries.get('installed_libraries', []) if isinstance(libraries, dict) else libraries
    nimble = next((x['library'] for x in entries if x.get('library', {}).get('name') == 'NimBLE-Arduino'), None)
    if not nimble or nimble.get('version') != LIBRARY:
        parser.error(f'Install NimBLE-Arduino@{LIBRARY} before building')

    out.mkdir(parents=True, exist_ok=True)
    # Build all modes first, so no partial kit can be mistaken for a completed one.
    modes = ['default'] + (['extended'] if args.extended else [])
    report = dict(fqbn=FQBN, arduino_esp32=CORE, nimble_arduino=LIBRARY,
                  arduino_cli=run_json('version'), hardware_tested=False,
                  phone_tested=False, mazda_hud_output=False, images={})
    for mode in modes:
        destination = out/mode
        build = command+['compile', '--fqbn', FQBN, '--build-path', str(out/(mode+'-build')),
                         '--output-dir', str(destination)]
        if mode == 'extended':
            flags = '-DCONFIG_BT_NIMBLE_EXT_ADV=1 -DCONFIG_BT_NIMBLE_MAX_EXT_ADV_INSTANCES=2'
            build += ['--build-property', 'compiler.cpp.extra_flags='+flags,
                      '--build-property', 'compiler.c.extra_flags='+flags]
        build += [str(ROOT/'emu/esp32-hud-emu/vmhud_emu')]
        print(f'Building {mode}; log: {out/(mode+".log")}', flush=True)
        with (out/(mode+'.log')).open('wb') as log:
            subprocess.run(build, stdout=log, stderr=subprocess.STDOUT, check=True)
        merged = destination/'vmhud_emu.ino.merged.bin'
        if merged.stat().st_size != 4*1024*1024:
            raise RuntimeError('Expected a 4 MiB merged image for the C3 4MB board')
        report['images'][mode] = dict(bytes=merged.stat().st_size, sha256=sha256(merged))

    kit.mkdir()
    for mode in modes:
        filename = 'vmhud-c3-merged.bin' if mode == 'default' else 'vmhud-c3-extended-experimental.bin'
        shutil.copyfile(out/mode/'vmhud_emu.ino.merged.bin', kit/filename)
    # Preserve repository-relative layout for decoder imports and the build script.
    source = kit/'source'
    paths = ['LICENSE', 'emu/esp32-hud-emu/README.vi.md', 'emu/esp32-hud-emu/build.py',
             'emu/esp32-hud-emu/capture_serial.py', 'emu/esp32-hud-emu/decode_log.py',
             'emu/esp32-hud-emu/vmhud_emu/vmhud_emu.ino', 'emu/esp32-hud-emu/vmhud_emu/hud_codec.h',
             'bridge/vmlhud_frame.py', 'bridge/vmlhud_nav.py', 'bridge/vmlhud_frame_test.py',
             'bridge/vmlhud_nav_test.py', 'tests/test_esp32_hud.py', 'tests/esp32_hud_driver.cpp',
             'tests/test_vmlhud_bridge.py', 'hud_emulator/__init__.py', 'hud_emulator/protocol.py']
    for relative in paths:
        target = source/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/relative, target)
    report['source_sha256'] = {p: sha256(ROOT/p) for p in paths}
    (kit/'BUILD-REPORT.json').write_text(json.dumps(report, indent=2)+'\n')
    shutil.copyfile(ROOT/'emu/esp32-hud-emu/README.vi.md', kit/'README.vi.md')
    shutil.copyfile(ROOT/'LICENSE', kit/'LICENSE')
    # Bundle the exact NimBLE source used, including its third-party license files.
    library_source = Path(nimble['install_dir'])
    with zipfile.ZipFile(kit/'NimBLE-Arduino-2.3.7-source.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(library_source.rglob('*')):
            if path.is_file() and '.git' not in path.parts:
                bundle.write(path, 'NimBLE-Arduino/'+path.relative_to(library_source).as_posix())
    (kit/'DEPENDENCIES.txt').write_text(
        'Sketch and codecs: AGPL-3.0-or-later; exact source included under source/.\n'
        'Arduino-ESP32 3.3.2: https://github.com/espressif/arduino-esp32/tree/3.3.2\n'
        'Core source: https://github.com/espressif/arduino-esp32/archive/refs/tags/3.3.2.tar.gz\n'
        'Build toolchain/IDF libraries: versions pinned by the 3.3.2 package manifest:\n'
        'https://espressif.github.io/arduino-esp32/package_esp32_index.json\n'
        'NimBLE-Arduino 2.3.7 exact source and license notices included in source ZIP.\n'
        'No Mazda firmware, VietMap app or credentials are included.\n')
    sums = ''.join(f'{sha256(path)}  {path.relative_to(kit).as_posix()}\n'
                   for path in sorted(kit.rglob('*')) if path.is_file())
    (kit/'SHA256SUMS').write_text(sums)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(kit.rglob('*')):
            if path.is_file():
                bundle.write(path, path.relative_to(out))
    print(f'{archive}\nSHA256 {sha256(archive)}')


if __name__ == '__main__':
    main()
