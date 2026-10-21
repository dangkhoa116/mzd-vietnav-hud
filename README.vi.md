# mzd-vietnav-hud

**Đưa dẫn đường tiếng Việt lên HUD zin (Active Driving Display) của Mazda Connect** — cho mọi app dẫn đường Việt Nam: VIETMAP LIVE, Waze, Google Maps. Cả hai phía điện thoại: **Android Auto** (GAL 1.6) và **Apple CarPlay** (iAP2).

[English](README.md) | Tiếng Việt

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
installer/
  build-kit.py                 Tạo bộ kit USB cài qua cảm ứng (TouchTune)
  install-patches.sh           Launcher TouchTune dùng chung với kit TPMS (chọn kit)
  vietnav-touch.sh             Menu cảm ứng: CÀI ĐẶT / THU THẬP / GỠ BỎ
  vietnav-install.sh           Installer thật (idempotent, fail-closed)
  vietnav-rollback.sh          Đảo ngược installer, có kiểm tra an toàn
  vietnav-collect.sh           Gói chẩn đoán chỉ-đọc cho buổi chạy xe
  libpatch.conf.vn             Config VN (không thẻ SD: transport vbs, GAL 1.6)
  VIETNAV-STEPS.txt / .vi.txt  Hướng dẫn trên xe
tests/
  road_fold_test.cpp           Host test cho bản vá (zig cc, chạy trên PC)
  test_installer.py            Test installer/rollback/launcher trên CMU giả
  shim/sys/                    Shim POSIX tối giản để test build trên Windows
  Makefile
```

## Cài qua cảm ứng (TouchTune USB)

Bộ installer dùng đúng cơ chế TouchTune USB như các kit khác trên xe này: cắm
dia → bấm INSTALL trên hộp thoại cập nhật → menu tiếng Việt. Không cần bàn
phím. Kit mang **sẵn cả hai mod**:

- **AA** — binary bản release 0.10.0 của oem-aa-mod (Android Auto → HUD, GAL 1.6)
- **CARPLAY** — bridge mazda-carplay-hud (bản ilshyma: fix km/h + fold tiếng Việt)

Menu: `CAI DAT` → chọn **AA / CARPLAY / CA HAI** rồi xác nhận · `THU THAP` →
gói chẩn đoán ra dia · `GO BO` → xác nhận rồi gỡ phần đã cài. Nguồn gốc + md5
từng binary nằm trong `vietnav-payload/PAYLOAD-SOURCES.md`, và trên xe bộ cài
kiểm tra md5 từng file trước khi ghi bất cứ gì; mỗi lần chạy đều để log trên USB
(`vietnav-touch.log`, `vietnav-install.log`, `vietnav-rollback.log`).

```
python installer/build-kit.py E:\        # hoặc bỏ đối số -> installer/dist/
```

`build-kit.py` lấy binary oem-aa-mod từ bản release upstream
(`VIETNAV_AA_MOD_RELEASE`) hoặc từ source build (`VIETNAV_AA_MOD` — đã áp
`patches/oem-aa-mod/*.patch`, cần nếu muốn fix tên đường dài trong binary
ship), và bridge CarPlay qua `VIETNAV_CP_HUD`. Nhóm file kích hoạt TouchTune
được copy từ thư mục all-in-one CarPlay-không-dây nếu dia chưa có (đổi bằng
`VIETNAV_TOUCHTUNE`); file đó thuộc GPL-3.0 của Miatafy nên không commit vào
repo. Mod nào thiếu binary sẽ không xuất hiện trong menu. Kiểm tra installer
trên PC (CMU giả, không cần xe): `python tests/test_installer.py`. Các bước trên xe:
[installer/VIETNAV-STEPS.vi.txt](installer/VIETNAV-STEPS.vi.txt)
([English](installer/VIETNAV-STEPS.txt)).

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
cd tests && make test OEM_AA_MOD=<đường-dẫn-oem-aa-mod>
# hoặc gọi trực tiếp:
python -m ziglang c++ -std=c++17 \
  -I shim -I <oem-aa-mod>/mazda/patches/blmjciaapa/hud \
  -I <oem-aa-mod>/mazda/patches -I <oem-aa-mod>/mazda/patches/common \
  road_fold_test.cpp <oem-aa-mod>/mazda/patches/blmjciaapa/hud/hud_nav16.cpp \
  -o road_fold_test && ./road_fold_test
```

Kỳ vọng: `RESULT: ALL PASS` (tên 81 byte raw → decode nguyên vẹn → fold còn 72 byte,
không còn ký tự 3 byte).

## Tương thích với các mod khác trên cùng xe

Đối chiếu với script của hai kit kia trên xe (kit CarPlay không dây và add-on
TPMS) và có test trong `tests/test_installer.py`: ba kit sửa các file khác
nhau, không kit nào làm hỏng phần của kit khác.

| Vùng trên CMU | Kit CarPlay không dây | Add-on TPMS | Kit này |
|---|---|---|---|
| `/jci/sm/sm.conf`, `sm_WCP.conf` | `reset_board="no"` mọi service trong `sm_WCP.conf`; rollback của nó khôi phục **cả hai** file từ backup riêng | không đụng | **chèn thêm** dòng `environ_var` vào `jciAAPA` / `aap_service` / `jciCARPLAY` ở **cả hai** file, `reset_board="no"` cho ba service đó |
| File khác trên rootfs | `/jci/scripts/get_board_type.sh` (gate) | `/jci/bds/bds` (wrapper + `bds.real`), một dòng trong `/jci/scripts/stage_wifi.sh` | `/etc/aap_system_attributes*.xml` (backup `.orig`), `NaviSupported` trong `/etc/devmgr_config_master.xml` |
| `/data/integration` (loader HMI) | không đụng | loader TPMS | không đụng |
| TouchTune cùng dia | `install-patches.sh` của nó, giữ lại thành `wcp-touch.sh` | `tpms-touch.sh` | `vietnav-touch.sh` |

- **Một dia, ba kit.** `install-patches.sh` là launcher dùng chung với kit TPMS
  (cùng một file, có dòng phiên bản `mzd-touch-launcher`). Nó tìm các payload
  `*-touch.sh` trên dia rồi hỏi chạy kit nào. jci-dialog tối đa 3 nút, nên màn
  chọn luôn hiện 3 nút chuẩn TPMS / CARPLAY / VIETNAV ở đúng vị trí mỗi khi
  dia có ít nhất 2 trong 3 kit, kèm mỗi kit một dòng báo đã cài trên xe hay
  chưa (DA CAI / CHUA CAI, chạy thử hay đang tắt; chỉ đọc, đọc lại mỗi lần
  màn chọn hiện lại). Kit nào không có trên dia không bị giấu đi:
  nút vẫn hiện, bấm vào sẽ báo ngay trên màn rồi quay lại màn chọn. Nút huỷ
  nằm sâu hơn một màn: menu của mỗi kit mở ra có sẵn HUY (payload kit CarPlay
  không viết cho launcher này nên được hỏi BAT DAU / HUY trước), và sau khi
  TPMS hoặc VIETNAV chạy xong và đã bấm đóng thông báo cuối, LAM TIEP / XONG
  hỏi có chọn kit nữa không; kit CarPlay tự khởi động lại máy nên chạy xong
  là hết phiên. Dia có thêm kit lạ (không phải 3 kit chuẩn) dùng màn chọn
  dựng từ những gì thật sự có mặt: 2 hoặc 3 kit trên một màn, 4 kit thì hai
  màn (TIEP). `build-kit.py` của mỗi kit giữ nguyên payload của
  kit khác, giữ launcher của kit CarPlay thành `wcp-touch.sh`, và không thay
  launcher dùng chung bản mới hơn.
- **Cả hai file sm.** Gate CarPlay boot `sm_WCP.conf`, nhưng hết lượt chạy thử
  hoặc rollback thì xe boot lại `sm.conf`; dòng của kit này có ở cả hai nên HUD
  vẫn chạy.
- **Sau khi rollback kit CarPlay** (`wcp-rollback.sh` / `GO BO` trong menu của
  nó) hai file sm trở về backup của kit đó, nên dòng của kit này có thể mất: menu
  VIETNAV sẽ báo *CHUA CAI*, bấm `CAI DAT` là có lại.
- **reset_board.** Rollback của kit này chỉ trả `reset_board="yes"` ở chỗ lúc
  cài đã ghi lại là có đổi trong `sm.conf`. `reset_board` của `sm_WCP.conf` là
  chốt chống boot-loop của kit CarPlay, để nguyên.
- **Mod khác trong cùng service.** Nếu `jciAAPA`, `aap_service` hoặc
  `jciCARPLAY` đã có `environ_var` của mod khác, installer dừng trước khi ghi bất
  cứ gì (exit 4; menu cảm ứng báo XE DA CO MOD KHAC / ANOTHER MOD IS IN). Xử lý
  mod kia trước. Mod nào chèn dòng vào cùng service *sau* khi đã cài kit này
  thì không chặn được việc gỡ: dòng của kit này được gỡ dù nằm ở đâu trong
  block, dòng của mod kia giữ nguyên.
- **Cùng bộ CarPlay bridge do bộ cài khác cài.** Có xe đã chạy bridge này từ
  `/data_persist/oem-carplay` (dòng `LD_PRELOAD` của nó, tiếp theo là đúng dòng
  `LD_LIBRARY_PATH` như của kit này). Nếu hai dòng đó là toàn bộ `environ_var`,
  nằm ngay dưới dòng `<service>`, bộ cài đổi `LD_PRELOAD` sang bản của kit này
  và ghi lại vào `/data_persist/vietnav/takeover`; trước khi cài, menu báo
  CHUA CAI, CO CARPLAY HUD CU. Gỡ cài thì trả lại dòng cũ, bản cũ chạy lại như
  trước. Thư mục `/data_persist/oem-carplay` không bị đụng tới.
- **Không cài dở.** File payload hỏng (sai md5) thì dừng trước khi ghi. Nếu
  đang ghi mà lỗi giữa chừng, mọi thứ lần chạy đó đã đổi (sm config, `/etc`,
  bản ghi của kit) được trả lại từ bản sao chụp ngay trước đó. Mỗi lúc chỉ
  một lần cài/gỡ chạy (`/tmp/vietnav.lock`).
- **Chỉ cài trên bản đã kiểm tra.** Các shim móc vào chỗ cố định trong
  `blmjciaapa.so`, `aap_service`, `blmjcicarplay.so` và
  `libdevmgr_interface.so` của xe. Bộ cài kiểm tra md5 các file này trước, chỉ
  cài khi đúng bản đã kiểm tra (74.00.324A, giống hệt từng byte trên
  74.00.331); bản khác thì dừng, không đổi gì, và menu cảm ứng báo
  KHONG HO TRO / NOT SUPPORTED.

## Trạng thái & lộ trình

- [x] Phân tích tĩnh VIETMAP LIVE (Android `updateTrip(Trip)` — đã xác nhận; iOS
      `startNavigationSession` + `CPMapTemplate` — đã xác nhận)
- [x] Chẩn đoán khoản trống tên đường + quy trình phân xử trên xe
- [x] Bản vá road-budget + host test
- [x] Bộ cài chạm cho firmware VN (74.00.331): AA mod + CarPlay bridge cùng một
      dia TouchTune, có gỡ cài và chế độ thu thập chẩn đoán; launcher dùng
      chung sống cùng kit TPMS và kit CarPlay không dây
- [x] Kiểm tra trên máy: 120 bài test với CMU giả lập, gồm round-trip cài/gỡ trên
      chính file sm cấu hình thật của xe và mọi hộp thoại được soi lại với những
      gì binary jci-dialog của xe thật sự hiển thị được
- [ ] Buổi chạy xe: AA, rồi CarPlay (chỉ THU THAP khi có lỗi) — xác nhận trên
      74.00.331 và đọc hành vi tên đường với VIETMAP LIVE (`road="--"` sẽ chốt
      giả thuyết H1; cần bản build debug)
- [ ] Build binary AA đã vá (road budget 64→256) bằng m3 toolchain; kit hiện ship
      binary upstream 0.10.0, bản vá nằm ở [patches/](patches/oem-aa-mod/) dạng
      nguồn
- [ ] Đóng góp bản vá ngược lên upstream oem-aa-mod

## Phiên bản

Ghi trong `VERSION`, mỗi bản có tag `vx.y.z`. Hộp thoại cài hiện bản trên USB ở
tiêu đề và bản đang cài ở dòng trạng thái (`DA CAI AA / installed 0.9.0`); các
log trên USB cũng ghi số bản, và khi cài xong số bản được lưu ở
`/data_persist/vietnav/version` (THU THAP có lấy file này). Đổi bản: sửa cùng lúc
`VERSION` và `VIETNAV_VERSION` trong `installer/vietnav-install.sh` -
`build-kit.py` từ chối build nếu hai chỗ khác nhau. Xe cài trước 0.9.0 không hiện
bản đang cài.

## Giấy phép & ghi công

Repo này phát hành theo **AGPL-3.0** (xem [LICENSE](LICENSE)) vì chứa bản vá và
test dẫn xuất từ các dự án AGPL. Ghi nguồn:

- [oem-aa-mod](https://github.com/VitaliyKurokhtin/oem-aa-mod) — VitaliyKurokhtin (AGPL-3.0)
- [mazda-carplay-hud](https://github.com/KidMixer/mazda-carplay-hud) — KID MIXER-MODER (AGPL-3.0)
- [mazda-hud-toolkit](https://github.com/ilshyma/mazda-hud-toolkit) — ilshyma (bản đóng gói km/h + VN fold)
- [headunit](https://github.com/Trevelopment/headunit) — nguồn gốc của các thành phần HUD sender

Tên "VIETMAP LIVE" và các thương hiệu liên quan thuộc về chủ sở hữu tương ứng; các
tên này chỉ được nhắc đến nhằm mục đích mô tả tương thích.
