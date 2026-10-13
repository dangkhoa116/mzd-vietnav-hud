# mzd-vietnav-hud

**Bring Vietnamese navigation onto the factory Mazda head-up display (Active Driving Display)** — for any Vietnamese navigation app: VIETMAP LIVE, Waze, Google Maps. Both phone platforms: **Android Auto** (GAL 1.6) and **Apple CarPlay** (iAP2).

English | [Tiếng Việt](README.vi.md)

> Compatibility research and patches for Mazda Connect CMU150 (MZD Connect; CX-5 KF / CX-8 and same-platform units). Not affiliated with Mazda, Vietmap, Google or Apple.

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
tests/
  road_fold_test.cpp           Host test for the patch (zig cc, runs on a PC)
  test_installer.py            Installer/rollback/launcher against a fake CMU
  shim/sys/                    Minimal POSIX shims so the test builds on Windows
  Makefile
```

## Touch install (TouchTune USB)

The installer kit uses the same TouchTune USB mechanism as the other kits for this
car (insert stick → tap INSTALL on the unit's update dialog → a Vietnamese menu).
No keyboard needed at the car. The kit ships **both mods ready to install**:

- **AA** — oem-aa-mod 0.10.0 release binaries (Android Auto → HUD, GAL 1.6)
- **CARPLAY** — the mazda-carplay-hud bridge (ilshyma build: km/h fix + VN fold)

Menu: `CAI DAT` → pick **AA / CARPLAY / CA HAI** · `THU THAP` → diagnostics pack
to the stick · `GO BO` → removes what is installed. Payload provenance and md5s
land in `vietnav-payload/PAYLOAD-SOURCES.md`; every run leaves its log on the
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
  buttons at most, so with three kits the chooser shows all three and the
  cancel lives one screen deeper: every kit's own menu opens with HUY (the
  CarPlay kit's payload, not written for this launcher, gets a BAT DAU / HUY
  confirm first), and after a kit finishes, LAM TIEP / XONG asks whether to
  pick another kit. A fourth kit pages behind TIEP. Each kit's `build-kit.py`
  keeps the other kits' payloads, keeps the CarPlay kit's launcher as
  `wcp-touch.sh`, and never replaces a newer shared launcher.
- **Both sm configs.** The CarPlay gate boots `sm_WCP.conf`, but a trial that
  runs out, or its rollback, boots `sm.conf` again; this kit's lines are in
  both, so the HUD keeps working either way.
- **After the CarPlay kit's rollback** (`wcp-rollback.sh` / `GO BO` in its
  menu) both sm files are back to that kit's backups, so this kit's lines may
  be gone: the VIETNAV menu then says *chua cai* again, and `CAI DAT` puts them
  back.
- **reset_board.** This rollback puts `reset_board="yes"` back only where the
  install recorded changing it in `sm.conf`. `sm_WCP.conf`'s `reset_board` is
  the CarPlay kit's boot-loop guard and is left as it is.
- **Another mod in the same service.** If `jciAAPA`, `aap_service` or
  `jciCARPLAY` already has an `environ_var` from a mod other than this one, the
  install stops before writing anything: no half install. Sort the other mod out
  first.

## Status & roadmap

- [x] Static analysis of VIETMAP LIVE (Android: `updateTrip(Trip)` confirmed;
      iOS: `startNavigationSession` + `CPMapTemplate` confirmed)
- [x] Street-name gap diagnosis + on-car adjudication procedure
- [x] Road-budget patch + host test
- [ ] On-car confirmation: run VIETMAP LIVE with a debug build and read the
      `nav16 STATE` road field (`"--"` would close hypothesis H1)
- [ ] Contribute the patch upstream to oem-aa-mod
- [ ] Unified installer for VN firmware (74.00.331): AA mod + CarPlay bridge +
      Vietnamese folding

## License & credits

Released under **AGPL-3.0** (see [LICENSE](LICENSE)) because it contains patches and
tests derived from AGPL projects. With thanks to:

- [oem-aa-mod](https://github.com/VitaliyKurokhtin/oem-aa-mod) — VitaliyKurokhtin (AGPL-3.0)
- [mazda-carplay-hud](https://github.com/KidMixer/mazda-carplay-hud) — KID MIXER-MODER (AGPL-3.0)
- [mazda-hud-toolkit](https://github.com/ilshyma/mazda-hud-toolkit) — ilshyma (packaged build with the km/h fix + VN folding)
- [headunit](https://github.com/Trevelopment/headunit) — origin of the HUD sender components

"VIETMAP LIVE" and related marks belong to their respective owners; they are
mentioned here for interoperability description only.
