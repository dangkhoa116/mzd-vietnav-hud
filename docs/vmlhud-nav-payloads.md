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

Điểm chung: đuôi có `gio u16be + phut u8 + time_third u8 + quang u32be +
toc_do u16be`; mọi số đa byte là **big-endian**, tên đường UTF-8. `time_third`
**là giây** ở cả ba layout — xem mục 10.2: ba tuyến chạy thật trên iOS 3.4.3 khớp
ETA trên màn hình, và builder Android `W7/e` sinh giờ/phút/giây từ một tham số
tổng giây (tag 5 = `tong % 60`). Cách đọc cũ ("byte thấp của tổng phút", suy từ
0x4A6C–0x4A70) đã bị runtime bác bỏ.

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
[..]   u16be remain_hours; u8 remain_minutes; u8 time_third_raw
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
[..]    u16be remain_hours; u8 remain_minutes; u8 time_third_raw
[..]    u32be remain_dist_m
[..]    u16be speed_kmh
```

Khối sau direction thực tế là `u32be image_len` + `image_len` byte ảnh/flag.
Mẫu trên ứng với `image_len=1`, flag=1; không dùng hằng số đó để loại các
khung có ảnh JPEG custom. Tối thiểu 22 byte, kiểm độ dài ảnh trước khi đọc
khoảng cách/tên đường. Xem mục 9 và `decode_nav_variable2`.

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
| `SID` | **serial** trong HUDInfo; quan hệ với API cấp quyền từng họ thiết bị chưa chốt |

Ví dụ đáp emulator: `MODEL:H50,HW:1.0.0,FW:1.0.0,PROTOCOL:2.2.2S,OBDV:0_1.0,SID:VMEMU0000001`

MODEL khác rỗng là điều kiện nhánh native này; chưa chứng minh Dart/server
chấp nhận thiết bị hoặc sẽ gửi dẫn đường. H50 còn có đường byte-pipe riêng.

## 6. Checksum khung và giới hạn bằng chứng về kiểm tra trên app

Trong `dataParsing`, MD5 được tính (0xd1dc–0xd1fc: subdata đuôi → hash →
`setGetData:`) nhưng **kết quả không ảnh hưởng luồng xử lý** — khung vẫn được
dispatch theo CMD dù hash không khớp. Chỉ hai điều kiện dài mới loại khung.
(Khung GỬI đi vẫn luôn kèm MD5 đúng — xem `vmlhud_frame.py`.)

Nhận xét trên chỉ áp dụng hàm native đã soi, không suy rộng cho H50/Dart.
Emulator vẫn kiểm checksum mặc định của khung nhận và gửi checksum chuẩn.
Trailer mới là **8 byte**, không phải MD5 thô 16 byte: mỗi 4 byte là tổng
modulo 2^32 của bốn word BE trong MD5(header+payload+UID16), một phần theo
runtime UID và một phần theo default UID. Serial SID không phải runtime UID.
Tổng khung = payload+21 = lenfield+8. Khung cũ C5 dùng CRC16 Modbus, tổng
payload+11. Xem `hud_emulator/protocol.py` và `bridge/vmlhud_frame.py`.

## 7. Bảng CMD đã thấy (app → HUD và HUD → app)

| CMD | Chiều | Ý nghĩa |
| --- | --- | --- |
| `0x00` | app → HUD | dẫn đường (fixed hoặc variable1) |
| `0x02` | app → HUD | heartbeat (payload mang tốc độ; chọn một nhánh protocol theo trạng thái) |
| `0x0E` | app → HUD | yêu cầu getHUDInfo (payload 1 byte) |
| `0x0E` | HUD → app | đáp getHUDInfo (payload text §5) |
| `0x40` | app → HUD | dẫn đường "Simplify" variable2 (**chưa thấy trên iOS**) |
| `0x01` | app → HUD | 4 byte = camera/biển báo; **8 byte trên iOS 3.4.3 chưa giải mã** (mục 10.6) |
| `0x09` | app → HUD | 5 byte `00`, thấy một lần lúc mở phiên; chưa rõ |
| `0x0B`,`0x0D`,`0x32`,`0x50`,`0x51`,`0x53`,`0x56`,`0x5A`,`0xF0`,`0xF2` | HUD → app | TPMS / OBD / OTA / cài đặt (dataParsing 0xd494–0xd518) |

## 8. Còn phải chốt bằng chạy thật (emulator ESP32)

1. **Bảng `direction`**: ~~đối chiếu byte với mũi tên trên màn app~~ — đã chạy
   thật ngày 22-10-2026 và **không lập được bảng**: iOS 3.4.3 gửi `0xFE` cho
   mọi loại mũi tên (mục 10.3). Câu hỏi thay thế: **điều kiện nào khiến nhánh
   iOS gửi CMD `0x40`** (variable2 mới mang `direction` + ảnh mũi tên).
2. **[0xAD..0xAE] của fixed**: suy là `speed u16be` theo đối xứng hai layout
   variable; xác nhận khi bắt được khung fixed. **Chưa bắt được khung fixed** —
   iOS chọn variable1 ngay khi emulator đáp getHUDInfo.
3. **Profile và cấp quyền**: ~~chưa xác nhận~~ — đã xong cả chuỗi quét → kết nối
   → subscribe → HUDInfo → **dẫn đường thật** với
   `MODEL:H50, PROTOCOL:2.2.2S, SID:VMEMU0000001` (SID không tồn tại). Không có
   cổng máy chủ nào chặn. Xem mục 10.

## 9. Doi chieu cheo voi APK Android (21-10-2026, bo sung buoi toi)

Giai ma jadx APK Android cua VIETMAP LIVE cho thay SDK DJ white-label viet bang
Kotlin/Java doc duoc 100% (goi `U7` = manager, `W7` = cac ban protocol). Moi
khai niem tren day duoc xac nhan lai tung byte:

- **Frame** (`p010a8.c.f`): `A5 5A 37 C3 | len BE (=payload+12, payload da gom
  CMD) | ts BE | payload (byte [0] = CMD) | checksum8`. iOS da xac dinh
  checksum8 nhu muc 6; khong thay bang MD5 tho 16 byte.
- **Nav payload** (`W7/c.java J()` = protocol 2.2.0/2.2.1, `W7/e.java` = 2.2.2S):
  TLV chi ghi gia tri thoi (khong tag). Thu tu: CMD 0x40, direction u8,
  **u32 image_len**, image/flag, distance u32, len+next_road, len+current_road,
  h u16 + m u8 + time_third u8, remain u32, speed u16. Y nghia byte
  time_third phai doi chieu tung builder; khong mac dinh la giay tren iOS.
- **Semantics khoi "00 00 00 01"**: do la `image_len = 1` = KHONG co anh mui ten
  custom; khi app co anh custom (Android nhan qua `imageBase64`) thi u32 =
  do dai JPEG va anh noi ngay sau do. Byte ke tiep khi image_len==1 la flag
  (0 = khong anh, 1 = giu anh cu).
- **Bang PROTOCOL chon hanh vi** (tu `U7/a.java`, sau khi parse getHUDInfo):
  `2.2.0`/`2.2.1` -> `W7/c`; `2.2.2` -> `W7/d`; `2.2.2S` -> `W7/e`; bat ky gia
  tri khac (gom ca "1.6") -> `W7/b` = **ban toi thieu, `J()` tra null: KHONG
  gui dan duong, chi heartbeat**. Emulator mac dinh tra 2.2.2S de thu nhanh co nav tren Android; khong
  suy rong bang nay cho moi nhanh iOS/Dart.
- **Hai ho thiet bi, hai bo GATT** (tu `Ma/i.java`, `Ma/j.java`):
  - H1/DJBT: service `FFF0` (`FFF2` write / `FFF1` notify / `FFF3` / `FFF4`)
  - H50: service `FFFF` (`9ABC` write / `1234` notify); handler native H50 chi
    la byte-pipe (`sendBytesData`) - toan bo protocol H50 nam phia Dart.
  Emulator hien expose ca hai dong thoi.
- **Ket noi theo dia chi** (`connectDeviceNativeApi {address, type}`):
  type 2 = H50, 3 = H1, con lai = DJBT - Dart tu quet qua plugin BLE chung
  roi moi truyen dia chi xuong.

Nguon phan tich: `work/analysis/apk/` (ngoai repo) - jadx output cua APK do chu
xe cung cap.

## 10. Doi chieu RUNTIME voi app that (22-10-2026, iOS)

Lan dau bat duoc **dan duong that**: VIETMAP LIVE **3.4.3** tren iPhone 8 Plus
da ket noi emulator ESP32-C3 (`MODEL:H50, PROTOCOL:2.2.2S, SID:VMEMU0000001`)
va gui lien tuc CMD `0x00` trong suot bon tuyen duong khac nhau. Log tho:
`out/cycle-trial-3.log`; ban giai ma: `out/cycle-trial-3.jsonl` (ca hai la
artifact ignored). Fixture byte that nam trong `bridge/vmlhud_nav_test.py`.

### 10.1 Layout variable1 dung nguyen van

iOS chon **variable1 / CMD 0x00** (dung nhu nhanh `hudInfo != nil`), khong he
gui CMD `0x40` trong ca phien. Moi offset o muc 3 khop byte-for-byte. Vi du
khung that, chup luc man hinh app hien "150m Quoc Lo 13 - 25p - 8.3km":

```
FE 000000 96 | 0E | 51 75 E1BB91 63 20 4C E1BB99 20 31 33 | 00 | 0000 19 26 0000203D 0000
^dir ^dist=150  ^len=14  ^"Quoc Lo 13" (UTF-8 14 byte)      ^cur="" ^h=0 ^m=25 ^s=38 ^8253m ^speed=0
```

### 10.2 Byte thoi gian thu ba LA GIAY (sua ket luan cu)

Muc 1 truoc day ghi "khong coi `time_third` la giay" dua tren doc tinh nhanh
iOS 0x4A6C-0x4A70. **Runtime bac bo cach doc do.** Ba tuyen doc lap deu khop
khi coi byte thu ba la giay, va sai neu coi la "byte thap cua tong phut":

| Man hinh app | h/m/byte3 tren song | Hieu theo giay | ETA app | Gio bat |
| --- | --- | --- | --- | --- |
| 25p / 8.3km | 0 / 25 / 38 | 25m38s | 15:19 | ~14:53 |
| 37p / 14.2km | 0 / 37 / 52 | 37m52s | 15:36 | ~14:58 |
| 22p / 12.2km | 0 / 22 / 5 | 22m05s | 15:22 | ~15:00 |

Doc lap voi do, builder Android `W7/e.java` + `m0()` cho thay ba the thoi gian
duoc sinh tu **mot tham so tong giay** `i12`: tag 3 = `i12/3600` (u16be gio),
tag 4 = `i12/60 - (i12/3600)*60` (u8 phut), tag 5 = **`i12 % 60`** (u8 giay).

`bridge/vmlhud_nav.py` nay dien `remain_time_s` cho ca ba layout; builder van
tra ve dung bo ba byte goc khi bo ba do khop `remain_time_s`, nen khung co byte
thu ba ngoai 0..59 (chua tung thay tren song) van round-trip nguyen ven.

### 10.3 `direction` tren iOS la HANG SO 0xFE - chua mang ma huong re

Byte `[0]` **luon bang 0xFE (254)** trong toan bo **1.963 khung** bat duoc, ke ca
khi mui ten tren man hinh app khac han nhau:

| Mui ten tren app | direction tren song |
| --- | --- |
| Re phai vao Quoc Lo 13 (ba tuyen) | `0xFE` |
| Bieu tuong **diem den** (tuyen 47m, "30m Duong So 7") | `0xFE` |
| Khong dan duong (khung nhan roi) | `0xFE` |

Nghia la **khong the dung CMD 0x00 cua iOS 3.4.3 de suy ra mui ten**. Tren
Android, `Ma/b.java` cho thay Dart gui kem `imageBase64` (anh mui ten da render)
va co co `isV2`. **Khong** ket luan 0xFE = "re phai".

Hai moc tinh giup doc ket qua nay (disassembly `vietmap_hud_sdk.framework`):

- `sendEndNavigationInformation` (0x4b4c) goi
  `sendNavigationInformationWithDirection:` voi **direction = 0xFF**, distance 0,
  ten duong rong, duoi toan 0; va nhanh 0x4e44 so `direction` voi `0xFF` de tat
  `NaviTimer`. Tuc la **0xFF moi la sentinel "het dan duong" cua SDK**, va `0xFE`
  la gia tri do lop Dart tu chon - app khong he goi `sendEndNavigationInformation`
  trong ca phien.
- **CMD 0x40 chi phat ra tu dung mot cho**: trong
  `insedeSendCustomNavigationInformationWithDirection:andDirectionImage:…`
  (0x4bb4), tren nhanh ma `directionImage` moi **bang** `lastNavigationImageData`
  da luu (`isEqualToData:` tai 0x4d88, nhanh bang di tiep toi `sendParamData:andCMD:`
  voi `w3=0x40` tai 0x4e14). Nhanh khac bang se `setLastNavigationImageData:` roi
  goi `sendNavigationInformationWithDirection:` = CMD 0x00.

Hệ quả thực tế: **doi `MODEL`/`PROTOCOL`/`HW`/`FW` trong dap getHUDInfo se KHONG
lam iOS chuyen sang CMD 0x40.** Viec chon entry point (`sendCustomNavigation…`
co anh mui ten, hay `sendNavigation…` khong anh) nam **tren** SDK, o lop Dart,
truoc khi bat ky truong nao cua HUDInfo duoc doc. Emulator khong co don bay nao
o day - muon co mui ten phai tac dong vao lop Dart hoac chap nhan HUD chi co chu.

### 10.4 Khung "het dan duong" = khung nhan roi

Khi bam Thoat khoi dan duong, app khong gui lenh xoa rieng. No quay ve khung
nhan roi, dung CMD 0x00 variable1:

```
FE FFFFFFFF 14 "31° mây đen u ám" 00 0000 00 00 00000000 0000
   ^dist = 0xFFFFFFFF            ^cur="" ^toan bo duoi = 0
```

Tuc la: `distance == 0xFFFFFFFF` + duoi toan 0 chinh la tin hieu **xoa guidance**
cho phia CMU. Truong `next_road` khi do mang chuoi thong tin (thoi tiet) chu
khong phai ten duong - decoder phia sau phai phan biet bang `distance`, khong
phai bang tien to `FE`.

### 10.5 Heartbeat CMD 0x02 that su mang toc do

764 khung heartbeat payload `0000`, dung **mot** khung `0028` = 40. Khop suy
luan u16be km/h o muc 7 (GPS fallback bat len mot nhip roi ve 0 vi xe dung yen).

### 10.6 CMD moi thay tren song, chua giai ma

| CMD | plen | Payload quan sat | Ghi chu |
| --- | --- | --- | --- |
| `0x01` | 8 | `0186A00000000000` (~1 Hz, bat bien) | **Da giai ma**: xem duoi |
| `0x09` | 5 | `0000000000` (dung 1 khung, luc bat dau phien) | Chua ro |
| `0x0D` | 1 | `FF` (2 khung) | OBD query, khop ghi nhan truoc do |

**CMD 0x01 8 byte = hai o camera.** `sendCameraInformationWithType:andDistance:andLimitSpeed:`
(0x5a90) ghi **mot** o 4 byte `[type u8, khoang_cach u16be, gioi_han_toc_do u8]`
roi gui CMD 1. `sendMultipleCameraInformationWithTypeArray:…` (0x5c08) ghi cung
dinh dang nhung lap nhieu o, **toi da 2** (`csel w22, w8, w23, hi` voi `w8=2` tai
0x5d58), nen payload dai 4 hoac 8 byte. Khung that giai ra:

| O | type | khoang cach | gioi han |
| --- | --- | --- | --- |
| 0 | `0x01` | `0x86A0` = 34464 m | 0 |
| 1 | 0 | 0 | 0 (o trong) |

34464 = **100000 mod 65536**: lop tren gui 100 km lam gia tri "khong co camera
phia truoc" roi bi cat con 16 bit. `decode_log.py` va sketch C3 nay doc ca hai o.

Khong suy doan y nghia vao codec khi chua co bang chung; moi khung tren van
duoc giu nguyen hex trong capture.
