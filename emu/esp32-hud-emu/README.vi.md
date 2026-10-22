# Thử VIETMAP LIVE bằng ESP32-C3 giả lập HUD BLE

Board **ESP32-C3 Mini/Super Mini 4MB** dùng được làm BLE peripheral. Công cụ
này quảng bá `VMHUD-EMU`, cung cấp hai họ GATT HUD, trả HUDInfo và ghi lại
khung app gửi. C3 không có Bluetooth Classic/SPP.

Ngày 22-10-2026 đã chạy `ble_central_probe.py` từ PC Windows qua **radio BLE
thật** trên board đã nạp ảnh khớp source: **22/22 check pass** cho cả hai họ
thiết bị (quảng bá, kết nối, subscribe, HUDInfo có kiểm checksum, nav tiếng
Việt qua ghi phân mảnh 20 byte, heartbeat CRC16 legacy, kết thúc dẫn đường).
**Vẫn chưa có bằng chứng VIETMAP LIVE tìm thấy/chấp nhận thiết bị, và chưa
xuất dữ liệu lên HUD Mazda.** PC đóng vai central không thay được app thật.

Mục tiêu trước mắt: kiểm VIETMAP LIVE trên điện thoại của chủ xe có nhận
profile này và gửi dẫn đường hay không. Việc đó độc lập với BlueZ/kernel CMU.
Không nhận được dẫn đường chưa chứng minh máy chủ từ chối serial.

## Nạp binary có sẵn

Giải nén `vietnav-esp32c3-hud-trial.zip`, mở terminal tại thư mục có
`vmhud-c3-merged.bin`. Cần Python và cáp USB truyền dữ liệu. Ví dụ Windows:

```sh
python -m pip install esptool==5.1.0 pyserial==3.5
python -m esptool --chip esp32c3 --port COM7 write-flash 0x0 vmhud-c3-merged.bin
```

Đổi `COM7` thành cổng board; Linux thường là `/dev/ttyACM0`, macOS là
`/dev/cu.usbmodem…`. Đây là ảnh **toàn bộ flash 4MB**, ghi từ `0x0`; thay
firmware và dữ liệu NVS đang có trên board. Nếu chưa vào được bootloader:
giữ **BOOT**, bấm/thả **RESET**, thả BOOT rồi chạy lệnh. Sau nạp bấm RESET để
chạy ứng dụng; cổng USB có thể đổi tên khi chuyển từ bootloader sang CDC.

Dùng **`vmhud-c3-merged.bin`** cho lần thử đầu. File
`vmhud-c3-extended-experimental.bin` chỉ thêm quảng bá mở rộng để quan sát
scan request; chưa có kiểm chứng phần cứng và không cần cho bài thử chính.
Mỗi ảnh có checksum trong `BUILD-REPORT.json`/`SHA256SUMS`; source đi kèm
trong `source/`. Không dùng ảnh này cho ESP32 thường, S2 hay S3.

## Kiểm board qua BLE thật, không cần điện thoại

Chạy trước khi thử app: nếu bước này fail thì lỗi nằm ở board/firmware, không
phải ở app. Cần `python -m pip install bleak` (và `pyserial` cho `--port`).

```sh
python emu/esp32-hud-emu/ble_central_probe.py --port COM3 --log out/ble-probe.json
```

PC đóng vai central thay app: quét theo tên, kết nối, subscribe, yêu cầu
HUDInfo, rồi gửi nav tiếng Việt, heartbeat legacy và lệnh kết thúc dẫn đường.
Mỗi khung được ghi thành từng đoạn 20 byte để kiểm đúng đường gom mảnh ở ATT
MTU mặc định 23. Có `--port` thì Serial log của board được in theo từng bước.
Thoát khác 0 nếu có check fail; `--log` ghi transcript JSON để đối chiếu sau.

Thêm `--family h1` hoặc `--family h50` nếu chỉ muốn thử một họ, `--address` để
bỏ qua quét, `--current-road`/`--next-road` để đổi tên đường thử.

**Giới hạn:** bài này xác nhận board, GATT và định dạng khung. Nó **không**
chứng minh VIETMAP LIVE quét thấy hay chấp nhận thiết bị — bộ lọc, cấp quyền
và nhánh profile của app chỉ kiểm được bằng phiên app thật ở mục dưới.

## Lấy log và thử trong app

Từ thư mục giải nén, chạy:

```sh
python source/emu/esp32-hud-emu/capture_serial.py COM7 capture.txt
```

1. Bấm RESET trên board khi công cụ đã mở cổng. Nếu USB mất cổng, chạy lại
   công cụ với cổng mới và tên file mới; file cũ được giữ nguyên.
2. Trong **VIETMAP LIVE → HUD/Bluetooth**, quét và chọn `VMHUD-EMU`. Ghi lại
   phiên bản app, loại điện thoại và mọi thông báo kết nối/cấp quyền.
3. Bắt đầu tuyến có rẽ và đổi tên đường; đối chiếu mũi tên, tên đường,
   khoảng cách trên app với log. Giữ log cả khi không tìm thấy/kết nối được.
4. Dừng bằng Ctrl+C. Giải mã log ra JSON Lines:

```sh
python source/emu/esp32-hud-emu/decode_log.py capture.txt > capture.jsonl
```

Có thể dùng Serial Monitor 115200 của Arduino IDE thay công cụ capture.
Chọn kết thúc dòng **Newline** để gửi `STATUS` và `PING`; đóng Monitor trước
khi mở capture vì chỉ một chương trình được giữ cổng Serial. `PING` kiểm một
vector khung chuẩn trong firmware, không kiểm đường truyền BLE.

| Log | Đọc kết quả |
| --- | --- |
| `[ADV] connectable start OK` | Stack board nhận yêu cầu quảng bá; cần điện thoại quét thấy để xác nhận ngoài thực tế |
| `[BLE] connected` | Có central kết nối; đối chiếu thao tác trên điện thoại để xác định ứng dụng |
| `[BLE] notify FFF1/1234 sub=0x0001` | App/central đã bật notify |
| `[W:FFF2]`, `[W:FFF3]`, `[W:9ABC]` | Byte ghi từ central, giữ nguyên cả dòng hex |
| `[EMU] HUDInfo via …` | Đã gửi phản hồi HUDInfo vào hàng đợi notify |
| `[NAV] … cur="…" next="…"` hoặc JSON `type=navigation` | Nhận và giải mã được payload dẫn đường |
| `[SCAN] …` ở bản extended | Có active scanner gửi yêu cầu, **không xác định được đó là VietMap**; không thấy dòng này cũng không chứng minh app không quét |

Nếu app chưa gửi nav, kiểm lần lượt: quét thấy → kết nối → subscribe → yêu
cầu/đáp HUDInfo → bắt đầu tuyến → lỗi app. Giữ profile mặc định cho lần đầu;
đừng đổi serial/model liên tục trước khi có một log đầy đủ. Không cần mua HUD
thật để làm bài thử này.

## Cấu hình qua Serial

Các lệnh là **mỗi lệnh một dòng**, không kèm chú thích:

```text
STATUS
PING
MODEL:H50
HW:1.0.0
FW:1.0.0
PROTOCOL:2.2.2S
SID:VMEMU0000001
NAME:VMHUD-EMU
ADV:BOTH
MFG:<hex>
CYCLE:1
```

### CYCLE: xoay vòng tên để dò bộ lọc tên của app

Phân tích tĩnh (xem `docs/hud-dart-layer-analysis.vi.md`) cho thấy tầng SDK
iOS chấp nhận mọi tên chứa `HUD`, nên nghi vấn còn lại là tầng Dart lọc tên
chặt hơn. `CYCLE:1` cho board **tự đổi tên mỗi 5 giây** theo danh sách
`VIETMAP-HUD, vmHUD, VIETMAP_HUD, HUD_V3, H50, H1AS, H1X, H1N` (lưu NVS, áp
dụng cả sau RESET; `CYCLE:0` trả về tên gốc). Danh sách cố định trong
firmware, cố tình gồm cả tên không chứa `HUD` mà lệnh `NAME:` từ chối. Xoay
tạm dừng khi có điện thoại đang kết nối.

Cách thử: gửi `CYCLE:1`, mở màn **Cài đặt → HUD → Kết nối thiết bị** của
VIETMAP LIVE, giữ nguyên màn hình **ít nhất 1 phút** (8 tên × 5 giây = 40
giây một vòng). Nếu một tên được Dart chấp nhận, nó sẽ hiện trong danh sách;
đọc log serial dòng `[CYCLE] i/8 name=...` để biết tên đang active lúc đó.
Nếu không tên nào hiện sau ≥2 vòng trên cả iPhone và tablet Android thì bộ
lọc tên không phải nguyên nhân (hoặc app không quét) — chuyển sang bắt
log/runtime trên máy jailbreak.

Cấu hình lưu vào NVS và giữ qua RESET/mất điện. `NAME` áp dụng sau RESET,
những trường khác dùng trong đáp HUDInfo tiếp theo; ngắt/kết nối lại app để
app đọc lại. NAME tối đa 20 byte, chứa `HUD`, không chứa `TPMS`. Giá trị khác
tối đa 64 byte, không chứa dấu `,` hoặc `:`. SID mặc định là danh tính thử,
không bảo đảm app/máy chủ chấp nhận. SID cũng không phải UID dùng tính checksum.

Giữ PROTOCOL 2.2.2S để thử nhánh dẫn đường Android; bảng SDK Android coi 1.6
là profile tối thiểu không có nav. Không suy rộng điều này cho mọi nhánh iOS.
H50/Dart và H1/native có thể chọn profile khác nhau; cần log thật để chốt.

## Build lại từ source

Đã compile bằng **Arduino CLI 1.3.1**, **Arduino-ESP32 3.3.2**,
**NimBLE-Arduino 2.3.7**. Trong source/repo gốc:

```sh
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.2 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli lib install NimBLE-Arduino@2.3.7
python emu/esp32-hud-emu/build.py --out out/c3-build
```

Script kiểm phiên bản, build, đóng ZIP kèm source/checksum, không nạp board.
Có thể thêm `--cli /path/arduino-cli --config /path/arduino-cli.yaml`.
Thêm `--extended` nếu cần bản scan diagnostic; script truyền cả hai macro
`CONFIG_BT_NIMBLE_EXT_ADV=1` và `CONFIG_BT_NIMBLE_MAX_EXT_ADV_INSTANCES=2`
cho C/C++, không cần sửa thư viện. Thư mục kit đã có sẽ bị từ chối ghi đè.

Với Arduino IDE: mở `vmhud_emu/vmhud_emu.ino`, cài đúng core/library trên,
chọn **ESP32C3 Dev Module**, **USB CDC On Boot: Enabled**, flash 4MB,
**Flash Mode: DIO**, partition mặc định. IDE mặc định build bản quảng bá legacy.

## Giao thức và giới hạn

- H1/DJBT: service FFF0, FFF2/FFF3 write, FFF1 notify, FFF4 dự phòng.
  H50: service FFFF, 9ABC write, 1234 notify. Cả tên và UUID được đặt trong
  gói quảng bá primary legacy để hỗ trợ cả passive scan.
- Một central tại một thời điểm; hai buffer nhận riêng theo họ thiết bị.
  Nhận tối đa 4096 byte/khung, kiểm checksum mặc định/CRC và mọi độ dài trước
  khi đọc. Ảnh mũi tên lớn hơn giới hạn sẽ bị loại và có log.
- Khung mới C3 có trailer **8 byte** (hai checksum 4 byte từ MD5+UID), không
  phải MD5 thô 16 byte. Khung cũ C5 dùng CRC16. Phản hồi chia notify **20 byte**
  để hoạt động với ATT MTU mặc định 23; chưa giả định app chấp nhận phản hồi.
- HUDInfo trả chuỗi MODEL/HW/FW/PROTOCOL/OBDV/SID. Checksum runtime dùng UID
  zero cho thí nghiệm, phần default UID đúng SDK. Chưa biết UID phiên thực;
  nếu app kiểm phần runtime sẽ cần thêm phân tích, không dùng SID thay UID.
- Fixed/variable1/variable2 được phân loại theo protocol và command; hỗ trợ
  ảnh custom variable2. Byte thời gian thứ ba của variable giữ raw, không
  tự coi là giây. Mã direction và đơn vị speed cần đối chiếu trên điện thoại.
- Chỉ đáp yêu cầu HUDInfo; heartbeat/camera/navigation được ghi log. Chưa
  giả định cần một cơ chế heartbeat reply khi chưa có capture xác nhận.
- Không ghép nối/bonding tự động; profile yêu cầu bảo mật hoặc hành vi khác
  có thể cần bổ sung sau khi xem log. Serial log là công cụ thử, chưa phải
  cầu nối thời gian thực cho xe.

Kiểm codec trên host (cần C++17, OpenSSL dev, ASan/UBSan và Python):

```sh
python -m unittest discover -s tests -p 'test_esp32_hud.py' -v
python -m unittest discover -s tests -p 'test_vmlhud_bridge.py' -v
python bridge/vmlhud_frame_test.py
python bridge/vmlhud_nav_test.py
```

Kiểm gồm vector SDK cố định, đối chiếu Python/C++, khung chia/gộp, dữ liệu
hỏng/độ dài giả, ảnh JPEG, UTF-8 và 50.000 đầu vào fuzz có sanitizer. Các kiểm
tra này và build firmware chưa thay thế thử radio, app VietMap hay HUD Mazda.
