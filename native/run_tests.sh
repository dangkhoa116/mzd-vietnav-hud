#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Host native + existing codec/BlueZ tests; optional period-toolchain ARM run.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
BUILD=${VIETNAV_NATIVE_BUILD:-$ROOT/out/native-build}
TPMS=${VIETNAV_TPMS_SOURCE:-$ROOT/../mzd-connect-tpms}
CC=${CC:-gcc}

"$PY" -m unittest discover -s tests -p 'test_hud_*.py'
"$PY" native/prepare.py --tpms "$TPMS/tpms/v3/v3.c" --out "$BUILD" --host-build
cp "$TPMS/tpms/v3/test_v3_unit.c" "$BUILD/test_tpms_mux.c"
"$CC" -O1 -Wall -Wextra -Werror -DTPMS_V3_UNIT -o "$BUILD/test_tpms_mux" \
    "$BUILD/test_tpms_mux.c" "$BUILD/hud_native.c" -ldl
"$BUILD/test_tpms_mux"
"$CC" -std=c99 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined \
    -fno-sanitize-recover=all -I native tests/native_fuzz.c native/hud_native.c \
    -o "$BUILD/native-fuzz-host"
"$BUILD/native-fuzz-host"

if [ "$#" -gt 0 ]; then
    [ "$#" = 1 ] || { echo "usage: native/run_tests.sh [m3-toolchain-directory]" >&2; exit 2; }
    TC=$1
    QEMU=${VIETNAV_TEST_QEMU:-qemu-arm}
    "$PY" native/build_arm.py --toolchain "$TC" --tpms "$TPMS" --out "$BUILD"
    "$TC/bin/arm-cortexa9_neon-linux-gnueabi-gcc" -std=gnu99 -O1 -g -Wall -Wextra -Werror \
        -static -I native tests/native_fuzz.c native/hud_native.c -o "$BUILD/native-core-arm"
    "$QEMU" "$BUILD/native-core-arm"
    VIETNAV_TEST_ARM_TOOLCHAIN="$TC" VIETNAV_TEST_LIBRARY="$BUILD/libvietnav-native-arm.so" \
        "$PY" tests/test_hud_native_transport.py
fi
