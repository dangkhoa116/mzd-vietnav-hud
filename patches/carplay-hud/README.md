# Patch: lấy hướng rẽ từ chữ khi app CarPlay không đặt `CPManeuverType`

## Vấn đề

Chủ xe đã cài `VIETNAV-HUD-0.9.1-USB` và test trên xe: **dẫn đường Google Maps
qua CarPlay lên HUD bình thường, VIETMAP LIVE thì HUD trống hoàn toàn.**

`nav.cpp` của [mazda-carplay-hud](https://github.com/KidMixer/mazda-carplay-hud)
phân loại maneuver từ `maneuverType` (offset `0x128` của khung iAP2 `0x8059`) và
loại bỏ mọi giá trị khớp `is_context_type()` — trong đó có **`0` = NoTurn**:

```c
uint32_t mtype = read_u32(b, n, kManeuverTypeOff);
if (idx == 0 || is_context_type(mtype)) return;   // <- nuốt sạch
```

Cách đó đúng với app có điền trường này. Nhưng `CPManeuver.maneuverType` chỉ có
**từ iOS 17.4**, và app hoàn toàn có quyền không bao giờ đặt nó: một app dẫn
đường CarPlay có thể chỉ gửi `instructionVariants` (chữ) + `symbolImage` (ảnh
mũi tên đã render). **VIETMAP LIVE 3.4.3 đúng là loại đó** — kiểm trong
`Frameworks/vietmap_live_navigation_plugin.framework`:

| Selector | Có |
| --- | --- |
| `setInstructionVariants:` | có |
| `setSymbolImage:` / `setSymbolSet:` | có |
| `setUpcomingManeuvers:` | có |
| `updateTravelEstimates:forManeuver:` | có |
| **`setManeuverType:`** | **không** |
| `setJunctionType:` / `setJunctionExitAngle:` | không |

Nên mọi maneuver của VietMap tới xe với `maneuverType == 0`, bị lọc sạch, và HUD
không bao giờ có gì để vẽ.

## Sửa

Thêm nhánh dự phòng: khi `maneuverType == 0` ở `idx >= 1`, **suy hướng rẽ từ
chuỗi lệnh** (`maneuverDesc`) thay vì vứt đi.

- `maneuver_text.h` — header độc lập, không phụ thuộc `patch.h`, nên test được
  trên máy thường. Nó fold tiếng Việt về ASCII thường ("Rẽ phải" → ` re phai `)
  rồi khớp từ khoá có neo biên từ.
- `nav.cpp` — đọc `text` sớm hơn, gọi `maneuver_text::classify()`, và chỉ nới
  điều kiện lọc khi có kết quả. `classify()` gốc vẫn giữ nguyên quyền với vòng
  xuyến (dải glyph theo chiều đường + góc thoát thật ở `0x346`).

**Chỉ `type == 0` được xét lại.** App có điền `maneuverType` (Apple Maps, Google
Maps) giữ nguyên hành vi lọc context cũ, không đổi một chút nào.

Hai `static_assert` khoá số hiệu `TURN_EVENT`/`SIDE_*` giữa header và `nav.cpp`,
để sau này sửa một bên là hỏng build chứ không hỏng âm thầm.

### Nguyên tắc: không đoán bừa

`classify()` **trả về false khi không chắc**. Câu bám đường ("Đi tiếp trên Quốc
Lộ 13", "Continue on…", "Head north") bị từ chối, vì đoán ở đó sẽ dán một mũi
tên sai suốt cả chặng. Từ chỉ hướng đứng một mình ("bên trái") cũng bị từ chối.

Thứ tự khớp có chủ ý: "đã đến đích, **bên phải**" là điểm đến chứ không phải cú
rẽ phải; "rẽ phải **gấp**" là rẽ gấp chứ không phải rẽ thường.

## Áp dụng

```sh
cd <checkout mazda-carplay-hud>
git apply --stat  .../patches/carplay-hud/0001-nav-recover-turn-from-instruction-text.patch   # xem trước
git apply         .../patches/carplay-hud/0001-nav-recover-turn-from-instruction-text.patch
# rồi build theo hướng dẫn của upstream (cần toolchain ARM m3-toolchain)
```

Patch tạo luôn `mazda/patches/blmjcicarplay/maneuver_text.h`, không phải copy tay.

## Kiểm chứng không cần xe

```sh
cd tests
python -m pip install ziglang
python -m ziglang c++ -std=c++17 -w -I ../patches/carplay-hud \
    maneuver_text_test.cpp -o maneuver_text_test
./maneuver_text_test        # 43 kiem tra, 0 loi
```

Test dựng từ các câu dẫn đường tiếng Việt thật, gồm cả nhóm **phải bị từ chối**.
Bản vá `nav.cpp` cũng đã được biên dịch sạch bằng `zig c++ -std=c++17`.

## Chưa chứng minh được điều gì

Đây là bản sửa theo **giả thuyết mạnh nhất**, chưa phải kết luận đã đo:

- Chưa có log trên xe nên **chưa biết chắc khung `0x8059` có tới `jciCARPLAY`
  khi chạy VietMap hay không**. Nếu iOS không phát luồng iAP2 cho app này thì
  patch này không cứu được gì — lúc đó lỗi nằm ngoài tầm với của phía xe.
- Chuỗi `maneuverDesc` thật của VietMap chưa được đọc lần nào; bộ từ khoá dựng
  theo cách hành văn thường gặp. Có log rồi thì chỉnh lại cho khớp.
- Bản phát hành chỉ log lỗi. Muốn thấy dòng `nav TEXT-FALLBACK …` phải build
  bản **debug** rồi chạy `vietnav-collect.sh`.

Xem [docs/carplay-vietmap-hud-gap.vi.md](../../docs/carplay-vietmap-hud-gap.vi.md).
