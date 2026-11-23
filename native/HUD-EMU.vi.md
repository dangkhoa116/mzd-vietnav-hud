# HUD emu: nhận khung, nhận dạng ảnh và phát dữ liệu HUD

Nhánh native đã có đầy đủ đường xử lý **ATT → khung SDK → ảnh JPEG/hướng rẽ,
tên đường, khoảng cách, biển tốc độ → cặp bản tin VBS**. Có emulator offline
dùng chính code C đó, bản ARM glibc 2.11 và USB thử R3. Không đánh đồng kết
quả này với radio CMU hoặc HUD trên xe: hai phần đó chưa được thử trong phiên.

## Chức năng

- HUDInfo của profile iOS đã chấp nhận: H50, protocol **2.2.2** (không có S).
- Khung mới C3 có checksum, write chia 20 byte, giới hạn 8192 byte.
- Dẫn đường fixed/variable1/variable2, UTF-8 và khoảng cách theo đơn vị ×10.
- JPEG baseline tối đa 128×128, không heap/libjpeg/libm. Picojpeg được pin,
  giữ notice và có các sửa UB/kiểm SOS ghi trong `vendor/picojpeg/PROVENANCE.md`.
- Mô hình mũi tên được dựng từ IPA/APK do chủ xe cung cấp. Không commit app,
  ảnh hay model vào repo. Chấp nhận khi bình phương tương quan ≥0.81 và cách
  nhóm hướng khác ≥0.02. Ảnh trống/thời tiết/không đủ tin cậy bị ẩn glyph,
  không suy thành đi thẳng hoặc giữ nhầm hướng cũ.
- JPEG mới đổi mũi tên; flag 1 giữ mũi tên; flag 0 xoá glyph.
- CMD 1 có một/hai camera: chọn giới hạn khác 0 gần nhất; giá trị 0 ẩn biển.
- CMD kết thúc có direction FF hoặc distance FFFFFFFF xoá guidance.
- Ngừng nhận nav 10 giây xoá guidance một lần; heartbeat không giữ nav cũ.
- Reset trạng thái theo phiên; VBS đồng bộ sync cả hai bản tin khi xoá và
  cho thử lại kết nối lỗi ở phiên kế tiếp.

Các asset có ảnh giống nhau có thể mang tên khác nhau. Kiểm model đo nhóm
hướng, không tuyên bố định danh được mọi tên asset hay góc thoát vòng xuyến
thực khi app chỉ gửi một hình đại diện. Hình học và font HUD xe cần đối chiếu.

## Chạy HUD emu offline

Linux/WSL, Python 3.10+, gcc và Pillow:

```sh
python -m pip install pillow
python native/hud_emu.py --app /path/vietmap.ipa --demo --out out/hud-demo
```

Tool dựng model, compile engine C và tạo `hud-raw.jsonl`, `hud-events.jsonl`,
`REPORT.json`. `--demo` dùng ảnh asset thật của app, tái mã hoá JPEG và gói
thành khung tổng hợp; **không phải capture mới từ điện thoại**.

Có checkout `mzd-connect-emu` cạnh repo này, thêm preview:

```sh
python native/hud_emu.py --app /path/vietmap.ipa --demo \
  --out out/hud-demo --render ../mzd-connect-emu/scripts/hud-render.py
```

Ảnh nằm ở `out/hud-demo/preview/sheet.png`. Receiver/renderer của repo emu
phải có bản sửa sign-only nếu cần thấy biển/chữ khi `icon=0`.

Replay log C3 hoặc `VML RX` của native:

```sh
python native/hud_emu.py --app /path/vietmap.ipa \
  --log capture.txt --family H1 --out out/hud-capture
```

`--family H50` chọn luồng 9ABC; H1 chọn FFF2/FFF3. Log được kiểm checksum mặc
định rồi giữ command/header/payload, tái ký runtime UID zero cho replay.
Các ranh giới phiên được chèn khung idle, số lỗi/thiếu frame có trong report.
Replay offline chạy 100 ms/khung và kiểm TTL cuối luồng; không mô phỏng chính
xác thời gian radio. Bus OEM trong tool này là **fake**, không gọi dịch vụ xe.

## Build ARM và bộ USB thử

Dựng model riêng và ARM bằng m3-toolchain GCC 4.9.1 / glibc 2.11:

```sh
python native/build_arrow_model.py --app /path/vietmap.ipa --out out/arrows.vna
python native/build_arm.py --toolchain /path/m3-toolchain \
  --tpms /path/tpms-hud-reviewed --arrow-model out/arrows.vna --out out/native-arm
python native/usb/build_kit.py --build out/native-arm \
  --tpms /path/tpms-hud-reviewed --touchtune /path/TouchTune \
  --dest out/hud-usb-r3 --zip out/vietnav-native-hud-r3-usb.zip
```

Builder kiểm toàn bộ source đã compile, gồm guidance, VBS, decoder và model;
source thay đổi buộc rebuild. Kit hoàn chỉnh yêu cầu model, không chấp nhận
artifact cũ thiếu model/manifest. Source tương ứng và notice đi cùng ZIP.

**Chỉ hỗ trợ source/wrapper TPMS 0.9.3 đã review**, không tự áp dụng lên
0.9.20 hoặc wrapper khác. Cây TPMS 0.9.20 đang dùng được giữ nguyên. Kit vẫn
là thử riêng: query controller trước, proof gắn đúng thư viện, advertise ở một
lần boot kế tiếp và rollback TPMS. Đọc `usb/STEPS.vi.txt` trước khi dùng.

## Kết quả kiểm trong phiên này

- Model IPA 3.4.3: 119 template, JPEG kiểm tra dựng từ asset nhận đúng nhóm
  hướng. Đây là kiểm ảnh trên host, không phải phép thử radio mới.
- Test classifier: JPEG nhiều quality/resize, ảnh lạ/flat/progressive/cắt
  ngắn, model sai checksum, nhóm mâu thuẫn và 20.000 JPEG mutation dưới
  ASan/UBSan.
- Test luồng đầy đủ: ATT → decoder JPEG thật → guidance → hàm VBS và backend
  ABI giả; giữ/xoá hướng, camera, idle, hết hạn và sync.
- ARM `.so` chỉ yêu cầu GLIBC_2.4, thêm các API chuẩn được kiểm export trong
  libc/libdl 2.11; 5 test preload/PTY dưới loader/libc gốc firmware đã qua.
- Replay ARM/QEMU và host cho JSONL giống từng byte.

Kết quả chi tiết, hash model và artifact nằm trong `out/hud-complete/` của
phiên cloud. Firmware/rootfs đã khôi phục từ ZIP người dùng cung cấp và giữ
ngoài Git. Bài radio thật, OEM `bds`/VBS chạy trên xe, chung sống với nhạc/
cuộc gọi và ảnh HUD vật lý vẫn cần xác nhận riêng.

## HUD màu kính lái trong guest Mazda

Repo `mzd-connect-emu`, commit **`2d31d7b`** trên `codex/hud-sign-only`, đã
kiểm lớp dẫn đường và biển báo qua VBS/VIM trên ARM/QEMU 74.00.333A. Profile
`--lab-hud-settings --usb-services` chọn jcinavi/LDS/Time gốc. Chọn thiết bị
`native_hud_settings(setting="variant", value=2)` để dùng WHUD màu trong guest.
[Hướng dẫn chạy guest và xem ảnh](https://github.com/dangkhoa116/mzd-connect-emu/tree/2d31d7b932238f437317487729f6a6ebef390327/docs/HUD-STOCK.vi.md)

**Đính chính `867b14e`.** Hai trường native 4/5 bị gán nhầm nhãn.
Field 5 điều khiển độ sáng. Display dùng native type 0 (0 ON / 1 OFF).
NavigationSignal là khóa Settings riêng (1 ON / 2 OFF). Bản mới đọc cả hai từ
dịch vụ Mazda gốc và chờ callback Settings sau cold boot.

Đã kiểm sáu tổ hợp thiết bị và công tắc, biển riêng, cập nhật độc lập khoảng
cách/tên đường, hết hạn cặp dở và xóa trạng thái khi firmware reboot. Phép thử
dùng client ARM tổng hợp. Chiều cao và xoay cần phản hồi HEC để xác nhận.
Font, tỷ lệ và hình học chiếu cần đối chiếu HUD vật lý.
[Kết quả ARM/QEMU](https://github.com/dangkhoa116/mzd-connect-emu/tree/2d31d7b932238f437317487729f6a6ebef390327/results/2026-11-23/hud-whud)
