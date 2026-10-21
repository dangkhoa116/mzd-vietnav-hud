# Yêu cầu cho mzd-connect-emu: test bộ cài USB trước khi giao khách

Tài liệu này dành cho bên phát triển [mzd-connect-emu](https://github.com/dangkhoa116/mzd-connect-emu).
Nó nói emu cần làm được gì để test các kit cài bằng USB (VIETNAV HUD, TPMS,
CarPlay không dây) **trọn quy trình như trên xe**, trước khi gửi USB cho khách.

## Vì sao cần

Tháng 10/2026 một khách (CX-5, firmware `MAZ_CMU-150_74.00.310`) cài VIETNAV
HUD và gặp lỗi `CAI DAT LOI / INSTALL FAILED`. Nguyên nhân: BusyBox trên xe là
**1.19.2**, `grep` của nó không có option `-x`. Test trên máy tính dùng GNU grep
nên không phát hiện. Chỉ một môi trường chạy **đúng file của firmware** mới bắt
được loại lỗi này trước khi khách gặp.

## Đã chạy được (bản thử, làm tay)

Với firmware `cmu150_ADR_74.00.333A_mass.up` đã làm được:

| Việc | Cách làm | Kết quả |
| --- | --- | --- |
| Lấy rootfs | `.up` là zip → `rootfs1/e0000000001.dat.gz` là `rootfs.tar.gz` → giải nén (bỏ `/dev`, không giữ owner) | `/bin/busybox`, `/jci/sm/sm.conf`, `/jci/tools/jci-dialog`… |
| Chạy BusyBox của xe | `qemu-arm -L <root> <root>/bin/busybox <applet>`; một wrapper + symlink cho mỗi applet, PATH chỉ chứa các symlink này | `BusyBox v1.19.2 (2020-02-14 18:04:06 JST)`: trùng với xe khách |
| Chạy script cài | `tests/test_installer.py` của repo VIETNAV với `BUSYBOX=<wrapper>`; đường dẫn xe được đổi sang thư mục tạm, `mount`/`smctl`/`jci-dialog` là stub | Bản lỗi tái hiện đúng lỗi của khách; bản 0.9.0 qua 104/104 |
| Vẽ hộp thoại thật | `build/bridge` của emu + `qemu-arm … /jci/tools/jci-dialog <args>` với `WAYLAND_DISPLAY=wayland-cmu` | Khung `wl_shm` 680×354 XRGB8888 → PNG, đúng font Mazda |

Giới hạn của bản thử: script chạy trên **cây thư mục giả**, không phải trong hệ
thống xe đang chạy; `jci-dialog` không bấm được (seat không có touch);
không có service manager, không khởi động lại, không có HUD.

## Cần emu làm được

Thứ tự là độ ưu tiên. P0 là đủ để test việc cài/gỡ; P1 để chắc chắn mod chạy
được sau khi cài; P2 để xem kết quả trên HUD.

### P0: cài và gỡ trọn quy trình

1. **Nhập firmware từ file `.up`**
   - Đầu vào là file cập nhật Mazda (`cmu150_*.up`). Đầu ra là cây root dùng
     được ngay, không bị sửa (chỉ đọc).
   - Ngoài `rootfs1`, phải đặt các file trong `resources/` đúng chỗ theo
     `files.ini`, vì nhiều file trong `/jci` nằm ở đây. Kiểm tra `rootfs.md5`.
   - Hỗ trợ nhiều bản firmware song song, chọn bản khi chạy. Cần ít nhất
     **74.00.310** (xe khách đang chạy, chưa có file), 74.00.324A, 74.00.331,
     74.00.333A.

2. **Chạy script trong chính hệ thống xe**
   - Script chạy trong root của firmware (chroot hoặc system guest), với
     `/bin/sh` là BusyBox của firmware, quyền root, `HOME=/root`, và PATH như
     trên xe.
   - Không được rơi về công cụ của máy chủ (GNU grep/awk/sed). Đây là điểm quan
     trọng nhất.

3. **Giả lập USB**
   - Một thư mục trên máy được gắn vào `/tmp/mnt/sda1` (cả `sdb1`… nếu cắm
     nhiều USB) với đặc tính FAT32: gắn chỉ đọc lúc đầu,
     `mount -o rw,remount /tmp/mnt/sda1` phải chạy được, không có bit thực thi,
     không phân biệt hoa thường, tên file dài tới 255 ký tự.
   - Lệnh rút USB giữa chừng, để test các trường hợp ghi dở.

4. **Kích hoạt cập nhật (TouchTune)**
   - Tái hiện cách CMU xử lý file `.up` trên USB: hiện hộp thoại cập nhật, bấm
     INSTALL, rồi chạy tên file như một lệnh shell. Tên file TouchTune là một
     đoạn `$(...)` dài 253 ký tự; nó kiểm tra `TOUCHTUNE.ID` rồi chạy
     `install-patches.sh`.
   - Nếu chưa tìm ra chương trình nào của CMU làm việc này, tạm thời làm một
     lệnh `emu trigger` chạy tên file đó y như CMU (cùng shell, cùng biến môi
     trường như `TT_ROOT`, `HOME`). Cần ghi rõ chỗ nào là giả lập.

5. **Hộp thoại bấm được và chụp được**
   - `jci-dialog` thật hiện lên, có bấm cảm ứng (`wl_touch`) theo **nhãn nút**
     (`emu tap "CAI DAT"`) hoặc theo toạ độ. Mã thoát trả về đúng như trên xe:
     OK = 0, cancel = 1, nút 3 = 2.
   - Mỗi hộp thoại tự lưu thành PNG kèm danh sách tham số đã gọi.
   - `killall jci-dialog` (script dùng để đóng hộp thoại cũ) phải chạy đúng.

6. **Ghi vào hệ thống như trên xe**
   - `/` gắn chỉ đọc; `mount -o remount,rw /` và `remount,ro` phải chạy được.
   - `/data_persist` ghi được và giữ lại qua các lần chạy.
   - Có file `/sys/class/gpio/Watchdog Disable/value` (tên có dấu cách).
   - Chụp trạng thái hệ thống file trước và sau mỗi lần chạy, rồi xuất **diff**
     (file thêm, xoá, sửa). Đây là cách kiểm tra "không đổi gì" khi cài lỗi, và
     "gỡ xong trở về y nguyên".

### P1: mod chạy được sau khi cài

7. **Service manager thật**
   - `/jci/sm/sm` chạy với `sm.conf`/`sm_WCP.conf`. `smctl -r -n jciAAPA`
     (`aap_service`, `jciCARPLAY`) khởi động lại được dịch vụ.
   - `environ_var` (`LD_PRELOAD`, `LD_LIBRARY_PATH`) thật sự được áp vào tiến
     trình: kiểm tra `/proc/<pid>/maps` có `libpatch-*.so`.
   - Ghi lại khi dịch vụ crash, và hành vi của `reset_board="yes"/"no"` (không
     được làm cả hệ thống khởi động lại liên tục).

8. **Tắt máy / bật máy**
   - Lệnh `emu power-cycle` giả lập tắt máy khoảng 10 phút rồi nổ lại:
     `/data_persist`, `/jci`, `/etc` giữ nguyên, các script khởi động chạy lại
     từ đầu.
   - Cần cho: `NaviSupported` (CarPlay chỉ đọc lúc khởi động), bộ đếm khởi động
     của TPMS, kit CarPlay không dây tự khởi động lại máy.

9. **Nhiều kit trên một xe**
   - Cài sẵn kit TPMS và/hoặc kit CarPlay không dây (theo kịch bản), rồi cài
     VIETNAV, để kiểm tra các kit không phá nhau. Launcher dùng chung
     (`install-patches.sh`) phải hiện màn chọn kit.

### P2: kết quả trên HUD

10. **Dữ liệu dẫn đường giả**
    - Bơm dữ liệu dẫn đường như từ điện thoại: Android Auto (GAL 1.6,
      navigation status/turn event) và CarPlay (iAP2 route guidance), mà không
      cần điện thoại thật.

11. **Chụp HUD (Active Driving Display)**
    - Bắt nội dung gửi ra HUD (mũi tên, khoảng cách, tên đường) thành ảnh hoặc
      dữ liệu, để kiểm tra tên đường tiếng Việt dài sau khi đã bỏ dấu.

## Cách dùng mong muốn

Một kịch bản chạy không cần màn hình, dùng được trong CI, xong trong khoảng
10 phút:

```sh
emu boot --firmware 74.00.310 [--preinstall tpms,wcp]
emu usb insert ./dist                # thư mục kit, như khi chép vào USB
emu expect-dialog "Cap nhat"         # hộp thoại cập nhật của CMU
emu tap INSTALL
emu expect-dialog "VIETNAV HUD 0.9.0" --text "CHUA CAI / not installed"
emu tap "CAI DAT"; emu tap "CA HAI"; emu tap "CAI DAT"
emu expect-dialog --text "DA CAI / INSTALLED" --timeout 120
emu tap OK
emu usb remove
emu power-cycle
emu check maps jciCARPLAY libpatch-blmjcicarplay.so
emu fs-diff > diff.txt
emu collect ./run-001                # ảnh từng hộp thoại, log, diff, log của USB
```

Mã thoát khác 0 khi bất kỳ bước nào không đạt.

## Tiêu chí nghiệm thu

- **Tái hiện lỗi thật:** commit `4ca44bc` của mzd-vietnav-hud phải ra **đúng**
  lỗi của khách: `grep: invalid option -- 'x'` rồi
  `sanity check failed for jciCARPLAY`, sau đó hộp thoại
  `CAI DAT LOI / INSTALL FAILED`, và diff hệ thống file rỗng.
- **Bản tốt cài được:** bản 0.9.0 (`main` từ commit `2873d9b`) cài được AA + CarPlay. Sau khi tắt/bật
  máy, `libpatch-*.so` có trong maps của `blmjciaapa`/`aap_service`/
  `blmjcicarplay`, và `NaviSupported` là `TRUE`.
- **Gỡ sạch:** GO BO đưa `sm.conf` trở về y nguyên từng byte so với trước khi
  cài.
- **Ảnh khớp xe thật:** ảnh hộp thoại khớp ảnh chụp trên xe (font, khung
  680×354, vị trí nút).

## Ràng buộc

- **Không đưa firmware lên repo:** file `.up`, rootfs, thư viện và font của
  Mazda/JCI không được commit vào repo nào. Người dùng tự cung cấp đường dẫn
  khi chạy.
- **Firmware chỉ đọc:** mỗi lần chạy dùng một bản sao hoặc snapshot.
- **Ghi rõ phần giả lập:** chỗ nào thay thế phần cứng (VIP, Vivante, CAN, nguồn
  điện) phải ghi rõ trong log kết quả, để không nhầm "qua trên emu" với "qua
  trên xe".

## Thông tin tham khảo

| | |
| --- | --- |
| BusyBox của xe | `v1.19.2 (2020-02-14 18:04:06 JST)`, ARM EABI5, `/lib/ld-linux.so.3`. `grep` chỉ có `-HhnlLoqvsriwFEcmABCef` |
| `jci-dialog` | Wayland `wl_shm` + `wl_ivi`/`wl_ivi_shell`, cairo. Option: `--info --warning --error --question --confirm --3-button-dialog --title= --text= --ok-label= --cancel-label= --button3-label= --no-cancel`. Chữ xuống dòng bằng `\n` viết thẳng trong chuỗi |
| File gốc bộ cài kiểm tra md5 | `blmjciaapa.so` `486628ae…`, `aap_service` `964e9af0…`, `blmjcicarplay.so` `0a4e3a67…`, `libdevmgr_interface.so` `e914face…`. Trùng nhau trên 74.00.310 / .324A / .331 / .333A |
| Các kit | [mzd-vietnav-hud](https://github.com/dangkhoa116/mzd-vietnav-hud), [mzd-connect-tpms](https://github.com/dangkhoa116/mzd-connect-tpms), CarPlay không dây (all-in-one 1.0.3). Trigger: TouchTune 1.2.1 (Miatafy, GPL-3.0) |
| Script build BusyBox 1.19.2 từ mã nguồn | `tests/build-busybox-1.19.sh` trong mzd-vietnav-hud (dùng khi không có firmware) |
