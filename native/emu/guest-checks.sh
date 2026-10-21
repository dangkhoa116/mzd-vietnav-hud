#!/bin/sh
# AGPL-3.0-or-later. DESTRUCTIVE FIXTURE SETUP, DISPOSABLE QEMU GUEST ONLY.
# Refuses ordinary hosts/CMUs; no UART, bds start, radio or reboot operation.
set -eu
grep -q 'CMU_VIETNAV_TEST=1' /proc/cmdline || exit 90
grep -q 'rdinit=/emu-vietnav-init' /proc/cmdline || exit 90
[ -f /tmp/emu-vietnav-fixtures.tar.gz ] || exit 90
OUT=/tmp/vietnav-guest-checks
mkdir -p "$OUT" /tmp/mnt/sda1
fail() { echo "VIETNAV_GUEST_FAIL $*"; exit 1; }
pass() { echo "VIETNAV_GUEST_PASS $*"; }
trap 'rc=$?; echo VIETNAV_GUEST_EXIT=$rc' EXIT
tar -xzf /tmp/emu-vietnav-fixtures.tar.gz -C "$OUT"
tar -xzf "$OUT/kit.tar.gz" -C /tmp/mnt/sda1
USB=/tmp/mnt/sda1
CTL=$USB/native-control.sh
D=/data_persist/vietnav-native
BDS=/jci/bds/bds
SO=/jci/bds/libvietnav-native.so
PREV=/jci/bds/bds.vietnav-prev
mount -o remount,rw /
[ ! -e /jci/bds/bds.real ] && [ ! -e "$D" ] || fail DIRTY_SNAPSHOT
cp -p "$BDS" /jci/bds/bds.real
cp -p "$OUT/tpms-bds-wrapper.sh" "$BDS"
chmod 755 "$BDS"
cp "$OUT/libtpms-v3.so" /jci/bds/libtpms-v3.so
mkdir -p /data_persist/tpms
cp "$OUT/ble.bts" /data_persist/tpms/ble.bts
md5sum /jci/bds/bds.real /jci/bds/libtpms-v3.so /data_persist/tpms/ble.bts /jci/sm/sm.conf > "$OUT/protected.md5"
md5sum "$BDS" | awk '{print $1}' > "$OUT/wrapper.md5"
pass PREINSTALLED_TPMS_FIXTURE
sh "$CTL" status | grep -q NOT_INSTALLED || fail INITIAL_STATUS
if sh "$CTL" arm advertise --yes > "$OUT/no-query.log" 2>&1; then fail ADVERTISE_WITHOUT_QUERY; fi
grep -q QUERY_REQUIRED "$OUT/no-query.log" || fail WRONG_ADVERTISE_GUARD
[ "$(md5sum "$BDS" | awk '{print $1}')" = "$(cat "$OUT/wrapper.md5")" ] || fail WRAPPER_CHANGED_ON_REFUSAL
pass ADVERTISE_REQUIRES_QUERY
sh "$CTL" arm query --yes || fail ARM_QUERY
[ -f "$D/installed" ] && [ -f "$D/armed" ] || fail INSTALL_MARKERS
cmp -s "$SO" "$USB/native-hud-payload/libvietnav-native.so" || fail LIBRARY_CHANGED
cmp -s "$PREV" "$OUT/tpms-bds-wrapper.sh" || fail BACKUP_CHANGED
md5sum -c "$D/runtime.md5" || fail RUNTIME_HASH
md5sum -c "$D/owned.md5" || fail OWNER_HASH
read -r mode trial boot < "$D/armed"
[ "$mode" = query ] && [ "$boot" = "$(cat /proc/sys/kernel/random/boot_id)" ] || fail ARM_BOOT_ID
pass INSTALL_BACKUP_LIBRARY_AND_BOOT_TOKEN
# No bds launch: verify the exact library loads under the real firmware loader
# with native mode unset (inert), in a harmless original BusyBox sleep process.
VIETNAV_NATIVE_MODE= TPMS_LOG=/tmp/vietnav-inert.log LD_PRELOAD="$SO" /bin/sleep 2 &
child=$!
sleep 1
grep -q libvietnav-native.so /proc/$child/maps || fail NATIVE_LIBRARY_NOT_MAPPED
wait "$child" || fail NATIVE_LIBRARY_LOADER
pass ORIGINAL_LOADER_MAPS_NATIVE_LIBRARY
sh "$CTL" disarm --yes || fail DISARM
[ ! -f "$D/armed" ] && [ ! -f "$D/latest-query" ] || fail DISARM_MARKERS
pass DISARM
sh "$CTL" collect || fail LOG_COLLECTION
ls "$USB"/native-hud-logs/*/STATUS.txt > /dev/null || fail LOG_FILES
pass USB_LOG_COLLECTION
# A foreign wrapper must be left alone. Restore the test's known dispatcher
# afterwards, then exercise normal uninstall. Writes stay in the QEMU snapshot.
mount -o remount,rw /
cp -p "$BDS" "$OUT/dispatcher"
printf '#!/bin/sh\nexit 42\n' > "$BDS"
if sh "$CTL" remove --yes > "$OUT/foreign.log" 2>&1; then fail FOREIGN_WRAPPER_OVERWRITTEN; fi
grep -q OWNED_FILES_CHANGED "$OUT/foreign.log" || fail WRONG_REMOVE_GUARD
grep -q 'exit 42' "$BDS" || fail FOREIGN_WRAPPER_CHANGED
cp -p "$OUT/dispatcher" "$BDS"
pass FOREIGN_WRAPPER_REFUSAL
sh "$CTL" remove --yes || fail UNINSTALL
cmp -s "$BDS" "$OUT/tpms-bds-wrapper.sh" || fail TPMS_NOT_RESTORED
[ ! -e "$SO" ] && [ ! -e "$PREV" ] && [ ! -e "$D/installed" ] && [ ! -e "$D/armed" ] || fail REMOVE_LEFTOVERS
md5sum -c "$OUT/protected.md5" || fail PROTECTED_FILES_CHANGED
pass TPMS_BYTE_EXACT_ROLLBACK_AND_PROTECTED_FILES
sh "$CTL" remove --yes || fail IDEMPOTENT_REMOVE
pass IDEMPOTENT_REMOVE
echo VIETNAV_GUEST_ALL_PASS
