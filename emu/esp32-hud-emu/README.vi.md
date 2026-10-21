# ESP32 giả lập "VIETMAP HUD" (công cụ thí nghiệm)

Phục vụ hai việc đang treo trong [docs/vietmap-hud-bridge.md](../../docs/vietmap-hud-bridge.md):

1. **Việc #2 — thử bước cấp quyền (nhánh A hay B).** App đọc `SID` (serial) từ
   đáp `getHUDInfo` rồi hỏi máy chủ Vietmap (`/v20/hud/UpdatePermission`).
   Emulator trả `SID` do mình cấu hình:
   - App **vẫn gửi dẫn đường** ⇒ nhánh A (server đăng ký dễ dãi) — CMU có thể
     tự đóng vai HUD, không cần phần cứng thêm.
   - App **dừng gửi / báo HUD không hợp lệ** ⇒ nhánh B (cần HUD thật làm mỏ neo).
2. **Việc #1 — chốt offset runtime + bảng mã hướng rẽ.** Layout payload đã chốt
   tĩnh ([bridge/vmlhud_nav.py](../../bridge/vmlhud_nav.py)); chạy dẫn đường thật
   với emulator để đối chiếu byte `direction` với mũi tên hiển thị trên app.

Firmware dùng thư viện **NimBLE-Arduino** (nhẹ, connect iOS ổn định, chạy được
trên mọi ESP32 kể cả **ESP32-C3 Super Mini**). Không cần dây cắm thêm gì —
board cắm USB là chạy.

## Nạp và chạy (ESP32-C3 Super Mini)

1. Arduino IDE:
   - *Boards Manager* → cài **esp32 by Espressif Systems**.
   - *Library Manager* → cài **NimBLE-Arduino** (bản 2.x).
2. Mở `vmhud_emu/vmhud_emu.ino`. Chọn:
   - Board: **ESP32C3 Dev Module**
   - **USB CDC On Boot: Enabled** (bắt buộc với Super Mini — Serial đi qua
     cổng USB-C tích hợp; nếu để Disabled sẽ không thấy log).
   - Flash Size: 4MB (mặc định), Partition Scheme: mặc định.
3. Nạp, mở *Serial Monitor* **115200**.
4. Điện thoại: **VIETMAP LIVE → HUD/Bluetooth → quét → kết nối "VMHUD-EMU"**,
   bật dẫn đường một tuyến có rẽ + đổi tên đường.
5. Đọc log: mỗi khung app ghi vào FFF2/FFF3 hiện `[W:FFF2] .. byte: <hex>`,
   khung tách xong hiện `[RX ] CMD .. : <hex>`, khung dẫn đường hiện thêm
   `[NAV] layout dir=.. dist=.. cur=".." next=".."` — đối chiếu `dir` với
   mũi tên đang vẽ trên app.

## Lệnh cấu hình qua Serial (không cần nạp lại)

```
MODEL:H50          # ten model tra trong getHUDInfo (H1AS / H1X / H50 ...)
HW:1.0.0
FW:1.0.0
PROTOCOL:2.2.2S     # 2.2.0/2.2.1/2.2.2/2.2.2S = co dan duong; "1.6" = ban toi
                    # thieu, app KHONG gui dan duong (chi heartbeat)
SID:VMEMU0000001   # serial; nhanh B: dung serial HUD that cua minh
NAME:VMHUD-EMU     # ten quang ba (phai chua "HUD", khong chua "TPMS")
STATUS             # xem cau hinh hien tai
PING               # in thu mot khung giai ma mau
```

Lưu ý: đổi `NAME:` chỉ ghi vào bộ nhớ — tên quảng bá áp dụng sau khi nạp lại
(những tham số còn lại áp dụng ngay cho đáp `getHUDInfo` tiếp theo).

## Ghi chú kỹ thuật

- GATT: service `FFF0`; `FFF1` notify (đáp getHUDInfo, log khi app subscribe),
  `FFF2` write (đường chính), `FFF3` write (nhánh phụ), `FFF4` notify (TPMS) —
  đủ để app thấy "thiết bị HUD" đầy đủ.
- Đáp `getHUDInfo` là **chuỗi text** `MODEL:..,HW:..,FW:..,PROTOCOL:..,OBDV:.._..,SID:..`
  (tách bằng "," rồi ":") — chốt từ `HUDInfoWithDataString:` trong
  `vietmap_hud_sdk.framework`; app chỉ cần `MODEL` khác rỗng là chấp nhận.
- MD5 trên khung **nhận** không được app dùng để từ chối (chỉ tính rồi bỏ qua),
  nên emulator không verify MD5 khung nhận; khung gửi vẫn kèm MD5 đúng chuẩn.
- App có thể chia khung lớn thành nhiều lần ghi (log SDK có "Chunk written") —
  emulator gom byte theo magic `A5 5A 37 C3` rồi tách khung tròn, giống
  `vmlhud_frame.split_stream`.
- ESP32-C3 Super Mini: không cần NTP; timestamp trong khung gửi lấy từ đồng hồ
  hệ thống (bắt đầu 1970) — app không kiểm tra giá trị này.

## Kết quả kỳ vọng

| Quan sát | Kết luận |
| --- | --- |
| App kết nối, nhận `getHUDInfo`, **gửi CMD 0x00/0x40 có tên đường** | Nhánh A — build daemon CMU (raw-HCI hoặc SPP) bơm thẳng `com.jci.vbs.navi` |
| App kết nối nhưng **dừng sau khi hỏi quyền**, không gửi nav | Nhánh B — mua HUD thật làm mỏ neo, nghe ké phiên BLE của chính mình |
| App không chịu kết nối dù tên đúng | Đối chiếu thêm bộ lọc quét của app (tên chứa "HUD"), thử NAME/MODEL khác |
