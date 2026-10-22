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

Máy đã test trên xe là **iPhone Air / iOS 27.0.1**, nên API này chắc chắn có
sẵn — không phải chuyện "iOS quá cũ". App đơn giản là không gọi nó.

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
```

Patch tạo luôn `mazda/patches/blmjcicarplay/maneuver_text.h`, không phải copy tay.

## Build bản ARM cho xe (không cần m3-toolchain)

`mazda/Makefile` của upstream build bằng submodule `m3-toolchain`
(`arm-cortexa9_neon-linux-gnueabi-g++`). Đó là **binary ELF Linux x86_64**, nên
trên máy Windows không WSL / không container thì chạy không nổi — đúng chỗ bế
tắc khiến chưa ra được **bản debug** để đọc log trên xe.

`build_arm_zig.py` build cùng bộ nguồn đó bằng zig (một exe Windows, cross-compile
thẳng sang `arm-linux-gnueabi`), rồi **tự kiểm lại** sản phẩm:

```sh
python -m pip install ziglang pyelftools
python patches/carplay-hud/build_arm_zig.py \
    --carplay ../mazda-carplay-hud \
    --baseline <libpatch-blmjcicarplay.so đang chạy trên xe>
```

Kết quả (zig 0.16.0, target `arm-linux-gnueabi.2.4.0`, `-mcpu=cortex_a9+neon`):

| Bản | Kích thước | Log |
| --- | --- | --- |
| release | 197.336 B | chỉ ERROR (như upstream) |
| debug | 3.365.148 B | có `nav PICK`, `nav TEXT-FALLBACK` |

Đã kiểm trong chuỗi byte của file: bản debug **có** `nav PICK` và
`TEXT-FALLBACK`, bản release **không** — đúng thiết kế `log.h` của upstream.

### Những gì script tự kiểm (và vì sao)

Không chỉ "biên dịch xong là xong" — nó so với **chính file .so đang chạy trên
xe** làm chuẩn:

- **EABI5, không `EF_ARM_ABI_FLOAT_HARD`**, và `.ARM.attributes` **không** có
  `TAG_ABI_VFP_ARGS`. Cả hai file đều vậy ⇒ cùng base AAPCS (soft-float). Sai
  chỗ này thì .so vẫn **nạp được** nhưng gọi hàm OEM sai thầm lặng — tệ hơn là
  lỗi nạp. `TAG_ABI_PCS_WCHAR_T=4`, `TAG_ABI_ENUM_SIZE=2`,
  `TAG_ABI_ALIGN_NEEDED=1`, `TAG_CPU_ARCH=10` (ARMv7-A) đều khớp y file trên xe.
- **Chỉ cần `GLIBC_2.4`**, trong khi CMU có glibc 2.11 (`native/build_arm.py`
  chốt cùng mốc này từ sysroot `libc-2.11.so`). Thừa chỗ thoải mái.
- **Xuất đúng 5 symbol** `msgrcv` + 4 `eDevMgr*`, không hơn. Xem
  [`exports.map`](exports.map): link tĩnh libc++ lôi theo `operator new` /
  `operator delete` thành symbol global, mà .so này nạp bằng `LD_PRELOAD` nên
  nằm đầu bảng tra symbol của cả tiến trình — để lọt thì nó **chiếm quyền cấp
  phát bộ nhớ của cả `jciCARPLAY`**. Version script chặn lại.
- Flag ELF lệch đúng `0x202` so với file trên xe (`EF_ARM_HASENTRY` 0x02 và
  `EF_ARM_ABI_FLOAT_SOFT` 0x200) — đúng mức dung sai mà
  `native/build_arm.py` đã đặt ra trước đó cho cùng cặp linker này.

Báo cáo đầy đủ ghi ra `out/carplay-arm/ARM-CHECKS.json`.

### Hai điểm khác upstream, nói rõ để không bị bất ngờ

1. **libc++ link tĩnh** thay vì dùng `libstdc++.so.6.0.14` của máy xe, đơn giản
   vì ở đây không có sysroot thiết bị. An toàn được là vì **không có kiểu C++
   nào đi qua biên module**: mọi lệnh gọi OEM đều là thunk C thuần resolve bằng
   `dlsym` (`oem/oem_thunk.h`), mọi symbol interpose đều `extern "C"`. Hệ quả:
   .so này **không** phụ thuộc `libstdc++.so.6` lẫn `libgcc_s.so.1` nữa.
2. **Một reloc mới: `R_ARM_TLS_DTPMOD32`** (12 byte `.tbss`). Đó là chỗ
   libc++abi giữ trạng thái exception đang bay (`__cxa_eh_globals`); bản upstream
   không cần vì nó mượn TLS của libstdc++ máy xe. **Không thể bỏ exception để
   tránh**: `nav.cpp`, `devmgr_shim.cpp` và `hud_send.cpp` đều bọc callback của
   thread OEM bằng `catch (...)`, và `hud_send.cpp:736` ghi rõ exception lọt ra
   là `std::terminate` → `SIGABRT` → **head unit reboot**. Reloc này là TLS
   local-dynamic nội bộ module, mà .so nạp bằng `LD_PRELOAD` nên thuộc initial
   load set — ld.so cấp module id ngay lúc khởi động, không phải ca `dlopen` cần
   static TLS surplus. ARM glibc lo được chuyện này từ lâu trước 2.11.

Ngoài ra bỏ `-flto` của upstream (không cần, giảm biến số) và tắt UBSan runtime
của zig: ở `-O0` zig bật sẵn, mà runtime đó lôi theo `std.Io` của zig
(`utimensat`…) — không có ở glibc 2.4 nên link debug đứt ngay, và một sanitizer
runtime cũng chẳng nên có mặt trong tiến trình mà `SIGABRT` là reboot xe.

## Kiểm chứng không cần xe

```sh
cd tests
python -m pip install ziglang
make test-carplay           # 43 kiem tra, 0 loi
```

Hoặc gọi trực tiếp, nếu máy không có `make`:

```sh
python -m ziglang c++ -std=c++17 -w -I ../patches/carplay-hud \
    maneuver_text_test.cpp -o maneuver_text_test
./maneuver_text_test        # 43 kiem tra, 0 loi
```

Test dựng từ các câu dẫn đường tiếng Việt thật, gồm cả nhóm **phải bị từ chối**.
Bản vá `nav.cpp` cũng đã được biên dịch sạch bằng `zig c++ -std=c++17`.

### Kiểm trên rootfs CMU thật (`check_rootfs.py`)

Bộ `mzd-connect-emu` cần Linux x86_64 + `qemu-user` nên không chạy được trên
máy Windows này (muốn dựng Linux thì xem
[docs/setup-linux.vi.md](../../docs/setup-linux.vi.md)). Nhưng **rootfs mà emu
đó tiêu thụ thì đọc được**, và nó trả lời được phần lớn câu "shim có chạy nổi
trên xe không":

```sh
python patches/carplay-hud/check_rootfs.py --rootfs <rootfs đã giải nén>
```

Chạy trên rootfs CMU150 `74.00.333A` — **PASS cả bốn mục**:

1. **6/6 symbol OEM mà shim gọi bằng `dlsym` đều có đúng tên** trong
   `jci/lib/libjcidbus.so` và `jci/lib/libjcivbsnaviclient.so`. Mục này đáng
   kiểm nhất: `oem_thunk.h` cố ý cho thunk **degrade êm** khi không resolve
   được, nên gõ sai một tên hàm sẽ ra đúng triệu chứng "HUD trống" mà **không
   một dòng log nào**. Không có cách nào khác bắt được lỗi đó mà không cần xe.
2. **53/53 symbol undefined của shim có trên `glibc 2.11.1` thật** của rootfs
   (`lib/libc-2.11.1.so` & co.). Mạnh hơn hẳn việc chỉ xem hình dạng ELF: nó
   nói .so này **link được** lúc nạp trên xe. Bản debug: 86/86.
3. **Chuỗi interpose có thật.** `LD_PRELOAD` chỉ ăn nếu có ai trong tiến trình
   gọi symbol đó qua PLT:
   - `jci/carplay/blmjcicarplay.so` (chính là service `jciCARPLAY`) **import cả
     4 symbol `eDevMgr*`** ⇒ phần hook đăng ký của shim chắc chắn ăn.
   - `usr/lib/libdevmgr_interface.so` **xuất 4 symbol `eDevMgr*` đó và gọi
     `msgrcv`** ⇒ đúng thư viện mà shim chen vào để tap khung iAP2.
4. `jciCARPLAY` có trong **cả `sm.conf` lẫn `sm_WCP.conf`** — khớp logic chọn
   config (có dây / không dây) của `install/install.sh`.

**Giới hạn:** đây là kiểm **tĩnh**. Nó chứng minh shim nạp được và chen đúng
chỗ; nó **không** chứng minh shim giải mã đúng khung iAP2 mà VietMap sinh ra.
Việc đó vẫn phải có log trên xe. Ghi chú thêm: `NaviSupported` trong
`etc/devmgr_config_master.xml` của rootfs gốc là `FALSE` — installer phải đặt
`TRUE`, đúng như `install/install.sh` đang làm.

## Chưa chứng minh được điều gì

Đây là bản sửa theo **giả thuyết mạnh nhất**, chưa phải kết luận đã đo:

- Chưa có log trên xe nên **chưa biết chắc khung `0x8059` có tới `jciCARPLAY`
  khi chạy VietMap hay không**. Nếu iOS không phát luồng iAP2 cho app này thì
  patch này không cứu được gì — lúc đó lỗi nằm ngoài tầm với của phía xe.
- Chuỗi `maneuverDesc` thật của VietMap chưa được đọc lần nào; bộ từ khoá dựng
  theo cách hành văn thường gặp. Có log rồi thì chỉnh lại cho khớp.
- **Bản .so ARM chưa từng chạy trên xe.** Nó chỉ được kiểm bằng cách đọc lại
  ELF và so với file đang chạy trên xe (xem trên). Đúng ABI không có nghĩa là
  đúng hành vi.
- Bản debug thì nay **đã build được** (trước đây bế tắc vì thiếu toolchain).
  Việc còn lại là cài nó rồi chạy `vietnav-collect.sh` để lấy dòng
  `nav PICK` / `nav TEXT-FALLBACK` trên xe.

Xem [docs/carplay-vietmap-hud-gap.vi.md](../../docs/carplay-vietmap-hud-gap.vi.md).
