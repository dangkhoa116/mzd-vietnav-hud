# mzd-vietnav-hud

**Compatibility research for Vietnamese navigation on the factory Mazda head-up display (Active Driving Display)** through **Android Auto** (GAL 1.6), **Apple CarPlay** (iAP2), and an experimental BLE HUD peripheral for VIETMAP LIVE.

English | [Tiếng Việt](README.vi.md)

[Continue on a local machine: handoff, setup and next steps (Vietnamese)](CONTINUE-LOCAL.vi.md).

> Compatibility research and patches for Mazda Connect CMU150 (MZD Connect; CX-5 KF / CX-8 and same-platform units). Not affiliated with Mazda, Vietmap, Google or Apple.

## In progress: VietMap BLE HUD emulation

The Linux/BlueZ `VIETNAV HUD` prototype and offline decoder implement the HUD
wire formats found in the supplied VML 3.4.3 IPA, including navigation, road
names and camera data. All 21 codec/CLI/D-Bus tests pass. **Phone acceptance over
real BLE and Mazda HUD output for this path remain unverified.** See the
[runbook and remaining work](docs/hud-emulator.md) (Vietnamese).

The [SDK notes](docs/vietmap-hud-sdk.md) correct the old checksum description
and distinguish evidence of a permission flow from an unverified claim that
every emulated HUD is rejected. The existing CarPlay bridge works with Google
Maps/Apple Maps on the tested car; VML 3.4.3 does not supply the needed CarPlay
metadata. The BLE prototype is separate from the 0.9.2 USB installer.

The [native CMU implementation](native/README.md) reuses the TPMS HCI mux for
advertising, one peripheral connection, GATT and HUDInfo exchange. It builds
with m3-toolchain/glibc 2.11: 70 host tests, 229 mux checks and 5 ARM/QEMU
transport tests pass. A [dedicated USB trial kit](native/usb/README.md) adds
query-first gating, a single native start, log collection and TPMS rollback.
Real BLE validation and VBS output for this path remain outstanding.

For the ESP32-C3 Mini already available, use the [C3 firmware and capture
guide](emu/esp32-hud-emu/README.vi.md). Both the default legacy-advertising
build and optional extended diagnostic compile with Arduino-ESP32 3.3.2 /
NimBLE 2.3.7. The shared C++ codec passes sanitizer checks, frozen SDK vectors,
Python cross-checks and 50,000 malformed inputs. On 2026-10-22 a flashed board
passed 22/22 checks over **real BLE** from a PC acting as the GATT central
(`emu/esp32-hud-emu/ble_central_probe.py`): advertising, connection, both
device families, checksum-verified HUDInfo, Vietnamese road names through
20-byte fragmented writes, the legacy CRC16 heartbeat and end-of-guidance.
Mazda HUD output remains unverified — a PC central is not the phone app.

> **Settled 2026-10-22 — the Android app discovers HUDs over Bluetooth Classic,
> not BLE.** On a Samsung running Android 16 with VIETMAP LIVE 3.4.3, the HUD
> screen calls `BluetoothAdapter.startDiscovery()` (a Classic inquiry) and never
> calls `startScan`. Android *did* find the board, parsed its `FFF0`+`FFFF` EIR
> UUIDs and cached the name `VMHUD-EMU`, yet the app reported "no devices
> nearby"; the board was the only `LE`-only entry among 53 `DUAL`/`BR/EDR`
> devices, and every relevant permission was granted. **The ESP32-C3 therefore
> cannot serve the Android branch** — a hardware limit, not a firmware fault.
> That branch needs a dual-mode part with SPP such as the original ESP32
> (WROOM-32); the **iOS branch is still worth trying on the C3**, since the iOS
> SDK uses CoreBluetooth on `FFF0`. See the
> [Dart-layer analysis](docs/hud-dart-layer-analysis.vi.md) (Vietnamese).

C3 supports BLE, not Classic SPP; stock CMU SPP capability
also remains conditional on controller ownership and the app's actual profile.

## Background

The CMU150-generation Mazda Connect projects a head-up display, but stock firmware only renders guidance from the built-in Navigation app (SD card). The community has two open (AGPL-3.0) solutions that put phone navigation on the HUD:

| Path | Community solution | Mechanism |
|---|---|---|
| **Android Auto** | [VitaliyKurokhtin/oem-aa-mod](https://github.com/VitaliyKurokhtin/oem-aa-mod) | LD_PRELOAD shim into `aap_service` — advertises **GAL 1.6** so the phone sends maneuver/lane/distance data |
| **Apple CarPlay** | [KidMixer/mazda-carplay-hud](https://github.com/KidMixer/mazda-carplay-hud) | LD_PRELOAD shim into `jciCARPLAY` — passively taps `msgrcv`, decodes iAP2 `0x8059/0x8058`, feeds `com.jci.vbs.navi` |

This project adds what is still missing for the Vietnamese market:

1. **Root-cause analysis of the missing street name** — why VIETMAP LIVE shows an arrow on the HUD but no street line, with a 10-minute on-car diagnostic procedure.
2. **A patch for oem-aa-mod** — fixes long Vietnamese street names being clipped before diacritic folding (an upstream-acknowledged "known limitation").
3. **A host test** — proves the patch on a PC, no car needed.
4. **A technical profile of VIETMAP LIVE** — static-analysis notes that feed the above.

## Repository layout

```
docs/
  vietmap-hud-gap.md           Diagnosis of "VIETMAP LIVE shows no street name" (tiếng Việt)
  vietmap-live-internals.md    VIETMAP LIVE 3.4.3 static-analysis profile (tiếng Việt)
  vmlhud-nav-payloads.md       HUD BLE nav payload layouts — pinned by disassembly (tiếng Việt)
  vietmap-hud-sdk.md           HUD wire formats and permission evidence (tiếng Việt)
  hud-emulator.md              BLE prototype runbook and limitations (tiếng Việt)
hud_emulator/
  protocol.py                  Legacy/new HUD codec; navigation/camera decoder
  bluez.py                     Linux/BlueZ peripheral and JSON Lines capture
  __main__.py                  CLI: ble / decode
patches/
  oem-aa-mod/
    0001-hud-nav16-road-budget-64-to-256.patch   Long-VN-road-name fix
    README.md                   What it changes and how to apply it (tiếng Việt)
installer/
  build-kit.py                 Builds the TouchTune USB stick kit
  install-patches.sh           TouchTune launcher, shared with the TPMS kit (picks a kit)
  vietnav-touch.sh             Touch menu: install / collect / rollback
  vietnav-install.sh           The real installer (idempotent, fails closed)
  vietnav-rollback.sh          Inverse of the installer, sanity-checked
  vietnav-collect.sh           Read-only diagnostics pack for the car session
  libpatch.conf.vn             VN runtime config (no nav SD: vbs transport, GAL 1.6)
  VIETNAV-STEPS.txt / .vi.txt  In-car instructions
bridge/                        VIETMAP HUD BLE frame + nav-payload codec (Python, host-tested)
emu/esp32-hud-emu/             ESP32-C3 firmware, FFF0 + FFFF, HUDInfo, frame/nav logs
                               build.py packages firmware + source; capture_serial.py
                               saves Serial; decode_log.py exports JSON Lines
tests/
  road_fold_test.cpp           Host test for the patch (zig cc, runs on a PC)
  test_installer.py            Installer/rollback/launcher against a fake CMU
  test_hud_protocol.py         17 codec/CLI tests with synthetic inputs
  test_hud_bluez.py            4 D-Bus/session tests without a BLE radio
  shim/sys/                    Minimal POSIX shims so the test builds on Windows
  Makefile
```

## Touch install (TouchTune USB)

The installer kit uses the same TouchTune USB mechanism as the other kits for this
car (insert stick → tap INSTALL on the unit's update dialog → a Vietnamese menu).
No keyboard needed at the car. The kit ships **both mods ready to install**:

- **AA** — oem-aa-mod 0.10.0 release binaries (Android Auto → HUD, GAL 1.6)
- **CARPLAY** — the mazda-carplay-hud bridge (ilshyma build: km/h fix + VN fold)

Menu: `CAI DAT` → pick **AA / CARPLAY / CA HAI**, then confirm · `THU THAP` →
diagnostics pack to the stick · `GO BO` → confirm, then removes what is
installed. Payload provenance and md5s land in
`vietnav-payload/PAYLOAD-SOURCES.md`, and the install checks every payload file
against them on the car before it writes anything; every run leaves its log on the
stick (`vietnav-touch.log`, `vietnav-install.log`, `vietnav-rollback.log`).

```
python installer/build-kit.py E:\        # or omit the arg -> installer/dist/
```

`build-kit.py` picks the oem-aa-mod binaries from an upstream release
(`VIETNAV_AA_MOD_RELEASE`) or a source build (`VIETNAV_AA_MOD`, with
`patches/oem-aa-mod/*.patch` applied — needed if you want the long-road-name
fix in the shipped binary), and the CarPlay bridge via `VIETNAV_CP_HUD`. It
also copies the TouchTune trigger files from the wireless-CarPlay all-in-one
folder when they are not on the stick (override with `VIETNAV_TOUCHTUNE`);
they are GPL-3.0 by Miatafy and therefore not committed here. A mod whose
binaries are missing is simply not offered in the menu.

Installer checks on a PC (fake CMU, no car): `python tests/test_installer.py`.

In-car steps: [installer/VIETNAV-STEPS.txt](installer/VIETNAV-STEPS.txt)
([tiếng Việt](installer/VIETNAV-STEPS.vi.txt)).

## The patch: long Vietnamese street names on the HUD

The problem: the HUD ECU only renders Unicode below U+0800, so precomposed Vietnamese
letters (U+1E00–U+1EFF, 3 UTF-8 bytes each) lose their diacritics. oem-aa-mod already
folds them (`translit.h`: ễ→ê, ớ→ơ…), but on the GAL 1.6 path the street name is
**truncated to 63 bytes at decode time — before folding**. An accented Vietnamese name
often exceeds 63 bytes raw yet shrinks to 1–2 bytes per letter once folded, so it gets
clipped unnecessarily.

The patch raises the decode budget of `AaGuidance.road` and `AaNav16HudState.road`
from 64 to 256 bytes — the same contract the GAL 1.5 path already uses
(`kRoadCap=255`). Details: [patches/oem-aa-mod/README.md](patches/oem-aa-mod/README.md).

Run the host test (no car required):

```
cd tests && make test OEM_AA_MOD=/path/to/oem-aa-mod
# or invoke zig directly:
python -m ziglang c++ -std=c++17 \
  -I shim -I <oem-aa-mod>/mazda/patches/blmjciaapa/hud \
  -I <oem-aa-mod>/mazda/patches -I <oem-aa-mod>/mazda/patches/common \
  road_fold_test.cpp <oem-aa-mod>/mazda/patches/blmjciaapa/hud/hud_nav16.cpp \
  -o road_fold_test && ./road_fold_test
```

Expected output: `RESULT: ALL PASS` (an 81-byte raw name decodes intact, folds to 72
renderable bytes).

## Compatibility with other mods on the same car

Checked against the scripts of the two other kits on this car (the
wireless-CarPlay kit and the TPMS add-on), and covered by
`tests/test_installer.py`: the three touch different files, and none of them
undoes another's.

| Area on the CMU | Wireless-CarPlay kit | TPMS add-on | This kit |
|---|---|---|---|
| `/jci/sm/sm.conf`, `sm_WCP.conf` | `reset_board="no"` on every service in `sm_WCP.conf`; its rollback restores **both** files from its own backups | not touched | **adds** `environ_var` lines to `jciAAPA` / `aap_service` / `jciCARPLAY` in **both** files, `reset_board="no"` on those three |
| Other root-fs files | `/jci/scripts/get_board_type.sh` (the gate) | `/jci/bds/bds` (wrapper + `bds.real`), one line in `/jci/scripts/stage_wifi.sh` | `/etc/aap_system_attributes*.xml` (`.orig` backups), `NaviSupported` in `/etc/devmgr_config_master.xml` |
| `/data/integration` (HMI loader) | not touched | TPMS loader | not touched |
| TouchTune on the same stick | its own `install-patches.sh`, kept as `wcp-touch.sh` | `tpms-touch.sh` | `vietnav-touch.sh` |

- **One stick, three kits.** `install-patches.sh` is a launcher shared with the
  TPMS kit (same file, `mzd-touch-launcher` version line). It finds the
  `*-touch.sh` payloads on the stick and asks which one. jci-dialog has three
  buttons at most, so the chooser shows the three standard kits - TPMS,
  CARPLAY, VIETNAV - in the same places whenever at least two of them are on
  the stick, over one line per kit saying whether it is installed on the car
  (DA CAI / CHUA CAI, trial or switched off; read only, refreshed every time
  the chooser comes back). A kit that is not on the stick is not hidden: its
  button stays and tapping it says so on screen, then the chooser comes back.
  The cancel lives one screen deeper: every kit's own menu opens with HUY (the CarPlay
  kit's payload, not written for this launcher, gets a BAT DAU / HUY confirm
  first). After TPMS or VIETNAV finishes and its last message is tapped
  away, LAM TIEP / XONG asks whether to pick another kit; the CarPlay kit
  restarts the unit, so it ends the session. A stick with an extra,
  non-standard kit gets the plain chooser built from what is actually there:
  two or three kits on one screen, four on two (TIEP).
  Each kit's `build-kit.py` keeps the other kits' payloads, keeps the CarPlay
  kit's launcher as `wcp-touch.sh`, and never replaces a newer shared
  launcher.
- **Both sm configs.** The CarPlay gate boots `sm_WCP.conf`, but a trial that
  runs out, or its rollback, boots `sm.conf` again; this kit's lines are in
  both, so the HUD keeps working either way.
- **After the CarPlay kit's rollback** (`wcp-rollback.sh` / `GO BO` in its
  menu) both sm files are back to that kit's backups, so this kit's lines may
  be gone: the VIETNAV menu then says *CHUA CAI* again, and `CAI DAT` puts them
  back.
- **reset_board.** This rollback puts `reset_board="yes"` back only where the
  install recorded changing it in `sm.conf`. `sm_WCP.conf`'s `reset_board` is
  the CarPlay kit's boot-loop guard and is left as it is.
- **Another mod in the same service.** If `jciAAPA`, `aap_service` or
  `jciCARPLAY` already has an `environ_var` from a mod other than this one, the
  install stops before writing anything (exit 4; the touch menu says
  XE DA CO MOD KHAC / ANOTHER MOD IS IN). Sort the other mod out first. A mod
  that adds its line to the same service *after* this install does not stop
  the rollback: our lines are taken out wherever they sit in the block, theirs
  stay.
- **The same CarPlay bridge from another installer.** Some cars already run
  this bridge from `/data_persist/oem-carplay` (its `LD_PRELOAD` line followed
  by the same `LD_LIBRARY_PATH` line). When those two lines are the whole
  `environ_var` set, right under the `<service>` line, the install points the
  `LD_PRELOAD` at our build instead and records it in
  `/data_persist/vietnav/takeover`; the menu shows
  CHUA CAI, CO CARPLAY HUD CU before. The rollback puts the old line back, so
  the old install runs again. `/data_persist/oem-carplay` is never touched.
- **No half install.** A damaged payload file (md5) stops the install before
  any write. A write that fails half-way puts back everything that run changed
  (sm configs, `/etc`, its own records) from copies taken just before. One
  install/rollback at a time (`/tmp/vietnav.lock`).
- **Only on checked builds.** The shims hook fixed places in the unit's own
  `blmjciaapa.so`, `aap_service`, `blmjcicarplay.so` and
  `libdevmgr_interface.so`. The install checks their md5 first and goes ahead
  only on the builds the mods were checked on (74.00.324A, byte-identical on
  74.00.331); anything else stops with nothing changed and the touch menu
  says KHONG HO TRO / NOT SUPPORTED.

## Status & roadmap

- [x] Static analysis of VIETMAP LIVE (Android: `updateTrip(Trip)` confirmed;
      iOS: `startNavigationSession` + `CPMapTemplate` confirmed)
- [x] Street-name gap diagnosis + on-car adjudication procedure
- [x] Road-budget patch + host test
- [x] Touch install kit for VN firmware (74.00.331): AA mod + CarPlay bridge on
      one TouchTune stick, with rollback and a diagnostics collect mode; the
      shared launcher coexists with the TPMS and wireless-CarPlay kits
- [x] Host checks: 120 checks against a fake CMU, including the install/rollback
      round trip on the car's own sm configs and every dialog checked against
      what the car's jci-dialog binary really shows
- [ ] On-car session: AA, then CarPlay (THU THAP only if one fails) — confirm
      on FW 74.00.331 and read the street-name behaviour with VIETMAP LIVE
      (`road="--"` would close hypothesis H1; needs the debug build)
- [ ] Build the patched AA binaries (road budget 64→256) with the m3 toolchain;
      the kit currently ships upstream 0.10.0 binaries, the patch lives in
      [patches/](patches/oem-aa-mod/) as source
- [ ] Contribute the patch upstream to oem-aa-mod

## Version

`VERSION` holds the version (x.y.z), and each release is tagged `vx.y.z`. The
touch installer shows the stick's version in its title and the installed one
in its status line (`DA CAI AA / installed 0.9.0`); every log on the stick
names it too, and the install records it in `/data_persist/vietnav/version`
(THU THAP collects it). To bump it, change `VERSION` and `VIETNAV_VERSION` in
`installer/vietnav-install.sh` together: `build-kit.py` refuses a kit where
they differ. Cars installed before 0.9.0 show no installed version.

## License & credits

Released under **AGPL-3.0** (see [LICENSE](LICENSE)) because it contains patches and
tests derived from AGPL projects. With thanks to:

- [oem-aa-mod](https://github.com/VitaliyKurokhtin/oem-aa-mod) — VitaliyKurokhtin (AGPL-3.0)
- [mazda-carplay-hud](https://github.com/KidMixer/mazda-carplay-hud) — KID MIXER-MODER (AGPL-3.0)
- [mazda-hud-toolkit](https://github.com/ilshyma/mazda-hud-toolkit) — ilshyma (packaged build with the km/h fix + VN folding)
- [headunit](https://github.com/Trevelopment/headunit) — origin of the HUD sender components

"VIETMAP LIVE" and related marks belong to their respective owners; they are
mentioned here for interoperability description only.
