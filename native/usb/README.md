# USB thử native HUD

Bản thử riêng, không nhập vào kit ổn định VIETNAV 0.9.1. Đọc
[các bước trên xe](STEPS.vi.txt) trước khi thử. Mục tiêu hiện tại là kiểm
radio, bắt tay VietMap và thu navigation/camera; **chưa xuất VBS/HUD Mazda**.

## Build

Cần ARM artifact đã qua `native/build_arm.py`, checkout TPMS đúng revision
và source TouchTune đầy đủ. Chạy từ gốc Vietnav:

```sh
python3 native/build_arm.py --toolchain /path/to/m3-toolchain
python3 native/usb/build_kit.py --touchtune /path/to/TouchTune
```

Output mặc định: `out/native-hud-usb/` và `out/vietnav-native-hud-usb.zip`.
Builder từ chối thư mục đích có sẵn nội dung hoặc ZIP đã tồn tại. Giải nén
**nội dung** ZIP vào gốc USB FAT32 riêng, không gộp với kit khác. TouchTune
chỉ cung cấp trigger; không cài các patch touch-while-driving của TouchTune.
ZIP chứa checksum, ARM loader report, giấy phép và corresponding source.

## Chọn chế độ

Menu có KIỂM TRA (query), KẾT NỐI (advertise), KHÁC (lưu log, gỡ, huỷ lịch).
Các nút trên CMU dùng chữ không dấu. Mỗi thao tác đặt lịch được xác nhận
trong menu; menu không kill/restart bds hoặc reboot xe.

1. Query: đặt lịch, rút USB, tắt xe/mở cửa, chờ màn hình tắt hẳn và thêm
   30 giây, mở xe. Chờ 2 phút. Query khởi tạo LE, đọc capability, không quảng bá.
2. Khởi động lại xe để về TPMS. Cắm USB, lưu log và đặt lịch advertise.
   Nếu không có kết quả `VML RESULT peripheral capability present; query only`
   với đúng runtime hiện tại, advertise bị từ chối.
3. Lần khởi động kế tiếp: sau khoảng 60–90 giây tìm `VIETNAV HUD` trong mục
   HUD của VietMap. Cửa sổ thử tối đa 180 giây sau preflight; nhận một kết nối,
   ngắt kết nối/hết hạn thì dừng. Lưu log, lần khởi động sau trở về TPMS.

Không tái đặt lịch trong cùng boot đã chạy native. Màn hình tắt chưa chứng
minh CMU đã reboot; boot ID phải đổi thì token mới được dùng. Nếu chưa đổi,
dispatcher tiếp tục chạy TPMS và giữ lịch cho boot mới.

## Cài đặt và khôi phục

Chỉ hỗ trợ TPMS production wrapper SHA256
`9026f4bc2336564b8c8da772a3df110de733d0fc4bf7d9f0582b8a3a97b39000`.
Cần `bds.real` ELF32 ARM, `libtpms-v3.so` và BLE pack `BTSB` hiện có. Không
đụng tới TPMS library, config, BLE pack, counters hoặc off switches.

Dispatcher thay `/jci/bds/bds`, giữ nguyên wrapper cũ tại
`/jci/bds/bds.vietnav-prev`. Nó kiểm checksum, boot ID, claim token bằng
rename và đánh dấu một lần trong `/tmp` trước khi preload. Không có token,
sai boot, file hỏng hoặc có off switch TPMS thì chạy wrapper cũ. Token đã
claim không được thử lại sau crash/reboot. TPMS trở lại ở start kế tiếp;
không chuyển sang TPMS giữa phiên native.

Controller dùng snapshot có checksum trước khi thay file, commit token cuối
cùng và khôi phục khi lỗi; lần chạy controller sau phục hồi journal còn lại
từ lần cài bị ngắt. Không tự phục hồi journal ngay trong boot bds; nếu điện
bị cắt trước khi commit token thì dispatcher chạy TPMS. Sau commit token,
runtime đã đủ file và qua checksum. Chỉ khôi phục journal nếu wrapper hiện
tại vẫn là bản TPMS gốc hoặc dispatcher của kit.

Monitor độc lập giữ log vào `/data_persist/vietnav-native/logs`, chỉ cấp
query proof cho ID query mới nhất. Watchdog cho 90 giây khởi động, kiểm mỗi
15 giây và chỉ dừng đúng PID/start-time/boot/cmdline bds.real nếu mất nhịp
và log không tăng ba lần liên tiếp. Không đặt cờ tắt TPMS vĩnh viễn.

GO BO trả wrapper TPMS về byte gốc, xoá library/marker/lịch native, giữ log.
Nếu tool khác đã đổi wrapper, gỡ từ chối ghi đè. Library hỏng hoặc payload
USB thiếu vẫn gỡ được nếu wrapper/backup còn đúng. Gỡ bản thử trước khi
cập nhật/gỡ TPMS. Luôn tắt/mở xe sau khi gỡ.

## Kiểm chứng

```sh
python3 -m unittest discover -s tests -p test_hud_native_usb.py -v
# Kiểm tra thêm bằng BusyBox 1.19.2 tối giản tự build từ source:
sh tests/build-busybox-1.19.sh /path/to/bb119
VIETNAV_TEST_BUSYBOX=/path/to/bb119/bin/busybox python3 tests/test_hud_native_usb.py -v
```

23 test tích hợp: cài/gỡ, lỗi ghi, mất điện giả lập, proof cũ/payload đổi,
file hỏng, off switch, token một lần/khác boot, monitor/exec/watchdog, menu
và ZIP từ artifact ARM thực. Mount, GPIO, `/proc` và kill được cách ly trong
filesystem giả. Các kiểm tra này không xác nhận radio hay firmware thật.

Đã qua cả 23 test trên BusyBox 1.19.2 build từ tag `1_19_2`
(`ed058016bf8fc98271de2e58bfb650de9e9d304d`), không dùng GNU applet trong
các lệnh kiểm tra/cài đặt. Các stub mount/id/cp/mv vẫn cách ly với host.
Đã sửa kiểm ELF để dùng `od -b`, tránh `od -A/-t` chỉ có khi bật desktop.
Đây là BusyBox build lại từ source trên host, chưa phải executable firmware.

Đã có firmware 74.00.333A và đã chạy thêm BusyBox/loader/dialog gốc cùng bài
cài/gỡ trong guest mzd-connect-emu. [Kết quả và giới hạn](../emu/README.md):
USB checkpoints pass, nhưng phiên GUI tổng thể chưa pass do Opera thoát 139.
Các test transport vẫn dùng controller/iPhone giả; chưa kiểm BLE trên xe.
