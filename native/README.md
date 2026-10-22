# VIETNAV HUD native — bản thử cho CMU150

Đã có code C và bản ARM thử nghiệm, tái sử dụng lớp HCI/UART của TPMS v3.
**Chưa thử với radio Mazda/iPhone thật; chưa gửi nhánh này lên VBS/HUD.**
Bộ cài USB VIETNAV 0.9.1 và checkout TPMS giữ nguyên.
Đã có [bộ USB thử riêng](usb/STEPS.vi.txt): menu kiểm tra BLE/kết nối,
thu log, huỷ lịch và gỡ; chỉ chạy HUD ở một lần khởi động kế tiếp.

## Đã triển khai

- Đọc đủ Supported Commands, Supported States (8 byte), kích thước/số buffer
  ACL trong preflight LE của TPMS. Thiếu dữ liệu/khả năng cần thiết thì dừng.
- Kiểm command bits 205/207/208/209 và state bits 2 (connectable advertising),
  7 (peripheral). Bản đầu chỉ nhận buffer LE riêng, ít nhất 27 byte/1 packet;
  chưa dùng chung pool ACL classic.
- Quảng bá `VIETMAP-HUD` (11 byte, đổi từ `VIETNAV HUD` cùng độ dài), FFF0,
  ADV_IND, interval 100–150 ms. Không sửa tên Bluetooth classic của xe.
- ATT server MTU 23: GAP/device name, GATT tĩnh, FFF0/FFF1–FFF4, CCCD;
  discovery, read/blob, write request/command, notify và ATT errors.
  Không bonding hoặc long write.
- Ghép yêu cầu HUD mới, kiểm checksum mặc định, trả HUDInfo qua FFF1,
  tối đa 20 byte/notify. Dùng timestamp từ yêu cầu và UID thử 16 byte zero.
  Danh tính **đã được app iOS 3.4.3 chấp nhận trên emulator ESP32-C3 ngày
  22-10-2026**: `MODEL:H50,HW:1.0.0,FW:1.0.0,PROTOCOL:2.2.2,OBDV:0_1.0,
  SID:VMEMU0000001`. Lưu ý `PROTOCOL` **không** có chữ "S" cuối: `2.2.2S`
  khiến app chỉ gửi CMD 0x00 không bao giờ gửi ảnh mũi tên CMD 0x40
  (docs/hud-dart-layer-analysis.vi.md). Chưa xác nhận UID runtime.
- Ghi BLE write của chính HUD thành `VML RX`. Tool Python đọc lại thành
  navigation/camera/heartbeat, kể cả legacy. Assembler bắt tay C chỉ xử lý
  khung mới, giới hạn 2048 byte; chưa xử lý ảnh/OTA lớn.
- **Đường VBS đã nối (host, chưa lên xe)**: khung nav CMD 0x00/0x40 được giải
  mã ngay trong core C (`hud_guidance.c`, parity từng field với
  `bridge/vmlhud_nav.py` + `vmlhud_vbs.py`, test 19 case), gộp thành guidance
  (dedup, sync bit 1..7, xoa khi khung rỗi) rồi `vn_vbs.c` đẩy cặp
  `VBS_NAVI_SetHUDDisplayMsgReq` + `VBS_NAVI_TMC_SetHUD_Display_Msg2` qua
  libjcidbus/libjcivbsnaviclient OEM (dlopen trong `vn_vbs_dl.c`, bus name
  riêng `com.jci.vietnav.hud`, probe GetHUDStatus fail-open, Msg2 luôn đi kèm
  Msg1, tên đường trống thành một dấu cách). Tên đường tiếng Việt được chuẩn
  hoá 3 byte → 2 byte cho font HUD (port từ hud_send.cpp của
  mazda-carplay-hud). Icon: giữ icon cũ, mặc định thẳng — nhận dạng mũi tên
  JPEG cần bộ fingerprint offline, vẫn nằm phía Python.
- Một ACL packet đang chờ completion tại một thời điểm. Completion của handle
  khác không cấp credit cho HUD; mux giữ traffic/credit của `bds`.

## Cách tích hợp

`prepare.py` kiểm SHA-256 của TPMS v3.c rồi tạo bản sao đã áp dụng patch trong
`out/`. Không sửa TPMS. SHA-256 source được hỗ trợ:

```
39ea9a0d9ff6c942b2798bb45c96cb222bb2bc8729c4ed938b065bf475c8cdd4
```

Giữ nguyên copyright/MIT notice của TPMS trong source tạo ra; phần bổ sung
Vietnav mang AGPL-3.0-or-later. `tpms_adapter.inc` nối core với UART/read lock,
khởi tạo BLE và bộ lọc TPMS. Đây là **một preload HUD-only**, không ghép hai
preload độc lập; không scan/kết nối TPMS khi thử HUD.

| Biến của bản native | Ý nghĩa |
|---|---|
| `VIETNAV_NATIVE_MODE` không đặt/giá trị lạ | Inert: không chủ động gửi HCI hoặc đổi service pack |
| `VIETNAV_NATIVE_MODE=query` | Khởi tạo/kiểm LE, không quảng bá |
| `VIETNAV_NATIVE_MODE=advertise` | Preflight rồi quảng bá, nhận một kết nối |
| `VIETNAV_NATIVE_TRIAL_MS` | Thời gian từ sau preflight: mặc định 60 s, tối đa 180 s |

Đây là cấu hình nội bộ của [launcher USB](usb/README.md), **không phải hướng
dẫn thêm preload vào bds đang chạy**. Cần BLE service pack như TPMS;
builder không chứa firmware.
Không dùng script TPMS `on/off` để cài đè thư viện này vào TPMS đang dùng.

Kế thừa trì hoãn/quiet window của TPMS. Lệnh quảng bá đi từng bước, cách nhau
ít nhất 200 ms, timeout 3 s. Hết hạn, lỗi hoặc ngắt kết nối thì dừng thử; không
tự kết nối lại. Cleanup yêu cầu tắt advertising/ngắt handle, chờ sự kiện ngắt;
không coi Command Status thành công là đã ngắt. Nếu UART/controller hỏng thì
cleanup chỉ có thể là best effort; chưa kiểm khôi phục trên xe cho bản này.

## Build và kiểm thử

Cần Python 3.10+, gcc, patch, dbus-daemon; dbus-next cho test backend Linux.
Chạy từ gốc repo:

```sh
python3 -m venv .venv-hud
.venv-hud/bin/pip install -r hud_emulator/requirements.txt
PYTHON=.venv-hud/bin/python sh native/run_tests.sh
```

Đã kiểm chứng:

- **96 test host** trên máy dev (protocol, bridge, hud_out, arrow, native
  21/21, module mới `test_hud_guidance` 19/19 — parity decode/builders với
  Python, normalize tiếng Việt, sender VBS với backend giả, đường ATT→frame→
  guidance); BlueZ/D-Bus, transport, USB, esp32 chạy trong CI Linux.
- Toàn v3.c đã patch + các file mới compile sạch nhắm x86_64-linux và
  arm-linux-gnueabi (cortex_a9) bằng zig trên máy Windows.
- **229 kiểm tra TPMS mux** vẫn pass với source đã ghép native.
- **50.000 input ATT lỗi** qua AddressSanitizer + UndefinedBehaviorSanitizer.
- Transport chạy preload thật, PTY thật, process giả bds; so đúng từng byte
  traffic bds nhận được. Controller/iPhone là giả lập, không có radio BLE.
  Bao gồm handshake, capture navigation, query không quảng bá, thiếu capability,
  controller từ chối và mặc định inert.
- Với firmware 74.00.333A do người dùng cung cấp: 23 test USB bằng BusyBox
  ARM gốc, 5 test transport với loader/libc gốc và 9 checkpoint cài/gỡ trong
  guest emu qua. `jci-dialog` gốc vẽ đúng menu. Toàn bộ phiên GUI emu **chưa
  qua** vì Opera thoát 139 trước khi chạy bài cài đặt;
  [bằng chứng và giới hạn](emu/README.md).

## ARM và loader CMU

Dùng [m3-toolchain](https://github.com/lmagder/m3-toolchain), bản đã dùng:
commit `61ec0343de84f6fc7c46840056df1d600d44be8a`, GCC 4.9.1, glibc 2.11.
Có QEMU user-mode `qemu-arm`:

```sh
PYTHON=.venv-hud/bin/python sh native/run_tests.sh /path/to/m3-toolchain
# Hoặc chỉ build ARM:
python3 native/build_arm.py --toolchain /path/to/m3-toolchain
```

Output `out/native-build/libvietnav-native-arm.so` và `ARM-CHECKS.json`.
Đã kiểm ELF32 ARM little-endian/EABI5, base calling convention, chỉ yêu cầu
**GLIBC_2.4**, không thêm relocation/required symbol so với TPMS v1 từng chạy
trên xe. Hai linker đặt cờ tùy chọn HASENTRY/SOFT_FLOAT khác nhau (`0x202`);
gate ghi nhận khác biệt và không sửa header để ép giống.

**5 test transport ARM/QEMU** pass với dynamic loader/libc 2.11 trong sysroot,
gồm preload/handshake qua PTY. Cùng 50.000 input ATT cũng chạy qua core ARM.
Các kiểm tra này không thay thế thử radio, firmware và bds trên xe.

## Đọc capture

```sh
python3 native/decode_capture.py /path/to/native.log
```

Chỉ đọc `VML RX`, chia phiên theo `VML connected/disconnected`, giữ Unicode.
`session_seen=false` nghĩa log thiếu dấu bắt đầu phiên; `incomplete_frame` nghĩa
thiếu byte. Không giải mã/log traffic classic.

## Mốc tiếp theo trên xe

Dùng USB riêng theo [hướng dẫn thử](usb/STEPS.vi.txt): query trước, lưu log,
khởi động lại về TPMS rồi đặt lịch advertise. Installer chỉ cho advertise
khi query thành công với cùng thư viện/monitor/BLE pack/bds.real.
Mốc cần xác nhận: VietMap tìm thấy HUD, mở GATT, nhận HUDInfo và gửi
navigation **và guidance thật lên được VBS/HUD xe** (đường VBS đã code xong,
chưa từng chạy trên xe — dlopen libjcidbus/libjcivbsnaviclient trong bds,
bus name `com.jci.vietnav.hud`). Sau đó chốt bảng mã hướng rẽ từ ảnh mũi tên
(nhận dạng vẫn phía Python) và xem speed/current_road có đổ khi chạy xe.
Chưa hỗ trợ TPMS central + HUD peripheral đồng thời. TPMS trở lại ở lần
start kế tiếp, không bật lại giữa phiên native khi hết thời gian thử.

Tham chiếu command/state:
[Bluetooth HCI specification](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/host-controller-interface/host-controller-interface-functional-specification.html),
[BlueZ 5.7 monitor tables](https://github.com/bluez/bluez/blob/5.7/monitor/packet.c).
