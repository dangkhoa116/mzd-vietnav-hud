# Tương thích MZD-AIO / CASDK

VIETNAV HUD không thêm hàng Applications, không hook systemApp, List2,
MainMenu hoặc framework routing. CASDK thay selectCallback không tác động
đến đường dẫn HUD hiện tại. Không cần thêm wrapper HMI.

Installer chỉ sửa các dòng dịch vụ thuộc VIETNAV trong sm.conf/sm_WCP.conf
và cấu hình dẫn đường đã được kiểm tra; gặp environ_var của mod khác thì
dừng trước khi ghi. Không sửa hoặc khôi phục file HMI của AIO, loader của
add-on khác hay stage_wifi.sh. Quyền boot script của add-on khác được giữ nguyên.

Gói THU THẬP ghi hash, quyền các file HMI dùng chung và stage_wifi.sh,
cùng dấu hiệu AIO/CASDK nếu có. Dấu hiệu chỉ hỗ trợ chẩn đoán, không chứng
minh AIO đã hoặc chưa cài; không tự sửa file dùng chung.

Kiểm thử PC: tests/test_installer.py kiểm tra dry run, cài, gỡ và giữ nguyên
byte/quyền các file dùng chung với dữ liệu giả lập AIO/CASDK. Không xác nhận
đã chạy trên xe có AIO.

## Kit 0.9.3 DEBUG

Bổ sung chẩn đoán AIO/CASDK; thư viện CarPlay giữ nguyên bản m3 DEBUG
đã vá fallback. Bản ZIP nằm trong installer/dist (ngoài Git), không kèm
trigger TouchTune hoặc payload Android Auto: chép đè lên USB cũ có trigger.
Giữ máy xe chạy khi bấm THU THẬP để không mất log trong /tmp.

Đã chạy toàn bộ tests/test_installer.py trên PC/WSL thành công; kiểm tra
cú pháp installer/*.sh và native/usb/*.sh bằng BusyBox ARM 1.19.2 của
firmware qua qemu-arm. Đã kiểm ZIP, MD5 toàn bộ payload, phiên bản 0.9.3,
collector mới và thư viện m3 DEBUG khớp byte. Chưa chạy kit trên xe có AIO.
