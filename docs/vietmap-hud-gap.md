# Khoản trống: VIETMAP LIVE không hiện tên đường trên HUD

Ngày phân tích: 13-10-2026 · VIETMAP LIVE 3.4.3 (Android APK + iOS IPA, bản công khai
CH Play / App Store) · oem-aa-mod tại thời điểm release 0.10.0.

Hiện tượng cộng đồng (thread otofun "Hack và kích hoạt các tính năng ẩn cho xe Mazda"):
VIETMAP LIVE (VML) chạy Android Auto qua mod oem-aa-mod cho **mũi tên + khoảng cách
trên HUD nhưng thiếu tên đường**, trong khi Google Maps hiển thị đủ.

## Chuỗi dữ liệu (mỗi mắt xích đã được xác minh bằng phân tích tĩnh)

```
VML Dart (Flutter, Pigeon — model CarManeuver_Args)
   │   KHÔNG có field "roadName" trong model. Các field: id, instruction,
   │   distance, remainingDistance, remainingDuration, destination, type,
   │   modifier, degrees, imageId, lanesImageId, nextStepImageId,
   │   nextStepInstruction, backgroundColorHex
   │ MethodChannel: dev.flutter.pigeon...GeneratedCarApi.setCarManeuver
   ▼
CarNavigationManager (Android native, plugin android_auto2)
   │ Trip builder (R8-obfuscated, đã đối chiếu descriptor):
   │   - cần 3 field kiểu Long non-null, thiếu 1 → Trip = null → KHÔNG updateTrip
   │   - Trip = 1 Destination + 1 Step:
   │       Step.setRoad( <field String> ?? "--" )
   │       Step.setManeuver( (type, modifier, degrees) — phong cách Mapbox )
   │     KHÔNG setLane / KHÔNG setCue
   ▼
androidx.car.app NavigationManager.updateTrip(Trip)   ← đã xác nhận ở mức code
   ▼
GAL 1.6 NavigationState (0x8006): steps[0] { maneuver=1, road=2, lanes=3, cue=4 }
   ▼
oem-aa-mod: aap_service quảng bá GAL 1.6, relay frame thô qua AF_UNIX
   ▼
blmjciaapa/hud_nav16 decode steps[0]; road.name (field 2); cue (field 4) bị bỏ qua
   ▼
fold tiếng Việt (translit.h — bảng U+1E00..U+1EFF hoàn chỉnh, đã verify trên xe)
   ▼
vbs_tx / svcnavi_tx → HUD: mũi tên + khoảng cách + tên đường
```

## Ba giả thuyết, xếp theo khả năng

**H1 (cao nhất) — VML không gửi tên đường lên GAL, chỉ gửi "--"**: model Pigeon
của VML không có trường tên đường; UX màn AA của họ vẽ mũi tên bằng ảnh
(`imageId`/`nextStepImageId`), chuỗi text chỉ có `instruction` (câu dẫn đường đầy
đủ) và `nextStepInstruction`. Trip builder đặt `"<field> ?? "--"` vào
`Step.setRoad` — nếu field rỗng trên wire thì HUD nhận `"--"`. Đồng chứng: trên
cùng một xe, Google Maps hiển thị tên đường còn VML thì không.

**H2 (thấp) — firmware EU blanking dòng street**: tài liệu oem-aa-mod
(docs/installation.md, mục `force_street_name`) ghi nhận trên firmware EU, dịch
vụ nav OEM tự xoá dòng tên đường; phải bật `force_street_name=true` (chỉ tác dụng
với `hud_transport=svcnavi` — cần thẻ SD nav). Xe VN thường không có thẻ SD →
chạy transport `vbs` → cơ chế blanking không áp dụng. Bác bỏ một phần vì cùng xe
vẫn thấy street của GMaps.

**H3 (đã sửa bằng patch trong repo này) — cắt cụt trước khi fold**: road bị cắt
ở 63 byte ngay khi decode, TRƯỚC khi fold dấu. Tên Việt nhiều dấu vượt 63 byte
khi nguyên dấu nhưng thu gọn về 1–2 byte/chữ sau fold → bị cụt oan. Chỉ gây hụt
cuối chuỗi, không mất trắng.

## Chẩn đoán trên xe — 10 phút

Build debug của oem-aa-mod (xem docs/build.md của dự án đó). Mỗi frame 0x8006
được log một dòng:

```
nav16 STATE: maneuver=8(TURN_NORMAL_RIGHT) glyph=3 road="..." steps=1 lanes=...
```

Chạy VIETMAP LIVE dẫn đường thật và đọc log:

| Log hiển thị | Kết luận |
|---|---|
| `road="--"` hoặc rỗng | H1 chốt — VML không gửi tên đường (xem hướng xử lý) |
| `road="Rẽ trái vào đường..."` (câu instruction) | dữ liệu CÓ, vấn đề nằm ở render/transport → kiểm tra `force_street_name`, transport config |
| `road` có tên đường ngắn hợp lệ | chỉ còn lỗi fold/truncate → bản vá trong repo này |

## Hướng xử lý theo kết quả

1. **Nếu H1 chốt** (khả năng cao): không sửa được từ phía mod (cue cũng rỗng vì
   VML không setCue). Đường đúng:
   - Gửi phản hồi cho Vietmap: thêm trường tên đường vào model Pigeon và đặt vào
     `Step.setRoad` — dữ liệu đã có sẵn trong app (instruction/nextStepInstruction).
   - Chia sẻ chẩn đoán này cho cộng đồng otofun (tác giả mod đoán đúng hướng
     nhưng chưa có artifact kiểm chứng).
   - Đường **iPhone/CarPlay** cũng vướng, vì lý do khác: xem mục "CarPlay" bên dưới.
2. **Nếu dữ liệu có mặt**: thử `force_street_name=true` (xe có thẻ SD, transport
   svcnavi).
3. **Bản vá road-budget** trong repo này áp dụng độc lập với kết quả trên.

## CarPlay: VML không cho iOS gửi dẫn đường sang xe (xác nhận 21-10-2026)

Trên xe (CX-5 74.00.324A, VIETNAV 0.9.1, CarPlay bridge chạy): **Google Maps lên
HUD, VIETMAP LIVE không lên**. Vậy chuỗi phía xe (bridge, `NaviSupported`, vbs)
chạy đúng; thiếu là ở phía app.

Với CarPlay, xe không đọc màn hình của app: iOS phát luồng route guidance iAP2
(cái mà mazda-carplay-hud đọc) chỉ khi app đồng ý chia sẻ dữ liệu dẫn đường với
xe, qua `CPMapTemplateDelegate.mapTemplateShouldProvideNavigationMetadata(_:)`
(iOS 17.4). Không cài đặt hàm này thì mặc định là không chia sẻ.

Phân tích tĩnh IPA 3.4.3 (`vietmap_live_navigation_plugin.framework`, không mã
hoá FairPlay; đọc danh sách method của từng lớp ObjC):

- Lớp `VIETMAPCarPlayManager2` cài đặt 10 hàm của `CPMapTemplateDelegate`
  (`startedTrip`, `displayStyleForManeuver`, `shouldShowNotificationForManeuver`,
  …) nhưng **không có `mapTemplateShouldProvideNavigationMetadata:`**. Không
  framework nào khác trong app cài đặt nó. Tên selector có trong binary chỉ vì
  nằm trong danh sách của protocol.
- Không dùng API dữ liệu dẫn đường cho xe của iOS 17.4: không `addManeuvers`,
  `maneuverType`, `junctionType`, `CPLaneGuidance`, `CPRouteInformation`,
  `currentRoadNameVariants`.
- Chỉ dùng API CarPlay cổ điển (`CPManeuver` với `instructionVariants`,
  `symbolImage`, `junctionImage`, `CPTravelEstimates`) để vẽ trên màn CarPlay.
- Model `FLTCarPlayCarManeuver_Args` giống bản Android: không có trường tên đường.

**Kết luận:** phía xe không sửa được, vì iOS không gửi gì để bridge đọc. Cần
Vietmap: cài đặt `mapTemplateShouldProvideNavigationMetadata` trả về `true`, và
để có mũi tên/tên đường đúng thì điền metadata iOS 17.4 cho `CPManeuver`
(`maneuverType`, `junctionType`, `roadFollowingManeuverVariants`, …). Trong lúc
chờ, trên iPhone dùng Google Maps hoặc Apple Maps để có HUD.

## Ghi chú thêm

- Maneuver của VML mã hoá theo (type, modifier, degrees) kiểu Mapbox → ánh xạ
  sang androidx Maneuver; nếu thiếu loại nào thì mất mũi tên (không phải triệu
  chứng hiện tại).
- Tài liệu mazda-carplay-hud cho rằng stock CMU "đã render AA nav trên HUD",
  trong khi tài liệu oem-aa-mod nói stock chỉ quảng bá GAL 1.5 (không có dữ liệu
  nav). Cần xác nhận trên xe khi test.
