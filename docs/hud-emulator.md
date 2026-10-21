# Giả lập HUD VietMap — bản thử BLE cho Vietnav

Ngày 21-10-2026. **Có code chạy thử trên Linux/BlueZ và decoder offline. Chưa
xác nhận VietMap Live chấp nhận, chưa đưa dữ liệu nhánh này lên HUD Mazda.**
Installer USB 0.9.1 vẫn giữ nguyên; không đưa bản thử vào kit cài trên xe.

**Cập nhật sau khi đối chiếu TPMS:** project TPMS đã có đường BLE trực tiếp
trên chip Mazda, tài liệu ghi nhận nhận frame thật trên xe. Ưu tiên tận dụng
lớp HCI trong `bds` để bổ sung peripheral/ATT server cho HUD; chưa cần chốt
phần cứng ngoài. [Đối chiếu code và ràng buộc dùng chung](hud-native-cmu.md).
Đã có [bản native C/ARM thử nghiệm](../native/README.md), kiểm trên máy và
QEMU; đã có [USB thử riêng](../native/usb/README.md) để query trước, đặt lịch
một lần khởi động, thu log và khôi phục wrapper TPMS. Chưa kiểm BLE trên xe.

## Mục tiêu và ảnh tham khảo

Ảnh người dùng cung cấp cho thấy màn Mazda có menu `VML HUD`, nguồn dẫn đường
`VietMap Live`, bật biển tốc độ và ngưỡng quá tốc độ. Nó cho thấy có một giải
pháp tích hợp để tham khảo, nhưng riêng ảnh này chưa chứng minh cách nhận dữ
liệu, phần cứng kèm theo, hoặc quá trình giả lập/bắt tay của giải pháp đó.

Hướng đang kiểm chứng:

```
VIETMAP LIVE trên iPhone
        │ BLE: FFF0 / FFF2 ghi / FFF1 notify
        ▼
VIETNAV HUD (Linux/Raspberry Pi thử nghiệm)
        │ ghép khung → kiểm checksum → giải mã
        ▼
JSON Lines: tên đường, mã hướng, khoảng cách, camera
        │ bước kế tiếp sau khi có capture thật
        ▼
bridge vào com.jci.vbs.navi → HUD zin Mazda
```

Mục tiêu trước mắt: app tìm thấy thiết bị, hỏi HUDInfo, rồi thật sự gửi CMD `00`
khi dẫn đường. Bằng chứng này cần có trước khi đóng gói bridge cho CMU.

## Đã có gì

- `hud_emulator/protocol.py`: ghép các BLE write bị chia nhỏ, kiểm CRC legacy /
  checksum mặc định mới, giải mã navigation/camera/heartbeat; giữ lệnh lạ để
  nghiên cứu. Không giả định bảng mã hướng rẽ VietMap giống Mazda.
- `hud_emulator/bluez.py`: peripheral tên `VIETNAV HUD`, dịch vụ `FFF0`,
  characteristic `FFF1–FFF4`, trả HUDInfo thử qua notification 20 byte/lần.
  Ghi cả byte thô và bản giải mã, xoá trạng thái khi điện thoại ngắt kết nối.
- `python -m hud_emulator decode`: đọc stream binary hoặc từng dòng hex,
  dùng được không có Bluetooth hay thư viện ngoài.
- 17 test codec/CLI và 4 test D-Bus/session. Test D-Bus dựng một bus riêng,
  giả lập `org.bluez` để kiểm đăng ký service, ghi dữ liệu và notify qua D-Bus
  thật, ngắt/nối lại và dọn đăng ký. Đây **không phải** kiểm thử BLE qua sóng.

Bằng chứng giao thức, địa chỉ hàm và SHA-256 SDK:
[vietmap-hud-sdk.md](vietmap-hud-sdk.md).

## Chạy thử với iPhone

Cần Python **3.10+**, Linux có `bluetoothd`/BlueZ và adapter BLE hỗ trợ vai trò
peripheral (máy Linux hoặc Raspberry Pi phù hợp để thử). Phiên cloud hiện tại
không có adapter để xác nhận qua sóng. Đây không phải binary chạy trực tiếp
trên Mazda. TPMS đã có BLE central trực tiếp trên CMU; nhánh peripheral/ATT
server cho HUD và khả năng chạy đồng thời với TPMS vẫn cần triển khai/xác minh.

Từ gốc repo:

```sh
python3 -m venv .venv-hud
.venv-hud/bin/pip install -r hud_emulator/requirements.txt
bluetoothctl power on
sudo .venv-hud/bin/python -m hud_emulator ble --output /tmp/vietnav-hud.jsonl
```

Dùng `sudo` trên máy thử nếu chính sách system D-Bus không cho user đăng ký
service/advertisement; không đổi cấu hình Bluetooth của xe để chạy lệnh này.
`--adapter hci1` chọn adapter khác. Dừng bằng Ctrl+C để gỡ đăng ký. Nếu lỗi
adapter tắt/không có GATT manager, xử lý thiết lập BlueZ trước khi thử app.

1. Để xe đỗ, mở mục kết nối HUD bên trong VietMap Live trên iPhone, tìm
   `VIETNAV HUD`. Ghi phiên bản app/iOS, loại adapter và trạng thái CarPlay.
2. Quan sát có `advertising`, `ble_write`, `hud_info_request`, `ble_notify`
   trong log không. `ble_notify` chỉ cho biết đã phát D-Bus signal để BlueZ gửi;
   chưa chứng minh app đã nhận/chấp nhận.
3. Nếu app báo kết nối thành công, bắt đầu một tuyến và đổi các chặng trên
   app để so tên đường/khoảng cách. Thành công của bước này là log có
   `type: navigation` cập nhật khớp với tuyến, không chỉ heartbeat.
4. Nếu app báo HUD không hợp lệ hoặc chỉ hỏi thông tin rồi ngắt, lưu nguyên
   log và nội dung lỗi. Đây là kết quả để xác định bước chưa tương thích.
5. Ngắt/nối lại một lần và kiểm không ghép lẫn fragment cũ.

Mặc định trả:

```
MODEL:VIETNAV,HW:0,FW:0,PROTOCOL:2.0
```

Đây là danh tính thử nghiệm và giá trị protocol thử; chưa được app xác nhận.
Không có serial hay token thiết bị chính hãng. `--hud-info '...'` thay payload
để nghiên cứu profile; `--no-info-reply` chỉ quảng bá/ghi nhận, không trả thông
tin. UID runtime của app chưa biết; reply thử dùng UID 16 byte zero, và luôn có
checksum mặc định đúng. Không suy từ việc SDK có nhận `MODEL` rằng toàn app đã
cấp quyền.

Log chứa tên đường và thông tin tuyến; kiểm tra nội dung trước khi chia sẻ.

## Giải mã offline

File binary gồm các byte ghi từ điện thoại vào characteristic:

```sh
python3 -m hud_emulator decode /path/to/phone-writes.bin
```

Hoặc mỗi dòng stdin là một fragment hex, không có tiền tố timestamp:

```sh
printf '%s\n' a55a37c50000000602ff3aa1 | python3 -m hud_emulator decode
```

Đây là **vector tự tạo**, không phải capture thật. Kết quả: heartbeat legacy,
`speed_raw=255`. `uid_valid=null` nghĩa là không kiểm UID runtime; decoder
khung mới vẫn kiểm checksum mặc định. CRC/checksum hỏng hoặc frame cuối thiếu
byte làm CLI trả lỗi. Một stream chỉ tương ứng một kết nối điện thoại.

## Phần còn lại để lên HUD Mazda

- Xác nhận app chấp nhận bắt tay và gửi navigation/camera trên iPhone thật.
- Lập bảng `direction_raw → Mazda glyph` từ các chặng rẽ trái/phải, thẳng,
  vòng xuyến, quay đầu và kết thúc; đối chiếu đơn vị tốc độ/khoảng cách.
- Ưu tiên native CMU dựa trên lớp HCI của TPMS; bổ sung peripheral/ATT server
  và kiểm tổ hợp kết nối mà controller hỗ trợ. Xem [thiết kế native](hud-native-cmu.md).
- Viết adapter vào VBS đã dùng bởi đường AA/CarPlay: fold tiếng Việt, mã hoá
  khoảng cách, đồng bộ mũi tên/tên đường; xoá guidance khi hết hạn/ngắt BLE;
  phân xử với nguồn AA/CarPlay để không có hai nguồn cùng ghi HUD.
- Kiểm trên xe rồi mới bổ sung tùy chọn nguồn vào menu/kit USB. Không mặc định
  HUD zin có thể vẽ mọi biểu tượng camera/biển báo như HUD rời.

## Kiểm thử trên máy

```sh
python3 tests/test_hud_protocol.py
.venv-hud/bin/python tests/test_hud_bluez.py
```

Test thứ hai cần `dbus-daemon`, dùng bus riêng và không cần thay cấu hình
Bluetooth thật. Các fixture đều tự tạo. Chưa có kiểm thử với app iOS,
Bluetooth radio hoặc VBS trên xe cho nhánh giả lập.

API BlueZ tham khảo:
[GATT](https://bluez.readthedocs.io/en/latest/gatt-api/) và
[advertising](https://bluez.readthedocs.io/en/latest/advertising-api/).
