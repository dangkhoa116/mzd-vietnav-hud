#!/bin/sh
# VIETNAV native one-start dispatcher. AGPL-3.0-or-later.
# Native experiments never update TPMS's counters, off switches or .so.
D=/data_persist/vietnav-native
PREVIOUS=/jci/bds/bds.vietnav-prev
REAL=/jci/bds/bds.real
SO=/jci/bds/libvietnav-native.so
BASE_MD5=__BASE_MD5__

# Never inherit a native selection into a subsequent normal start.
unset VIETNAV_NATIVE_MODE VIETNAV_NATIVE_TRIAL_MS
fallback() {
    if [ ! -x "$REAL" ]; then
        [ -x /data_persist/tpms-backup/bds ] && exec /data_persist/tpms-backup/bds "$@"
        exec /bin/true
    fi
    H=$(md5sum "$PREVIOUS" 2>/dev/null | awk '{print $1}')
    [ "$H" = "$BASE_MD5" ] && [ -x "$PREVIOUS" ] && exec "$PREVIOUS" "$@"
    exec "$REAL" "$@"
}
[ -f "$D/installed" ] && [ -f "$D/armed" ] || fallback "$@"
# Native trials also honour the owner's existing TPMS off switches.
[ -e /data_persist/tpms/bds-off ] && fallback "$@"
[ -e /data_persist/tpms/disabled ] && fallback "$@"
[ -x "$REAL" ] || fallback "$@"
BOOT=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
MODE= ID= BEFORE= EXTRA=
read -r MODE ID BEFORE EXTRA < "$D/armed"
case "$MODE" in query|advertise) ;; *) fallback "$@" ;; esac
case "$ID" in ''|*[!a-zA-Z0-9-]*) fallback "$@" ;; esac
case "$BOOT:$BEFORE" in *[!a-zA-Z0-9:-]*|:|*:) fallback "$@" ;; esac
[ -n "$BOOT" ] && [ -n "$BEFORE" ] && [ -z "$EXTRA" ] || fallback "$@"
# An unexpected restart in the boot that armed the trial must still run TPMS.
[ "$BOOT" != "$BEFORE" ] || fallback "$@"
md5sum -c "$D/runtime.md5" > /dev/null 2>&1 || fallback "$@"
[ "$(head -c 4 /data_persist/tpms/ble.bts 2>/dev/null)" = BTSB ] || fallback "$@"
[ "$(md5sum "$PREVIOUS" 2>/dev/null | awk '{print $1}')" = "$BASE_MD5" ] || fallback "$@"
mkdir -p /tmp/vietnav-native /tmp/tpms "$D/claims" "$D/logs/$ID" 2>/dev/null || fallback "$@"
# A single native attempt per physical boot and per armed token.
mkdir /tmp/vietnav-native/used 2>/dev/null || fallback "$@"
mv "$D/armed" "$D/claims/$ID" 2>/dev/null || fallback "$@"
sync
MODE= CLAIM_ID= BEFORE= EXTRA=
read -r MODE CLAIM_ID BEFORE EXTRA < "$D/claims/$ID"
[ "$CLAIM_ID" = "$ID" ] && [ -z "$EXTRA" ] || fallback "$@"
case "$MODE" in query|advertise) ;; *) fallback "$@" ;; esac
[ -r "$D/monitor.sh" ] || fallback "$@"
START=$(awk '{print $22}' /proc/$$/stat 2>/dev/null)
case "$START" in ''|*[!0-9]*) fallback "$@" ;; esac
# Record identity before exec: PID and /proc start time survive exec, not reboot.
printf '%s %s %s %s\n' "$$" "$START" "$BOOT" "$ID" > /tmp/vietnav-native/active
printf '%s\n' "$MODE" > "$D/logs/$ID/mode"
cp "$D/runtime.md5" "$D/logs/$ID/runtime.md5" 2>/dev/null || fallback "$@"
# Start independent keeper/watchdog BEFORE LD_PRELOAD is exported.
sh "$D/monitor.sh" "$$" "$START" "$BOOT" "$ID" "$MODE" > /dev/null 2>&1 &
TPMS_LOG=/tmp/vietnav-native/native.log
TPMS_V3_BTS=/data_persist/tpms/ble.bts
TPMS_V3_STOP=query
TPMS_V3_RUNMS=60000
VIETNAV_NATIVE_MODE=$MODE
VIETNAV_NATIVE_TRIAL_MS=180000
export TPMS_LOG TPMS_V3_BTS TPMS_V3_STOP TPMS_V3_RUNMS
export VIETNAV_NATIVE_MODE VIETNAV_NATIVE_TRIAL_MS
LD_PRELOAD=$SO
export LD_PRELOAD
exec "$REAL" "$@"
