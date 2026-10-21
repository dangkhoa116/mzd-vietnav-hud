# Tận dụng BLE của project TPMS để giả HUD ngay trên Mazda

Đối chiếu ngày 21-10-2026 với hai checkout `mzd-connect-tpms` và
`mzd-connect-tpms-research` trong workspace. **Có cơ sở để ưu tiên đường native
CMU. Đã bổ sung peripheral/ATT server riêng trong Vietnav; TPMS gốc giữ nguyên.**

**Trạng thái:** [bản native C/ARM](../native/README.md) đã có core, patch ghép
HCI và build bằng m3-toolchain/glibc 2.11. Đã kiểm PTY/preload trên host và
ARM/QEMU. Đã có [launcher USB thử riêng](../native/usb/README.md) với query
trước, chạy một lần, backup/rollback TPMS và thu log. Chưa thử radio/iPhone
thật hoặc có output VBS cho nhánh này.

## Bằng chứng đã có

- `mzd-connect-tpms/tpms/v3/README.md`, mục trip 14b: ghi nhận chạy chuỗi BLE
  trên xe, nhận **1001 và 1643 frame** từ hộp TPMS. Đây là kết quả được ghi
  trong tài liệu dự án, không phải buổi thử mới trong phiên làm việc này.
- `tpms/v3/v3.c`: preload vào `bds`, dùng chung UART `/dev/ttymxc3`, nạp
  service pack có BLE qua cơ chế đổi file đọc khi `bds` khởi tạo. Không cần
  một adapter BLE ngoài để thực hiện nhánh TPMS này.
- Có sẵn gửi HCI, ghép/lọc HCI event và ACL, L2CAP CID `0x0004`, mã hoá ATT,
  xử lý Completed Packets để giữ traffic/credit của `bds`, reconnect và cơ chế
  tự tắt của wrapper. Đây là nền có thể tái sử dụng cho HUD.

Vì vậy không nên mặc định cần ESP32/Raspberry Pi cho phương án cuối. Bản Python
BlueZ hiện có vẫn dùng làm bản đối chiếu giao thức trên máy thử.

## Vai trò cần bổ sung

| TPMS hiện tại | HUD giả cần có |
|---|---|
| CMU scan, chủ động tạo kết nối tới hộp | CMU phát quảng bá connectable, iPhone chủ động kết nối |
| CMU là BLE central và ATT client | CMU là BLE peripheral và ATT server |
| Tìm FFE0/FFE1, bật notify, nhận frame | Cung cấp FFF0/FFF1–FFF4, nhận write và phát notify |

Code TPMS gốc chỉ có chuỗi scan/create connection và ATT client. Không có chuỗi
set advertising parameters/data/scan response/enable hoặc bảng attribute để
điện thoại discover. Các phần đó đã được bổ sung trong `native/` của Vietnav;
không chỉ đổi FFE0 thành FFF0.

## Ràng buộc khi sống cùng TPMS

**Chỉ một lớp điều phối HCI dùng chung. Không nạp thêm hai thư viện độc lập
cùng nhận mình sở hữu mọi gói LE.** Trong `v3.c`:

- `claims_opcode()` coi mọi opcode `0x20xx` là của TPMS sau khi đã bật claim.
- `rx_is_ours()` lấy toàn bộ LE Meta Event `0x3E` ra khỏi luồng của `bds`.
- `our_handle` là một biến duy nhất; `conn_complete()` gán handle rồi lập tức
  chạy discovery FFE1; `rewrite_ncp()` chỉ xử lý handle đó.

Đưa một kết nối iPhone vào code này mà không sửa điều phối sẽ khiến nó chạy
nhầm state machine TPMS, ghi đè handle hoặc làm sai credit. Cần phân luồng theo
vai trò/kết nối, giữ traffic classic của `bds`, và để TPMS/HUD cùng dùng cơ chế
service pack, command scheduler và wrapper hiện có.

Tài liệu trip 14 ghi controller trả lời Supported States; bản tóm tắt trong
`mzd-connect-tpms-research/STATUS.md` có `ff 0f 00 00`. Phải đọc đủ bitmap và
kiểm tổ hợp trạng thái để biết có thể **đồng thời** giữ TPMS central và HUD
peripheral hay không. Thành công của TPMS chưa chứng minh tổ hợp này. Có thể
thử HUD riêng trước, sau đó mới bật cả hai nếu controller hỗ trợ.

## Hướng triển khai tiếp

1. Tái sử dụng khởi tạo BLE và lớp vận chuyển từ v3, thêm chế độ HUD riêng;
   giữ các giới hạn thời gian và cơ chế thoát của wrapper.
2. Kiểm supported commands/states cho quảng bá connectable và kết nối
   peripheral. Ghi kết quả cụ thể thay vì suy từ việc đã scan được.
3. Quảng bá `VIETNAV HUD`, service FFF0; nhận kết nối iPhone theo role/handle.
4. Thêm ATT server: MTU, discover service/characteristic/descriptor, CCCD,
   read/write và notify; xử lý yêu cầu cập nhật kết nối nếu điện thoại gửi.
5. Chuyển byte ghi FFF2/FFF3 vào codec HUD đã phân tích, trả HUDInfo qua FFF1;
   xác nhận VML thực sự gửi CMD `00` trên iPhone.
6. Nối dữ liệu đã xác minh vào VBS/HUD, có chọn nguồn và xoá guidance khi
   ngắt/hết hạn; sau đó mới kiểm TPMS, HUD và wireless CarPlay cùng hoạt động.

Không chạy nguyên bản Python BlueZ trên CMU: nhánh TPMS hoạt động bên trong
`bds` qua HCI riêng. Tài liệu `tpms/KERNEL-BLUEZ.md` ở repo research mô tả
BlueZ 4 trên firmware và đường thử kernel phải giành UART khỏi `bds`; đó là
đường khác, không tương đương backend `GattManager1` của bản thử trên Linux.
