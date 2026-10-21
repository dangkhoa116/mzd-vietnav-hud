# Giao thức VIETMAP LIVE ↔ HUD rời (phân tích tĩnh, phục vụ tương thích)

Ngày phân tích: 21-10-2026 · VIETMAP LIVE 3.4.3 (IPA công khai, `vn.vietmap.live`
3.4.3 build 179094172) · framework `vietmap_hud_sdk.framework` (không mã hoá
FairPlay).

Mục đích: xem app gửi dẫn đường cho **HUD rời chính hãng Vietmap** (H1AS, H1X,
H50…) như thế nào, để tính một cầu nối đưa dữ liệu đó lên HUD zin của xe. Không
chạy app, không sửa đổi, không phân phát lại binary. Chỉ đọc danh sách method
ObjC và disassembly.

## Vì sao quan tâm đường này

So với CarPlay (iOS không gửi gì nếu app không bật metadata) và Android Auto
(gửi được nhưng tên đường là `"--"`), **đường HUD rời là nơi app gửi dữ liệu dẫn
đường đầy đủ nhất, có cả tên đường**. Hàm chính:

```
sendNavigationInformationWithDirection:andDistance:andNextRoad:andCurrentRoad:
    andRemainTime:andRemainDistance:andCurrentSpeed:
```

→ hướng rẽ, khoảng cách tới điểm rẽ, **tên đường hiện tại**, **tên đường tiếp
theo**, thời gian còn lại, quãng còn lại, tốc độ. Có thêm `sendCameraInformation…`
(camera/giới hạn tốc độ), `sendRoadImage…`, `sendText…`.

## Lớp và kết nối

- **Lớp quản lý:** `DJBTManager` (Objective-C) dưới một lớp Swift
  `DJBTSDKHandler` nối ra Flutter plugin `SwiftVietmapHudSdkPlugin`. Phía Dart
  gọi xuống qua FlutterMethodChannel.
- **Transport:** BLE (CoreBluetooth). App quét thiết bị **có tên chứa chuỗi
  `HUD`** (so sánh chữ hoa), lọc bỏ thiết bị tên chứa `TPMS`.
- **Dịch vụ / characteristic:** service `FFF0`; trong đó
  - `FFF1` — notify (nhận từ HUD), app bật `setNotifyValue:YES`
  - `FFF2` — characteristic hiện hành để ghi (đường nhận/ghi chính)
  - `FFF3` — characteristic ghi (một nhánh)
  - `FFF4` — notify (nhánh TPMS)
  (UUID BLE đầy đủ dạng `0000FFFx-0000-1000-8000-00805f9b34fb`.)
- **Sau khi kết nối:** app gọi `getHUDInfo`, rồi đặt một timer gửi **nhịp tim**
  (`sendHeartBeat`) định kỳ để giữ kết nối.

## Khung gói tin (hàm `sendParamData:andCMD:`)

Mỗi khung dữ liệu (little-endian trừ chỗ ghi rõ):

| offset | dài | nội dung |
|---|---|---|
| 0 | 4 | magic cố định `A5 5A 37 C3` (ghi vào bộ đệm dạng `0xC337_5AA5`) |
| 4 | 4 | độ dài phần sau = `len(payload) + 13`, big-endian |
| 8 | 4 | dấu thời gian: `getNowTime` = `timeIntervalSince1970` (giây), big-endian |
| 12 | 1 | mã lệnh (CMD) |
| 13 | n | payload |
| 13+n | 16 | MD5 của (magic..payload), ghi 16 byte nhị phân |

- `getHUDInfo` → CMD `0x0E`, payload 1 byte.
- `sendHeartBeat` → gửi hai khung, một theo nhánh protocol 1.6
  (`sendParamDataProtocol_1_6WithData:andCMD:`) CMD `0x02`, một theo
  `sendParamData:` CMD `0x02`, payload mang tốc độ hiện tại.
- Dẫn đường (`insideSendNavigationInformation…`): có **BA định dạng payload**;
  toàn bộ offset đã được chốt tĩnh ngày 21-10-2026 (disassembly đầy đủ) — xem
  [vmlhud-nav-payloads.md](vmlhud-nav-payloads.md):
  - **fixed 0xAF byte** (khi `hudInfo == nil`), CMD `0x00`, nhánh protocol 1.6;
  - **variable1** (`hudInfo != nil`), CMD `0x00`, `sendParamData:`;
  - **variable2 "Simplify"** (header `00 00 00 01 01`), CMD `0x40`.
  Đáp `getHUDInfo` là chuỗi text `MODEL:..,HW:..,FW:..,PROTOCOL:..,OBDV:.._..,SID:..`;
  MD5 trên khung nhận không dùng để từ chối.
- Khung nhận về (`dataParsing` trên characteristic notify): byte `0x5A` phân
  loại, các trường TPMS/OBD/HUDInfo cắt theo `subdataWithRange:`, và có nhánh
  so MD5 trên dữ liệu nhận.

Các mã lệnh khác đã thấy: cấu hình HUD (đơn vị tốc độ/nhiệt độ/khoảng cách, ngôn
ngữ, múi giờ, độ sáng, chuông), OTA firmware, hình làn đường, điện thoại, camera.

## Rào cản: app yêu cầu HUD được máy chủ Vietmap cấp quyền

Đây là điểm quyết định tính khả thi của một cầu nối **giả lập HUD**.

Trong code Dart của app (`App.framework`) có luồng kiểm tra quyền phía máy chủ:

- trạng thái `HudFeatureGrantState` / `HudFeatureGrantEvent`
  (`startRequest`, `success`, `failured`, `removePermission`);
- lỗi `HUDGrantPermissionFailure.serverError`, `.unexpected`;
- `HUDResponse.onInvalidHUDConnected(address:)`, `verifyHUD`,
  `HUDResponse.receiceSerial(serial:)`;
- endpoint API `/v20/hud/UpdatePermission` (và `/v20/hud/updatefirmware`,
  `/hud/updatefirmware`);
- chuỗi `HUD not start auto connect when unauth`,
  `vietmap_lock_hud_device_address`.

Diễn giải: khi kết nối HUD, app đọc **số serial** của thiết bị, gửi lên máy chủ
Vietmap để xin cấp quyền; HUD không hợp lệ → `onInvalidHUDConnected`, app không
gửi dẫn đường. Vậy một thiết bị **đóng giả HUD** (không có serial được Vietmap
công nhận) nhiều khả năng **bị app từ chối gửi dữ liệu**. Chưa xác nhận trên
thiết bị thật, nhưng bằng chứng tĩnh đủ rõ để coi đây là rào cản thật.

## Hướng đi hợp lệ

1. **Cầu nối từ HUD Vietmap thật.** Mua một HUD rời chính hãng (app cấp quyền
   bình thường), đọc dữ liệu BLE mà app gửi tới HUD đó — dữ liệu của chính người
   dùng, trên thiết bị của chính họ — rồi chuyển sang CMU để bơm lên HUD zin
   (đường `com.jci.vbs.navi` đã có trong repo). Có HUD thật trong vòng nên không
   phải giả mạo thiết bị; và đây là đường **có đủ tên đường**.
2. **Yêu cầu chính thức cho Vietmap:** bật chia sẻ dẫn đường với xe qua CarPlay
   (`mapTemplateShouldProvideNavigationMetadata`) và Android Auto, kèm tên đường.
   Bền nhất, áp dụng cho mọi khách, không cần phần cứng thêm.

Tài liệu này **không** mô tả cách qua mặt bước cấp quyền của app; đó là ngoài
phạm vi dự án.

## Trước mắt cho khách

Trên bản 0.9.1, **Google Maps và Apple Maps đã lên HUD** (xác nhận trên xe
74.00.324A). iPhone dùng VIETMAP LIVE thì chưa lên được, vì các lý do ở
[vietmap-hud-gap.md](vietmap-hud-gap.md).
