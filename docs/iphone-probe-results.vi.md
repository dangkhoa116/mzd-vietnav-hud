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
