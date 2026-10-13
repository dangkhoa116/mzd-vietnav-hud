# Patch: road-name budget 64 → 256 byte (hud_nav16)

## Vấn đề

Trên đường GAL 1.6 của oem-aa-mod, tên đường bị cắt ở 63 byte ngay khi decode
(`AaGuidance.road[64]`) — **trước khi** fold dấu tiếng Việt chạy (`translit.h`,
chỉ co chuỗi: ký tự 3 byte → 1–2 byte). Hệ quả: một tên đường Việt Nam nhiều dấu
vượt 63 byte khi còn nguyên dấu sẽ bị cụt, dù sau khi fold nó lọt vừa dải hiển
thị. Chính repo upstream ghi nhận đây là "known limitation" trong comment của
`hud_nav16.cpp` (dec_step, field 2), và đường GAL 1.5 vốn đã làm đúng
(`kRoadCap=255` + fold trước khi truncate).

## Sửa

Ba thay đổi, giữ nguyên hành vi với chuỗi ngắn:

1. `mazda/patches/blmjciaapa/hud/hud_nav16.h` — `AaGuidance.road[64]` → `road[256]`
   kèm comment hợp đồng budget mới.
2. `mazda/patches/blmjciaapa/hud/hud.cpp` — `AaNav16HudState.road[64]` → `road[256]`
   (accumulator/change-gate; hai struct cùng тип nên memcmp gate không đổi ngữ nghĩa).
3. `mazda/patches/blmjciaapa/hud/hud_nav16.cpp` — cập nhật comment tại dec_step:
   budget decode 256 byte, fold chạy phía sau, transport tự cắt theo cap của nó.

Không thay đổi wire format, không thay đổi glyph/unit/lane logic. Chi phí bộ nhớ:
2 static struct lớn thêm ~380 byte mỗi cái.

## Áp dụng

```
git clone https://github.com/VitaliyKurokhtin/oem-aa-mod
cd oem-aa-mod
git apply --stat ../0001-hud-nav16-road-budget-64-to-256.patch   # xem trước
git apply ../0001-hud-nav16-road-budget-64-to-256.patch
# build theo docs/build.md của upstream (make / make debug)
```

Hoặc bằng `patch -p1 < 0001-....patch`.

## Kiểm chứng không cần xe

Host test trong `tests/road_fold_test.cpp` dựng một frame 0x8006 tổng hợp với tên
đường "Nguyễn " × 9 (81 byte raw) và asserting: decode giữ nguyên vẹn (không còn
cắt ở 63), fold ra đúng 72 byte, không còn byte 3 byte, ễ→ê. Xem README chính để
lệnh build/run.
