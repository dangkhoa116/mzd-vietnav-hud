# Hồ sơ kỹ thuật VIETMAP LIVE 3.4.3 (phân tích tĩnh)

Phân tích tĩnh phục vụ mục đích tương thích (interoperability) với head unit Mazda.
Đối tượng: bản công khai trên CH Play (`vn.vietmap.live` 3.4.3, build 179094172,
arm64) và App Store (id1574847851). Không chạy app, không sửa đổi, không phân
phát lại binary.

## Kiến trúc app

- **Flutter** (Dart AOT `libapp.so` + Flutter engine), map engine **Mapbox** native,
  ONNX runtime cho trợ lý giọng nói, sqlite, Firebase.
- Cầu nối Dart ↔ native: **Flutter Pigeon** (codegen type-safe), namespace
  `dev.flutter.pigeon.vietmap_live_navigation_plugin.*`.

## Android Auto — đã xác nhận đẩy dữ liệu ra cluster

- Manifest: service `VIETMAP Live Android Auto`
  (`vn.vietmap.vietmap_live_navigation_plugin.android_auto2.VIETMAPLiveAndroidAutoService`),
  intent `androidx.car.app.CarAppService`, category
  `androidx.car.app.category.NAVIGATION`, `minCarApiLevel 1`, file
  `car-app-api.level = 7`, quyền `androidx.car.app.NAVIGATION_TEMPLATES` +
  `ACCESS_SURFACE` (tự vẽ bản đồ lên mặt AA).
- Code: có đầy đủ `VIETMAPLiveAndroidAutoSession`, `VIETMAPLiveAndroidAutoMainScreen`,
  `CarNavigationManager`; **`CarNavigationManager` gọi
  `NavigationManager.updateTrip(Trip)`** (đối chiếu descriptor phương thức sau R8).
- Cách dựng Trip: xem [vietmap-hud-gap.md](vietmap-hud-gap.md) — điểm mấu chốt là
  model dữ liệu không có trường tên đường riêng.

## iOS / CarPlay — đã xác nhận tạo phiên dẫn đường

- Info.plist: 2 scene CarPlay — `CPTemplateApplicationSceneSessionRoleApplication`
  (delegate `VIETMAPCarPlayManager2`) và Dashboard
  (`CPSupportsDashboardNavigationScene: true`).
- Binary `vietmap_live_navigation_plugin.framework` (bản phân tích đã được bóc
  lớp mã hoá FairPlay): có `startNavigationSession` (selector dùng thật), `CPMapTemplate`,
  `CPManeuver`, `CPTrip`, `CPNavigationAlert`, `CPInterfaceController`.
- **Sửa (21-10-2026):** trước đây ghi rằng iOS tự phát luồng iAP2 khi app gọi
  `startNavigationSession`. Không đúng: app phải đồng ý qua
  `mapTemplateShouldProvideNavigationMetadata`, và VML 3.4.3 không cài đặt hàm
  này, nên trên xe Google Maps lên HUD còn VML thì không. Chi tiết:
  [vietmap-hud-gap.md](vietmap-hud-gap.md#carplay-vml-không-cho-ios-gửi-dẫn-đường-sang-xe-xác-nhận-21-10-2026).

## Giao thức phụ kiện của nhà sản xuất (tham khảo)

- `vietmap_hud_sdk` (Android + iOS): class gốc `DJBTManager` — giao diện
  `getHUD*/sendHUD*`, `TPMSDetailInfo`, `getTPMSInfo`. Transport: Bluetooth
  classic SPP (UUID `00001101-...`) song song BLE bridge (service
  `0000fff0/0000fff1`, `0000ae00`, `00009abc`). 4 họ firmware lệnh:
  V1.6 / V221 / V222 / V22S (tương ứng các dòng thiết bị HUD rời của nhà phân
  phối). Lệnh gồm: gửi thông tin dẫn đường, độ sáng, chuông, đơn vị tốc độ, múi
  giờ, truy vấn thông tin máy.
- `vietmap_tpms` (iOS): model `TPMSData` (deviceID, pressure, temperature,
  isLowBattery) — app parse cảm biến áp suất lốp BLE.
- `on_bluetooth` / `flutter_blue_plus`: BLE nói chung.

Những thông tin trên cho thấy: HUD rời và cảm biến lốp của cùng hệ sinh thái giao
tiếp qua serial Bluetooth đơn giản — không phải giao thức độc quyền đóng.

Chi tiết giao thức BLE của đường HUD rời (khung gói tin, service/characteristic,
và bằng chứng về luồng cấp quyền chưa xác minh khi giả lập):
[vietmap-hud-sdk.md](vietmap-hud-sdk.md). Bản thử peripheral và hướng dẫn:
[hud-emulator.md](hud-emulator.md).
