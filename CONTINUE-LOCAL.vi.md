# Bàn giao Vietnav để tiếp tục trên máy local

Cập nhật: **22-10-2026, giờ Việt Nam**. Dành cho người dùng hoặc agent tiếp
tục dự án sau phiên cloud này. Các đường dẫn `/workspace/...` bên dưới thuộc
máy cloud cũ; thay bằng thư mục local tương ứng.

## Cập nhật phiên 22-10-2026 (lần 4): ĐÃ CÓ DẪN ĐƯỜNG THẬT TRÊN EMULATOR

Mục tiêu số 1 của bàn giao trước đã xong. App VIETMAP LIVE 3.4.3 trên iPhone
**streaming dẫn đường thật** cho emulator ESP32-C3 qua bốn tuyến. Bằng chứng và
bảng đối chiếu từng byte: [docs/vmlhud-nav-payloads.md §10](docs/vmlhud-nav-payloads.md).
Log tho `out/cycle-trial-3.log`, ban giai ma `out/cycle-trial-3.jsonl`.

Bốn kết quả chốt được:

1. **Layout variable1 (CMD 0x00) đúng nguyên văn** như phân tích tĩnh. Ví dụ
   khung thật khớp màn hình "150m Quốc Lộ 13 · 25p · 8.3km". iOS **không hề**
   gửi CMD 0x40 trong cả phiên.
2. **Byte thời gian thứ ba LÀ GIÂY** — sửa kết luận cũ. Ba tuyến độc lập khớp
   ETA trên màn hình (25m38s/37m52s/22m05s), và builder Android `W7/e` sinh
   giờ/phút/giây từ một tham số tổng giây (`tag 5 = tổng % 60`).
   `bridge/vmlhud_nav.py` đã điền `remain_time_s` cho cả ba layout.
3. **Không lập được bảng direction↔mũi tên**: byte `[0]` bằng `0xFE` trong cả
   1.963 khung, kể cả khi app hiện mũi tên rẽ phải, biểu tượng điểm đến, hay
   không dẫn đường. **Đây là rủi ro lớn nhất còn lại**: nếu không ép được iOS
   sang CMD 0x40 thì HUD Mazda chỉ có chữ, không có mũi tên.
4. **Thoát tuyến = khung nhàn rỗi**, không có lệnh xoá riêng: `distance` quay về
   `0xFFFFFFFF` và toàn bộ đuôi về 0 (trường `next_road` lúc đó mang chuỗi thời
   tiết). Đây chính là tín hiệu "xoá guidance" cho phía CMU.

### Đã truy tiếp trong cùng phiên (disassembly SDK iOS)

- **CMD 0x01 8 byte đã giải mã**: là **hai ô camera**, mỗi ô 4 byte
  `[type, khoảng cách u16be, giới hạn tốc độ]` (`sendMultipleCameraInformation…`
  giới hạn đúng 2 ô). Giá trị thật: ô 0 = type 1, 34464 m, không giới hạn — và
  34464 = 100000 mod 65536, tức lớp trên gửi "100 km = không có camera" rồi bị
  cắt còn 16 bit. `decode_log.py` và sketch C3 đã đọc cả hai ô; số khung chưa
  giải mã trong capture rơi từ 2.833 xuống 18.
- **ĐÃ TÌM RA ĐÒN BẨY ÉP CMD 0x40 — và chính emulator đang tự chặn mình.**
  Đầu `insedeSendCustomNavigation…` (0x4c20–0x4d70) rẽ nhánh **chỉ** theo chuỗi
  `PROTOCOL` mà emulator trả về trong getHUDInfo:
  `protocol < "2.2.2"` **hoặc** `protocol` chứa chữ **"S"** → đi nhánh bỏ ảnh
  (CMD 0x00); ngược lại mới so ảnh với `lastNavigationImageData` và gửi **CMD 0x40**
  khi trùng. Emulator đang trả `PROTOCOL:2.2.2S` → **có "S" → bị ép bỏ ảnh**.
- **Frida xác nhận lớp Dart CÓ gửi ảnh mũi tên**: mỗi giây một **PNG 744 byte**
  qua `sendCustomNavigationInformation…`, và `dir=-2` (=0xFE) là do chính Dart
  chọn. Checksum ảnh **bất biến** qua 8 lần gọi liên tiếp, nên nếu vào được nhánh
  so sánh thì từ khung thứ hai trở đi sẽ trùng và app sẽ gửi CMD 0x40.
  `setLastNavigationImageData:` chưa bao giờ được gọi — đúng như suy luận.
- **0xFF mới là sentinel "hết dẫn đường" của SDK** (`sendEndNavigationInformation`
  gửi direction 0xFF + toàn 0, và SDK so direction với 0xFF để tắt NaviTimer).
  App không hề gọi hàm đó; `0xFE` là giá trị lớp Dart tự chọn.

### ĐÃ LẤY ĐƯỢC MŨI TÊN THẬT (15:25) — đổi `PROTOCOL:2.2.2` là đủ

Gửi `PROTOCOL:2.2.2` qua CLI serial rồi khởi động lại app để nó đọc lại
getHUDInfo. Log: `out/protocol-222-trial.log`.

- App **chuyển hẳn sang CMD `0x40` (variable2)** — trước đó chưa từng thấy khung nào.
- Khung ảnh là **JPEG** (`FF D8 FF E0 … JFIF`), không phải PNG: lớp Dart đưa PNG
  744 byte cho SDK, SDK mã hoá lại thành JPEG trước khi gửi.
- Bắt được ba ảnh: icon nhàn rỗi, icon thời tiết (mây mưa), và **mũi tên RẼ PHẢI**
  (2438 byte) đi kèm `dist=150m`, `next="Quốc Lộ 13"`, `25m27s`, `8253m` — khớp
  đúng màn hình app. Ảnh gửi **một lần mỗi khi đổi**; 165 khung sau dùng
  `image_len=1, flag=1` = "giữ ảnh cũ".
- `decode_nav_variable2` có sẵn **giải mã đúng, không phải sửa codec**.
- Sketch C3 nay đổi mặc định sang `g_protocol = "2.2.2"`. Đánh đổi: bảng PROTOCOL
  của APK Android chọn `W7/e` cho `2.2.2S` và `W7/d` cho `2.2.2`; nhánh Android
  chưa kiểm lại, nhưng nhánh đó vốn không dùng được với C3 (không có Classic).

**Ý nghĩa**: `direction` vẫn luôn `0xFE` và vô nghĩa, nhưng **mũi tên thì lấy
được** — HUD Mazda có thể hiện mũi tên thật, không chỉ chữ. Rủi ro lớn nhất của
phần dẫn đường coi như đã gỡ.

### Việc tiếp theo ngay (thứ tự mới)

1. ~~Đổi PROTOCOL~~ — **ĐÃ CHẠY VÀ THÀNH CÔNG trong phiên này.** Xem mục dưới.
2. **Lấy mẫu khi xe chạy thật**: đứng yên thì `speed` luôn 0 và `current_road`
   luôn rỗng. Mang board + điện thoại lên xe, chạy một tuyến ngắn có rẽ, xem
   `direction` có rời 0xFE không và hai trường kia được điền ra sao.
3. **Nếu `direction` vẫn là 0xFE khi chạy**: chốt rằng HUD chỉ nhận được chữ, rồi
   quyết định — suy mũi tên từ văn bản/khoảng cách phía CMU, hoặc đào lớp Dart
   (Flutter AOT) để tìm chỗ gọi `sendCustomNavigationInformation…`.
4. **CMD 0x09** (5 byte `00`, một lần lúc mở phiên) vẫn chưa rõ; 18 khung lẻ còn
   lại trong capture phần lớn là nhiễu serial lúc bắt tay.
5. Sang giai đoạn CMU: daemon native ATT (`native/`) ăn theo profile đã được app
   chấp nhận (MODEL:H50/PROTOCOL:2.2.2S qua FFF0); rồi nối `com.jci.vbs.navi`.

Lưu ý thiết bị: helper `work/tools/iosmcp.py` nói chuyện thẳng với ios-mcp trên
máy (`http://192.168.68.104:8090/mcp`) và **vẫn chạy được khi connector MCP của
Claude báo 502**. `long_press`/`swipe_screen` nhận `duration` theo **mili giây**
— truyền `2.0` nghĩa là 2 ms và thao tác sẽ không ăn.

## Cập nhật phiên 22-10-2026 (lần 3, tối): APP iOS ĐÃ KẾT NỐI EMULATOR — permission gate TRẢ LỜI: nhánh A

Đọc [docs/hud-dart-layer-analysis.vi.md](docs/hud-dart-layer-analysis.vi.md)
mục "ĐÃ CHỐT BẰNG FRIDA" để có bằng chứng đầy đủ. Tóm tắt trạng thái:

- **Board ESP32-C3 (COM3) đang chạy bản NimBLE 2.5.1 extended** (build tay
  `out/ext251-build`, KHÔNG phải source pin 2.3.7 của build.py — nimconfig
  của thư viện đã bị patch EXT_ADV=1/instances=2; **đã reinstall 2.3.7** sau
  đó nên bản rebuild lại từ source repo sẽ là 2.3.7 default). `CYCLE:1` đang
  bật trong NVS — xoay 8 tên, pause khi có kết nối. Muốn tên cố định:
  `CYCLE:0` rồi `NAME:<ten>` + reset. Capture serial đang chạy nền ghi
  `out/cycle-trial-3.log` — **đang ghi phiên app đã kết nối!**
- **iPhone 8 Plus jailbreak** (192.168.68.104, ios-mcp HTTP
  `http://192.168.68.104:8090/mcp`; helper `work/tools/iosmcp.py` ngoài
  repo, kèm session id trong `iosmcp_session.txt`): VIETMAP LIVE 3.4.3 đã
  đăng nhập, đã bấm Đồng ý fallback OBD → GPS speed, **app đang streaming
  tới board**: heartbeat CMD 0x02, frame thời tiết CMD 0x00 prefix `FE`
  ("31° mây đen u ám"), CMD 0x01 8 byte ~1 Hz, OBD query CMD 0x0D.
- **frida-server mobile** chạy trên phone cổng **27043** (bản extract từ
  deb `re.frida.server` tại `/var/mobile/Library/Caches/frida-extract`,
  chạy bằng `(setsid ./frida-server -l 0.0.0.0:27043 &)` qua run_command;
  server root sẵn có nghe localhost:27042 không dùng được từ PC). PC đã cài
  `frida` 17.24.3 (pip). Hook script `work/tools/vml_hud_hook.js` attach
  theo PID + offset IMP; watcher `work/tools/vml_frida_watch.py` (cần sửa
  attach theo PID lấy từ ios-mcp vì enumerate_processes as mobile rỗng).
  Log `C:\work\mazda\work\frida-hud-watch.log`.
- **Điểm dễ hỏng khi lặp lại trial listing**: danh sách chỉ nhận thiết bị
  **mới** trong cửa sổ quét ~10 giây của màn scan; discover lại cùng MAC
  chỉ REPLACE im lặng. Tên phải chứa "HUD" đúng lúc scan chạy (CYCLE đảm
  bảo 4/8 tên qua cửa). Cách chắc nhất: để CYCLE bật, mở màn scan, nếu
  không thấy → Thử lại → chờ vòng tên tiếp theo.
- **Câu hỏi lớn đã đóng**: không có server gate — app streaming cho
  SID không tồn tại (VMEMU0000001). **Nhánh A xác nhận khả thi.**

### Việc tiếp theo ngay (thứ tự)

1. **Bắt nav thật**: app → tìm điểm đến → Bắt đầu chỉ đường; đọc
   `out/cycle-trial-3.log` dòng `[NAV]` để lấy frame CMD 0x00/0x40
   variable2 thật (tên đường, direction, distance). Ghi bảng
   direction↔mũi tên trên app (chụp màn hình từng bước rẽ).
2. **Phân nhánh decoder cho frame FE** (info/thời tiết) để không giải
   nhầm variable1; đối chiếu CMD 0x01 8 byte với SDK (W7/e).
3. Đóng gói lại firmware pin 2.3.7 (có thể thêm hook FE-info), build
   kit bằng build.py, và lấy capture làm fixture test.
5. Sang giai đoạn CMU: daemon native ATT (thư mục `native/`) ăn theo
   profile đã được app chấp nhận (MODEL:H50/PROTOCOL:2.2.2S qua FFF0);
   rồi nối `com.jci.vbs.navi`.

## Bắt đầu từ đây (bản cũ, phần lớn đã bị vượt qua)

Mục tiêu: **VIETMAP LIVE trên điện thoại → giả HUD VietMap → dẫn đường và tên
đường lên HUD zin Mazda CMU150**. Người dùng có **ESP32-C3 Mini/Super Mini**.
Bước cần làm ngay là thử BLE thật bằng C3 và lấy log, sau đó mới chốt profile
để triển khai trên CMU. Chưa có bằng chứng app đã gửi nav cho emulator thật.

## Cập nhật từ phiên local 22-10-2026

- Đã clone main trên Windows và chạy lại 7 test bridge/capture, 36 kiểm frame,
  65 kiểm nav: PASS. Chưa chạy lại bộ C++ sanitizer/ARM trên máy này.
- Board đang có firmware khác source bàn giao. PC thấy VMHUD-EMU, kết nối GATT
  được; probe FFF2 không đáp, H50 trả khung thừa 8 byte. Người dùng vẫn chưa
  thấy thiết bị trong màn HUD của VIETMAP LIVE 3.4.3 trên Android/iOS.
- Đã phân tích nhánh OTA bằng REA 6.7.0 và DAE 0.1.13 bổ trợ iOS; xác định
  POST /v20/hud/updatefirmware, sáu trường body và response.downloadUrl.
  Chưa lấy được response có xác thực hay firmware; không coi 401 là bằng
  chứng server yêu cầu serial thật. fwnew.bin là đường dẫn local.
- ADB đã kết nối tablet Samsung, app 3.4.3 đang chạy; run-as không được phép,
  log app chưa có token/request OTA. Chưa cấu hình proxy hoặc cài CA.
- Đọc [báo cáo OTA](docs/hud-firmware-ota-analysis.vi.md) và
  [công cụ tái kiểm/tải](tools/hud_ota/README.vi.md) để tiếp tục.
- Cài REA/MCP nằm ngoài Git, cần khởi động lại Codex để dùng MCP; CLI đã chạy.
  Không có kết quả tải firmware, flash board/xe hay nav thật trong phiên này.

## Cập nhật phiên local 22-10-2026 (lần 2): board đã nạp và kiểm BLE thật

- **Đã xác định firmware lạ trên board**: build **16-09-2026**, IDF v5.5.5, log
  tiếng Việt không dấu, in `conn=%d`, và `remain=%ds/%dm` (coi byte thời gian
  thứ ba là giây — cách hiểu đã bị bác). Đây là bản **trước các bản sửa tháng
  10**, khớp triệu chứng "H50 trả khung thừa 8 byte" trong bàn giao (trailer
  MD5 16 byte thay vì checksum 8 byte).
- **Đã backup toàn bộ 4MB flash cũ** ra `out/board-flash-backup-20261022-013057.bin`
  trước khi ghi đè; firmware đó không có source trong repo nên backup là bản
  duy nhất. Muốn quay lại: `write-flash 0x0` chính file này.
- Kit `C:\work\mazda\vietnav-esp32c3-hud-trial` đã kiểm: ZIP SHA256 khớp bàn
  giao, `vmhud-c3-merged.bin` khớp `SHA256SUMS`, và **7 file source trong kit
  khớp byte-for-byte với repo** — nên ảnh này là bản build của source hiện tại.
- Đã nạp `vmhud-c3-merged.bin` (esptool 5.1.0, hash verified). Board giờ in
  `connected=0` và `[PING] frozen SDK-format vector: OK`.
- **Kiểm BLE thật lần đầu: 22/22 check pass** bằng `ble_central_probe.py` mới,
  PC làm GATT central cho cả hai họ. BLE MAC `38:44:BE:42:E5:8E`, MTU 256.
  Quảng bá có tên + FFF0 + FFFF; HUDInfo đáp đúng và parse qua kiểm checksum;
  `cur="Đường Nguyễn Văn Linh" next="Đại lộ Võ Nguyên Giáp"` nguyên vẹn qua
  ghi phân mảnh 20 byte; heartbeat CRC16 legacy và `dir=0xFF` đều decode được.
  Transcript: `out/ble-probe-20261022.json`.
- **Giả thuyết "app không thấy vì advertisement thiếu tên/UUID" đã bị bác**:
  quét từ PC thấy tên và cả hai UUID, RSSI −51. Nguyên nhân app không liệt kê
  thiết bị nằm ở phía app (bộ lọc, cấp quyền, hoặc nhánh profile), chưa rõ.
- **Đã sửa bug UTF-8 thật trên Windows**: `python -m hud_emulator decode > x.jsonl`
  và `decode_log.py capture.txt > capture.jsonl` — đúng lệnh trong README —
  thoát 1 với `'charmap' codec can't encode` ngay khi gặp tên đường tiếng Việt
  (locale cp1252), file ra rỗng. Đã pin UTF-8 cho stdout ở `hud_emulator/__main__.py`
  và `emu/esp32-hud-emu/decode_log.py`; test cũng pin `encoding='utf-8'` để
  bắt được lỗi này. `test_hud_protocol.py` từ 16/17 lên **17/17**.
- Chưa chạy được `tests/test_esp32_hud.py` trên máy này: cần `g++` (chưa cài).
  Codec C++ đã được kiểm bằng radio thật ở trên, không thay cho bộ sanitizer.
- **Vẫn chưa có**: nav từ app thật và mọi đầu ra lên HUD Mazda. Chưa chốt
  đường truyền board → CMU.

### PHÁT HIỆN LỚN: app Android dùng Bluetooth Classic, không dùng BLE

Thử trực tiếp trên **Samsung SM-X236B, Android 16**, VIETMAP LIVE **3.4.3**
qua ADB (Cài đặt → Cài đặt thiết bị → HUD → Kết nối thiết bị):

- Quyền **không phải nguyên nhân**: `BLUETOOTH_SCAN`/`CONNECT`/`ADVERTISE`,
  `ACCESS_FINE/COARSE/BACKGROUND_LOCATION` đều `granted=true`,
  `location_mode=3`, `bluetooth_on=1`.
- Màn HUD gọi **`BluetoothAdapter.startDiscovery()`** (inquiry **Classic**).
  Trong cả phiên **không có** `startScan`/`ScanFilter`/`[FBP]`.
- Android **đã thấy board**, đọc đúng **EIR UUID FFF0 + FFFF**, và cache tên
  **`VMHUD-EMU`**; `dumpsys bluetooth_manager` ghi board là **`[ LE ]`** trong
  khi 53 thiết bị khác đều `DUAL`/`BR/EDR`.
- App vẫn báo **"Không có thiết bị nào xung quanh bạn"**. Board quảng bá liên
  tục, không central nào kết nối.

**Kết luận: ESP32-C3 không thể hiện trong màn HUD của app Android** vì C3
không có Bluetooth Classic. Đây là giới hạn phần cứng, **không phải lỗi
firmware** — firmware hiện tại đã pass 22/22 qua BLE thật.

Hệ quả:
1. Nhánh **Android** cần chip dual-mode có SPP: **ESP32 gốc (WROOM-32/WROVER)**.
   C3/S3/C6/H2 đều BLE-only, không dùng được.
2. Nhánh **iOS vẫn đáng thử với board C3 đang có** — SDK iOS dùng CoreBluetooth
   service `FFF0`, không phải SPP. **Chưa thử iPhone lần nào.**
3. **Đổi hướng nhánh CMU**: BlueZ 4.98 thiếu GATT từng bị coi là ngõ cụt, nhưng
   rootfs có `rfcomm.ko`, `sdptool`, `rfcomm`, plugin Serial. Nếu app đi SPP
   thì stack Classic của CMU **hợp hướng hơn** giả định cũ.

Chi tiết, log và evidence: [docs/hud-dart-layer-analysis.vi.md](docs/hud-dart-layer-analysis.vi.md).
Ảnh màn hình và log thô trong `out/` (ignored): `logcat-hudscan.txt`,
`tablet-1..8.png`, `app-trial-hudscreen.log`.

## Lấy source trên local

Source và tài liệu này được gom trong cùng đợt commit/push lên `main` của
`dangkhoa116/mzd-vietnav-hud`. Commit `3338914` là **nền trước phần bàn giao**;
không checkout riêng mốc đó nếu muốn có code đã hoàn thiện trong phiên cloud.
Xem `git log -1` để lấy hash commit bàn giao chính xác.

Có Git và Python 3.10+, mở terminal tại thư mục chứa các project:

```sh
git clone https://github.com/dangkhoa116/mzd-vietnav-hud.git
cd mzd-vietnav-hud
git log -1 --oneline
git status --short
```

Nếu đã có checkout local, kiểm `git status` và lưu công việc đang dở trước
khi cập nhật; không reset/clean để làm sạch thay đổi. Source mới gồm cả
`native/`, `hud_emulator/`, codec C3 và test. Các artifact ở `out/` bị Git
ignore; clone source không tự có firmware đã build hay log cloud.

Tải thêm các ZIP cần dùng từ phiên chat, hoặc build lại theo hướng dẫn:

- `vietnav-esp32c3-hud-trial.zip`: đủ để nạp board và thu log ngay.
- `vietnav-native-hud-usb-r2.zip`: chỉ khi tiếp tục thử native trên CMU.
- `vietnav-emu-333-results.zip`: bằng chứng kết quả emu.
- `vietnav-local-continuation.zip`: bản tải kèm source, các ZIP và log đã
  chọn; giải nén rồi copy `artifacts/` vào `out/` của repo nếu cần đối chiếu.
  File `TRANSFER.json` ghi commit/source và `SHA256SUMS` kiểm từng file.

ZIP bàn giao không chứa IPA, firmware Mazda, rootfs, toolchain hay môi trường
Python/Arduino đã cài. Chỉ cần source GitHub và ZIP C3 để thử BLE đầu tiên.

## Trạng thái các repo

| Repo | Commit đã kiểm | Ghi chú |
| --- | --- | --- |
| `dangkhoa116/mzd-vietnav-hud` | `3338914db9ccd8405534c80b24a994f057acbdbe` | Nền trước commit bàn giao; lấy `main` mới nhất để có source hiện tại |
| `dangkhoa116/mzd-connect-tpms` | `dbb870daba6f68907932f6fe57d59e0143500ac1` | TPMS 0.9.3, checkout cloud sạch và không sửa |
| `dangkhoa116/mzd-connect-emu` | `8a400472d718d8cb693e898024049a9d7de8aab9` | Checkout cloud sạch; runtime/ảnh guest là file ignored, không đi theo Git |

Vietnav đã fast-forward từ `11bca8b` tới `3338914` bằng autostash và giải
conflict README/tài liệu SDK, giữ cả công việc native cũ lẫn commit mới.
Cloud còn `stash@{0}: autostash` làm bản dự phòng; **không pop lại** trên cây
đã hợp nhất. Source đã hợp nhất được commit cùng tài liệu này, không cần stash
này trên local.

## Việc đã hoàn thành

### ESP32-C3 và codec

- Sketch `emu/esp32-hud-emu/vmhud_emu/vmhud_emu.ino` dùng Arduino-ESP32
  **3.3.2**, NimBLE-Arduino **2.3.7**, CLI **1.3.1**.
- Cung cấp đồng thời H1/DJBT: FFF0, FFF2/FFF3 write, FFF1 notify; và H50:
  FFFF, 9ABC write, 1234 notify. C3 chỉ có **BLE**, không có Classic/SPP.
- Quảng bá mặc định legacy có tên `VMHUD-EMU` và cả hai UUID trong primary.
  Profile mặc định `MODEL:H50`, `PROTOCOL:2.2.2S`, `SID:VMEMU0000001` là
  danh tính thử, chưa được xác nhận app/máy chủ chấp nhận.
- Đã sửa nhầm trailer MD5 16 byte thành checksum 8 byte; gom frame phân
  mảnh, kiểm độ dài/checksum, xử lý dữ liệu lỗi và chia notify thành 20 byte.
- `hud_codec.h` là core C++ portable thực sự dùng trong sketch và test
  ASan/UBSan. Buffer 4096 byte; ảnh mũi tên lớn hơn sẽ bị loại và ghi log.
- NVS lưu cấu hình qua Serial; đổi NAME áp dụng sau RESET. Có STATUS/PING.
- `capture_serial.py` thu log raw; `decode_log.py` xuất JSONL, tách luồng
  H1/H50 và phiên kết nối; `build.py` build và đóng kit kèm source/checksum.
- Đã sửa tương ứng `bridge/vmlhud_frame.py`, `bridge/vmlhud_nav.py`, test
  và tài liệu để thống nhất với codec SDK đã phân tích trước đó.

**Chú ý giao thức:**

- Mới: magic `A5 5A 37 C3`, len BE = payload+13; tổng payload+21 = len+8.
  Trailer có hai checksum 4 byte, mỗi checksum là tổng modulo 2^32 của bốn
  word BE trong MD5(header+payload+UID16). Default UID:
  `f7fd157502da528ef0fc3139722ce9e2`. Runtime UID chưa biết, **không phải SID**.
- Cũ: magic `A5 5A 37 C5`, len = payload+5; CRC16 Modbus ghi byte cao trước;
  tổng payload+11. Không tự thay bằng CRC endian khác.
- Vector mới HUDInfo request:
  `A55A37C30000000E000000000E004DC64215C1C48DA3`.
- Vector cũ heartbeat: `A55A37C50000000602FF3AA1`.
- Fixed 175 byte: legacy CMD 0; variable1: new CMD 0; variable2: CMD 0x40,
  có image_len và ảnh JPEG/flag, không chỉ header hằng số.
- Byte thời gian thứ ba của variable **là giây** (đã chốt bằng runtime 22-10,
  xem phần cập nhật lần 4 ở đầu file); codec điền `remain_time_s` cho cả ba
  layout và vẫn giữ bộ ba byte gốc khi dựng lại khung. Mã hướng rẽ trên iOS là
  hằng số `0xFE`; đơn vị speed vẫn cần mẫu khi xe chạy.

### Native CMU và USB thử riêng

- `native/`: core ATT server, quảng bá, HUDInfo, HCI adapter ghép vào TPMS v3;
  dùng chung UART `/dev/ttymxc3` bên trong `bds`. Không dùng BlueZ 5 D-Bus.
- Bản native hiện mới phục vụ họ FFF0; **chưa tự đồng bộ mọi cải tiến/profile
  FFFF/H50 của C3**. Profile native vẫn VIETNAV/protocol 2.0, chưa kiểm app.
- ARM build bằng m3-toolchain GCC 4.9.1/glibc 2.11; kiểm ABI yêu cầu GLIBC_2.4.
- USB trial R2: query trước, chỉ advertise khi có proof phù hợp; đặt lịch
  chạy một lần ở boot tiếp theo, thu log, backup/rollback wrapper TPMS.
- Không bật TPMS central và HUD peripheral đồng thời trong bản thử này.
  TPMS trở lại ở lần start kế tiếp, không chuyển giữa phiên.
- **Chưa thử radio/iPhone thật và chưa nối output `com.jci.vbs.navi`**.
  Installer ổn định 0.9.1 không được thay thế bằng kit thử này.

Đọc: [native/README.md](native/README.md),
[native/usb/README.md](native/usb/README.md),
[docs/hud-native-cmu.md](docs/hud-native-cmu.md).

## Artifact và kết quả đã kiểm

Các đường dẫn sau tính từ gốc repo sau khi khôi phục ZIP:

| Artifact | Nội dung |
| --- | --- |
| `out/vietnav-esp32c3-hud-trial.zip` | Firmware C3 thường + extended thử nghiệm, source, công cụ capture/decode, checksum |
| `out/esp32-c3-validation.json` | Kết quả build, hash firmware/source và log các test gần nhất |
| `out/vietnav-native-hud-usb-r2.zip` | USB native thử riêng; đọc hướng dẫn trước khi dùng trên xe |
| `out/vietnav-emu-333-results.zip` | Báo cáo/ảnh kết quả emu, gồm giới hạn GUI |

SHA256 ZIP C3:
`98662fe14defa12775f1114a1c37f339fab1f0dbfc36bbe5a95f68440c0b9a52`.

Đã kiểm trong phiên cloud, không phải kết quả chạy mới trên local:

- 70 unittest HUD/native/USB host **PASS**.
- 8 test codec C3 có ASan/UBSan **PASS**, gồm 50.000 input fuzz.
- 7 unittest bridge/capture **PASS**.
- Script frame: **36 pass**; script nav: **65 pass**.
- Hai cấu hình firmware C3 compile **PASS**; esptool xác nhận ESP32-C3,
  4MB, DIO, image checksum/hash hợp lệ. ZIP và mọi SHA256SUMS khớp.
- Native trước đó: 229 kiểm tra mux, 50.000 input ATT sanitizer và 5 test
  transport ARM/QEMU **PASS**; đây là bài riêng với fuzz codec C3.

Các log mới nằm trong `out/*-latest.log`; xem đường dẫn chính xác trong
`out/esp32-c3-validation.json`. Build/test host không chứng minh BLE thật.

## Bước tiếp theo: nạp C3 và lấy capture thật

Giải nén ZIP C3. Windows dùng Python 3.10+, cáp USB data và cổng ví dụ COM7:

```sh
python -m pip install esptool==5.1.0 pyserial==3.5
python -m esptool --chip esp32c3 --port COM7 write-flash 0x0 vmhud-c3-merged.bin
python source/emu/esp32-hud-emu/capture_serial.py COM7 capture.txt
```

**Ảnh ghi toàn flash 4MB, thay firmware/NVS của board.** Chọn ảnh thường
`vmhud-c3-merged.bin` trước. Nếu cần vào bootloader: giữ BOOT, bấm/thả RESET,
thả BOOT; sau nạp RESET để chạy, USB CDC có thể đổi cổng.

Trong lúc capture: RESET board nếu cổng vẫn giữ được; vào VietMap → HUD →
quét/kết nối `VMHUD-EMU` → bắt đầu tuyến có rẽ và tên đường. Dừng Ctrl+C rồi:

```sh
python source/emu/esp32-hud-emu/decode_log.py capture.txt > capture.jsonl
```

Nếu chạy công cụ từ repo thay vì source trong kit, bỏ tiền tố `source/`.
Ghi lại loại điện thoại, phiên bản app/OS, thông báo UI và từng bước:
quét thấy → connected → notify subscribed → HUDInfo request/response → nav.
Giữ toàn bộ dòng `[W:FFF2]`, `[W:FFF3]`, `[W:9ABC]` và thông tin tuyến.

Không nhận nav **chưa chứng minh bị server chặn**. `[SCAN]` của bản extended
không xác định scanner là VietMap; vắng SCAN cũng không chứng minh app không
quét. Chưa cần mua HUD thật để làm thử nghiệm đầu này.

Chi tiết: [emu/esp32-hud-emu/README.vi.md](emu/esp32-hud-emu/README.vi.md).

## Build/test lại trên local

Để thử C3 bằng binary có sẵn chỉ cần bước trên. Để chạy test native, nên dùng
Linux hoặc WSL2; GCC/OpenSSL/ASan không có sẵn trong Windows Python.

Đặt repo TPMS cạnh Vietnav, đúng revision để hash gate chấp nhận:

```sh
git clone https://github.com/dangkhoa116/mzd-connect-tpms.git ../mzd-connect-tpms
git -C ../mzd-connect-tpms checkout dbb870daba6f68907932f6fe57d59e0143500ac1
sudo apt-get update
sudo apt-get install python3-venv g++ libssl-dev patch dbus-daemon
python3 -m venv .venv-hud
.venv-hud/bin/python -m pip install -r hud_emulator/requirements.txt
.venv-hud/bin/python -m unittest discover -s tests -p 'test_hud_*.py' -v
.venv-hud/bin/python -m unittest discover -s tests -p 'test_esp32_hud.py' -v
.venv-hud/bin/python -m unittest discover -s tests -p 'test_vmlhud_bridge.py' -v
.venv-hud/bin/python bridge/vmlhud_frame_test.py
.venv-hud/bin/python bridge/vmlhud_nav_test.py
```

Một số kiểm packaging cần artifact/dependency cục bộ có thể skip; đọc output,
không coi skip là đã xác minh. Script `native/run_tests.sh` chạy thêm kiểm mux
và fuzz native; đọc hướng dẫn native trước khi chạy bộ ARM mở rộng.

Build firmware C3: cài Arduino CLI, core `esp32:esp32@3.3.2`, library
`NimBLE-Arduino@2.3.7` theo README C3, rồi:

```sh
python emu/esp32-hud-emu/build.py --out out/c3-local-build
```

Thêm `--extended` nếu thật sự cần scan diagnostic. Không copy nguyên config
cloud có proxy `http://proxy:8080` sang local. Các thư mục toolchain ở
`/workspace/.mzd-tools/` và `.venv-mzd` không nằm trong ZIP.

## Firmware/rootfs và emu: phần nào đã có, phần nào chưa

Người dùng đã cung cấp firmware qua Drive:
https://drive.google.com/file/d/1rnsfv55JZPIyilmT_fNJSHUEbZbqY1Sc/view

Cloud đã tải và giải rootfs, **không còn bị chặn vì thiếu firmware**:

- `/workspace/.mzd-tools/firmware/cmu-update.zip`: ZIP ngoài khoảng 3,67 GB.
- `cmu150_ADR_74.00.333A_mass.up`: khoảng 2,05 GB; SHA256
  `8082edfe61c8788b770b46e0a0f899b4a5c3f941ba52864052ef5d27885e3928`.
- `/workspace/.mzd-tools/firmware/rootfs-333`: rootfs đã đối chiếu
  **8.478/8.478 MD5** và **714 CRC resource**.

Các file lớn trên không đi theo ZIP bàn giao; local cần tự tải/chuẩn bị nếu
tiếp tục emu. Không cần chúng để thử C3. Không commit IPA/rootfs/firmware.

Kết quả với rootfs thật: **23 test USB** chạy BusyBox ARM gốc **PASS**,
**5 test transport ARM** với loader/libc gốc **PASS**, guest emu qua
**9 checkpoint** cài/thu log/rollback. `jci-dialog` gốc vẽ đúng menu.

**Toàn phiên GUI emu chưa pass**: Opera thoát 139 trước bài installer, MMUI
dừng health check, ảnh cuối đen. Thử sửa quyền traverse Mesa chưa giải quyết.
Emu không tái hiện radio TI/HFP/A2DP/LE đồng thời; không dùng kết quả guest
để khẳng định BLE hay HUD thật hoạt động.

Đọc [native/emu/README.md](native/emu/README.md),
[docs/emu-yeu-cau.md](docs/emu-yeu-cau.md). Runtime ignored ở cloud nằm trong
`/workspace/mzd-connect-emu/local/`; cần dựng lại theo docs của repo emu.

## Những kết luận không được lặp lại như sự thật

- BlueZ 4.98 thiếu API GATT hiện đại là đúng; chuỗi lệnh LE trong binary
  **không chứng minh** controller nhận advertising.
- `AttributeServer=false` tắt ATT thử nghiệm của BlueZ, không tự chứng minh
  toàn bộ stack Mazda chỉ có Classic.
- Có RFCOMM/module/plugin không chứng minh SPP dùng ngay: `bds` đang sở hữu
  UART/radio; cần kiểm ownership và app Android thực sự chọn SPP.
- TPMS đã nhận BLE central trên xe không chứng minh peripheral hoặc chạy
  central+peripheral cùng nhạc/cuộc gọi. Phải đọc đủ capability và thử xe.
- iPhone thường không dùng generic SPP thiếu hỗ trợ MFi phù hợp; không vì
  vậy mà kết luận phải mua HUD thật. C3 và native ATT là các hướng thử đã có.
- Mua HUD thật không tự cho CMU nghe được phiên BLE của hai thiết bị khác;
  relay/encryption/quyền app còn là phần nghiên cứu chưa triển khai.
- SID, runtime UID checksum và dấu vết API cấp quyền là ba thứ khác nhau.
  Không nhận nav chưa đủ để quy về server/serial.

## Thứ tự công việc sau khi có log

1. Phân biệt không thấy thiết bị, không kết nối, thiếu subscribe, HUDInfo
   không được nhận, hay có kết nối nhưng chưa có nav; sửa đúng bước lỗi.
2. Đối chiếu direction/tên đường/khoảng cách với UI; giữ fixture từ capture
   thật cho codec. Kiểm profile H1 hay H50 app chọn.
3. Mang profile đã xác nhận sang native CMU, dùng kit query trước và chỉ
   thử advertise theo proof; không sửa checkout TPMS gốc hoặc chồng preload.
4. Khi nhận nav thật trên CMU, nối struct dẫn đường vào `com.jci.vbs.navi`:
   hướng rẽ, tên đường, khoảng cách, nguồn ưu tiên và xoá guidance khi hết hạn.
5. Kiểm trên xe: reconnect, ngừng tuyến, rollback, nhạc/cuộc gọi và TPMS.
   Chỉ tích hợp installer ổn định sau khi có bằng chứng.

## Prompt cho agent chạy local

> Đọc CONTINUE-LOCAL.vi.md và các README được dẫn trước khi sửa. Tiếp tục dự
> án Vietnav đưa VIETMAP LIVE lên HUD zin Mazda theo hướng giả HUD. Source local
> kế thừa phần bàn giao trên nền 3338914; giữ mọi thay đổi đang dở. Ưu tiên thử
> board ESP32-C3 có sẵn và phân tích capture BLE thật. Đã có firmware build,
> codec/test, native ATT và USB trial; đừng phân tích lại từ đầu hay yêu cầu
> mua HUD thật chỉ vì BlueZ 4.98. Chưa có app/board thật được xác nhận và chưa
> nối output VBS. Nếu có log mới, dùng capture/decode để xác định bước lỗi;
> nếu chưa có, kiểm setup local và hướng dẫn nạp/lấy log. Phân biệt kết quả
> host/QEMU với radio trên xe. Tiếp tục phần có thể làm, không tự flash xe
> hoặc publish/push khi chưa được yêu cầu.
