# mzd-vietnav-hud

**Đưa dẫn đường tiếng Việt lên HUD zin (Active Driving Display) của Mazda Connect** — cho mọi app dẫn đường Việt Nam: VIETMAP LIVE, Waze, Google Maps. Cả hai phía điện thoại: **Android Auto** (GAL 1.6) và **Apple CarPlay** (iAP2).

> Dự án nghiên cứu + bản vá tương thích cho Mazda Connect CMU150 (MZD Connect, đời CX-5 KF / CX-8 / cùng nền tảng). Không liên kết với Mazda, Vietmap, Google hay Apple.

## Bối cảnh

Mazda Connect thế hệ CMU150 có HUD chiếu kính lái, nhưng firmware gốc chỉ hiển thị dẫn đường từ app Navigation zin (thẻ SD). Cộng đồng quốc tế đã có 2 giải pháp mở (AGPL-3.0) để đưa dẫn đường điện thoại lên HUD:

| Đường | Giải pháp cộng đồng | Cơ chế |
|---|---|---|
| **Android Auto** | [VitaliyKurokhtin/oem-aa-mod](https://github.com/VitaliyKurokhtin/oem-aa-mod) | LD_PRELOAD shim vào `aap_service` — quảng bá **GAL 1.6** để điện thoại gửi maneuver/lane/khoảng cách |
| **Apple CarPlay** | [KidMixer/mazda-carplay-hud](https://github.com/KidMixer/mazda-carplay-hud) | LD_PRELOAD shim vào `jciCARPLAY` — tap thụ động `msgrcv`, decode iAP2 `0x8059/0x8058` rồi bơm vào `com.jci.vbs.navi` |

Dự án này bổ sung phần còn thiếu cho thị trường Việt Nam:

1. **Phân tích khoản trống tên đường tiếng Việt** — vì sao VIETMAP LIVE hiện mũi tên trên HUD nhưng thiếu tên đường, kèm quy trình chẩn đoán trên xe (10 phút, không đoán mò).
2. **Bản vá cho oem-aa-mod** — sửa lỗi tên đường Việt Nam dài bị cắt cụt trước khi fold dấu (bug "known limitation" chính chủ ghi nhận).
3. **Host test** — chứng minh bản vá bằng cách build/test trên PC, không cần xe.
4. **Hồ sơ kỹ thuật VIETMAP LIVE** — kết quả phân tích tĩnh app Android + iOS phục vụ tương thích.

## Nội dung repo

```
docs/
  vietmap-hud-gap.md           Chẩn đoán khoản trống "VML không hiện tên đường"
  vietmap-live-internals.md    Hồ sơ kỹ thuật VIETMAP LIVE 3.4.3 (phân tích tĩnh)
patches/
  oem-aa-mod/
    0001-hud-nav16-road-budget-64-to-256.patch   Bản vá tên đường VN dài
    README.md                   Cách áp dụng
tests/
  road_fold_test.cpp           Host test cho bản vá (zig cc, chạy trên PC)
  shim/sys/                    Shim POSIX tối giản để test build trên Windows
  Makefile
```

## Bản vá: tên đường Việt Nam dài trên HUD

Sự cố: HUD ECU chỉ render ký tự Unicode < U+0800; chữ Việt precomposed (U+1E00–U+1EFF,
3 byte UTF-8) bị mất dấu. oem-aa-mod đã có bảng fold (`translit.h`: ễ→ê, ớ→ơ…) nhưng
trên đường GAL 1.6, tên đường bị **cắt ở 63 byte ngay khi decode — trước khi fold**.
Tên Việt nhiều dấu thường vượt 63 byte khi còn nguyên dấu (mỗi chữ có dấu = 3 byte)
nhưng thu về 1–2 byte/chữ sau fold → bị cụt oan.

Bản vá nới budget decode của `AaGuidance.road` và `AaNav16HudState.road` từ 64 lên
256 byte — cùng hợp đồng với đường GAL 1.5 vốn đã làm đúng (`kRoadCap=255`). Chi tiết:
[patches/oem-aa-mod/README.md](patches/oem-aa-mod/README.md).

Chạy host test (không cần xe):

```
cd tests && make test
# hoặc gọi trực tiếp:
python -m ziglang c++ -std=c++17 -I shim \
  -I <oem-aa-mod>/mazda/patches/blmjciaapa/hud \
  -I <oem-aa-mod>/mazda/patches -I <oem-aa-mod>/mazda/patches/common \
  road_fold_test.cpp <oem-aa-mod>/mazda/patches/blmjciaapa/hud/hud_nav16.cpp \
  -o road_fold_test && ./road_fold_test
```

Kỳ vọng: `RESULT: ALL PASS` (tên 81 byte raw → decode nguyên vẹn → fold còn 72 byte,
không còn ký tự 3 byte).

## Trạng thái & lộ trình

- [x] Phân tích tĩnh VIETMAP LIVE (Android `updateTrip(Trip)` — đã xác nhận; iOS
      `startNavigationSession` + `CPMapTemplate` — đã xác nhận)
- [x] Chẩn đoán khoản trống tên đường + quy trình phân xử trên xe
- [x] Bản vá road-budget + host test
- [ ] Xác nhận trên xe: chẩn đoán `road="--"` khi chạy VML (debug build, log
      `nav16 STATE`)
- [ ] Đóng góp bản vá ngược lên upstream oem-aa-mod
- [ ] Gói cài đặt thống nhất cho firmware VN (74.00.331): AA mod + CarPlay bridge
      + fold tiếng Việt

## Giấy phép & ghi công

Repo này phát hành theo **AGPL-3.0** (xem [LICENSE](LICENSE)) vì chứa bản vá và
test dẫn xuất từ các dự án AGPL. Ghi nguồn:

- [oem-aa-mod](https://github.com/VitaliyKurokhtin/oem-aa-mod) — VitaliyKurokhtin (AGPL-3.0)
- [mazda-carplay-hud](https://github.com/KidMixer/mazda-carplay-hud) — KID MIXER-MODER (AGPL-3.0)
- [mazda-hud-toolkit](https://github.com/ilshyma/mazda-hud-toolkit) — ilshyma (bản đóng gói km/h + VN fold)
- [headunit](https://github.com/Trevelopment/headunit) — nguồn gốc của các thành phần HUD sender

Tên "VIETMAP LIVE" và các thương hiệu liên quan thuộc về chủ sở hữu tương ứng; các
tên này chỉ được nhắc đến nhằm mục đích mô tả tương thích.
