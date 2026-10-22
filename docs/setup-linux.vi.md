# Dựng máy Linux cho dự án Vietnav HUD

Tài liệu này dành cho người (hoặc agent) dựng một máy Linux để chạy những phần
mà **máy Windows hiện tại không chạy được**. Làm theo từ trên xuống; mỗi mức
chạy độc lập, không cần làm mức sau mới dùng được mức trước.

Nguồn của mọi câu lệnh dưới đây là `.github/workflows/host-tests.yml`,
`native/run_tests.sh` và `scripts/` của `mzd-connect-emu` — không phải công
thức chung chung.

## Windows đang kẹt những gì

| Việc | Windows | Vì sao |
| --- | --- | --- |
| `qemu-arm` (user-mode) | **không** | QEMU user-mode chỉ build cho host Linux. Không có bản Windows, kể cả khi cài QEMU for Windows (bản đó chỉ có `qemu-system-*`) |
| `mzd-connect-emu` | **không** | `docs/SETUP.md` của nó yêu cầu Linux x86_64 + `qemu-user` |
| `m3-toolchain` | **không** | submodule toàn binary ELF Linux x86_64 |
| `make`, `gcc` | không | chưa cài, và `tests/Makefile` + `native/run_tests.sh` cần |
| Chạy BusyBox 1.19.2 của xe | **không** | cần `qemu-arm` + rootfs ARM |
| Test sanitizer C++ | không | cần gcc/clang host |
| Build .so ARM | **có** (bằng zig) | xem `patches/carplay-hud/build_arm_zig.py` |
| Nạp/giao tiếp board ESP32-C3 | **có** | COM3 đang dùng trên Windows |
| Chạy Frida với iPhone | **có** | đang chạy trên Windows |

Hai dòng cuối là lý do **đừng bỏ máy Windows**: USB/serial và BLE của board,
cùng Frida với iPhone, đang chạy tốt ở đó. Linux là để bù phần build/test.

## Lợi ích lớn nhất khi có Linux: build .so ARM "chuẩn upstream"

Bản ARM hiện tại build bằng zig và có **hai điểm lệch so với upstream** đã ghi
trong `patches/carplay-hud/README.md`: libc++ link tĩnh (thay vì mượn
`libstdc++` của máy xe) và thêm một reloc `R_ARM_TLS_DTPMOD32`.

Trên Linux thì dùng được **chính `m3-toolchain`** mà upstream dùng, nên cả hai
điểm lệch đó biến mất. Nếu bản zig chạy trên xe có vấn đề, đây là cách loại trừ
dứt khoát xem lỗi do bản build hay do bản vá.

## Chọn cách dựng

| Cách | Hợp khi | Lưu ý |
| --- | --- | --- |
| **WSL2 trên chính máy này** | muốn nhanh nhất | Rẻ nhất, dùng chung thư mục `C:/work`. Đủ cho mức 1–3. Không dùng để nạp board (USB passthrough phiền) |
| VM (VirtualBox/Hyper-V) | muốn tách bạch | Cấp ≥ 4 CPU, 8 GB RAM, 60 GB đĩa nếu định build QEMU |
| Máy Linux thật / cloud | chạy emu đồ hoạ lâu | Cần cho phần Wayland/Mesa |

Khuyến nghị: **WSL2 + Ubuntu 24.04**, vì mọi thứ trong tài liệu này là
Debian/Ubuntu và CI cũng chạy `ubuntu-latest`.

```powershell
# PowerShell, chạy với quyền admin, rồi khởi động lại máy
wsl --install -d Ubuntu-24.04
```

Đĩa cần: ~5 GB cho mức 1–2, thêm ~25 GB nếu build QEMU và giải firmware.

## Mức 1 — Bộ test host (không cần firmware, không cần ARM)

Đây là mức đáng làm trước: nó chạy hết những test mà Windows đang bỏ qua.

```sh
sudo apt-get update
sudo apt-get install -y build-essential git python3-pip python3-venv \
    libssl-dev dbus pkg-config

git clone https://github.com/dangkhoa116/mzd-vietnav-hud.git
cd mzd-vietnav-hud
python3 -m pip install -r hud_emulator/requirements.txt pillow numpy ziglang pyelftools
```

Chạy:

```sh
# 1. Unit test python (CI chạy từng module riêng cho dễ lần lỗi)
python3 -m unittest discover -s tests -p 'test_*.py' -v

# 2. Bộ test dạng script
python3 bridge/vmlhud_frame_test.py
python3 bridge/vmlhud_nav_test.py
python3 bridge/vmlhud_vbs_test.py

# 3. Test C++ của bản vá CarPlay (43 kiểm tra)
make -C tests test-carplay

# 4. Test codec kèm sanitizer — đây là thứ Windows không chạy được
python3 tests/test_esp32_hud.py -v

# 5. Test installer dưới đúng BusyBox 1.19.2 của xe
sh tests/build-busybox-1.19.sh /tmp/bb119
env -i HOME="$HOME" PATH=/tmp/bb119/bin BUSYBOX=/tmp/bb119/bin/busybox \
    "$(command -v python3)" tests/test_installer.py
```

Mục 5 là cái đã từng cứu một ca lỗi thật: BusyBox trên xe không có `grep -x`,
test bằng GNU grep trên PC không phát hiện ra (xem
[emu-yeu-cau.md](emu-yeu-cau.md)).

`test_hud_bluez` cần D-Bus; nếu báo lỗi session bus thì chạy
`dbus-run-session -- python3 -m unittest tests.test_hud_bluez -v`.

## Mức 2 — ARM thật: qemu-user + rootfs + m3-toolchain

### 2.1 Cài

```sh
sudo apt-get install -y qemu-user binutils
```

`qemu-user` cho ra lệnh `qemu-arm`, là thứ `native/run_tests.sh` và
`tests/test_hud_native_transport.py` gọi tới (ghi đè được bằng
`VIETNAV_TEST_QEMU`).

### 2.2 Lấy m3-toolchain

```sh
cd <thư mục chứa repo>
git clone https://github.com/KidMixer/mazda-carplay-hud.git
cd mazda-carplay-hud
git submodule update --init --recursive      # kéo mazda/m3-toolchain
```

Submodule này nặng. Kiểm nhanh là nó chạy được:

```sh
mazda/m3-toolchain/bin/arm-cortexa9_neon-linux-gnueabi-g++ --version
```

### 2.3 Build bản .so CarPlay đúng kiểu upstream

```sh
cd mazda-carplay-hud
git apply ../mzd-vietnav-hud/patches/carplay-hud/0001-nav-recover-turn-from-instruction-text.patch
cd mazda
make debug           # ra build/debug/libpatch-blmjcicarplay.so
make release
```

So lại với bản zig để thấy đúng hai điểm lệch đã ghi:

```sh
cd ../../mzd-vietnav-hud
python3 patches/carplay-hud/check_rootfs.py \
    --rootfs <rootfs đã giải nén> \
    --shim ../mazda-carplay-hud/mazda/build/debug/libpatch-blmjcicarplay.so
```

Bản m3 phải **không** có `R_ARM_TLS_DTPMOD32` và **phải** có `libstdc++.so.6`
trong `DT_NEEDED` — ngược với bản zig. Cả hai đều phải PASS bốn mục.

### 2.4 Bộ test native ARM

```sh
cd mzd-vietnav-hud
git clone https://github.com/dangkhoa116/mzd-connect-tpms.git ../mzd-connect-tpms
sh native/run_tests.sh ../mazda-carplay-hud/mazda/m3-toolchain
```

Không truyền tham số thì nó chỉ chạy phần host; truyền đường dẫn toolchain thì
chạy thêm `native/build_arm.py` (bộ kiểm ELF ARM) và
`tests/test_hud_native_transport.py` dưới `qemu-arm`.

### 2.5 Chạy BusyBox và công cụ của xe

```sh
qemu-arm -L <rootfs> <rootfs>/bin/busybox          # phải in BusyBox v1.19.2
```

## Mức 3 — mzd-connect-emu đầy đủ

`mzd-connect-emu` là **repo riêng tư**; cần quyền truy cập (CI dùng secret
`EMU_TOKEN`, một PAT có scope `repo`).

```sh
git clone https://github.com/dangkhoa116/mzd-connect-emu.git
cd mzd-connect-emu
sudo apt-get install -y libwayland-dev pkg-config qemu-user python3-venv \
    binutils ca-certificates debian-archive-keyring
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
bash scripts/build.sh            # cầu nối host (Wayland)
bash scripts/fetch-runtime.sh    # tải Mesa/glibc armel vào local/mesa-root
```

Phần guest full-system cần **QEMU v10.0.13 tự build kèm patch** (script tự
clone và kiểm đúng commit):

```sh
sudo apt-get install -y ninja-build meson libglib2.0-dev libpixman-1-dev flex bison
bash scripts/build-qemu.sh       # ra local/qemu-build/qemu-system-arm
```

Nếu `configure` báo thiếu gói nào thì cài theo đúng thông báo — danh sách trên
là mức tối thiểu đã biết, không chắc đủ cho mọi bản distro.

Đọc `docs/SETUP.md`, `docs/SOFTWARE-SYSTEM.md` của repo đó trước khi chạy guest.
**Lưu ý thực tế:** theo bàn giao, toàn phiên GUI emu **chưa bao giờ pass** —
Opera thoát 139 trước bài installer. Đừng coi mức 3 là điều kiện để tiến tiếp.

## Chuẩn bị firmware / rootfs

Không commit firmware, rootfs, IPA hay APK vào repo.

File `.up` thực chất là zip:

```text
cmu150_ADR_74.00.333A_mass.up      (zip)
└── rootfs1/e0000000001.dat.gz     (chính là rootfs.tar.gz)
```

Giải nén **bỏ `/dev`, không giữ owner**, rồi đặt tiếp các file trong
`resources/` đúng chỗ theo `files.ini`, và kiểm `rootfs.md5`. Chi tiết trong
[emu-yeu-cau.md](emu-yeu-cau.md).

Trên máy Windows hiện tại đã có sẵn:

```text
C:/work/mazda/work/firmware/rootfs                     (74.00.333A, đã giải)
C:/work/mazda/CMU-FWs/.../cmu150_ADR_74.00.333A_mass.up
```

Dùng WSL2 thì truy cập thẳng qua `/mnt/c/work/mazda/work/firmware/rootfs`,
khỏi giải lại.

## Chạy xong thì phải thấy gì

| Mức | Lệnh | Kết quả đúng |
| --- | --- | --- |
| 1 | `make -C tests test-carplay` | `43 kiem tra, 0 loi` |
| 1 | `python3 tests/test_esp32_hud.py -v` | OK, không lỗi sanitizer |
| 1 | `tests/test_installer.py` dưới BusyBox | toàn bộ PASS |
| 2 | `qemu-arm -L <rootfs> <rootfs>/bin/busybox` | `BusyBox v1.19.2` |
| 2 | `check_rootfs.py` | `KẾT QUẢ: PASS` cả bốn mục |
| 2 | `native/run_tests.sh <toolchain>` | không lỗi |

## Linux vẫn KHÔNG giải quyết được gì

Nói rõ để không kỳ vọng sai:

- **Không tái hiện được phiên CarPlay của iPhone thật.** Emu không có iPhone,
  không có luồng iAP2. Câu hỏi còn lại của dự án — "VietMap có phát khung
  `0x8059` không, và `maneuverDesc` mang chuỗi gì" — **chỉ log trên xe mới trả
  lời được**.
- **Không tái hiện radio TI** (HFP/A2DP/LE đồng thời). Không dùng kết quả guest
  để kết luận BLE hay HUD thật chạy được.
- Chạy được trong emu **không** chứng minh chạy được trên xe, và ngược lại.

Nói cách khác: Linux giúp **build chuẩn hơn và test nhiều hơn**, nhưng không
thay được một lần cắm máy vào xe.
