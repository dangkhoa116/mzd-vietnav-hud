# Cầu nối VIETMAP LIVE → HUD zin qua đường HUD BLE

Mục tiêu: đưa **dẫn đường VIETMAP LIVE (có tên đường)** lên HUD zin của Mazda,
giống sản phẩm "VML HUD" đang bán ngoài thị trường (ví dụ Bamboo Auto). Đây là
đường đang nghiên cứu để lấy đầy đủ tên đường từ VietMap. Với VML 3.4.3 đã soi,
CarPlay chưa gửi metadata cần thiết và đường Android Auto đã quan sát thiếu
tên đường. Xem [vietmap-hud-gap.md](vietmap-hud-gap.md).

Phạm vi: tương thích thiết bị của **chính khách** — xe của họ, điện thoại của họ,
app VIETMAP LIVE họ tự cài. Bước cấp quyền còn phải kiểm chứng; không coi việc
thay serial hay mua HUD thật là cách giải quyết đã được xác nhận.

## Kiến trúc

```
VIETMAP LIVE (điện thoại khách, BLE central)
   │  quét thiết bị có tên chứa "HUD", kết nối
   │  service FFF0:  FFF2 ghi  /  FFF1 notify
   ▼
vmlhud-bridge   (daemon trên CMU, BLE peripheral)
   │  1. quảng bá tên "...HUD..."; expose FFF0/FFF1/FFF2
   │  2. trả getHUDInfo (CMD 0x0E), đáp heartbeat (0x02)
   │  3. nhận sendNavigationInformation (0x00) → giải mã khung A5 5A 37 C3
   │  4. decode payload → hướng rẽ, tên đường, khoảng cách, tốc độ, biển báo
   ▼
com.jci.vbs.navi   (MQ sẵn có — cầu CarPlay đang bơm vào đây)
   ▼
HUD zin (Active Driving Display)
```

Repo có mã tham khảo cho **đầu ra** `com.jci.vbs.navi` → HUD và bản vá tên đường
VN dài trong `patches/oem-aa-mod/`. Cần tích hợp đầu vào BLE với đường này và
kiểm thực tế, chưa thể coi đầu ra của nhánh VietMap BLE là hoàn tất.

## Thành phần trong repo

| File | Vai trò | Trạng thái |
| --- | --- | --- |
| `bridge/vmlhud_frame.py` | Khung mới: hai checksum 4 byte; khung cũ: CRC16 Modbus | Đối chiếu codec Python/native và vector SDK; chưa có capture từ điện thoại thật |
| `bridge/vmlhud_nav.py` | Ba layout dẫn đường, kể cả ảnh mũi tên variable2 | Giải mã tĩnh; cần xác nhận bảng direction và đơn vị tốc độ ngoài thực tế |
| `emu/esp32-hud-emu/` | BLE peripheral FFF0 và FFFF trên ESP32-C3 | Build Arduino ESP32 3.3.2 + NimBLE 2.3.7; chưa thử board/điện thoại thật |
| `native/` | ATT server chạy trong tiến trình `bds`, chia sẻ UART với TPMS | Đã kiểm bằng transport giả, ARM và guest CMU; chưa xác minh advertising trên xe |
| `native/usb/` | Kit thử native, thu log, phục hồi wrapper TPMS | Xem [hud-native-cmu.md](hud-native-cmu.md) và [kết quả emu](../native/emu/README.md) |

Native hiện là công cụ thử kết nối; chưa nối dữ liệu nhận được vào
`com.jci.vbs.navi`. Phần đầu ra có mã tham khảo trong repo nhưng vẫn phải tích
hợp và kiểm tra trước khi gọi đây là sản phẩm dẫn đường lên HUD Mazda.

## Bước tiếp theo: thử BLE bằng ESP32-C3

Nạp [firmware và hướng dẫn](../emu/esp32-hud-emu/README.vi.md) vào board C3
đang có. C3 hỗ trợ BLE peripheral, **không hỗ trợ Bluetooth Classic/SPP**.
Phép thử này tách việc app chấp nhận profile HUD khỏi khả năng Bluetooth CMU.

1. Giữ cấu hình thử mặc định `VMHUD-EMU`, model H50, protocol 2.2.2S.
2. Thu Serial 115200 từ trước khi mở trang HUD trong VIETMAP LIVE.
3. Quét, kết nối và bắt đầu một tuyến có tên đường/hướng rẽ.
4. Giữ log từ kết nối, subscribe, yêu cầu HUDInfo đến các lần ghi FFF2/FFF3
   hoặc 9ABC. Công cụ `decode_log.py` xuất JSON để đối chiếu tên đường,
   khoảng cách và `direction` với app.

Nhận được CMD 0x00/0x40 hợp lệ có tên đường chứng minh app đã gửi dữ liệu cho
**profile và phiên thử đó**. Không nhận được dẫn đường chưa xác định nguyên
nhân: có thể do bộ lọc quét, họ thiết bị, subscribe, phiên dẫn đường, protocol,
hoặc cấp quyền. Cần giữ thông báo của app cùng log để phân biệt.

## Quyền sử dụng và HUD thật

IPA có dấu vết `verifyHUD`, `onInvalidHUDConnected` và
`/v20/hud/UpdatePermission`; xem [phân tích SDK](vietmap-hud-sdk.md). Dấu vết
này chưa chứng minh `SID` của mọi họ thiết bị được gửi tới endpoint đó, cũng
chưa chứng minh mọi phiên dẫn đường đều bị chặn bởi kiểm tra serial. HCI snoop
chỉ thấy giao thức Bluetooth, không cho biết trực tiếp nội dung yêu cầu HTTPS.

Nếu cần đối chiếu, HUD thật của chủ xe là nguồn capture tốt. Trên Android có
thể lấy Bluetooth HCI snoop/bug report và giải mã ATT trong Wireshark. Khung có
thể bị chia qua nhiều write; phải gom luồng trước khi parse. Việc này bổ sung
cho thử C3, không phải điều kiện bắt buộc để bắt đầu.

Cầu nối qua HUD thật là một phương án nghiên cứu khác, **chưa được triển
khai**. CMU không tự đọc được phiên BLE giữa hai thiết bị khác; nghe thụ động
cũng không bảo đảm giải mã được khi mã hoá liên kết bật. Relay chủ động cần
thiết kế, hai phiên kết nối và kiểm tra quyền riêng; mua HUD không tự giải
quyết các phần đó.

## Khả năng Bluetooth của CMU: phân biệt bằng chứng tĩnh và chạy thật

Đã đọc rootfs 74.00.333A; các kết quả dưới đây không thay thế kiểm tra controller
trên xe:

| Hạng mục | Quan sát | Điều còn chưa biết |
| --- | --- | --- |
| BlueZ | 4.98; thiếu API D-Bus `GattManager1`/`LEAdvertisingManager1` của BlueZ 5 | Không thể dùng nguyên backend GATT BlueZ 5 trên CMU |
| Kernel | 3.0.35, i.MX6; có module Bluetooth/RFCOMM/shared transport TI | Module hiện diện không chứng minh adapter BlueZ đang hoạt động |
| Cấu hình ATT | `AttributeServer = false` trong `main.conf` | Tắt server thử nghiệm của BlueZ; không kết luận toàn bộ đường Bluetooth của Mazda chỉ có Classic |
| Lệnh LE | Có chuỗi lệnh quảng bá trong binary, `hcitool` có lệnh LE | Đây là code hỗ trợ lệnh; chưa chứng minh controller/firmware chấp nhận advertising |
| SPP | Có `rfcomm.ko`, `sdptool`, `rfcomm`, plugin Serial | Cần adapter dùng được, đăng ký SDP và phiên VietMap Android thực sự chọn SPP |
| Đường Mazda | `bds` dùng UART `/dev/ttymxc3`, nạp `/jci/bds/TI128x_INIT.bts` | Không được giả định BlueZ cũng sở hữu radio hoặc có thể dùng đồng thời |

`/jci/bds/TI128x_INIT.bts` (TI P6_15.113) là đường firmware mà `bds` nạp.
`/lib/firmware/TIInit_10.6.15.bts` (P6_15.42) chỉ là file khác hiện diện trong
rootfs. Hai file gốc đã soi chưa có BLE add-on như bản TPMS vá. TPMS cung cấp
bằng chứng sử dụng BLE **central** sau khi vá, không chứng minh peripheral hay
HFP/A2DP cùng advertising hoạt động.

- **Android:** SDK có nhánh SPP UUID 1101, nhưng chưa đủ để chọn SPP cho app,
  model và controller thực tế. Chỉ viết server sau khi xác định app dùng nhánh
  đó và ai sở hữu radio. Chưa thể khẳng định chạy ngay trên stack zin.
- **iPhone:** app thường không dùng được generic SPP cho phụ kiện chưa có hỗ
  trợ MFi phù hợp. BLE vẫn là hướng thử; C3 hiện là cách kiểm profile độc lập.
  Native ATT/raw-HCI qua `bds` đã có bản thử trong repo, chưa xác minh trên xe.
  Chưa có căn cứ kết luận bắt buộc phải mua HUD thật.
- **Chung sống với nhạc/cuộc gọi:** phải thử trên xe. Emu CMU kiểm được ABI,
  installer, log và rollback nhưng không tái hiện radio TI hay HFP/A2DP/LE
  đồng thời.

## Tích hợp trên CMU sau khi có capture

1. Đối chiếu khung C3/capture với codec, chốt mã hướng rẽ và profile app dùng.
2. Dùng kit native để truy vấn controller, thử advertising/ATT có log và
   rollback; giữ TPMS nguyên bản làm đường phục hồi.
3. Khi transport thật đã nhận được dẫn đường, chuyển struct trung lập sang
   thông điệp `com.jci.vbs.navi`, kiểm tên đường, khoảng cách và hướng rẽ.
4. Kiểm cuộc gọi/nhạc, kết nối lại, ngừng dẫn đường và phục hồi trên xe trước
   khi tích hợp vào installer ổn định.

## Ranh giới

Tài liệu và mã ở đây **không** mô tả cách qua mặt bước xác thực của máy chủ
Vietmap. Dùng thiết bị/tài khoản của chủ xe; cấu hình emulator là danh tính
thử nghiệm. Nếu app từ chối, giữ log để tìm nguyên nhân và chọn phương án
được hỗ trợ, không coi việc sửa serial là giải pháp đã được kiểm chứng.
