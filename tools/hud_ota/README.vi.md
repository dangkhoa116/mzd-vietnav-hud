# Tái kiểm OTA VIETMAP LIVE 3.4.3

Đọc [báo cáo](../../docs/hud-firmware-ota-analysis.vi.md) trước khi dùng.
Các công cụ không flash thiết bị. Binary app, token và kết quả đặt trong out/
(đã Git ignore); không commit hoặc gửi OTP/mật khẩu vào chat.

## Đối chiếu object pool iOS

Cần Python 3.10+, App.framework/App của bản iOS đã phân tích và file
text/strings.txt do DAE 0.1.13 export từ chính binary đó. SHA256 được kiểm
trước khi dùng offset; bản khác bị từ chối. Script không thực thi app.

```sh
python tools/hud_ota/inspect_ios_pool.py /path/App.framework/App /path/dae/text/strings.txt --out out/ios-ota-evidence.json
```

Chỉ kiểm 160.386 entry và các cặp ADD-from-PP/LDR liền nhau trong vùng mã
đã xác định. Không phục dựng toàn bộ call graph hoặc giải mã mọi phiên bản
Dart. Không lấy tên hàm gần nhất làm ranh giới hàm.

## Tải bằng phiên đăng nhập do người dùng cung cấp

Công cụ thử nghiệm: đã kiểm CLI và nhánh đầu vào lỗi, chưa tải file thật.
Sao chép request.template.json vào out/, điền sáu trường bằng thông tin của
HUD được chọn. Không dùng serial của người khác. Script không tạo phiên đăng
nhập và không bỏ qua kiểm tra server.

```sh
python tools/hud_ota/fetch_firmware.py out/hud-request.json --out out/hud-firmware-download
```

Nhập Bearer token ở prompt ẩn trên máy local (không truyền qua dòng lệnh).
Token không được in hoặc lưu, chỉ gửi tới API VIETMAP; không chuyển header
Authorization cho host chứa file. Request metadata không tự theo redirect.
Nếu API trả lỗi, script chỉ in mã HTTP. Thư mục output phải chưa tồn tại.

Metadata được lưu local, có thể chứa signed download URL: không chia sẻ
nguyên file. Chỉ tải khi response có đúng một downloadUrl HTTPS. Có nhiều
URL thì dừng để chọn đúng thiết bị; không tự đoán. Tải tối đa 128 MiB,
file lỗi/dở còn đuôi .partial, tải xong đổi tên firmware.download và ghi SHA256.
SHA256 chỉ định danh file, không chứng minh nguồn hay kiến trúc phần cứng.
Chưa kiểm header/chữ ký, chưa so khớp fileSize do đơn vị chưa xác định.
Không dùng file này để nạp ESP32-C3 hoặc Mazda trước khi phân tích phần cứng.
