#!/usr/bin/env python3
"""Build a dedicated, empty-stick native HUD USB kit; never merge stable kits."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE_SHA256 = '9026f4bc2336564b8c8da772a3df110de733d0fc4bf7d9f0582b8a3a97b39000'
TPMS_SHA256 = '39ea9a0d9ff6c942b2798bb45c96cb222bb2bc8729c4ed938b065bf475c8cdd4'
TRIGGER_FILES = ('jci-autoupdate', 'LAUNCHER.NAME', 'TOUCHTUNE.ID', 'LICENSE', 'NOTICE')


def digest(path, algorithm='sha256'):
    return hashlib.new(algorithm, path.read_bytes()).hexdigest()


def build(dest, archive, build_dir, tpms, touchtune):
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError('destination must be empty; use a dedicated USB, not another kit')
    if archive.exists() or dest == archive or dest in archive.parents:
        raise ValueError('archive must be a new file outside the USB directory')
    library = build_dir / 'libvietnav-native-arm.so'
    report = json.loads((build_dir / 'ARM-CHECKS.json').read_text())
    if digest(library) != report['sha256'] or report['tpms_source_sha256'] != TPMS_SHA256:
        raise ValueError('ARM artifact differs from its loader-check report')
    raw = library.read_bytes()
    if raw[:6] != b'\x7fELF\x01\x01' or raw[18:20] != b'\x28\x00':
        raise ValueError('library must be ELF32 little-endian ARM')
    if report['glibc'] != ['GLIBC_2.4'] or report['optional_flag_difference'] & ~0x202:
        raise ValueError('unexpected ARM loader requirements')
    wrapper = tpms / 'tpms/install/tpms-bds-wrapper.sh'
    if digest(wrapper) != BASE_SHA256 or digest(tpms / 'tpms/v3/v3.c') != TPMS_SHA256:
        raise ValueError('unsupported TPMS source/wrapper revision')
    # Ship exactly the sources that were compiled, and reject stale core copies.
    for name in ('v3.c', 'hud_native.c', 'hud_native.h', 'tpms_adapter.inc'):
        if digest(build_dir / name) != report['compiled_sources'][name]:
            raise ValueError('compiled source differs from ARM report: ' + name)
    for name in ('hud_native.c', 'hud_native.h', 'tpms_adapter.inc'):
        if (build_dir / name).read_bytes() != (HERE.parent / name).read_bytes():
            raise ValueError('rebuild ARM: source changed: ' + name)
    up = list((touchtune / 'usb').glob('*.up'))
    if len(up) != 1 or any(not (touchtune / 'usb' / f).is_file() for f in TRIGGER_FILES):
        raise ValueError('complete TouchTune source/USB bootstrap required')
    # Stage everything before touching the destination.
    with tempfile.TemporaryDirectory(prefix='vietnav-kit-') as temporary:
        stage = Path(temporary) / 'usb'
        payload = stage / 'native-hud-payload'
        payload.mkdir(parents=True)
        base_md5 = digest(wrapper, 'md5')
        for name, target in (('native-control.sh', stage), ('install-patches.sh', stage),
                             ('bds-dispatch.sh', payload), ('monitor.sh', payload)):
            body = (HERE / name).read_text().replace('__BASE_MD5__', base_md5)
            if '\r' in body or '__BASE_MD5__' in body:
                raise ValueError('invalid shell source ' + name)
            (target / name).write_text(body, encoding='utf-8', newline='\n')
            (target / name).chmod(0o755)
            subprocess.run(['sh', '-n', str(target / name)], check=True)
        shutil.copyfile(library, payload / 'libvietnav-native.so')
        names = ('bds-dispatch.sh', 'monitor.sh', 'libvietnav-native.so')
        (payload / 'MANIFEST.md5').write_text(''.join(
            f'{digest(payload / name, "md5")}  {name}\n' for name in names))
        shutil.copyfile(build_dir / 'ARM-CHECKS.json', payload / 'ARM-CHECKS.json')
        shutil.copyfile(HERE / 'STEPS.vi.txt', stage / 'DOC-TRUOC.txt')
        shutil.copyfile(ROOT / 'LICENSE', stage / 'LICENSE.native')
        shutil.copyfile(tpms / 'LICENSE', stage / 'LICENSE.tpms')
        # Never pass the shell-code filename through a shell.
        for path in [*(touchtune / 'usb' / f for f in TRIGGER_FILES), up[0]]:
            shutil.copyfile(path, stage / path.name)
        with tarfile.open(stage / 'CORRESPONDING-SOURCE.tar.gz', 'w:gz') as sources:
            for directory in ('native', 'hud_emulator', 'tests'):
                for path in sorted((ROOT / directory).rglob('*')):
                    if path.is_file() and '__pycache__' not in path.parts:
                        sources.add(path, 'vietnav/' + str(path.relative_to(ROOT)))
            sources.add(ROOT / 'LICENSE', 'vietnav/LICENSE')
            for name in ('v3.c', 'hud_native.c', 'hud_native.h', 'tpms_adapter.inc', 'PROVENANCE.txt'):
                sources.add(build_dir / name, 'compiled/' + name)
            sources.add(tpms / 'LICENSE', 'compiled/LICENSE.tpms')
            sources.add(wrapper, 'tpms/tpms-bds-wrapper.sh')
            for path in sorted(touchtune.rglob('*')):
                if path.is_file() and '.git' not in path.parts and '__pycache__' not in path.parts:
                    sources.add(path, 'TouchTune/' + str(path.relative_to(touchtune)))
        (stage / 'NATIVE-PROVENANCE.txt').write_text(
            'VIETNAV native HUD trial 0.1.0; HUD-only; no car/radio validation.\n'
            'This kit adds an independent one-start dispatcher + USB controller.\n'
            f'ARM SHA256: {digest(library)}\nTPMS wrapper SHA256: {BASE_SHA256}\n'
            f'TPMS v3.c SHA256: {TPMS_SHA256}\n'
            'Native: AGPL-3.0-or-later; TPMS: MIT; TouchTune: GPL-3.0.\n'
            'https://github.com/dangkhoa116/mzd-vietnav-hud\n'
            'https://github.com/dangkhoa116/mzd-connect-tpms\n'
            'https://github.com/Miatafy/TouchTune\n'
            'Sources, build scripts and compiled translation units included.\n'
            'No BLE firmware/service pack is redistributed. Existing TPMS pack required.\n')
        (stage / 'SHA256SUMS').write_text(''.join(
            f'{digest(path)}  {path.relative_to(stage)}\n'
            for path in sorted(stage.rglob('*')) if path.is_file()))
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(stage, dest, dirs_exist_ok=True)
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as output:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    output.write(path, str(path.relative_to(stage)))
    return digest(archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', type=Path, default=ROOT / 'out/native-hud-usb')
    parser.add_argument('--zip', type=Path, default=ROOT / 'out/vietnav-native-hud-usb.zip')
    parser.add_argument('--build', type=Path, default=ROOT / 'out/native-build')
    parser.add_argument('--tpms', type=Path, default=ROOT.parent / 'mzd-connect-tpms')
    parser.add_argument('--touchtune', type=Path, required=True, help='complete TouchTune source checkout')
    args = parser.parse_args()
    try:
        checksum = build(*(p.resolve() for p in (args.dest, args.zip, args.build, args.tpms, args.touchtune)))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'USB build: {exc}\n')
    print(f'USB kit: {args.dest}\nZIP: {args.zip}\nSHA256: {checksum}')


if __name__ == '__main__':
    main()
