#!/usr/bin/env python3
"""Kiểm cầu CarPlay->HUD dựa trên rootfs CMU thật, không cần chạy emu.

Bộ `mzd-connect-emu` cần Linux x86_64 + `qemu-user`, nên trên máy Windows không
WSL/Docker thì không chạy được. Nhưng rootfs mà emu đó tiêu thụ thì vẫn đọc
được, và nó trả lời được phần lớn câu hỏi "shim có chạy nổi trên xe không" bằng
cách đọc tĩnh — kể cả vài kiểu hỏng mà chạy emu cũng khó thấy.

Bốn thứ kiểm được, và vì sao từng thứ đáng kiểm:

1. **Symbol OEM mà shim gọi bằng `dlsym`.** `oem/oem_thunk.h` thiết kế để
   symbol không resolve được thì thunk **degrade êm** về giá trị thất bại chứ
   không crash. Tốt cho ổn định, nhưng nghĩa là gõ sai một tên hàm sẽ cho ra
   đúng triệu chứng "HUD trống" mà không một dòng log nào. Đây là cách duy
   nhất bắt được chuyện đó mà không cần xe.
2. **Mọi symbol undefined của shim có trên glibc của xe không.** Trả lời câu
   "nạp lên xe có link nổi không" — mạnh hơn hẳn việc chỉ xem hình dạng ELF.
3. **Chuỗi interpose có thật không.** `msgrcv` và `eDevMgr*` phải được một thư
   viện nào đó trong tiến trình `jciCARPLAY` gọi qua PLT, nếu không `LD_PRELOAD`
   chen vào chỗ không ai đi qua.
4. **Service `jciCARPLAY` trong `sm.conf`** — đúng chỗ installer vá LD_PRELOAD.

Cách dùng:
    python check_rootfs.py --rootfs <thư mục rootfs đã giải>
                           [--shim out/carplay-arm/release/libpatch-blmjcicarplay.so]
"""
import argparse
import os
import sys

from elftools.elf.dynamic import DynamicSection
from elftools.elf.elffile import ELFFile

# Console Windows mặc định cp1252, không in nổi tiếng Việt. Đặt thẳng ở đây chứ
# không dựa vào PYTHONIOENCODING: chạy với `python -I` là biến môi trường bị bỏ.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Tên hàm OEM lấy từ các macro OEM_THUNK trong mazda/patches/blmjcicarplay/oem/.
OEM_SYMBOLS = {
    'jci/lib/libjcidbus.so': [
        'JCIDBUS_conn_create', 'JCIDBUS_conn_connect', 'JCIDBUS_worker_start',
    ],
    'jci/lib/libjcivbsnaviclient.so': [
        'VBS_NAVI_SetHUDDisplayMsgReq', 'VBS_NAVI_TMC_SetHUD_Display_Msg2',
        'VBS_NAVI_GetHUDStatus',
    ],
}

# Nơi tìm thư viện trong rootfs khi giải DT_NEEDED.
LIB_DIRS = ('lib', 'usr/lib', 'jci/lib')

# Luôn tính vào, kể cả khi không nằm trong DT_NEEDED: loader và libgcc.
EXTRA_PROVIDERS = ['lib/ld-2.11.1.so', 'lib/libgcc_s.so.1']

# Symbol shim interpose, tức phải có ai đó trong tiến trình gọi tới.
INTERPOSED = ['msgrcv', 'eDevMgrRegisterProcess', 'eDevMgriPodStartCallStateUpdates',
              'eDevMgriPodStartCommunicationUpdates', 'eDevMgriPodSendLocationInformation']

SCAN_DIRS = ('jci/lib', 'jci/carplay', 'usr/lib', 'lib', 'jci/bin', 'usr/bin', 'bin')


def dynsyms(path):
    """Trả (exported, undefined) của .dynsym; ({}, {}) nếu không phải ELF."""
    exported, undefined = set(), set()
    try:
        with open(path, 'rb') as fh:
            if fh.read(4) != b'\x7fELF':
                return exported, undefined
            fh.seek(0)
            section = ELFFile(fh).get_section_by_name('.dynsym')
            if section is None:
                return exported, undefined
            for sym in section.iter_symbols():
                if not sym.name:
                    continue
                name = sym.name.split('@')[0]
                if sym['st_shndx'] == 'SHN_UNDEF':
                    # Undefined WEAK là hợp lệ: loader để NULL và code tự kiểm
                    # trước khi gọi (__gmon_start__, _Jv_RegisterClasses,
                    # _ITM_*TMCloneTable mà gcc luôn phát ra). File .so gốc
                    # đang chạy trên xe cũng có đúng bốn cái đó.
                    # native/build_arm.py lọc weak theo cùng lý do.
                    if sym['st_info']['bind'] != 'STB_WEAK':
                        undefined.add(name)
                elif sym['st_info']['bind'] in ('STB_GLOBAL', 'STB_WEAK'):
                    exported.add(name)
    except (OSError, Exception):
        pass
    return exported, undefined


def check_oem(rootfs, report):
    print('== 1. Symbol OEM mà shim gọi bằng dlsym ==')
    print('   (thunk degrade êm khi thiếu => gõ sai tên = HUD trống, không log)')
    ok = True
    for relative, names in OEM_SYMBOLS.items():
        path = os.path.join(rootfs, relative)
        if not os.path.isfile(path):
            print('   ** thiếu thư viện %s **' % relative)
            ok = False
            continue
        exported, _ = dynsyms(path)
        for name in names:
            present = name in exported
            ok &= present
            print('   %-34s %-16s %s' % (name, 'CÓ' if present else '** KHÔNG CÓ **', relative))
    report['oem_symbols_ok'] = ok
    return ok


def find_lib(rootfs, soname):
    """Tìm soname trong rootfs. Bản giải nén bằng Windows mất hết symlink, nên
    phải dò thêm tên có số phiên bản (libc.so.6 -> libc-2.11.1.so)."""
    for directory in LIB_DIRS:
        path = os.path.join(rootfs, directory, soname)
        if os.path.isfile(path):
            return path
    stem = soname.split('.so')[0]
    for directory in LIB_DIRS:
        full = os.path.join(rootfs, directory)
        if not os.path.isdir(full):
            continue
        for name in sorted(os.listdir(full)):
            if name.startswith(stem + '-') and '.so' in name:
                return os.path.join(full, name)
    return None


def check_link(rootfs, shim, report):
    print()
    print('== 2. Shim có link nổi trên glibc của xe không ==')
    with open(shim, 'rb') as fh:
        sonames = []
        for sec in ELFFile(fh).iter_sections():
            if isinstance(sec, DynamicSection):
                sonames = [t.needed for t in sec.iter_tags('DT_NEEDED')]
    provided = set()
    for soname in sonames:
        path = find_lib(rootfs, soname)
        if path is None:
            print('   ** rootfs không có %s (DT_NEEDED) **' % soname)
            continue
        exported, _ = dynsyms(path)
        print('   %-22s -> %s (%d symbol)'
              % (soname, os.path.relpath(path, rootfs).replace(os.sep, '/'), len(exported)))
        provided |= exported
    for relative in EXTRA_PROVIDERS:
        exported, _ = dynsyms(os.path.join(rootfs, relative))
        provided |= exported
    _, needed = dynsyms(shim)
    if not needed:
        print('   ** không đọc được shim: %s **' % shim)
        report['link_ok'] = False
        return False
    missing = sorted(n for n in needed if n not in provided)
    print('   shim cần %d symbol, thiếu %d' % (len(needed), len(missing)))
    if missing:
        print('   THIẾU:', ', '.join(missing))
    else:
        print('   => mọi symbol đều có trên rootfs thật')
    report['link_ok'] = not missing
    report['missing'] = missing
    return not missing


def check_interpose(rootfs, report):
    print()
    print('== 3. Chuỗi interpose có thật trong firmware không ==')
    callers = {name: [] for name in INTERPOSED}
    scanned = 0
    for base in SCAN_DIRS:
        directory = os.path.join(rootfs, base)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            _, undefined = dynsyms(path)
            if not undefined:
                continue
            scanned += 1
            for symbol in INTERPOSED:
                if symbol in undefined:
                    callers[symbol].append(base + '/' + name)
    print('   quét %d ELF' % scanned)
    ok = True
    for symbol in INTERPOSED:
        hits = callers[symbol]
        ok &= bool(hits)
        shown = ', '.join(hits[:3]) + (' ...' if len(hits) > 3 else '')
        print('   %-38s %s' % (symbol, shown if hits else '** không ai gọi **'))
    report['interpose_callers'] = callers
    report['interpose_ok'] = ok
    return ok


def check_service(rootfs, report):
    print()
    print('== 4. Service jciCARPLAY trong sm.conf ==')
    found = []
    base = os.path.join(rootfs, 'jci/sm')
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if not name.endswith('.conf'):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, 'rb') as fh:
                    data = fh.read()
            except OSError:
                continue
            if b'jciCARPLAY' in data:
                found.append(name)
                print('   %-24s có jciCARPLAY' % name)
    if not found:
        print('   ** không thấy jciCARPLAY trong jci/sm/*.conf **')
    report['sm_conf'] = found
    return bool(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rootfs', required=True, help='rootfs CMU đã giải nén')
    parser.add_argument('--shim', default=None,
                        help='libpatch-blmjcicarplay.so cần kiểm (mặc định: bản release đã build)')
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    shim = args.shim or os.path.join(here, '..', '..', 'out', 'carplay-arm',
                                     'release', 'libpatch-blmjcicarplay.so')
    rootfs = os.path.abspath(args.rootfs)
    shim = os.path.abspath(shim)
    if not os.path.isdir(rootfs):
        parser.exit(1, 'không thấy rootfs: %s\n' % rootfs)

    print('rootfs: %s' % rootfs)
    print('shim  : %s' % shim)
    print()
    report = {}
    results = [
        check_oem(rootfs, report),
        check_link(rootfs, shim, report) if os.path.isfile(shim) else None,
        check_interpose(rootfs, report),
        check_service(rootfs, report),
    ]
    if results[1] is None:
        print()
        print('(bỏ qua mục 2: chưa build shim -- chạy build_arm_zig.py trước)')
        results[1] = True

    print()
    print('KẾT QUẢ:', 'PASS' if all(results) else 'CÓ VẤN ĐỀ')
    print()
    print('Lưu ý: đây là kiểm TĨNH. Nó chứng minh shim nạp được và chen đúng chỗ,')
    print('KHÔNG chứng minh nó giải mã đúng khung iAP2 của VietMap -- việc đó vẫn')
    print('phải có log trên xe.')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
