# Giao thức VIETMAP LIVE ↔ HUD rời

Phân tích lại ngày 21-10-2026 từ IPA người dùng cung cấp: `vn.vietmap.live`
3.4.3, build 179094172. Framework `vietmap_hud_sdk` có `cryptid=0`, SHA-256
`47b26de05293e451dad65a834a751a5c2898dd432cd1dc34614d832e7ca5a68f`.
Các địa chỉ dưới đây là virtual address arm64 trong framework này, imagebase 0.
Đây là phân tích tĩnh; chưa có capture BLE từ iPhone/HUD thật.

**Đính chính:** bản tài liệu trước ghi trailer là MD5 16 byte và kết luận quá
chắc về việc thiết bị giả lập bị máy chủ từ chối. Trailer thực tế là 8 byte;
phần cấp quyền phía Dart vẫn phải kiểm tra bằng kết nối thật. Bản thử và cách
thu thập bằng chứng: [hud-emulator.md](hud-emulator.md).

## Dữ liệu cần lấy

`DJBTManager` gửi hướng rẽ, khoảng cách tới điểm rẽ, đường tiếp theo, đường hiện
tại, thời gian/quãng đường còn lại và tốc độ qua
`sendNavigationInformationWithDirection:andDistance:andNextRoad:andCurrentRoad:andRemainTime:andRemainDistance:andCurrentSpeed:`.
Đường này độc lập với metadata CarPlay, vì vậy đáng thử cho trường hợp VML
không gửi iAP2 guidance. Cảnh báo camera/giới hạn tốc độ có lệnh riêng.

## BLE

App có bộ lọc tên chứa `HUD` (phân biệt hoa/thường), loại tên chứa `TPMS`.
Nhánh `DJBTManager` dùng service `FFF0`; `FFF1` notify, `FFF2` ghi chính,
`FFF3` ghi ở một nhánh, `FFF4` notify cho nhánh TPMS. UUID đầy đủ:
`0000FFFx-0000-1000-8000-00805f9b34fb`. Không mặc định các họ HUD/H50 đều dùng
cùng nhánh giao thức. Bản thử chỉ triển khai nhánh này.

`getHUDInfo` (`0x4398`) gửi CMD `0x0E`, payload `00` bằng định dạng mới.
Heartbeat (`0x43F4`) chọn **một** nhánh theo việc `hudInfo` đã có hay chưa:

- `hudInfo == nil`: định dạng legacy, CMD `02`, payload `FF`.
- Có `hudInfo`: định dạng mới, CMD `02`, tốc độ big-endian 2 byte hoặc `FFFF`.

## Định dạng mới (`sendParamData:andCMD:`, `0xB044`)

Tất cả số nhiều byte trong khung dùng **big-endian**; magic là chuỗi byte.

| Offset | Dài | Nội dung |
|---|---|---|
| 0 | 4 | `A5 5A 37 C3` |
| 4 | 4 | `len(payload) + 13` |
| 8 | 4 | Unix time, giây |
| 12 | 1 | CMD |
| 13 | n | payload |
| 13+n | 4 | tổng 4 word big-endian của `MD5(header + payload + UIDTokenOne)`, modulo 2³² |
| 17+n | 4 | cùng phép tính với `default_uid` |

Tổng khung **n+21 byte**, bằng trường length cộng 8. `default_uid` là hằng
16 byte trong SDK (`__const`, `0x302F8`). `UIDTokenOne` là trạng thái runtime;
`+[DJBTManager startWithUID:]` (`0x4228`) copy 16 byte vào nó. Không suy ra UID
runtime từ số serial. Bộ giải mã kiểm checksum mặc định và chỉ báo
`uid_valid=true` khi được cung cấp UID runtime đúng; mặc định là `null`.

## Định dạng legacy 1.6 (`0x11064`)

`A5 5A 37 C5` + `BE32(n+5)` + CMD + payload + CRC 2 byte.
CRC-16/MODBUS (init `FFFF`, polynomial reflected `A001`) tính trên
`length + CMD + payload`, **ghi high byte trước**. Tổng **n+11 byte**.

Ba layout payload đã được mô tả thêm trong [vmlhud-nav-payloads.md](vmlhud-nav-payloads.md): fixed 175 byte, variable1 và variable2/Simplify CMD `40`. Các layout này dùng lớp khung/trailer ở trên; không dùng MD5 nguyên 16 byte.

## Dẫn đường (CMD `00`, `insideSendNavigationInformation…`, `0x460C`)

Legacy có payload đúng **175 byte**:

| Offset payload | Dài | Nội dung |
|---|---|---|
| 0 | 1 | mã hướng rẽ; `FF` = kết thúc dẫn đường (`0x4B4C`) |
| 1 | 4 | khoảng cách tới điểm rẽ |
| 5 | 80 | đường tiếp theo, UTF-8 cắt/đệm NUL |
| 85 | 80 | đường hiện tại, UTF-8 cắt/đệm NUL |
| 165 | 2 | giờ còn lại |
| 167 | 1 | phút trong giờ |
| 168 | 1 | giây trong phút |
| 169 | 4 | khoảng cách còn lại |
| 173 | 2 | tốc độ |

Định dạng mới: hướng 1 byte + khoảng cách 4 byte + độ dài đường tiếp theo 1
byte + UTF-8 + độ dài đường hiện tại 1 byte + UTF-8 + đuôi 10 byte tương tự
legacy. Dài **17 + số byte UTF-8 hai tên đường**.

Một chi tiết trong bản SDK này: nhánh mới (`0x4A6C–0x4A70`) ghi byte thấp của
**tổng số phút** vào trường thời gian thứ ba, thay vì biến giây mà nhánh legacy
sử dụng (`0x495C–0x4960`). Bản giải mã giữ `remaining_time_third_raw`, không tự
gọi đó là giây. Cần đối chiếu với thời gian trên app khi capture thật.

Khoảng cách được diễn giải là mét theo API; đơn vị tốc độ và bảng mã hướng rẽ
chưa được xác nhận bằng chạy thật. Giữ mã thô, chưa ánh xạ sang glyph Mazda.
Legacy có thể cắt giữa ký tự UTF-8, decoder biểu diễn bằng U+FFFD.

## Camera (CMD `01`, `0x5A90`)

Payload 4 byte: loại camera 1 byte + khoảng cách BE16 + giới hạn tốc độ 1 byte.
Không tự suy đoán ý nghĩa từng loại camera hoặc đơn vị tốc độ.

## Phản hồi HUDInfo và cấp quyền

`dataParsing` nhận khung mới, rẽ nhánh CMD `0E` ở `0xD49C → 0xDC98`, chuyển
payload UTF-8 cho `HUDInfoWithDataString:` (`0x103EC`). Hàm này bỏ dấu cách,
tách bằng dấu phẩy rồi dấu hai chấm, đọc `MODEL`, `HW`, `FW`, `PROTOCOL`, `OBDV`,
`SID`. Nhánh native kiểm `MODEL` khác rỗng rồi lưu `hudInfo` và gọi delegate
(`0xE088`); **điều đó không chứng minh Dart sẽ cho gửi dẫn đường**.

Trong `App.framework` vẫn có `HudFeatureGrantEvent`, `verifyHUD`,
`HUDResponse.onInvalidHUDConnected`, `HUDResponse.receiceSerial`,
`/v20/hud/UpdatePermission`, `HUD not start auto connect when unauth` và
`vietmap_lock_hud_device_address`. Đây là bằng chứng tồn tại luồng kiểm tra,
chưa xác định được chính xác điều kiện chặn cho profile BLE này.

Delegate Swift `DJBTSDKHandler…didGet…DJHUDInfo` (`0x20CCC`) chuyển các trường
model, hardware/firmware version, protocol và OBD sang JSON rồi phát callback
`receiveHUDInfo` (`0x2134C`). Không thấy chuyển `SID` trong callback này. Vì vậy
không thể lấy riêng chuỗi `receiceSerial` để kết luận nhánh `FFF0` này bắt buộc
serial được máy chủ công nhận; cần truy vết Dart/capture thực tế tiếp.

Bản giả lập dùng `MODEL:VIETNAV,HW:0,FW:0,PROTOCOL:2.0`, không có SID mặc định.
Giá trị protocol là cấu hình thử, chưa được xác nhận là profile app chấp nhận.
Nếu app chỉ gửi yêu cầu thông tin rồi từ chối/ngắt, phải ghi nhận kết quả đó;
không suy rằng nhận được heartbeat đồng nghĩa đã nhận được dẫn đường.
