# Phân tích cập nhật HUD trong VIETMAP LIVE 3.4.3

Ngày kiểm: 22-10-2026, giờ Việt Nam. Phân tích tĩnh trên bản app của chủ xe;
chưa chạy một phiên cập nhật trên điện thoại và chưa tải được firmware.

## Nguồn và khả năng tái kiểm

- XAPK local: `C:/work/mazda/VIETMAP+LIVE+-+MiMi+AI_3.4.3_APKPure.xapk`.
- Java đã decompile: `C:/work/mazda/work/analysis/apk/out/sources/`.
- iOS đã giải: `C:/work/mazda/work/ipa/extracted/Payload/Runner.app/`.
- XAPK SHA256: f6b32f14ffa110f413cd3550c6f54c39ba8a102a08295adc97bbcaad00340231.
- Android libapp.so SHA256: 960025049b46c76add2b915010d2e3fbb1a473d0b4fe5220e4f685416f32900d.
- Binary, app và token không đưa vào Git.

## Điều đã xác nhận

### API và tài nguyên

Android `libapp.so` chứa `/hud/updatefirmware` tại file offset `0xb8c13`,
`/v20/hud/updatefirmware` tại `0x1f317e`, `Firmware.GetFirmwares`,
`HUDFirmwareState.needUpdate`, `remoteFirmwareInfo`, `localFirmwareInfo`,
`downloadUrl` và `fileUrl`. Các chuỗi này chưa đủ để khẳng định quan hệ gọi
hàm hay schema JSON cụ thể.

GET `https://api.vietmap.live/production/v20/hud/updatefirmware` trả 405.
POST `{}` với Content-Type application/json trả 401, body trống.
Đây là request thử chưa xác thực, CHƯA phải request đã phục dựng đúng của app.
Không từ 401 suy ra cần HUD thật, SID thật hoặc quyền server cụ thể.

Không tìm thấy firmware HUD dạng `.bin`, `.hex` hay `.fw` trong APK chính
và split arm64. Không coi AssetManifest.bin hoặc DebugProbesKt.bin là firmware.
Đã xác định `/fwhud/fwnew.bin` là đường dẫn lưu local; xem bằng chứng iOS bên dưới.

### Cầu nối Flutter sang native Android

`Ma/b.java:815` nhận `updateOTAWithFilePath` với đối số String đường dẫn;
null phát `updateOTAFailure=wrong_params`. Dòng 824 gọi `U7.f.o(...).a(path,...)`.
`U7/f.java:71` mở `FileInputStream(new File(path))`: đây là FILE LOCAL,
không phải hàm tải HTTP. Reader chia block 1024 byte, bỏ block đầu,
copy các block sau thành buffer. Cách đọc này có thể padding zero cho block cuối;
không khẳng định 1024 byte đầu có schema gì khi chưa có mẫu file.

`Ma/b.java:827` nhận `sendOTAPacketData`, các khóa đã xác nhận:
`index` (Integer), `total` (Integer), `dataPacket` (byte[]).
Đây là tham số METHOD CHANNEL, KHÔNG phải body API HTTP.
Nó chuyển qua `U7/e.java:200` tới `U7.b.S(...)`.

### Đóng gói họ protocol 2.2.2S (W7/e.java)

- `S` tại dòng 827 chuyển index từ zero-based sang one-based rồi gọi `i0`.
- `i0` tại dòng 271: payload = `F0 | total:u16BE | index:u16BE | data | MD5(data):16`;
  tiếp đó bọc bằng frame SDK `p010a8.c.f`.
- `g0` tại dòng 249 có bố cục tương tự, CMD `F2`.
- `v` tại dòng 1317 chia buffer 4096 byte, dùng CMD F0.
- `P` tại dòng 736 chia buffer 4096 byte, dùng CMD F2.
- MD5 của CHUNK 16 byte ở đây khác checksum8 của FRAME ngoài. Không nhầm hai lớp.
- Không suy rộng các builder W7/e cho mọi firmware H50/Dart.

Có nhánh IAP riêng: `U7/a.java:910` nhận `BOOTIAP`, trả `ATFWUPDATE\r\n`,
sau ACK `ATFWUPDATE` gửi `UPDATECONF\r\n`. `W7/e.java:1371` chia IAP thành
1152 byte, padding FF; `b0` dòng 75 tạo `FW | index:u16LE | data | CRLF`,
gói cuối mang index FFFF. Đây là nhánh riêng, chưa khẳng định là nhánh app
chọn khi cập nhật HUD hiện tại.

## Trạng thái thử BLE và thiết bị local

- PC quét thấy tên VMHUD-EMU, UUID FFF0 và FFFF; kết nối GATT thành công.
- Firmware đang chạy không trùng source bàn giao: probe FFF2 không có phản hồi;
  nhánh H50 trả 100 byte trong khi lenfield=84 yêu cầu tổng 92 byte.
  Chưa suy ra đây là nguyên nhân VIETMAP không hiển thị thiết bị.
- Người dùng báo VIETMAP LIVE 3.4.3 trên Android và iOS đều không thấy board
  trong màn HUD. Các kết nối Bleak từ PC không phải bằng chứng app đã kết nối;
  SCAN cũng không xác định được scanner là ứng dụng nào.
- ADB đã kết nối tablet Samsung SM-X236B, package vn.vietmap.live 3.4.3,
  versionCode 179094172. Không commit serial thiết bị, screenshot bản đồ hay log.
- run-as bị từ chối vì package không debuggable. Log giới hạn theo PID app
  không có Bearer token hoặc request OTA trong lần đọc. USB debugging chưa
  cung cấp nội dung HTTPS. Chưa cấu hình proxy hoặc cài CA trên tablet.
- Chưa tải được firmware HUD, chưa flash board/xe và chưa nhận nav từ app.

## Cập nhật sau khi cài REA và đọc object pool iOS

Các địa chỉ dưới đây thuộc App.framework/App của bản iOS đã phân tích.
Chưa có response có xác thực và chưa tải được firmware.

### Công cụ đã chạy

- REA 6.7.0 cài trong `../rea-tools/runtime/node_modules/rea-agents`.
  MCP đăng ký trong `C:/Users/ADMIN/.codex/config.toml`, bản sao lưu
  `config.toml.rea.backup`. Skill cài tại
  `C:/Users/ADMIN/.agents/skills/reverse-engineer-anything`.
  Setup trả `ready`. MCP chưa xuất hiện trong phiên đang chạy; CLI đã chạy.
- `inspect-dart-aot` và `identify-flutter-build` chạy trên split arm64 APK:
  snapshot hash `f71c76320d35b65f1164dbaa6d95fe09`, FullAOT kind 3;
  đây là họ Dart 3.2.x, không xác định được patch chỉ từ hash.
- DAE 0.1.13 bổ trợ đọc snapshot: Android báo lỗi UnexpectedEof tại cluster
  CID 23; không dùng kết quả đó. Bản iOS đọc được VM+isolate, 99.447
  instruction-table entries; không có warning parser. Điều này không tự chứng
  minh mọi xref/pseudocode đúng.
- DAE findrefs bỏ sót chuỗi ở các slot object pool lớn trong bài này.
  Đã đọc lại stream ObjectPool iOS ở file offset `0x1dd1c9f`, 160.386 entry;
  điểm kết thúc khớp cluster tiếp theo `0x1e620d2`. Đối chiếu các ref ID với
  bảng strings và đọc cặp lệnh ARM64 `ADD PP+high; LDR low` bằng Capstone.
  Không coi xref gần nhất theo bảng tên obfuscation là ranh giới hàm đã xác minh.

### Request đã xác nhận từ disassembly iOS

Tại `0x1757a5c`, code gọi serializer `0x6542b0`, đặt method `POST` tại
`0x1757b14`, nạp `/v20/hud/updatefirmware` tại `0x1757b8c`.
Serializer tạo map với sáu khóa (giá trị lấy từ object tham số):

```json
{
  "model": "<model>",
  "hardwareVersion": "<hardwareVersion>",
  "firmwareVersion": "<firmwareVersion>",
  "obdModel": "<obdModel>",
  "obdVersion": "<obdVersion>",
  "serialNumber": "<serialNumber>"
}
```

Các địa chỉ nạp khóa: `0x6542d8`, `0x6542f0`, `0x654304`, `0x654318`,
`0x65432c`, `0x654340`. Đây là body HTTP serializer của nhánh iOS,
khác `index/total/dataPacket` ở MethodChannel native.

URL production đã probe vẫn là
`https://api.vietmap.live/production/v20/hud/updatefirmware`.
POST chưa có xác thực trả 401; chưa gửi request có body trên bằng tài khoản.
Có `serialNumber` trong schema không chứng minh server yêu cầu serial thật
hay đã cấp quyền cho board; chưa biết quy tắc kiểm phía server.

### Response model

Deserializer bắt đầu `0x653ac8` đọc các khóa sau:

- `version` (`0x653b28`)
- `fileSize` (`0x653b88`)
- `iconUrl` (`0x653c14`)
- **`downloadUrl`** (`0x653c74`)
- `descriptions` (`0x653cd4`)
- `upgradeNotes` (`0x653dac`)
- `force` (`0x653e84`)
- **`allowTranferData`** (`0x653ee0`, đúng chính tả bị thiếu s trong binary)
- `allowGrantPermission` (`0x653f3c`)

Đã xác nhận tên trường của model, CHƯA có giá trị thực, chưa xác nhận lớp
wrapper response HTTP (ví dụ data/result) và chưa chứng minh các cờ quyết định
cho phép nav theo cách nào. Không tự diễn giải cờ thành cơ chế bypass/cấp quyền.

### File fwnew.bin

Hàm `0x16b5794` gọi helper lấy đường dẫn nền, nối chuỗi `/fwhud/fwnew.bin`
(`0x16b5804`) rồi tạo đối tượng file và gọi các thao tác filesystem. Điều này
cho thấy đây là đường dẫn lưu file local, không phải URL firmware cố định.
Không nối `/fwhud/fwnew.bin` với hostname để đoán link tải.

### Bằng chứng giữ ở out/ota-analysis (Git ignored)

`rea-dart-aot.json`, `rea-flutter-build.json`, `rea-doctor.json`,
`dae-ios-info.txt`, `dae-ios-fill.log`, `ios-ota-pool-mapping.json`,
`ios-ota-manual-xrefs.json`, `ios-ota-request-disasm.txt`,
`ios-ota-body-disasm.txt`, `ios-fw-response-disasm.txt`,
`ios-fw-path-disasm.txt` và các script `map_ios_ota_pool.py`,
`find_ios_ota_refs.py`, `annotate_ios.py`. DAE export gồm code obfuscation
và pseudocode chỉ là dữ liệu hỗ trợ, phải kiểm lại disassembly trước khi kết luận.

### Tái kiểm và công cụ đã lưu trong repo

Xem [tools/hud_ota/README.vi.md](../tools/hud_ota/README.vi.md).
`inspect_ios_pool.py` kiểm SHA256 của App.framework/App, đọc object pool và
xuất các cặp ADD/LDR liền nhau. Công cụ không phụ thuộc đường dẫn máy cũ.
`fetch_firmware.py` nhận body JSON và nhập token ẩn trên máy local; chưa có
kiểm chứng tải firmware thật. Các script thăm dò cũ trong out vẫn là dữ liệu
local ignored. Không commit APK/IPA, code decompile, log, token hoặc cấu hình MCP.

### Việc còn thiếu để tải firmware

Cần response từ một phiên VIETMAP LIVE được người dùng đăng nhập hợp lệ,
hoặc request có thông tin xác thực được chủ tài khoản cung cấp riêng trong
môi trường local. Không cần gửi OTP/mật khẩu vào chat. Sau khi có
`downloadUrl`, tải file và kiểm SHA256/header/kiến trúc. Chưa nạp board hoặc xe.

Nguồn công cụ: https://github.com/morluto/rea và https://github.com/ejfkdev/dae.


### Xác thực HTTP

Tại iOS `0x309428` code ghép chuỗi Bearer với giá trị runtime và đặt header
Authorization (`0x30945c`); có thao tác tương tự ở `0x3094d8`/`0x309504`.
Đây là bằng chứng header được lấy từ phiên đăng nhập, không phải token tĩnh
đã tìm được trong APK. Bằng chứng local: `ios-auth-interceptor.txt`.
