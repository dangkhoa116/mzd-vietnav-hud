# Tầng Dart của VIETMAP LIVE: quét BLE và chọn thiết bị HUD

Phân tích ngày **22-10-2026** bằng REA 6.7.0 trên APK người dùng cung cấp.
Mục tiêu: tìm logic quét/lọc quyết định thiết bị HUD nào được liệt kê, tức là
nguyên nhân board `VMHUD-EMU` không hiện trong màn HUD của app.

Đây là **phân tích tĩnh**. Không có phiên app thật nào được quan sát trong
phân tích này; mọi nhận định về hành vi chạy thật đều được ghi là chưa xác minh.

## Artifact và danh tính

| Mục | Giá trị |
| --- | --- |
| APK | `work/analysis/apk/vietmap.apk` (ngoài repo), 351.523.812 byte |
| APK SHA-256 | `5365b441afe72317d971acf740eec7aa2dfa941b15460fe9d0d81df5d173dfa1` |
| `lib/arm64-v8a/libapp.so` | 36.963.248 byte, SHA-256 `926e2e63c536ad358ed5ec1ecc30444d3b970c5ddccea3865ce4126a8fba70aa` |
| Dart snapshot hash | `f71c76320d35b65f1164dbaa6d95fe09` (giống nhau ở cả 3 ABI) |
| Evidence REA | `ev_0aa897b3…` (identify_flutter_build), `ev_7caeb9bb…` (inspect_dart_aot) |

Snapshot hash chỉ map sang bản Dart SDK qua dataset ngoài; REA không tra cứu.
Các offset dưới đây tính theo file `libapp.so` đã nêu hash, mục đích tái kiểm.

## Quan sát được

- **App là Flutter**, package `vietmap_live`, entrypoint
  `package:vietmap_live/main_production.dart`. Chỉ 6 package URI còn trong
  snapshot — source URI bị strip như release AOT thường làm.
- **Code Dart đã bật obfuscation.** String pool đầy các tên dạng
  `_mc@4048458`, `_Njm@717383858`, `aFD`, `SJb`. Vì vậy **logic lọc không để
  lại dấu vết dạng string** và không đọc được bằng phân tích string.
- **Hai plugin Bluetooth cùng được biên dịch vào app:**

  | Plugin | Kênh thấy trong Dart và DEX | Loại |
  | --- | --- | --- |
  | `flutter_blue_plus` | `flutter_blue_plus/methods` | BLE |
  | `flutter_bluetooth_serial` | `/methods`, `/discovery`, `/read/`, `/state` | **Classic/SPP** |

  Log của flutter_blue_plus có mặt trong snapshot (`[FBP] stopScan: already
  stopped`, 0x00172b42), xác nhận plugin BLE này thực sự được dùng ở đâu đó
  trong app.
- **Dart không chứa UUID nào** của HUD: tìm `0000fff0…`, `0000ffff…`,
  `00009abc…`, `00001234…` và `00001101…` trong `libapp.so` đều **0 kết quả**.
- **Toàn bộ UUID nằm trong DEX** (phía native), khớp `Ma/i.java`/`Ma/j.java`
  đã đọc trước đây: `0000fff0/fff1/fff2/fff3/fff4`, `0000ffff`, `00009abc`,
  `00001234` (chữ thường) và `00001101-…-00805F9B34FB` (chữ **hoa**, khác
  nguồn — thuộc nhánh SPP của flutter_bluetooth_serial).
- `connectDeviceNativeApi` (Dart 0x00131610, cũng có trong DEX) và
  `vietmap_hud_sdk` (0x00158cf5), `DJBTSdk` (0x0014a30e).
- **Quét dùng chung với TPMS**: `TpmsEvent.startScan()` (0x0010d49e),
  `TpmsEvent.stopScan()` (0x001b9a89). Khớp việc bộ lọc native loại tên
  chứa `TPMS`.
- Họ enum H50 còn tên kiểu (dùng cho `toString`): `H50ManeuverType.`,
  `H50ProtocolCmd.`, `H50LaneInfoType.`, `H50BluetoothMode.`,
  `HUDH50BluetoothType.`, `H50UpcomingAlertType.`, `H50StickyAlertType.`,
  `H50DirectionInfo(distance: `, `H50Protocol`.
- **DEX có cả hai cơ chế quét**: `BluetoothLeScanner`, `ScanFilter`,
  `ScanSettings`, `setServiceUuid`, `setDeviceName` (BLE) và `startDiscovery`
  (Classic), cùng `connectGatt`, `discoverServices`,
  `setCharacteristicNotification`, `getBondedDevices`, `createBond`.
- **Manifest không có `neverForLocation`** (kiểm cả UTF-8 và UTF-16LE trong
  `AndroidManifest.xml`). Quyền khai báo gồm `BLUETOOTH_SCAN`,
  `BLUETOOTH_CONNECT`, `BLUETOOTH_ADVERTISE`, `BLUETOOTH`, `BLUETOOTH_ADMIN`,
  `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`.

## Suy ra (chưa phải quan sát chạy thật)

1. **App gần như chắc chắn không quét kèm bộ lọc service UUID.** Nếu Dart gọi
   `startScan(withServices: [...])` thì UUID phải là literal trong snapshot;
   không có UUID nào. Các tên tham số `withServices`/`withNames`/`withKeywords`
   cũng không xuất hiện. Suy ra app quét rộng rồi **lọc kết quả bên phía Dart**.
2. **Vì vậy bộ lọc tên là nghi phạm yếu** cho việc board không hiện: tên
   `VMHUD-EMU` chứa `HUD` và không chứa `TPMS`, thoả quy tắc đã biết từ SDK iOS.
3. **Nghi phạm mạnh nhất là quyền quét trên Android 12+.** `BLUETOOTH_SCAN`
   khai báo **không** kèm `neverForLocation` nghĩa là hệ thống coi kết quả quét
   có thể suy ra vị trí: BLE scan khi đó đòi **quyền vị trí được cấp và dịch vụ
   định vị đang bật**, ngoài quyền "Thiết bị ở gần". Thiếu một trong các điều
   kiện đó, `startScan` trả về **danh sách rỗng mà không báo lỗi** — đúng triệu
   chứng "app không liệt kê thiết bị" trong khi PC quét thấy board rõ ở −51 dBm.
4. Sự hiện diện của `flutter_bluetooth_serial` mở khả năng màn HUD dùng
   **discovery Classic** cho một họ thiết bị nào đó. Nếu đúng với họ đang thử,
   board ESP32-C3 (chỉ BLE, không có Classic) sẽ **không bao giờ** xuất hiện.
   Chưa có bằng chứng xác định màn HUD gọi plugin nào.

## Chưa giải quyết được

- **Plugin nào phục vụ màn HUD** (BLE hay Classic) và **bộ lọc chính xác**:
  nằm trong code Dart đã obfuscate, không có dấu vết string. jadx không giúp
  ở đây vì nó đọc Java/Kotlin, còn quyết định này ở tầng Dart.
- **Bảng `direction` (byte đầu payload nav) vẫn chưa tách được, và giờ đã rõ
  lý do**: 179 icon mũi tên trong
  `assets/flutter_assets/lib/assets/hud/directions/{dark,…}/` được đặt tên theo
  **type+modifier kiểu Mapbox** (`direction_roundabout_slight_left.png`,
  `direction_on_ramp_sharp_right.png`), **không đánh số**. Ánh xạ
  `H50ManeuverType` → số là logic trong code đã obfuscate, không để lại string.
  Đây là tìm kiếm âm có giới hạn, không phải bằng chứng ánh xạ không tồn tại.
  Cách chốt vẫn là đối chiếu runtime: byte nhận được so với mũi tên trên app.

## ĐÃ CHỐT BẰNG CHẠY THẬT (22-10-2026): app Android dùng Bluetooth Classic

Thiết bị thử: Samsung **SM-X236B** (Galaxy Tab A11+ 5G), **Android 16 / SDK 36**,
VIETMAP LIVE **3.4.3 (179094172)** — đúng build đã phân tích tĩnh ở trên.
Điều hướng qua ADB: Cài đặt → Cài đặt thiết bị → **HUD → Kết nối thiết bị**.

**Quyền đã loại trừ.** `dumpsys package vn.vietmap.live` cho thấy
`BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`, `BLUETOOTH_ADVERTISE`,
`ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`
đều `granted=true`; `location_mode=3`, `bluetooth_on=1`. Giả thuyết
`neverForLocation` ở mục suy ra số 3 **bị bác bỏ**.

**Quan sát trong logcat** (pid 25857 = `vn.vietmap.live`):

```
02:18:59.781 25857 I BluetoothAdapter: startDiscovery
02:18:59.786  3060 I BluetoothAdapterServiceBinder: startDiscovery: from uid/pid=10315/25857
02:19:12.637  3060 I BluetoothAdapterProperties: discoveryStateChangeCallback with state:0
02:19:12.652 25857 I BluetoothAdapter: cancelDiscovery
```

Màn HUD gọi **`BluetoothAdapter.startDiscovery()`** — inquiry **Bluetooth
Classic**. Trong toàn bộ phiên **không có** `BluetoothLeScanner.startScan`,
không có `ScanFilter`, không có dòng `[FBP]` nào của flutter_blue_plus.

**Android đã tìm thấy board và đọc đúng advertisement:**

```
02:19:00.412 btif_dm_search_devices_evt: EIR UUIDs for xx:xx:xx:xx:e5:8e[public]
02:19:00.412   0000fff0-0000-1000-8000-00805f9b34fb
02:19:00.412   0000ffff-0000-1000-8000-00805f9b34fb
02:19:00.413 BluetoothRemoteDevices: Remote class is UNCATEGORIZED
02:19:00.414 BluetoothRemoteDevices: deviceFoundCallback: Remote Address is:XX:XX:XX:XX:E5:8E
02:19:00.423 BluetoothAdapter: BluetoothAdapter() : vn.vietmap.live
02:19:00.426 btif_dm_get_connection_state: Acl is not connected to peer:xx:xx:xx:xx:e5:8e
```

`dumpsys bluetooth_manager` sau đó:

```
XX:XX:XX:XX:E5:8E(Public) => … [  LE  ] [0x001F00] … VMHUD-EMU
XX:XX:XX:XX:45:31(Public) => … [ DUAL ] … [TV] Samsung 7 Series (43)
XX:XX:XX:XX:AA:D6(Public) => … [BR/EDR] … LAPTOP-V36HIMFN
```

Tên board **đã phân giải đúng là `VMHUD-EMU`** (chứa `HUD`, không chứa `TPMS`,
tức thoả bộ lọc tên đã biết), và board là thiết bị **`LE`-only duy nhất**;
53 thiết bị còn lại đều `DUAL` hoặc `BR/EDR`. Dù vậy app kết thúc quét với
**"Không có thiết bị nào xung quanh bạn"**. Phía board, `record_app_trial.py`
xác nhận board quảng bá liên tục suốt phiên và **không có central nào kết nối**.

### Kết luận

**Quan sát:** app nhận được một thiết bị tên `VMHUD-EMU` thoả bộ lọc tên, đã
truy vấn riêng địa chỉ của nó, và vẫn không liệt kê nó.

**Suy ra:** danh sách HUD của app Android yêu cầu thiết bị **dùng được qua
Bluetooth Classic** (`BR/EDR` hoặc `DUAL`); peripheral **chỉ có LE** bị loại
sau khi hệ thống đã phát hiện. Phù hợp với toàn bộ bằng chứng tĩnh: 4 kênh
`flutter_bluetooth_serial`, UUID SPP `00001101-…` trong DEX, và
`getBondedDevices`/`createBond`.

**Hệ quả cho dự án:** **ESP32-C3 không thể xuất hiện trong màn HUD của app
Android**, vì C3 không có Bluetooth Classic. Đây là giới hạn phần cứng, không
phải lỗi firmware — firmware hiện tại đã pass 22/22 qua BLE thật.

- Muốn đi tiếp nhánh **Android**: cần chip **dual-mode** có BT Classic/SPP,
  ví dụ **ESP32 gốc (ESP32-WROOM-32/WROVER)**. Các dòng C3/S3/C6/H2 đều
  BLE-only và không dùng được cho nhánh này.
- Nhánh **iOS vẫn đáng thử với board C3 hiện có**: SDK iOS dùng
  `DJBTManager` + CoreBluetooth với service `FFF0` (xem
  [vietmap-hud-sdk.md](vietmap-hud-sdk.md)), không phải SPP. Chưa thử iPhone.
- **Đổi hướng cho nhánh CMU:** BlueZ 4.98 thiếu GATT từng bị coi là ngõ cụt,
  nhưng rootfs **có `rfcomm.ko`, `sdptool`, `rfcomm` và plugin Serial**. Nếu
  app Android thật sự đi SPP, thì stack Classic của CMU **hợp hướng hơn** so
  với giả định trước đây. Vẫn phải kiểm quyền sở hữu radio của `bds`.

**Chưa biết:** vị từ lọc chính xác (theo `getType()`, theo `BluetoothClass`,
hay theo thứ khác) vẫn nằm trong code Dart đã obfuscate. Quan sát này đến từ
**một thiết bị, một phiên bản app**; chưa kiểm iOS và chưa kiểm model khác.

## Nhánh iOS (22-10-2026): iPhone thấy board, app vẫn không liệt kê

Thiết bị: iPhone có Dynamic Island (14 Pro trở lên), VIETMAP LIVE
**3.4.3 (179094172)** — đúng build đã phân tích.

**Đã loại trừ bằng quan sát, không phải suy đoán:**

| Nghi phạm | Cách loại | Kết quả |
| --- | --- | --- |
| iOS không nhận được quảng bá | nRF Connect trên chính iPhone đó | **Thấy**: tên + `Services: FFF0 and FFFF`, −55 dBm |
| `peripheral.name` nil | nRF hiển thị được tên qua CoreBluetooth | Tên có sẵn |
| Quyền Bluetooth của app | Cài đặt → VIETMAP LIVE → Bluetooth | **Đang bật** |
| Sai phiên bản app | Màn Cài đặt của app trên iPhone | **3.4.3 (179094172)**, khớp |
| Bộ lọc tên dùng `contains` | Tên `VMHUD-EMU` chứa `HUD` và cả `HUD-` | Không hiện |
| Bộ lọc tên dùng **tiền tố** | Đổi `NAME:HUD-H50` (bắt đầu bằng HUD, model thật) | **Vẫn không hiện** |

Mỗi lần thử đều có `record_app_trial.py` xác nhận board quảng bá liên tục
(−45…−55 dBm) và **không central nào kết nối**; log: `out/ios-trial-1.log`,
`out/ios-trial-2-hudh50.log`.

**Bằng chứng tĩnh về đường quét iOS:** Dart gọi `startScanDevice`/
`stopScanDevice` → màn HUD dùng bộ quét CoreBluetooth trong
`vietmap_hud_sdk.framework` (`scanForPeripheralsWithServices:options:`,
`CBCentralManagerDelegate`). Trong 376 selector của framework có `name` nhưng
**không có** `kCBAdvDataLocalName` hay key advertisement nào khác — bộ lọc đọc
`peripheral.name`. Framework có hằng `'HUD'`, `'TPMS'`, `containsString:`.

**Hằng số tên trong Dart iOS:** `'HUD-'`, `'HUD_'`, `'vmHUD'`, và các model
thật `hudH1AS`, `hudH1N`, `hudH1X`, `hudH2AS`, `hudH6`, H50, cùng `'VIETMAP'`,
`'VIETMAP_LIVE'`. Bộ lọc thật vẫn nằm trong code Dart đã obfuscate.

### Bổ sung 22-10-2026 (lần 2): iPhone jailbreak, đã đăng nhập

Thiết bị thứ hai: **iPhone 8 Plus (iPhone10,5), iOS 16.7.15**, jailbreak
rootless (Dopamine), điều khiển qua `ios-mcp`. VIETMAP LIVE **3.4.3
(179094172)**, **đã đăng nhập tài khoản**. (Các lần "không thấy" trước đó là
trên một iPhone khác có Dynamic Island, cũng đã đăng nhập — nên đều hợp lệ.)

- **Tính năng HUD khoá sau đăng nhập.** Khi chưa đăng nhập, bấm vào Cài đặt
  hiện hộp thoại "Vui lòng đăng nhập tài khoản để sử dụng tính năng này".
  Sau khi đăng nhập thì vào được Cài đặt → Cài đặt thiết bị → HUD → Kết nối
  thiết bị. Vậy "list rỗng" **không** do chưa đăng nhập.
- **Đã thử 4 biến thể advertising, tên `HUD-H50`**, mỗi lần board được PC xác
  nhận quảng bá liên tục (−37…−52 dBm) và không central nào kết nối:

  | ADV | Service trong gói | iPhone (đăng nhập) |
  | --- | --- | --- |
  | FFF0 | chỉ FFF0 | không thấy |
  | FFFF | chỉ FFFF | không thấy |
  | NONE | không UUID | không thấy |
  | BOTH | FFF0 + FFFF | không thấy |

  → **Việc board hiện ra không phụ thuộc service UUID trong advertisement.**
  Giả thuyết "sai họ service" (mục 2 dưới đây) **bị loại**.
- Firmware này cho đổi `NAME`/`ADV`/`MFG` qua serial, áp dụng sau reset; đã
  pass host test và kiểm BLE thật trước đó.
- `log show`/unified log trên bản rootless không trả dữ liệu (thiếu quyền);
  Frida chưa cài. Chưa bắt được syslog CoreBluetooth tương đương logcat Android.

### Giả thuyết còn lại (chưa kiểm được)

1. **Advertisement thiếu manufacturer data.** Board không phát trường này.
   Tầng Dart phải xác định `type` thiết bị (2=H50, 3=H1, còn lại=DJBT) để
   truyền cho `connectDeviceNativeApi`; nếu `type` suy ra từ manufacturer data
   thì thiết bị không có trường đó sẽ bị loại. **Không đoán được nội dung
   trường này nếu không có capture từ HUD thật hoặc firmware HUD thật.**
2. ~~Board quảng bá đồng thời cả FFF0 và FFFF.~~ **ĐÃ LOẠI** — thử FFF0-only,
   FFFF-only, NONE, BOTH trên iPhone đăng nhập đều không hiện (bảng trên).
3. **App chưa thật sự quét / quét rồi loại vì thiếu trường khác.** Trên Android
   đã chứng minh có quét bằng logcat; **trên iOS chưa bắt được syslog tương
   đương** (rootless thiếu quyền unified log, Frida chưa cài).
4. **Advertisement thiếu manufacturer data** vẫn là nghi phạm mạnh nhất còn
   lại: board để trống trường này; SDK iOS phải suy ra `type` thiết bị để
   truyền cho tầng native. Không đoán được nội dung nếu không có capture/
   firmware từ HUD thật. Firmware mới đã có lệnh `MFG:<hex>` để thử khi biết
   giá trị cần phát.

Lưu ý mẫu hình chung: trên **cả hai** nền tảng, danh sách HUD của app **luôn
trống**, kể cả khi Android đã phát hiện 53 thiết bị có tên. Chưa loại trừ được
khả năng tính năng HUD bị chặn bởi một điều kiện khác (tài khoản, gói dịch vụ,
hoặc đăng ký thiết bị) trước cả bước lọc.

## ĐÃ CHỐT BẰNG DISASSEMBLY (22-10-2026, lần 3): toàn bộ chuỗi native iOS không lọc gì ngoài tên chứa "HUD"

Disassembly ARM64 `vietmap_hud_sdk.framework` (IPA 3.4.3, SHA-256 ở đầu tài
liệu SDK; địa chỉ file offset của slice arm64 đầu tiên):

1. **Quét không lọc service.** `DJBTManager.startSearchingBluetooth` @
   `0x4254` gọi `[centraManager scanForPeripheralsWithServices:nil
   options:nil]` (`x2=0, x3=0` tại `0x429c-0x42a4`). Không có danh sách
   CBUUID nào ở tầng quét. Giả thuyết "sai họ service trong advertisement"
   chết lần thứ hai bằng chứng độc lập.
2. **Filter duy nhất ở `didDiscoverPeripheral`** @ `0xbeb8`:
   ```objc
   if (peripheral.name == nil) return;                            // 0xbf0c
   if (![name.uppercaseString containsString:@"HUD"]) return;     // 0xbf34-0xbf54
   // tạo DJPeripheral{peripheral, RSSI}, dedup theo identifier.UUIDString,
   // thay thế entry cũ rồi gọi delegate BTManager:didFinishSearchWithArray:
   ```
3. **Delegate không lọc thêm.** Lớp Swift
   `_TtC15vietmap_hud_sdk14DJBTSDKHandler` implement
   `BTManager:didFinishSearchWithArray:` @ `0x183ac` (method-list entry
   `0x2f3e8`): map mảng `DJPeripheral` rồi forward nguyên mảng về Dart qua
   event `didFinishSearchWith…` với JSON `{"peripheral": [...]}` (cstring
   `0x314c0`). Không có check model/UUID/manufacturer nào.
4. **Dart không thể lọc theo manufacturer data trên iOS.** `DJPeripheral`
   chỉ giữ `{CBPeripheral, RSSI}` ( setter tại `0xbf6c`/`0xbf7c`);
   advertisementData nhận trong callback **không được lưu lại**. Mỗi phần tử
   JSON chỉ có thể mang name/rssi/identifier. **Giả thuyết số 1 ở mục
   "Giả thuyết còn lại" (thiếu manufacturer data) bị bác bỏ hoàn toàn** —
   không chỉ ở ADV variants đã thử mà về mặt cấu trúc dữ liệu.
5. **Chuỗi debug để kiểm runtime trên máy jailbreak:** framework in
   `'Peripheral count: '` (`0x310e0`), `'foundPeripheral: '` (`0x31100`) và
   `'Main ==== update device found '` (`0x314a0`) khi scan trả kết quả.
   Trên iPhone jailbreak, mở Console/os_log rồi vào màn HUD: có các dòng
   này ⟹ app đang quét và SDK trả kết quả; không có ⟹ app không gọi scan
   (gate nằm ở Dart/feature flag).

### Hệ quả định hướng lại điều tra

- **Lý thuyết thống nhất mới (mạnh nhất):** tầng Dart lọc tên chặt hơn
  `contains("HUD")`. Nó giải thích **cùng một lúc** việc `VMHUD-EMU` và
  `HUD-H50` không hiện trên iPhone (SDK đã chắc chắn chuyển chúng về Dart)
  **và** trên Android. Kết luận "Android loại thiết bị LE-only" ở trên
  thành **chưa chắc chắn**: có thể tên mới là nguyên nhân duy nhất, khi đó
  tablet Samsung cũng có thể hiện board dù board chỉ có BLE.
- Các hằng số tên trong Dart iOS (`'HUD-'`, `'HUD_'`, `'vmHUD'`, `'VIETMAP'`,
  model `H1AS/H1N/H1X/H2AS/H6/H50`, chuỗi toString `'HUD_V3(BLE)'` ở file
  offset `0x24c7140` của App.framework) vẫn là ứng viên cho bộ lọc; Facebook
  group Vietmap nói tên thiết bị hiện dạng "VIETMAP-HUD".
- **Thí nghiệm mới (rẻ, không cần jailbreak):** firmware C3 có chế độ
  `CYCLE:1` — xoay tên `VIETMAP-HUD, vmHUD, VIETMAP_HUD, HUD_V3, H50, H1AS,
  H1X, H1N` mỗi 5 giây trong lúc app đang mở màn quét. Xem
  [emu/esp32-hud-emu/README.vi.md](../emu/esp32-hud-emu/README.vi.md). Đã
  verify trên air từ PC bằng bleak: cả 5 tên đầu hiện xoay vòng đúng.
  - Một tên nào đó hiện trong app ⟹ chốt được tên Dart chấp nhận ⟹ đặt
    tên cố định, làm tiếp kết nối/HUDInfo/nav.
  - Không tên nào hiện sau ≥2 vòng trên cả hai máy ⟹ bộ lọc tên không phải
    nguyên nhân; ưu tiên bắt os_log trên iPhone jailbreak (mục 5 trên).

## Cách lấy bằng chứng chạy thật (bước tiếp theo rẻ nhất)

`flutter_blue_plus` ghi log có tiền tố `[FBP]`. Cắm tablet/điện thoại qua ADB
rồi lọc logcat trong lúc mở màn HUD và bấm quét:

```sh
adb logcat -c
adb logcat | findstr /i "FBP flutter_blue_plus BluetoothAdapter ScanFilter vietmap_hud"
```

Thấy `[FBP] startScan` chứng minh màn HUD đi đường **BLE**; chỉ thấy
`startDiscovery`/`flutter_bluetooth_serial` thì đó là **Classic** và board
BLE-only không dùng được cho họ đó. Không thấy dòng nào mà cũng không có kết
quả quét thì kiểm quyền theo mục suy ra số 3 trước khi sửa firmware.

Đối chiếu song song bằng `emu/esp32-hud-emu/record_app_trial.py`, công cụ này
tự phân biệt nấc hỏng: quảng bá → kết nối → subscribe → HUDInfo → nav.
