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
   - Lưu ý: đường **iPhone/CarPlay** (mazda-carplay-hud) không phụ thuộc Trip của
     app Android — iAP2 stream do iOS sinh từ CPNavigationSession, và VML iOS có
     đầy đủ CPManeuver/instruction → không vướng H1.
2. **Nếu dữ liệu có mặt**: thử `force_street_name=true` (xe có thẻ SD, transport
   svcnavi).
3. **Bản vá road-budget** trong repo này áp dụng độc lập với kết quả trên.

## Ghi chú thêm

- Maneuver của VML mã hoá theo (type, modifier, degrees) kiểu Mapbox → ánh xạ
  sang androidx Maneuver; nếu thiếu loại nào thì mất mũi tên (không phải triệu
  chứng hiện tại).
- Tài liệu mazda-carplay-hud cho rằng stock CMU "đã render AA nav trên HUD",
  trong khi tài liệu oem-aa-mod nói stock chỉ quảng bá GAL 1.5 (không có dữ liệu
  nav). Cần xác nhận trên xe khi test.
