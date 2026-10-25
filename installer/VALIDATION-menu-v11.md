# Shared USB menu v11 — 25 October 2026

The standard kit launcher is byte-identical to TPMS and Utils v11: includes
Utils, names a single kit directly and remounts the USB before the Log path
writes its first file. The shared collector retains recent TPMS boot evidence
and Utils state, with the literal printable-character range for BusyBox 1.19.2.

`python3 installer/test_cmu_logs.py` passed all fake-CMU scenarios including
privacy, read-only USB, single-kit navigation and the five-kit Utils button.
The test stubs all mutating commands, including under BusyBox ash.

`native/usb/install-patches.sh` is a separate BLE trial menu with explicit
query, arm, collect and removal safeguards. It is intentionally not replaced
by the standard installer chooser. No navigation/HUD binary changed and no
package was deployed to the car.
