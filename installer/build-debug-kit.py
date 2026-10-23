#!/usr/bin/env python3
"""Dựng bộ cài DEBUG từ một bộ cài đã phát hành, chỉ đổi cầu CarPlay.

    python installer/build-debug-kit.py --kit VIETNAV-HUD-0.9.1-USB.zip \\
        --shim out/carplay-arm-m3/debug/libpatch-blmjcicarplay.so \\
        --out VIETNAV-HUD-0.9.1-DEBUG-USB.zip

Vì sao cần: `vietnav-collect.sh` đã có sẵn trong mọi bộ cài (nút THU THẬP trên
màn hình), nhưng **bản phát hành chỉ ghi log khi có LỖI** (`log.h`: release ⇒
ERROR, `LOGD`/`LOGV` bị bỏ lúc biên dịch). Nên thu thập trên bản thường sẽ ra
một `carplay_bridge.log` gần như rỗng. Thứ còn thiếu không phải công cụ thu
thập, mà là một `.so` chịu ghi.

Script này giữ nguyên mọi thứ khác của bộ cài đã chạy được trên xe — kể cả
trigger TouchTune — và chỉ thay `vietnav-payload/libpatch-blmjcicarplay.so`.

Hai chỗ bắt buộc phải đúng, nếu không xe từ chối cài:

1. `vietnav-install.sh` đối chiếu md5 **từng** file payload với bảng trong
   `PAYLOAD-SOURCES.md`, nên đổi .so thì phải sửa md5 trong bảng.
2. Nó đọc bảng bằng `awk -F'|'`, lấy cột 2 là tên và cột 3 là md5, nên định
   dạng dòng `| tên | `md5` | nguồn |` phải giữ nguyên.

Chạy trên Linux/WSL: tên file trigger TouchTune dài hơn giới hạn MAX_PATH của
Windows nên Windows không giải nén nổi bộ cài.
"""
import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import zipfile

TARGET = 'libpatch-blmjcicarplay.so'

MARKER_NAME = '0-BAN-DEBUG.txt'
MARKER = """BAN DEBUG - CHI DE LAY LOG, KHONG DUNG HANG NGAY
=================================================

Bo nay giong het ban {version}, chi khac DUNG MOT FILE: cau CarPlay
(libpatch-blmjcicarplay.so) la ban DEBUG, co ghi log chi tiet.

Ban thuong chi ghi log khi co LOI, nen khong biet duoc vi sao VietMap khong
hien tren HUD. Ban debug ghi ra /tmp/carplay_bridge.log tung khung dan duong
nhan duoc tu iPhone.

CACH LAM
--------
1. Cam USB, cai nhu binh thuong (chon muc CarPlay).
2. Khoi dong lai xe.

3. THU GOOGLE MAPS TRUOC (buoc quan trong nhat).
   Cam iPhone, mo Google Maps, dan duong 1-2 phut.
   - Neu kinh lai CO hien mui ten: tot, di tiep buoc 4.
   - Neu kinh lai KHONG hien gi: dung lai, bam GO / ROLLBACK ngay,
     roi bao lai. Khong can lam tiep buoc 4.

4. Mo VIETMAP LIVE, DAN DUONG MOT DOAN THAT (co re it nhat 2-3 lan).
   Khoang 5-10 phut la du. Dung yen mot cho thi khong co du lieu.
   VietMap CO THE VAN CHUA HIEN tren kinh lai - khong sao, dung la vay,
   thu can lay la file log o buoc 5.

5. VAN DE NGUYEN MAY, KHONG TAT XE. Cam USB vao, bam nut "THU THAP".
   No luu file vietnav-collect-<ngay>.tgz ngay tren USB.
   Tat xe truoc khi thu thap la MAT SACH log, phai lam lai tu dau.

6. Mang USB ve, gui file .tgz do.

SAU KHI LAY LOG XONG
--------------------
Nen bam GO / ROLLBACK roi cai lai ban thuong. Ban debug ghi log vao /tmp
(nam tren RAM); khong hong gi, chi la khong can de mai.

LUU Y
-----
File .so nay build bang dung trinh bien dich cua hang (m3-toolchain) va da nap
thu thanh cong duoi dung loader glibc 2.11 cua xe. Nhung no CHUA tung chay that
trong jciCARPLAY - day chinh la thu dang di kiem chung. Neu cai xong ma CarPlay
khong len, bam GO / ROLLBACK la ve nhu cu.
"""


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_kit(kit, work):
    if os.path.isdir(kit):
        shutil.copytree(kit, work, dirs_exist_ok=True)
    else:
        with zipfile.ZipFile(kit) as z:
            z.extractall(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kit', required=True, help='bộ cài đã phát hành (.zip hoặc thư mục)')
    parser.add_argument('--shim', required=True, help='libpatch-blmjcicarplay.so bản debug')
    parser.add_argument('--out', required=True, help='file .zip sẽ ghi ra')
    parser.add_argument('--version', default='da phat hanh', help='tên bản gốc, chỉ để ghi chú')
    args = parser.parse_args()

    if not os.path.isfile(args.shim):
        parser.exit(1, 'không thấy shim debug: %s\n' % args.shim)
    if os.name == 'nt':
        print('CẢNH BÁO: trên Windows, tên file trigger TouchTune vượt MAX_PATH '
              'nên nhiều khả năng giải nén hỏng. Nên chạy trong WSL.', file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix='vietnav-debug-kit-') as work:
        load_kit(args.kit, work)
        payload = os.path.join(work, 'vietnav-payload')
        dest = os.path.join(payload, TARGET)
        if not os.path.isfile(dest):
            parser.exit(1, 'bộ cài không có vietnav-payload/%s\n' % TARGET)

        old = md5(dest)
        old_size = os.path.getsize(dest)
        shutil.copyfile(args.shim, dest)
        new = md5(dest)
        print('%s: %d B (%s) -> %d B (%s)'
              % (TARGET, old_size, old[:12], os.path.getsize(dest), new[:12]))

        manifest = os.path.join(payload, 'PAYLOAD-SOURCES.md')
        with open(manifest, encoding='utf-8') as fh:
            text = fh.read()
        if old not in text:
            parser.exit(1, 'không thấy md5 cũ trong PAYLOAD-SOURCES.md -- dừng lại, '
                           'vì cài lên xe sẽ bị từ chối\n')
        text = text.replace(old, new)
        text = re.sub(r'(\| %s \|[^|]*\|)[^|]*\|' % re.escape(TARGET),
                      r'\1 BAN DEBUG (mazda-carplay-hud + patches/carplay-hud, '
                      r'build bang m3-toolchain, AGPL-3.0) |', text)
        text += ('\n> **Bản DEBUG.** Cầu CarPlay ở đây ghi log chi tiết ra '
                 '`/tmp/carplay_bridge.log`. Xem `%s` ở gốc USB.\n' % MARKER_NAME)
        with open(manifest, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)

        with open(os.path.join(work, MARKER_NAME), 'w',
                  encoding='utf-8', newline='\r\n') as fh:
            fh.write(MARKER.format(version=args.version))

        out = os.path.abspath(args.out)
        if os.path.exists(out):
            os.remove(out)
        count = 0
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, files in os.walk(work):
                for name in sorted(files):
                    full = os.path.join(root, name)
                    z.write(full, os.path.relpath(full, work))
                    count += 1
        print('xong: %s (%d file, %d B)' % (out, count, os.path.getsize(out)))
        print('Nhớ kiểm lại bằng cách chạy đúng awk của vietnav-install.sh verify().')


if __name__ == '__main__':
    main()
