# Vì sao CarPlay đưa Google Maps lên HUD mà không đưa VietMap

Ngày: 22-10-2026. Bối cảnh: chủ xe đã cài `VIETNAV-HUD-0.9.1-USB` (gồm cả
`libpatch-blmjcicarplay.so` lẫn `libpatch-blmjciaapa.so`) và test trên xe:
**dẫn đường Google Maps qua CarPlay lên HUD bình thường, VietMap thì không**.

Tài liệu này ghi những gì đã kiểm được **mà không cần ra xe**, và chốt lại
thứ bắt buộc phải có log trên xe mới trả lời được.

## 1. VietMap iOS thật sự có chạy một phiên dẫn đường CarPlay

Không phải trường hợp "app chỉ vẽ map, không khai dẫn đường". Kiểm trong
`Payload/Runner.app`:

- `Info.plist` khai cả `CPTemplateApplicationSceneSessionRoleApplication` lẫn
  `CPTemplateApplicationDashboardSceneSessionRoleApplication`
  (`VIETMAPCarPlayDashboardManager2`).
- Binary ký kèm entitlement **`com.apple.developer.carplay-maps`** — entitlement
  bắt buộc của app dẫn đường CarPlay.

Trong `Frameworks/vietmap_live_navigation_plugin.framework`, các selector có mặt:

| Selector | Có |
| --- | --- |
| `startNavigationSessionForTrip:` | có |
| `setUpcomingManeuvers:` | có |
| `updateTravelEstimates:forManeuver:` | có |
| `updateTravelEstimates:forTrip:` | có |
| `setInstructionVariants:` | có |
| `setSymbolImage:` / `setSymbolSet:` | có |
| `setInitialTravelEstimates:` | có |
| `cancelTrip` | có |

Tức là app **có** tạo `CPNavigationSession`, **có** đẩy danh sách maneuver,
**có** cập nhật khoảng cách/ETA. Đây không phải lỗ hổng phía app theo kiểu
"thiếu API".

## 2. Thứ app KHÔNG đặt — và vì sao điều đó chưa kết luận được gì

Không thấy selector nào trong nhóm mô tả **kiểu** rẽ có cấu trúc:

| Selector | Có |
| --- | --- |
| `setManeuverType:` | **không** |
| `setJunctionType:` | **không** |
| `setJunctionExitAngle:` / `setJunctionElementAngles:` | **không** |

Thoạt nhìn đây là lời giải: cầu CarPlay đọc `maneuverType` tại offset `0x124`
của khung iAP2 `0x8059`, và `nav.cpp` lọc bỏ `maneuverType == 0` qua
`is_context_type()` — maneuver không có kiểu sẽ bị **bỏ hết**, HUD trống đúng
như triệu chứng.

Lưu ý một nhầm lẫn đã được chủ xe đính chính: iPhone 8 Plus / iOS 16.7.15 là
**máy nghiên cứu BLE**, KHÔNG phải máy dùng để test trên xe.

**Máy đã test trên xe: iPhone Air, iOS 27.0.1.** Điều này chốt hẳn phía iOS:
`CPManeuver.maneuverType` có từ iOS 17.4, nên trên máy này API **chắc chắn có
sẵn**. Không còn đường thoát "hệ điều hành quá cũ" — app không điền trường đó là
vì bản thân app không bao giờ gọi `setManeuverType:`, đúng như kiểm trong
`vietmap_live_navigation_plugin.framework`.

Vậy lời giải cho đúng triệu chứng là: Google Maps đặt `maneuverType` → xe nhận
enum thật → có mũi tên; VietMap không đặt → xe nhận `0` = NoTurn →
`is_context_type()` nuốt sạch → HUD trống.

Phần còn lại **vẫn chưa đo**: chưa có log trên xe nên chưa biết chắc khung
`0x8059` có tới `jciCARPLAY` khi chạy VietMap hay không.

### Bản vá theo giả thuyết này

[`patches/carplay-hud/`](../patches/carplay-hud/README.md) thêm nhánh dự phòng
vào `nav.cpp`: khi `maneuverType == 0` ở `idx >= 1` thì suy hướng rẽ từ chuỗi
lệnh (`maneuverDesc`) thay vì vứt đi. Chỉ `type == 0` được xét lại nên app có
điền trường này giữ nguyên hành vi cũ. Đã biên dịch sạch bằng `zig c++` và có
43 kiểm tra host (gồm nhóm câu **phải bị từ chối** như "Đi tiếp trên Quốc Lộ 13",
để không dán mũi tên sai suốt cả chặng).

## 2b. Cập nhật 25-10: hai điều chỉnh sau đợt probe iPhone jailbreak

Đợt probe 4 phiên (xem `docs/iphone-probe-results.vi.md` §7–19) điều chỉnh
giả thuyết trên ở hai điểm, không bác nó:

1. **Điều kiện tiên quyết mới — tuyến phải bắt đầu từ MÀN HÌNH XE.** Hook
   toàn bộ plugin cho thấy: tuyến bắt đầu trên phone tạo 0 phiên CarPlay
   dẫn đường (0 instance `CPNavigationSession`/`CPManeuver`); chỉ khi tìm
   điểm và bấm bắt đầu ngay trên màn hình CarPlay thì
   `startNavigationSessionForTrip:` → `setInstructionVariants:` (1200+ lần)
   → `updateTravelEstimates:forManeuver:` (~1 Hz) mới chạy đầy đủ. Lần test
   trên xe trước đó có thể dừng ngay từ bước này — không có khung nào cho
   bridge đọc, bất kể maneuverType.
2. **App CÓ đặt maneuverType lúc chạy** — qua KVC
   `setValue:forKey:@"maneuverType"` (selector không được compile vào binary
   nên quét tĩnh không thấy, xem probe-results §14). Giá trị đó có tới khung
   `0x8059` hay không là điều bản debug trả lời trực tiếp bằng dòng
   `nav PICK`; bản vá fallback chỉ áp dụng khi giá trị trên khung thật sự
   là 0, nên đúng trong mọi trường hợp.

Lưu ý đóng gói (phát hiện khi quét token bảng từ: `bung binh`, `hoi lech`,
`tiep tuc di thang`): bản `out/carplay-arm/release` (build zig 23-10)
**KHÔNG chứa bản vá** (0/7 token), còn `out/carplay-arm/debug` là bản vá cũ
thiếu cặp từ `hoi lech` / `tiep tuc di thang`. Kit 0.9.2 phải đóng từ
`out/carplay-arm-m3/{debug,release}` — bản m3 mới đủ bảng từ cuối cùng.

## 3. Thứ bắt buộc phải có log trên xe

Câu hỏi duy nhất còn lại là: **với VietMap, khung `0x8059`/`0x8058` có tới
`jciCARPLAY` không, và nếu có thì `maneuverType` (@`0x124`) và `maneuverDesc`
(@`0x24`) mang giá trị gì?**

- Không có khung nào → iOS không phát luồng iAP2 cho VietMap; mọi sửa phía xe
  đều vô ích.
- Có khung nhưng `maneuverType == 0` kèm `desc` có chữ → **sửa được phía ta**:
  thêm nhánh dự phòng trong `nav.cpp` suy hướng rẽ từ chuỗi `desc` tiếng Việt
  ("Rẽ phải", "Rẽ trái", "Đi thẳng", "Quay đầu"…) khi `maneuverType` không dùng
  được, thay vì để `is_context_type()` nuốt mất.
- Có khung và `maneuverType` hợp lệ → lỗi nằm ở khâu chọn/đẩy, cũng sửa được.

Trở ngại cũ: bản phát hành chỉ log lỗi (`log.h`: release ⇒ ERROR, `LOGD`/`LOGV`
bị bỏ). Muốn có dòng `nav PICK …` phải **build bản debug** của
`libpatch-blmjcicarplay.so`, mà build cần toolchain ARM `m3-toolchain` — binary
ELF Linux, không chạy được trên máy Windows này (không WSL, không container).

**Trở ngại đó đã gỡ.** `patches/carplay-hud/build_arm_zig.py` cross-build cùng
bộ nguồn bằng zig và tự kiểm lại ELF so với chính file .so đang chạy trên xe:
soft-float base AAPCS (không `TAG_ABI_VFP_ARGS`), chỉ cần `GLIBC_2.4` (CMU có
2.11), xuất đúng 5 symbol interpose. Cả hai bản đã có:

- `out/carplay-arm/release/libpatch-blmjcicarplay.so` — 197.336 B
- `out/carplay-arm/debug/libpatch-blmjcicarplay.so` — 3.365.148 B, có sẵn chuỗi
  `nav PICK` và `nav TEXT-FALLBACK`

Việc còn lại là **cài bản debug lên xe rồi chạy `vietnav-collect.sh`**. Lưu ý
chưa có .so nào trong hai bản này từng chạy trên xe — đúng ABI không có nghĩa là
đúng hành vi.

## 4. Đường rẻ hơn nên thử trước: Android Auto

Bản Android của VietMap publish dữ liệu dẫn đường **có cấu trúc đầy đủ**, kiểm
từ APK đã giải mã:

- Manifest khai `androidx.car.app.CarAppService` + category
  `androidx.car.app.category.NAVIGATION` + `NAVIGATION_TEMPLATES`.
- `vn/vietmap/.../android_auto2/car_components/CarNavigationManager.java` dựng
  `Trip` rồi gọi `updateTrip`.
- `Ra/h.java` dựng `Trip` gồm `Destination`, `TravelEstimate`, `Step`,
  **`Maneuver`**, và cả `Lane`/`LaneDirection`.
- `Sa/a.java` ánh xạ modifier sang đúng hằng `Maneuver.TYPE_*` chuẩn:
  `slight left`→5, `slight right`→6, `left`→7, `right`→8, `sharp left`→9,
  `sharp right`→10, `uturn`→39, `straight`→…

Nhánh AA của mod (`libpatch-blmjciaapa.so`) ăn `NavigationState` qua GAL 1.6 —
mà host AA sinh ra **trực tiếp từ chính `Trip` đó**. Đường này ngắn và được đặc
tả rõ hơn CarPlay nhiều, nên khả năng chạy được cao. `libpatch.conf` đã bật sẵn
`use_protocol_v1_6 = true` và `hud = true`.

**Việc nên làm trước tiên: cắm một máy Android chạy VietMap qua Android Auto và
nhìn HUD.** Không tốn dòng code nào.

## 5. Quan hệ với nhánh BLE giả HUD

Nhánh BLE trong repo này **không phụ thuộc Apple hay Google**: app nói chuyện
thẳng với thiết bị HUD giả qua BLE, và đã lấy được tên đường, khoảng cách, thời
gian và ảnh mũi tên (xem [vmlhud-nav-payloads.md §10](vmlhud-nav-payloads.md)).
Nếu cả CarPlay lẫn Android Auto đều không ra mũi tên VietMap thì đây là đường
duy nhất còn lại — và phần đổi dữ liệu sang khung HUD đã viết xong
(`bridge/vmlhud_hud_out.py`).
