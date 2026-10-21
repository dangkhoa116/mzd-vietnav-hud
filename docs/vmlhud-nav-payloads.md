# Payload dẫn đường VIETMAP LIVE → HUD rời: layout đã chốt từ disassembly

Ngày: 21-10-2026 · Nguồn: `vietmap_hud_sdk.framework` (IPA `vn.vietmap.live`
3.4.3 build 179094172, framework không mã hoá FairPlay).

Phương pháp: parse Mach-O ARM64 (chained fixups, small method list) + map toàn
bộ `__objc_stubs` → selector + disassembly có chú thích của
`DJBTManager` (209 method). Bộ phân tích nằm ngoài repo
(`work/analysis/` của máy nghiên cứu: `macho.py`, `hudis.py`).

Kết quả: **offset payload dẫn đường đã chốt tĩnh**, không còn phụ thuộc mua HUD
thật mới decode được. Việc còn phải chạy thật: (a) bảng mã hướng rẽ
(`direction` byte → tên mũi tên), (b) xác nhận 2 byte cuối layout fixed, (c)
thí nghiệm bước cấp quyền — cả ba làm bằng emulator ESP32
(`emu/esp32-hud-emu/`).

## 1. Ba định dạng payload và đường gửi

Cùng một bộ tham số (direction, distance, nextRoad, currentRoad, remainTime,
remainDist, currentSpeed) được đóng gói theo **ba** layout, chọn lúc chạy:

| Layout | Builder | CMD | Nhánh gửi | Khi nào |
| --- | --- | --- | --- | --- |
| **fixed** (0xAF byte) | inline trong `insideSendNavigationInformation…` (0x48c4) | `0x00` | `sendParamDataProtocol_1_6WithData:andCMD:` | `self.hudInfo == nil` (chưa có đáp getHUDInfo) — kiểu HUD 1.6 cũ |
| **variable1** | inline trong `insideSendNavigationInformation…` (0x4804) | `0x00` | `sendParamData:andCMD:` | `self.hudInfo != nil` |
| **variable2** ("Simplify") | `SimplifyNavigationInformationData…` (0x5348) | `0x40` | `sendParamData:andCMD:0x40` | đường gửi mới (H50), hai caller (0x4ddc, 0x52ac) đều gửi CMD 0x40 |

Điểm chung: **mọi layout đều kết thúc bằng** `gio u16be + phut u8 + giay u8 +
quang u32be + toc_do u16be`; mọi số đa byte là **big-endian**; tên đường
UTF-8 (`dataUsingEncoding:4`).

## 2. Layout "fixed" — 0xAF (175) byte

```
[0]        u8    direction
[1..4]     u32be distance_m (met)
[5..0x54]  80B   next_road    UTF-8, cắt tại 0x50 byte, đệm 0x00
[0x55..0xA4] 80B current_road UTF-8, cắt tại 0x50 byte, đệm 0x00
[0xA5..0xA6] u16be remain_hours
[0xA7]     u8    remain_minutes
[0xA8]     u8    remain_seconds
[0xA9..0xAC] u32be remain_dist_m
[0xAD..0xAE] u16be speed_kmh   (suy đoán theo đối xứng; chưa đối chiếu runtime)
```

Việc cắt tên đường: nếu `len(utf8) > 0x4F` thì lấy 0x50 byte, sau đó
`memset` đệm 0 về hết 80 byte (code tại 0x46cc–0x47c8).

## 3. Layout "variable1" — CMD 0x00

```
[0]    u8    direction
[1..4] u32be distance_m
[5]    u8    len(next_road)
[6..]  next_road UTF-8 (đúng độ dài thật)
[..]   u8    len(current_road)
[..]   current_road UTF-8
[..]   u16be remain_hours; u8 remain_minutes; u8 remain_seconds
[..]   u32be remain_dist_m
[..]   u16be speed_kmh
```

## 4. Layout "variable2" (Simplify) — CMD 0x40

```
[0]     u8    direction
[1..4]  00 00 00 01        (hằng số, ghi bằng `movi v0.2s, #1, lsl #24`)
[5]     01                 (hằng số)
[6..9]  u32be distance_m
[10]    u8    len(next_road)
[11..]  next_road UTF-8
[..]    u8    len(current_road)
[..]    current_road UTF-8
[..]    u16be remain_hours; u8 remain_minutes; u8 remain_seconds
[..]    u32be remain_dist_m
[..]    u16be speed_kmh
```

Header `00 00 00 01 01` là dấu hiệu nhận biết tin cậy của variable2.

## 5. Đáp `getHUDInfo` (CMD 0x0E) là chuỗi text

`dataParsing` (0xd05c) tách khung: cần tổng dài ≥ `lenfield+8`, phần trong ≥
0xD; **CMD tại offset 12, payload tại [13..độ_dài-21]**. Nhánh `CMD == 0x0E`
(0xd49c → 0xdc98):

```
[[NSString alloc] initWithData:payload encoding:NSUTF8StringEncoding]
→ [self HUDInfoWithDataString:text]
→ nếu hudInfo.model == @""  ⇒ loại bỏ
```

`HUDInfoWithDataString:` (0x103ec) tách `text` bằng "," rồi ":", nhận **6 khoá**:

| Khoá | Vào trường DJHUDInfo |
| --- | --- |
| `MODEL` | model (bắt buộc khác rỗng) |
| `HW` | hardwareVersion |
| `FW` | firmwareVersion |
| `PROTOCOL` | protocol |
| `OBDV` | tách "_" → obdModel + obdVersion |
| `SID` | **serial** — thứ app đem lên `/v20/hud/UpdatePermission` |

Ví dụ đáp emulator: `MODEL:H50,HW:1.0.0,FW:1.0.0,PROTOCOL:1.6,OBDV:0_1.0,SID:VMEMU0000001`

## 6. MD5 trên khung NHẬN không dùng để gate

Trong `dataParsing`, MD5 được tính (0xd1dc–0xd1fc: subdata đuôi → hash →
`setGetData:`) nhưng **kết quả không ảnh hưởng luồng xử lý** — khung vẫn được
dispatch theo CMD dù hash không khớp. Chỉ hai điều kiện dài mới loại khung.
(Khung GỬI đi vẫn luôn kèm MD5 đúng — xem `vmlhud_frame.py`.)

Điều này giúp emulator: không cần MD5 chuẩn trong khung gửi đi cũng được app
chấp nhận (vẫn nên gửi chuẩn).

## 7. Bảng CMD đã thấy (app → HUD và HUD → app)

| CMD | Chiều | Ý nghĩa |
| --- | --- | --- |
| `0x00` | app → HUD | dẫn đường (fixed hoặc variable1) |
| `0x02` | app → HUD | heartbeat (payload mang tốc độ; gửi trên cả hai nhánh protocol) |
| `0x0E` | app → HUD | yêu cầu getHUDInfo (payload 1 byte) |
| `0x0E` | HUD → app | đáp getHUDInfo (payload text §5) |
| `0x40` | app → HUD | dẫn đường "Simplify" variable2 |
| `0x0B`,`0x0D`,`0x32`,`0x50`,`0x51`,`0x53`,`0x56`,`0x5A`,`0xF0`,`0xF2` | HUD → app | TPMS / OBD / OTA / cài đặt (dataParsing 0xd494–0xd518) |

## 8. Còn phải chốt bằng chạy thật (emulator ESP32)

1. **Bảng `direction`**: byte đầu mỗi payload. Phía Dart là
   `H50ManeuverType` (asset icon `lib/assets/hud/directions/…/direction_*`),
   ánh xạ tên → số chưa tách được khỏi Dart AOT; khi chạy, đối chiếu byte với
   mũi tên trên màn app.
2. **[0xAD..0xAE] của fixed**: suy là `speed u16be` theo đối xứng hai layout
   variable; xác nhận khi bắt được khung fixed.
3. **Bước cấp quyền** (`SID` → máy chủ): quyết định nhánh A/B của cả kiến trúc
   (xem `vietmap-hud-bridge.md`).
