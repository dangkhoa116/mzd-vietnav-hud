# Kiểm tra USB native trong mzd-connect-emu

Firmware do người dùng cung cấp: **CMU150 ADR 74.00.333A**, SHA256
`8082edfe61c8788b770b46e0a0f899b4a5c3f941ba52864052ef5d27885e3928`.
Không commit firmware, resources, account database hoặc ảnh đĩa vào repo.

## Kết quả 21-10-2026

- Đối chiếu **8.478/8.478** file rootfs với manifest gốc: khớp MD5.
  Đặt 714 resource theo `resources/files.ini.gz`, kiểm CRC từng file.
- **23/23** kiểm tra USB chạy với executable BusyBox gốc ARM
  `1.19.2 (2020-02-14 18:04:06 JST)` và loader/libc firmware qua QEMU user-mode.
  Đường dẫn CMU, mount, GPIO, dialog và identity process vẫn là fixture cách ly.
- **5/5** test transport của chính thư viện ARM trong USB R2 qua QEMU,
  dùng loader/libc firmware thay cho sysroot m3-toolchain. Controller,
  iPhone và process bds là các peer giả qua PTY.
- `jci-dialog` gốc chạy trên legacy IVI bridge của emu, vẽ menu
  680×354 với ba nút và năm dòng đúng font; đã xem ảnh, không cắt chữ.
  Bridge này chưa phát sự kiện touch; đây là kiểm hình ảnh, chưa phải thao
  tác bấm nút thật trên toàn bộ bộ cài.
- Guest ARM system của emu chạy **9 checkpoint USB thành công**: chuẩn bị
  TPMS fixture, chặn advertise thiếu query, cài/backup/checksum/boot token,
  nạp thư viện vào process thật, huỷ lịch, thu log, từ chối wrapper lạ,
  rollback TPMS/protected files đúng byte, gỡ lặp lại.

**Toàn bộ phiên giao diện emu chưa pass.** Opera thoát với mã **139** ngay sau
khi khởi chạy, trước bài cài đặt; MMUI sau đó dừng vì thiếu GUI health response.
Ảnh cuối là màn hình đen. Một lần kiểm tra bổ sung đã đổi quyền traverse của
root và `/usr` trên bản sao Mesa image từ 0700 sang 0755; Opera vẫn thoát 139.
Đây chưa phải chẩn đoán nguyên nhân segfault và không được tính là kiểm chứng
HomeScreen/CarPlay hay tính ổn định trên CMU thật.

## Guest và giới hạn

Emu revision `8a400472d718d8cb693e898024049a9d7de8aab9`, backend GPL
`PatrikTheDev/MazdaConnect-QEMU` revision
`a7e5a7f3994ccd68bf75bde4d482b1785fec4148`.
Generic Linux `6.1.176-cmu-soft`, 2 GiB userspace, Cortex-A15 TCG, 2 CPU,
1 GiB RAM, original SM/MMUI/VBS/native services, Mesa software graphics,
synthetic VIP, silent HDA. Bật intro-race fix có kiểm hash của backend.
Không chạy kernel Mazda gốc hoặc Vivante, không có controller BLE cho bds.

`guest-checks.sh` chỉ chạy khi có cả boot argument `CMU_VIETNAV_TEST=1` và
`rdinit=/emu-vietnav-init`. Nó **thay file trong guest để dựng fixture TPMS**;
chỉ dùng với QEMU snapshot dùng một lần. Không chạy script này trên xe.
Thư viện TPMS/wrapper từ checkout TPMS, BLE pack được ghép offline từ pack
Mazda và public TI `TIInit_10.6.15.bts`. Không chạy bds hoặc nạp pack vào radio.
Thư viện native được kiểm bằng `/proc/<pid>/maps` của BusyBox sleep ở chế độ
inert, không phải một phiên dẫn đường thật.

USB được đưa vào guest bằng tar trên tmpfs `/tmp/mnt/sda1`; chưa mô phỏng
FAT32/USB mass storage hoặc trigger cập nhật TouchTune. Boot ID ghi trong token
là boot ID guest thật, nhưng chưa kiểm nhiều lần power-cycle với data_persist
lưu trên đĩa. Luồng token qua nhiều boot đã được kiểm riêng trong 23 test fixture.

## Chạy lại trong workspace đã chuẩn bị

```sh
VIETNAV_TEST_BUSYBOX=/workspace/.mzd-tools/bin/cmu333-busybox \
  python3 tests/test_hud_native_usb.py -v

VIETNAV_TEST_ARM_TOOLCHAIN=/workspace/.mzd-tools/m3-toolchain \
VIETNAV_TEST_QEMU=/workspace/.mzd-tools/root/usr/bin/qemu-arm \
VIETNAV_TEST_ARM_SYSROOT=/workspace/.mzd-tools/firmware/rootfs-333 \
VIETNAV_TEST_LIBRARY=out/native-build/libvietnav-native-arm.so \
  python3 tests/test_hud_native_transport.py -v
```

Các input guest và bản sao boot/services nằm trong
`/workspace/mzd-connect-emu/local/vietnav-guest*` (ignored). QEMU wrapper thêm
boot flag kiểm tra và chọn `/emu-vietnav-init`; script/checks và fixture tar
được thêm vào initramfs bằng `scripts/add-initramfs-file.py`, không sửa các
entry gốc. Runner dùng `-snapshot`; guest không ghi lại vào root image gốc.
Các run directory `runs/vietnav-usb-333*` giữ cả phiên không pass và probe JSON.
Không dùng exit code riêng của guest checks để kết luận toàn bộ emu pass.

Các bước dựng root/kernel/runtime gốc xem
[SOFTWARE-SYSTEM.md](https://github.com/dangkhoa116/mzd-connect-emu/blob/main/docs/SOFTWARE-SYSTEM.md).
Mốc tiếp theo của Vietnav là kiểm BLE/iPhone thật (có thể dùng ESP32-C3),
chốt navigation/camera và nối output VBS/HUD. Chưa xác nhận các phần này bằng emu.
