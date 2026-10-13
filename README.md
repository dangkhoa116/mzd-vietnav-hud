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
tests/
  road_fold_test.cpp           Host test for the patch (zig cc, runs on a PC)
  shim/sys/                    Minimal POSIX shims so the test builds on Windows
  Makefile
```

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
