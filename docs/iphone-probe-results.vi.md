# Kết quả đợt probe iPhone jailbreak ngày 2026-10-23 (dở: máy chết giữa chừng)

Báo cáo theo mục 6 của `docs/iphone-probe.vi.md`. Phiên bị cắt ngang vì
iPhone hết RAM (~70 MB free) kill frida-server + app liên tục, sau đó không
còn đường điều khiển nào từ PC (không SSH, USB cắm vào đầu "Carplay-Receiver"
không phải PC). Cần **khởi động lại điện thoại** rồi chạy tiếp phần "còn lại"
ở cuối file.

## 1. Model máy + phiên bản iOS (bắt buộc)

- **iPhone 8 Plus (iPhone10,5), iOS 16.7.15** (Darwin 22.6.0), jailbreak
  rootless `/var/jb`, RAM 3 GB (free ~70 MB lúc probe), pin 100%.
- Lưu ý của tài liệu đã đúng một nửa: trên iOS 16.7.15 này lớp `CPManeuver`
  **CÓ** selector `setManeuverType:` (hook được, không báo "không có").
  Tức API có mặt từ trước 17.4 (ít nhất là selector; có thể là SPI). Nhưng
  máy không có phiên CarPlay nên không quan sát được việc gọi.

## 2. Kết nối CarPlay

- Điện thoại đang cắm USB vào một phụ kiện tên **"Carplay-Receiver"** (widget
  pin hiển thị, đang sạc). Hostname của chính điện thoại cũng là
  "Carplay-Receiver" (đã đặt tên trùng).
- **KHÔNG có phiên CarPlay nào thiết lập**: trong cả SpringBoard lẫn process
  VIETMAP LIVE đều 0 instance của `CPTemplateApplicationScene`,
  `CPInterfaceController`, `CPMapTemplate`, `CPNavigationSession`,
  `CPManeuver`. Bài B (hook setter khi chạy) **chưa thực hiện được**.

## 3. Kiến trúc cầu nối CarPlay trong app (bổ sung cho phần 3 của tài liệu)

Runtime xác nhận cấu trúc plugin `vietmap_live_navigation_plugin`:

- `VIETMAPCarPlayManager2` **chỉ là scene delegate** (các method
  `templateApplicationScene:didConnectInterfaceController:toWindow:`,
  `mapTemplate:displayStyleForManeuver:` v.v.) — **không có**
  `handleMethodCall:result:`. Bài A cách 2 (hook handleMethodCall) **sẽ
  không thấy dữ liệu maneuver CarPlay**.
- Dart→native đi qua **PIGEON API** `CarPlayMethodChannel2` với method kiểu
  `- previewRoutesRoutesResponse:routeIndex:error:`,
  `- showRoutesRoutesResponse:routeIndex:error:`,
  `- sendVMLCommonDataData:error:`, camera/style/layer... Khi có phiên
  CarPlay thật, **hook các method pigeon này + setter CP\*** là đúng chỗ.
- Plugin chính `SwiftVIETMAPLiveNavigationPlugin` chỉ có
  `+registerWithRegistrar:` (tức nó đăng ký pigeon host, không nhận channel).

## 4. Dữ liệu runtime đã bắt được (tuyến thật đang chạy)

Tuyến "Nhà" còn sống từ hôm trước (banner "150m Quốc Lộ 13", ETA 1h34p,
còn 50.9 km; máy đứng yên, vị trí không tiến). Hook
`handleMethodCall:result:` trên 12 plugin bắt được:

- `vietmap_hud_sdk.sendCustomNavigationInformationWithDirection` lặp y hệt:
  `{"direction":-2,"imageBase64":"iVBORw0KGgo..."}` — PNG 60×60, **không
  có text**. Đây là khung thời tiết, khớp khung BLE `FE` + UTF-8 đã biết.
  **Đáng chú ý: direction từ Dart là -2, cast int8 = 0xFE** — byte direction
  trên dây BLE lấy thẳng từ Dart. Chưa xác định maneuver thật có đổi giá trị
  này không (cần xe chạy / giả lập GPS).
- `vietmap_hud_sdk.sendCameraInformation`: 2 slot
  `[{cameraDistance:100000,x:0,y:0,cameraType:1,cameraSpeed:0},
    {cameraDistance:100,x:0,y:0,cameraType:0,cameraSpeed:50}]` —
  `cameraSpeed` = 50 chính là **giới hạn tốc độ 50 km/h** đang hiển thị.
  Khớp phân tích CMD 0x01 = 2 ô camera; ô thứ hai mang speed limit.
- Location engine: `getCurrentLocation` (accuracy 5, distanceFilter 0),
  `getLastKnownLocation`, `cancelGetCurrentLocation`.
- Không thấy bất kỳ đẩy maneuver nào sang plugin CarPlay hay Live Activities
  khi không có đầu CarPlay.

## 5. Chuỗi lệnh nguyên văn (Q3) — CHƯA LẤY ĐƯỢC

Đã dựng xong hạ tầng bắt plaintext API tuyến (hook BoringSSL
`SSL_write`/`SSL_read` — cả hai symbol đều export toàn cục trong process,
script `work/tools/vm_all_hooks.js` ngoài repo) để lấy `bannerInstructions`
khi lập tuyến lại, nhưng frida-server chết trước khi kịp lập tuyến mới.
Không kịp xác minh chuỗi có phải bộ từ vựng UTF-16LE đóng gói sẵn không.

## 6. Còn lại khi có lại điện thoại

1. Khởi động lại iPhone (substrate sẽ nạp lại ios-mcp vào SpringBoard →
   port 8090). Nếu 8090 không lên sau reboot: dùng frida dlopen
   `/var/jb/Library/MobileSubstrate/DynamicLibraries/ios-mcp.dylib` (đã
   chứng minh hoạt động).
2. frida-server phải bật tay (as mobile, từ
   `/var/mobile/Library/Caches/frida-extract/.../frida-server -l 0.0.0.0:27043`);
   plist `re.frida.server.plist` có trong LaunchDaemons nhưng không tự sống
   lại trên cổng 27042/27043 sau crash.
3. Mở khóa từ xa (passcode do chủ xe cung cấp): frida vào SpringBoard,
   `SBLockScreenManager.sharedInstance()` + `attemptUnlockWithPasscode:`
   **bắt buộc dispatch qua `_dispatch_main_q`** (gọi thẳng = crash
   SpringBoard; NSTask trên iOS 16 cũng crash SB — dùng posix_spawn).
4. Chạy `vm_all_hooks.js` (spawn mode `frida -f vn.vietmap.live`) rồi lập
   tuyến mới trong UI → bắt JSON tuyến; cho xe chạy / giả lập GPS để xem
   maneuver thật đổi `direction` không.
5. Nếu cắm vào đầu CarPlay thật (xe): thêm hook pigeon
   `CarPlayMethodChannel2` + quan sát `setManeuverType:` (selector TỒN TẠI
   trên 16.7).

Log thô: `work/tools/vm_hooks_run1.log`, `vm_all_out.log` (ngoài repo).

---

# Đợt probe 2 ngày 2026-10-25 (CarPlay thật đang nối — kết luận dứt điểm Q1/Q2/Q4)

Sau reboot sạch, ios-mcp và frida tự sống lại. Điện thoại mở khóa, còn nối
CarPlay với đầu xe **cả buổi** (scene không bao giờ rơi). App VIETMAP LIVE
build **179094172**, PID 16339 sống nguyên phiên (hết hiện tượng jetsam).

## 7. Phiên CarPlay trong app (Q1/Q2/Q4 — kết luận dứt điểm)

Trạng thái nhắc lại suốt phiên (ObjC.chooseSync tại nhiều thời điểm):

- `CPTemplateApplicationScene=1 CPInterfaceController=1 CPWindow=1
  CPMapTemplate=1` — app **đang là ứng dụng active trên màn hình xe**
  (rootTemplate = topTemplate = CPMapTemplate của VietMap; 4 CPListTemplate
  tồn tại nhưng chưa present).
- Đã lập **3 tuyến thật** (Nhà 31 m — hoàn thành tức thì; Chợ Bến Thành;
  Sân bay Tân Sơn Nhất, banner chỉ dẫn hiện rõ "1,2 km • Rẽ trái vào…",
  "800 m • Rẽ trái vào…" + dòng phụ "Sau đó rẽ phải"), chạy tổng ~20 phút
  rồi kết thúc có xác nhận dialog.

Kết quả hook (script `vm_final_hooks.js` ngoài repo: 12 channel + toàn bộ
setter CPManeuver/CPNavigationSession/CPMapTemplate + KVC lọc
maneuver/junction/instruction + AVSpeechUtterance.setSpeechString: + 12
method gửi của DJBTManager):

- **`CPNavigationSession` KHÔNG BAO GIỜ được tạo** (0 instance khi rảnh,
  khi 3 tuyến đang chạy, và sau khi kết thúc). `CPMapTemplate.navigationSession`
  = nil.
- **`CPManeuver` 0 instance tuyệt đối** → không setter nào được gọi:
  `setInstructionVariants:`, `setManeuverType:`, `setSymbolSet:`… im lặng
  hoàn toàn; KVC `setValue:forKey:` với key maneuver/junction/instruction
  cũng không có.
- Pigeon CarPlay **không hoạt động**: không một method-call nào từ
  `CarPlayMethodChannel2`/`SwiftVIETMAPLiveNavigationPlugin` trong suốt
  phiên (kể cả khi start/end tuyến).

**Kết luận:** điều khiển từ màn hình phone, VietMap LIVE **không dùng
CPNavigationSession/CPManeuver chút nào** — maneuver chỉ tồn tại trong cây
widget Flutter của phone; màn hình CarPlay là bản vẽ map riêng. Muốn thấy
CPManeuver chỉ còn khả năng lập tuyến **từ UI trên màn hình xe** (phải bấm
trên đầu xe — ngoài tầm điều khiển từ xa). Q4 (nhịp setUpcomingManeuvers)
theo đó không có để đo.

## 8. Pipeline BLE HUD (DJBTManager) — liệt kê đủ API, xác nhận bị chặn

`$methods` của DJBTManager cho đủ 12 selector gửi (frida 17 không còn
`$ownMethods`, phải dùng `$methods` + `cls['- selector']`):

- `sendNavigationInformationWithDirection:andDistance:andNextRoad:
  andCurrentRoad:andRemainTime:andRemainDistance:andCurrentSpeed:`
- `insideSendNavigationInformation…`, `sendCustomNavigationInformation…
  andDirectionImage:…`, `insedeSendCustomNavigationInformation…` (typo
  "insede" có thật trong binary), `SimplifyNavigationInformationData…`
- `sendEndNavigationInformation`, `sendNavigationHold`, `sendHeartBeat`
- `sendCameraInformationWithType:andDistance:andLimitSpeed:`,
  `sendMultipleCameraInformation…Array`, `sendCustomeCameraInformation…`
- `sendNavigationRoutePlanningWithImage:andSelectedIndex:andTitles:
  andTimes:andDistances:andTrafficLights:andSepends:`

Hook đủ 12 selector trong lúc tuyến đang chạy + lúc kết thúc tuyến:
**KHÔNG một lần nào được gọi** (kể cả `sendEndNavigationInformation`).
Channel `vietmap_hud_sdk` cũng chỉ có vòng lặp `startScanDevice/
stopScanDevice` mỗi 10 s. Tức **toàn bộ pipeline phát BLE bị chặn cho tới
khi có thiết bị HUD thật nối BLE** — hôm trước bắt được khung camera/thời
tiết là do trạng thái app khác (đang di chuyển). Muốn bắt payload nav thật:
bật emu ESP32 cho app nối rồi chạy xe.

## 9. Bắt plaintext API tuyến — đã thử, không đi qua libboringssl

`SSL_write/SSL_read` toàn cục thực chất thuộc **libboringssl.dylib của
Apple** (findExportByName từng module; Runner export đúng 1 symbol).
Hook đọc được plaintext nhưng toàn handshake/quản lý của hệ thống; JSON
tuyến của VietMap chạy qua **BoringSSL static liên kết trong Dart**
(symbol ẩn) — không hook được bằng export. Muốn lấy JSON phải pattern-scan
binary hoặc mitm proxy (cài CA — máy đã jailbreak nên khả thi nhưng heavy).

## 10. Chuỗi nguyên văn (Q3) — hiện trạng

Nguồn duy nhất đạt được lúc đứng yên là banner trên màn hình phone (AI-OCR,
dấu chưa khẳng định 100%): mẫu câu xác nhận là **"Rẽ trái vào <tên đường>"**
kèm khoảng cách "1,2 km"/"800 m" và dòng phụ **"Sau đó rẽ phải"**. Bộ chuỗi
đủ 10–20 mẫu nhiều loại maneuver phải chờ: (a) chạy xe với emu ESP32 nối
BLE rồi đọc payload DJBT (tên đường UTF-8 nguyên bản từng khung), hoặc
(b) đọc JSON tuyến (§9), hoặc (c) bấm lập tuyến từ màn hình CarPlay trên xe.

## 11. Ghi chú kỹ thuật frida 17 (để lần sau không mất giờ)

- `Memory.readByteArray` đã bị bỏ → dùng `ptr.readByteArray(n)`.
- `Module.findExportByName(moduleName, sym)` tĩnh tra không ra dù export có
  thật → dùng `module.findExportByName(sym)` trên object module.
- Python API: `console.log` của script KHÔNG tới on_message — chèn shim
  `console.log = function(){ send(...) }` (đã vá trong
  `work/tools/vm_hook_runner.py`).
- `$ownMethods` không còn — dùng `$methods` (mảng) hoặc `cls['- sel']`.

Log thô đợt này: `work/tools/vm_run6.log`, `vm_final.log` (ngoài repo).

## 12. Bổ sung quan trọng 25-10 tối: đường CPNavigationSession CÓ trong binary

Sửa lại phần suy đoán ở §7 (đã tránh nói sai trong doc nhưng cần chốt bằng
bằng chứng tĩnh): kiểm tra chuỗi selector trong
`vietmap_live_navigation_plugin.framework` bằng Python (lưu ý: `grep -r`
trên Git Bash **bỏ sót file binary** — phải quét byte bằng Python):

- **CÓ**: `setInstructionVariants:`, `setUpcomingManeuvers:`,
  `startNavigationSessionForTrip:`, `setSymbolImage:`, `setSymbolSet:`,
  `updateTravelEstimates:forManeuver:`, `CPManeuverDisplayStyle`,
  `_objc_msgSend$startNavigationSessionForTrip:`,
  `_objc_msgSend$upcomingManeuvers:`
- **KHÔNG có**: `setManeuverType:` (app build bằng SDK cũ — API 17.4+
  không được biên dịch vào; **iOS 17 cũng không gọi được**),
  `presentNavigationSession`.

Tức app **có sẵn toàn bộ đường CarPlay navigation chuẩn** (tạo session từ
`startNavigationSessionForTrip:` → dựng CPManeuver bằng
`setInstructionVariants:`/`setSymbolImage:` → `setUpcomingManeuvers:` →
`updateTravelEstimates:`), nhưng đường đó **không chạy khi lập tuyến từ
phone** — khả năng lớn nó chỉ kích hoạt từ handler
`mapTemplate:startedTrip:using:` khi bấm bắt đầu tuyến **trên màn hình
xe**. Ngoài ra app còn có model maneuver riêng cho màn CarPlay:
`FLTCarPlayCarManeuver_Args` (pigeon) với các trường
`instruction, modifier, degrees, distance, imageId, lanesImageId,
nextStepInstruction, nextStepImageId, remainingDistance,
remainingDuration, destination, backgroundColorHex`.

**Hệ quả thực tế:**
1. Không cần (và không có cách) giả lập iOS 17 — mọi selector then chốt
   đều iOS 12+, chạy được trên 16.7; riêng maneuverType không nằm trong
   app nên phiên bản iOS không đổi gì.
2. Cách kích hoạt đường này: **bấm lập tuyến từ màn hình CarPlay trên
   đầu xe** trong lúc hooks đang chạy — sẽ bắt được Q1 (setter+giá trị),
   Q3 nguyên văn (setInstructionVariants), Q4 (nhịp setUpcomingManeuvers).

---

# Đợt probe 3 đêm 25-10 (lập tuyến TỪ MÀN HÌNH XE — câu trả lời Q1/Q2/Q4)

Phiên quan trọng nhất: user bấm tìm đích + bắt đầu tuyến **trên màn hình
CarPlay của đầu xe** (iPhone 8 Plus iOS 16.7.15, app 3.4.3 build 179094172,
CarPlay wireless còn nối cả đêm).

## 13. Đường CarPlay maneuver HOÀN TOÀN SỐNG khi lập tuyến từ màn xe

Hook thụ động (v3 — chỉ log tên selector, zero ObjC call trong onEnter)
bắt được trên phiên app ổn định:

- **`CPManeuver setInstructionVariants:`** được gọi liên tục (hơn 1.200
  lần trong phiên) — chuỗi chỉ dẫn có mặt.
- **`CPManeuver setManeuverType:`** CŨNG ĐƯỢC GỌI (Q2 trả lời: CÓ) — qua
  KVC (`setValue:forKey:@"maneuverType"`, key string có trong binary) nên
  không thấy selector tĩnh trong plugin; hệ thống 16.7 có sẵn setter.
- `CPManeuver setSymbolImage:`, **`CPNavigationSession
  updateTravelEstimates:forManeuver:` ~1 Hz** (Q4: nhịp cập nhật ước tính mỗi giây cho từng maneuver).
- Backtrace crash (thời điểm hook cũ còn lỗi) cho thấy chuỗi dựng maneuver
  của app: `FLTCarPlayCarManeuver_Args.toCPManeuver(cache:)` →
  `CPManeuver init` → KVC `setInitialDistance:` (category private
  CPAccNavUpdate của Apple) — xác nhận app build CPManeuver từ model
  pigeon.

Tức: **mọi câu Q1/Q2/Q4 đều có dữ liệu thật; đường chuẩn CarPlay chỉ
kích hoạt khi tuyến bắt đầu từ UI trên đầu xe** (khớp dự đoán §12).

## 14. Chuỗi nguyên văn (Q3) — banner ghép với hook

Ghép thời điểm `setInstructionVariants` với screenshot banner phone
(cùng nội dung maneuver):

- "350 m — Rẽ trái vào Quốc Lộ 13" / dòng phụ "sau đó Đi thẳng"
- "900 m — Rẽ trái vào Quốc Lộ 13" / "sau đó Đi thẳng"
- (tuyến sân bay, chiều phone-driven) "1,2 km — Rẽ trái vào …" /
  "800 m — Rẽ trái vào …"

Đủ để khẳng định cấu trúc câu: **"<khoảng cách> — <Động từ maneuver>
vào <tên đường>"** + dòng phụ **"sau đó <maneuver kế tiếp>"**. Bộ chuỗi
đa dạng còn thiếu vì phiên bị cắt (xem §15).

## 15. Xe ảo (giả lập GPS) — hạ tầng sẵn, chờ phiên ổn định

User đứng yên ở nhà; đã viết `work/tools/vm_drive5.js` (hook
`-[CLLocation coordinate]`, đọc/ghi struct kết quả) + `vm_gps_drive.js`
(thay mảng vị trí trong delegate). Đêm đó frida-server kiệt sức
(TransportError timeout khi tạo session mới sau ~10 lần attach/detach)
nên chưa chạy được chuyến ảo; mọi script + supervisor `vm_supervisor.py`
( tự gắn lại hooks khi app bị kill) đã sẵn sàng cho phiên sau.

## 16. Bài học crash-loop (quan trọng cho phiên sau)

Hook cũ gây crash app 2 lần, 2 cơ chế khác nhau:

1. describe() ObjC tùy tiện trên tham số KVC/DJBT → `object_getClass`
   segfault tại địa chỉ 0xff (giá trị direction 255 bị coi là con trỏ).
2. safeStr gọi `ObjC.api.class_getName(isa)` → chết trong
   `objc_class::demangledName` (Swift class demangle trên isa không hợp
   lệ) — SIGSEGV địa chỉ rác ~0x21a2….

Nguyên tắc v3 (đã chứng minh ổn định): **onEnter/onLeave KHÔNG gọi bất
kỳ API ObjC nào** — chỉ log tên selector + con trỏ thô. Lấy giá trị
chuỗi bằng cách ghép screenshot banner với thời điểm hook. Phiên không
hook sống khỏe >4 phút trong khi mọi bản hook "mô tả giá trị" chết
trong 9–21 giây.

Log thô: `work/tools/vm_v3.log` (1.204 lần setInstructionVariants),
`vm_cp2.log`, `vm_car.log` (ngoài repo).

---

# Đợt probe 4 (25-10, ~03:00): XE ẢO GPS — hoàn thành Q3 với 88 chuỗi nguyên văn

## 17. Giả lập chuyển động — thành công toàn trình

Kỹ thuật (script `work/tools/vm_drive6.js` ngoài repo): hook delegate
**`VMLocationEngine.LocationEngine`** (delegate thật của engine vị trí
VietMap — tìm bằng cách quét mọi class implement
`locationManager:didUpdateLocations:`, rút kinh nghiệm đêm trước quét dừng
ở match đầu bỏ sót). Mỗi lần hệ thống đẩy vị trí, thay mảng CLLocation
bằng object tạo tại tọa độ giả đi thẳng về đích (Chợ Bến Thành) 28 m/lần.
App nhận là GPS thật — dialog "Thông tin GPS" báo **"GPS Mạnh"**.
Chi tiết ABI đã giải: `coordinate()` trả [lat, lon] (mảng); selector 2
tham số thì mảng vị trí nằm ở `args[3]` (args[2] là CLLocationManager).

Xe ảo chạy từ nhà (Bình Dương) 48 km về Quận 1 trong ~30 phút, đi qua
đầy đủ loại đường; app tự re-route khi đi thẳng gãy tuyến (ra cả chuỗi
"lệch tuyến"/"tính lại").

## 18. Kết luận kiến trúc chuỗi chỉ dẫn CarPlay (Q3 — câu trả lời cuối)

Hook đọc giá trị (`vm_strings.js`, ngoài repo — hook HẸP chỉ
setInstructionVariants:/setUpcomingManeuvers:, đọc NSArray/NSString của
chính app truyền vào: an toàn, chạy ổn >30 phút):

- **`instructionVariants` = TÊN ĐƯỜNG/ĐIỂM MỐC, KHÔNG có động từ**.
  Câu đầy đủ ("Rẽ trái vào Quốc Lộ 13") chỉ tồn tại trên UI phone; sang
  CarPlay app gửi symbol (setSymbolImage:/setSymbolSet:) + tên đường.
  Đây là mô hình GIỐNG HỆT protocol BLE HUD (direction byte + tên đường)
  — xác nhận lần nữa hướng thiết kế bridge của ta đúng bản chất app.
- Phone UI khi có CarPlay: chỉ hiện "bảng 9 ô" điều khiển map trên xe
  (user xác nhận: banner chỉ vẽ trên màn CarPlay).

Bộ 88 chuỗi nguyên văn (file đầy đủ `work/tools/out/q3_strings_final.txt`
ngoài repo; đếm = số lần setInstructionVariants nhận giá trị đó):

- Đường lớn: `Mỹ Phước Tân Vạn` (260), `Đại Lộ Bình Dương` (53),
  `Cách Mạng Tháng 8` (38), `Hà Huy Giáp`, `Phan Văn Trị`, `Lê Văn Duyệt`,
  `Nguyễn Thị Minh Khai`, `Võ Thị Sáu`, `Lê Duẩn`, `Tôn Đức Thắng`,
  `Đào Duy Anh`, `Nơ Trang Long`, `Phan Đăng Lưu`, `Vườn Lài`, `Huỳnh Đình Hai`…
- Đường số/hẻm: `Thạnh Xuân 38`, `Thạnh Lộc 29`, `Nhị Bình 8`,
  `An Sơn 1`, `Hẻm 198 Thạnh Xuân 52` (hẻm + số nhà!), `Đường Số 1`.
- Công nghiệp Bình Dương: `Đường NA3/NA4/NA7/N7/DA4/NK9/KH1/DL14/NL12/DJ5`,
  `NJ 12`, `ĐX 78`.
- Điểm mốc: `Cầu`, `Cầu An Phú Đông`, `Bùng Binh` (vòng xoay).
- Đặc biệt: **`Đường Không Tên`** (46 lần — đường không tên là chuỗi
  THẬT, không phải rỗng), **chuỗi rỗng ""** (10 lần — HUD phải xử lý),
  và `null` (1.207 lần — update không kèm text).
- Chuỗi hệ thống: `Đi theo đường dẫn trên bản đồ`, `Bạn đang đi lệch
  khỏi tuyến đường`, `Đang tính toán tuyến đường...`.
- Đích đến gần nhất: `Lê Duẩn || Tôn Đức Thắng` (setUpcomingManeuvers
  n=2 — luôn kèm 2 maneuver kế tiếp).

Tất cả giữ nguyên dấu tiếng Việt; encode UTF-8 qua NSArray nguyên bản.

## 19. Trạng thái cuối

Đáp ứng đủ mục 6 của docs/iphone-probe.vi.md: model+iOS ✓, thông tin
CarPlay ✓ (scene + banner vẽ trên màn xe), setter list ✓ (Q1/Q2),
nhịp session ✓ (Q4: updateTravelEstimates ~1 Hz), chuỗi nguyên văn ✓
(88 >> 10–20 yêu cầu). Còn thiếu duy nhất: JSON route API (Dart BoringSSL
static, đã ghi rõ §9) và đối chứng direction khi maneuver thật đổi
(cần xe chạy thật với emu BLE).
