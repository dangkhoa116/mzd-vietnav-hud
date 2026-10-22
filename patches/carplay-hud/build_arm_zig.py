#!/usr/bin/env python3
"""Cross-build the CarPlay -> HUD shim for the CMU150 without the m3 toolchain.

Upstream `mazda/Makefile` builds `libpatch-blmjcicarplay.so` with the m3
toolchain submodule (`arm-cortexa9_neon-linux-gnueabi-g++`). Those are Linux
x86_64 ELF binaries, so on a Windows host with no WSL and no container runtime
they cannot run at all -- which is what blocked producing the *debug* build
needed to read `nav PICK` / `nav TEXT-FALLBACK` lines off the car.

This script cross-builds the same sources with zig (`pip install ziglang`),
which is a native Windows binary that targets arm-linux-gnueabi directly, then
verifies the result against the properties the CMU actually requires.

One deliberate difference from upstream: there is no device sysroot here, so
libc++ is linked statically instead of borrowing the device's
libstdc++.so.6.0.14. That is safe only because no C++ type crosses the module
boundary -- every OEM call is a dlsym-resolved plain-C thunk (oem/oem_thunk.h)
and every interposed symbol is `extern "C"`. See `exports.map` for why the
static link then *must* be hidden behind a version script.

Usage:
    python build_arm_zig.py --carplay ../../../mazda-carplay-hud [--mode both]
                            [--baseline <on-car libpatch-blmjcicarplay.so>]
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from elftools.elf.dynamic import DynamicSection
from elftools.elf.elffile import ELFFile
from elftools.elf.enums import ENUM_RELOC_TYPE_ARM
from elftools.elf.gnuversions import GNUVerNeedSection
from elftools.elf.relocation import RelocationSection
from elftools.elf.sections import ARMAttributesSection

HERE = Path(__file__).resolve().parent

TARGET = 'arm-linux-gnueabi.2.4.0'
MCPU = 'cortex_a9+neon'

# The CMU ships glibc 2.11 -- native/build_arm.py pins the same bound against
# the m3 sysroot's lib/libc-2.11.so.
CMU_GLIBC = (2, 11)

# Exactly the symbols devmgr_shim.cpp marks PRELOAD_EXPORT, i.e. the ones that
# must interpose jciCARPLAY. Anything else exported from an LD_PRELOAD object
# would interpose process-wide by accident.
WANT_EXPORTS = {
    'msgrcv',
    'eDevMgrRegisterProcess',
    'eDevMgriPodStartCallStateUpdates',
    'eDevMgriPodStartCommunicationUpdates',
    'eDevMgriPodSendLocationInformation',
}
# Linker-generated section markers upstream also exports; harmless either way.
ALLOWED_EXTRA_EXPORTS = {
    '_init', '_fini', '_edata', '_end', '__end__', '__bss_start',
    '__bss_start__', '__bss_end__', '_bss_end__',
}

ALLOWED_NEEDED = {
    'libc.so.6', 'libpthread.so.0', 'libdl.so.2', 'libm.so.6',
    # soft-float ARM loader; a hard-float build would name ld-linux-armhf.so.3
    'ld-linux.so.3',
}

# These live in glibc, not libstdc++, despite the C++-looking names.
LIBC_PROVIDED_CXX = {'__cxa_atexit', '__cxa_finalize', '__cxa_thread_atexit_impl'}

# Relocation types the on-car baseline never used but that are still safe here.
#
# Static libc++abi keeps the in-flight exception state (__cxa_eh_globals, 12
# bytes in .tbss) in a thread-local, which the upstream build did not need
# because it borrowed the device libstdc++ and its TLS block. Exceptions cannot
# be dropped to avoid this: nav.cpp, devmgr_shim.cpp and hud_send.cpp each wrap
# an OEM callback thread in `catch (...)`, and hud_send.cpp:736 notes that an
# escaping exception means std::terminate -> SIGABRT -> head-unit reboot.
#
# The single relocation is module-local local-dynamic TLS. The shim is loaded
# via LD_PRELOAD, so it is part of the initial load set and ld.so assigns its
# TLS module id at startup -- not the dlopen case that needs static TLS
# surplus. ARM glibc has handled this since long before the CMU's 2.11.
ALLOWED_NEW_RELOCS = {'R_ARM_TLS_DTPMOD32', 'R_ARM_TLS_DTPOFF32'}

# .ARM.attributes tags that change how the shim passes arguments to OEM code.
# A mismatch here does not fail to load -- it silently miscalls the OEM process,
# which is far worse. TAG_ABI_VFP_ARGS must stay absent: present-and-1 means
# floats travel in VFP registers, against a soft-float host.
ABI_CRITICAL_TAGS = ('TAG_ABI_VFP_ARGS', 'TAG_ABI_PCS_WCHAR_T', 'TAG_ABI_ENUM_SIZE',
                     'TAG_ABI_ALIGN_NEEDED', 'TAG_CPU_ARCH', 'TAG_CPU_ARCH_PROFILE')

FEATURE_FLAGS = ['-DCARPLAY_NO_SPLIM', '-DCARPLAY_VN_NORMALIZE=1']

COMMON = [
    '-std=c++11', '-fPIC', '-fvisibility=hidden',
    '-D_GLIBCXX_USE_CXX11_ABI=0',   # parity with upstream; inert against libc++
    '-w',                           # zig builds libc++ from source: silence its warnings
    # zig enables its UBSan runtime by default at -O0. That runtime pulls in
    # zig's std.Io (utimensat, fstatat, ...), which does not exist at glibc 2.4
    # and so breaks the debug link outright. A sanitizer runtime also has no
    # business inside an OEM process that reboots the head unit on SIGABRT.
    '-fno-sanitize=undefined',
]

MODES = {
    'release': (['-O3', '-DNDEBUG', '-ffunction-sections', '-fdata-sections'],
                ['-Wl,--gc-sections', '-Wl,-s']),
    'debug':   (['-O0', '-g3', '-DDEBUG'], []),
}


def zig(*args, cwd=None):
    subprocess.run([sys.executable, '-m', 'ziglang', 'c++', *args], cwd=cwd, check=True)


def reloc_name(reloc):
    want = reloc['r_info_type']
    for name, value in ENUM_RELOC_TYPE_ARM.items():
        if value == want:
            return name
    return 'R_ARM_%d' % want


def inspect_elf(path):
    """Read back every property the CMU loader actually cares about."""
    with open(path, 'rb') as handle:
        elf = ELFFile(handle)
        header = elf.header
        if elf.elfclass != 32 or not elf.little_endian or header['e_machine'] != 'EM_ARM':
            raise ValueError('expected 32-bit little-endian ARM ELF')
        flags = header['e_flags']
        if flags & 0xff000000 != 0x05000000:
            raise ValueError('expected EABI version 5, flags=0x%08x' % flags)
        if flags & 0x400:
            raise ValueError('hard-float ABI (EF_ARM_ABI_FLOAT_HARD) is incompatible with the CMU')

        needed, soname = [], []
        glibc, exports, undefined, relocs = set(), set(), set(), set()
        attributes = {}
        for sec in elf.iter_sections():
            if isinstance(sec, ARMAttributesSection):
                for subsec in sec.iter_subsections():
                    for sss in subsec.iter_subsubsections():
                        for attr in sss.iter_attributes():
                            attributes[attr.tag] = attr.value
            if isinstance(sec, DynamicSection):
                needed = [tag.needed for tag in sec.iter_tags('DT_NEEDED')]
                soname = [tag.soname for tag in sec.iter_tags('DT_SONAME')]
            elif isinstance(sec, GNUVerNeedSection):
                for _verneed, auxs in sec.iter_versions():
                    glibc.update(a.name for a in auxs if a.name.startswith('GLIBC_'))
            elif isinstance(sec, RelocationSection):
                relocs.update(reloc_name(r) for r in sec.iter_relocations())
        if attributes.get('TAG_ABI_VFP_ARGS'):
            raise ValueError('TAG_ABI_VFP_ARGS set: hard-float argument ABI')

        dynsym = elf.get_section_by_name('.dynsym')
        if dynsym:
            for sym in dynsym.iter_symbols():
                if not sym.name:
                    continue
                if sym['st_shndx'] == 'SHN_UNDEF':
                    undefined.add(sym.name.split('@')[0])
                elif sym['st_info']['bind'] in ('STB_GLOBAL', 'STB_WEAK'):
                    exports.add(sym.name.split('@')[0])

    for version in glibc:
        if tuple(int(n) for n in version[6:].split('.')) > CMU_GLIBC:
            raise ValueError('%s exceeds the CMU glibc %d.%d' % (version, *CMU_GLIBC))

    return dict(flags=flags, needed=needed, soname=soname, glibc=sorted(glibc),
                exports=sorted(exports), undefined=sorted(undefined),
                relocations=sorted(relocs),
                abi={tag: attributes.get(tag) for tag in ABI_CRITICAL_TAGS})


def check(report, baseline=None):
    """Fail on anything that would misbehave on the car, not merely differ."""
    problems = []

    extra = set(report['exports']) - WANT_EXPORTS - ALLOWED_EXTRA_EXPORTS
    if extra:
        problems.append('exports symbols an LD_PRELOAD object must not export: '
                        + ', '.join(sorted(extra)))
    missing = WANT_EXPORTS - set(report['exports'])
    if missing:
        problems.append('missing interposed symbols: ' + ', '.join(sorted(missing)))

    unexpected = set(report['needed']) - ALLOWED_NEEDED
    if unexpected:
        problems.append('unexpected DT_NEEDED: ' + ', '.join(sorted(unexpected)))

    # Undefined C++ runtime symbols would have to be satisfied by the device
    # libstdc++ / libgcc_s, which this build deliberately does not link.
    runtime = [s for s in report['undefined']
               if s.startswith(('_Z', '__cxa', '_Unwind', '__gxx', '__aeabi_unwind'))
               and s not in LIBC_PROVIDED_CXX]
    if runtime and 'libstdc++.so.6' not in report['needed']:
        problems.append('undefined C++ runtime symbols with no libstdc++ dependency: '
                        + ', '.join(sorted(runtime)))

    if baseline:
        for tag in ABI_CRITICAL_TAGS:
            if report['abi'][tag] != baseline['abi'][tag]:
                problems.append('%s differs from the on-car baseline: %r vs %r'
                                % (tag, report['abi'][tag], baseline['abi'][tag]))
        new_relocs = (set(report['relocations']) - set(baseline['relocations'])
                      - ALLOWED_NEW_RELOCS)
        if new_relocs:
            problems.append('relocation types the on-car baseline never used, so the CMU '
                            'loader is unproven for them: ' + ', '.join(sorted(new_relocs)))
        # native/build_arm.py established the same tolerance: the two linkers set
        # EF_ARM_HASENTRY (0x02) and EF_ARM_ABI_FLOAT_SOFT (0x200) differently,
        # and both mean base AAPCS.
        difference = report['flags'] ^ baseline['flags']
        if difference & ~0x202:
            problems.append('unexpected ELF flag difference from the baseline: 0x%x' % difference)
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--carplay', type=Path, required=True,
                        help='checkout of mazda-carplay-hud with the patch applied')
    parser.add_argument('--out', type=Path, default=HERE.parents[1] / 'out/carplay-arm')
    parser.add_argument('--mode', choices=('release', 'debug', 'both'), default='both')
    parser.add_argument('--baseline', type=Path,
                        help='on-car libpatch-blmjcicarplay.so to compare relocations/flags against')
    args = parser.parse_args()

    mazda = args.carplay.resolve() / 'mazda'
    patch_dir = mazda / 'patches/blmjcicarplay'
    if not patch_dir.is_dir():
        parser.exit(1, 'not a mazda-carplay-hud checkout: %s\n' % args.carplay)
    if not (patch_dir / 'maneuver_text.h').exists():
        parser.exit(1, 'maneuver_text.h missing -- apply '
                       '0001-nav-recover-turn-from-instruction-text.patch first\n')

    sources = sorted(p.relative_to(mazda).as_posix() for p in patch_dir.rglob('*.cpp'))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    baseline = inspect_elf(args.baseline.resolve()) if args.baseline else None
    modes = ('release', 'debug') if args.mode == 'both' else (args.mode,)
    version = subprocess.run([sys.executable, '-m', 'ziglang', 'version'],
                             capture_output=True, text=True).stdout.strip()
    report = dict(target=TARGET, mcpu=MCPU, compiler='zig ' + version, sources=sources,
                  baseline=str(args.baseline) if args.baseline else None, builds={})

    try:
        for mode in modes:
            cxxflags, ldflags = MODES[mode]
            build = out / mode
            build.mkdir(parents=True, exist_ok=True)
            objects = []
            for source in sources:
                obj = build / (source.replace('/', '_')[:-4] + '.o')
                zig('-target', TARGET, '-mcpu=' + MCPU, *COMMON, *FEATURE_FLAGS,
                    '-Idbus', *cxxflags, '-c', source, '-o', str(obj), cwd=mazda)
                objects.append(str(obj))
            library = build / 'libpatch-blmjcicarplay.so'
            zig('-target', TARGET, '-mcpu=' + MCPU, '-shared',
                '-Wl,--no-undefined',
                '-Wl,--version-script=' + str(HERE / 'exports.map'),
                '-Wl,-soname,libpatch-blmjcicarplay.so',
                *ldflags, *objects, '-lpthread', '-ldl', '-o', str(library), cwd=mazda)

            info = inspect_elf(library)
            problems = check(info, baseline)
            info.update(path=str(library), bytes=library.stat().st_size,
                        sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                        problems=problems)
            report['builds'][mode] = info
            if problems:
                raise ValueError('%s build: %s' % (mode, '; '.join(problems)))
            print('%-7s OK  %8d B  glibc=%s  %s'
                  % (mode, info['bytes'], ','.join(info['glibc']) or 'none', library))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        (out / 'ARM-CHECKS.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        parser.exit(1, 'ARM build/check: %s\n' % exc)

    report['status'] = ('cross-built with zig and ELF-verified against the CMU requirements; '
                        'NOT yet run on the car')
    (out / 'ARM-CHECKS.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('report -> %s' % (out / 'ARM-CHECKS.json'))


if __name__ == '__main__':
    main()
