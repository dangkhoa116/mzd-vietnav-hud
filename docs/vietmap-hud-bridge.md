# Cầu nối VIETMAP LIVE → HUD zin qua đường HUD BLE

Mục tiêu: đưa **dẫn đường VIETMAP LIVE (có tên đường)** lên HUD zin của Mazda,
giống sản phẩm "VML HUD" đang bán ngoài thị trường (ví dụ Bamboo Auto). Đây là
đường **duy nhất có đủ tên đường** — hơn hẳn CarPlay (iOS không gửi gì) và
Android Auto (tên đường là `--`). Xem [vietmap-hud-gap.md](vietmap-hud-gap.md).

Phạm vi: tương thích thiết bị của **chính khách** — xe của họ, điện thoại của họ,
app VIETMAP LIVE họ tự cài. Không bẻ khoá máy chủ Vietmap; nếu bước cấp quyền
khoá cứng theo serial thật thì dùng **HUD Vietmap thật làm mỏ neo** (mục "Hai
nhánh" bên dưới), không giả mạo thiết bị.

## Kiến trúc

```
VIETMAP LIVE (điện thoại khách, BLE central)
   │  quét thiết bị có tên chứa "HUD", kết nối
   │  service FFF0:  FFF2 ghi  /  FFF1 notify
   ▼
vmlhud-bridge   (daemon trên CMU, BLE peripheral)
   │  1. quảng bá tên "...HUD..."; expose FFF0/FFF1/FFF2
   │  2. trả getHUDInfo (CMD 0x0E), đáp heartbeat (0x02)
   │  3. nhận sendNavigationInformation (0x00) → giải mã khung A5 5A 37 C3
   │  4. decode payload → hướng rẽ, tên đường, khoảng cách, tốc độ, biển báo
   ▼
com.jci.vbs.navi   (MQ sẵn có — cầu CarPlay đang bơm vào đây)
   ▼
HUD zin (Active Driving Display)
```

Phần **đầu ra** (`com.jci.vbs.navi` → HUD, kèm bản vá tên đường VN dài trong
`patches/oem-aa-mod/`) repo đã có. Việc mới chỉ là **đầu vào BLE**.

## Thành phần trong repo

| File | Vai trò | Trạng thái |
| --- | --- | --- |
| `bridge/vmlhud_frame.py` | Mã hoá/giải mã khung `A5 5A 37 C3` (magic, length, timestamp, CMD, payload, MD5) | **Xong**, 36/36 test pass. Lớp khung đã xác nhận từ static analysis |
| `bridge/vmlhud_nav.py` | Giải mã payload dẫn đường → struct trung lập | **Scaffold** — offset trường CHƯA chốt, chờ capture |
| `bridge/vmlhud_frame_test.py` | Test tự nhất quán của lớp khung | Xong |
| (chưa có) `bridge/vmlhud-bridge` | Daemon BLE peripheral trên CMU (BlueZ GATT) + inject `com.jci.vbs.navi` | Chờ chốt giao thức |

## Việc #1 — bắt một phiên thật (quyết định mọi thứ)

Static analysis cho **cấu trúc khung** (đã chắc) nhưng **không cho offset từng
trường trong payload dẫn đường** cho chắc. Phải bắt một phiên thật:

1. **Mua một HUD rời Vietmap thật** (H1AS/H1X/H50… — vài trăm nghìn). Đây vừa là
   nguồn capture, vừa là mỏ neo cấp quyền hợp lệ cho nhánh B.
2. Trên Android: bật **Developer options → Enable Bluetooth HCI snoop log**, chạy
   VIETMAP LIVE kết nối HUD thật, dẫn đường một đoạn có rẽ + đổi tên đường, rồi
   lấy `btsnoop_hci.log` (qua bug report).
3. Mở bằng Wireshark, lọc ATT ghi vào characteristic `FFF2`. Mỗi gói bắt đầu
   `a5 5a 37 c3` là một khung — `vmlhud_frame.parse()` tách được ngay.
4. Đối chiếu nội dung dẫn đường đang hiện trên app với byte trong payload CMD
   `0x00` để **chốt offset**: hướng rẽ, khoảng cách, tên đường hiện tại/tiếp
   theo, thời gian/quãng còn lại, tốc độ; và CMD camera cho biển báo tốc độ.
   Điền vào `decode_nav_fixed`/`decode_nav_variable`, thêm test với chính byte
   capture được.

Không có HUD thật thì chỉ dừng ở lớp khung; không thể bảo đảm đúng trên xe khách.

## Việc #2 — test bước cấp quyền (xác định nhánh A hay B)

App có luồng xin quyền phía máy chủ (`/v20/hud/UpdatePermission`, `verifyHUD`,
`onInvalidHUDConnected`, "HUD not start auto connect when unauth" — xem
[vietmap-hud-sdk.md](vietmap-hud-sdk.md)). Câu hỏi: nó **khoá cứng** hay chỉ
**đăng ký dễ dãi**? Sản phẩm bán ngoài chợ ⇒ nhiều khả năng dễ dãi. Kiểm chứng:

- Trong `btsnoop` ở Việc #1, xem app có gọi API cấp quyền **trước khi** gửi
  dẫn đường không, và serial nó đọc từ HUD nằm ở đâu (đáp `getHUDInfo` 0x0E).
- Cho daemn CMU quảng bá tên `...HUD...`, trả `getHUDInfo` với **cùng serial của
  HUD thật mình đang sở hữu** (serial của chính mình, không bịa của người khác),
  xem app có chịu gửi dẫn đường không.
  - **Chịu gửi ⇒ nhánh A.** Server chỉ đăng ký, không khoá. CMU đóng vai HUD
    trực tiếp, không cần phần cứng thêm. (Gần như chắc đây là cái Bamboo Auto làm.)
  - **Không gửi ⇒ nhánh B.** Server khoá theo serial hợp lệ. Không bịa serial.

## Hai nhánh

**Nhánh A — CMU đóng vai HUD (nếu cổng cấp quyền dễ dãi).**
`vmlhud-bridge` là BLE peripheral đầy đủ: quảng bá, `getHUDInfo`, heartbeat, nhận
dẫn đường, inject HUD. Khách chỉ cần bật VIETMAP LIVE + BLE. Không phần cứng thêm.

**Nhánh B — cầu nối từ HUD thật (nếu cổng khoá cứng).**
Để HUD Vietmap thật kết nối app bình thường (được cấp quyền thật), CMU **nghe
cùng phiên BLE** / đặt giữa (app ↔ HUD thật), đọc khung dẫn đường **của chính
người dùng trên thiết bị của họ**, rồi inject lên HUD zin. HUD thật nằm trong
vòng nên không giả mạo gì. Tốn thêm một HUD rời nhỏ nhưng chắc chắn hợp lệ.

Cùng một `vmlhud_frame.py` + `vmlhud_nav.py` dùng cho cả hai nhánh; chỉ khác chỗ
daemon lấy byte từ đâu (tự nhận hay nghe ké).

## Việc #3 — daemon trên CMU

- BLE peripheral: MZD Connect dùng **BlueZ**. Cần xác nhận CMU đăng ký được một
  GATT server / advertise song song với HFP/A2DP cho điện thoại. Kiểm trên emu
  hoặc rootfs firmware trước (xem `docs/emu-yeu-cau.md`).
- Inject: dùng đúng đường `com.jci.vbs.navi` mà cầu CarPlay đang dùng — đọc cách
  nó đóng gói guidance rồi tái sử dụng.
- Đóng gói: thêm một kit cài USB thứ ba bên cạnh AA/CarPlay, cùng cơ chế
  `install-patches.sh` (màn chọn kit đã có).

## Ranh giới

Tài liệu và mã ở đây **không** mô tả cách qua mặt bước xác thực của máy chủ
Vietmap. Nếu Việc #2 cho thấy server khoá cứng, đi **nhánh B** (HUD thật làm mỏ
neo), không bịa/forge serial của thiết bị người khác.
