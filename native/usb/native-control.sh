#!/bin/sh
# VIETNAV native USB controller. AGPL-3.0-or-later. BusyBox ash.
# No bds kill/restart; the owner power-cycles after arming or removing.
set -u
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || exit 1
P=$HERE/native-hud-payload
D=/data_persist/vietnav-native
BDS=/jci/bds/bds
REAL=/jci/bds/bds.real
SO=/jci/bds/libvietnav-native.so
PREV=/jci/bds/bds.vietnav-prev
BTS=/data_persist/tpms/ble.bts
TXN=$D/txn
LOCK=/tmp/vietnav-native.lock
WDOG='/sys/class/gpio/Watchdog Disable/value'
BASE_MD5=__BASE_MD5__
CMD=${1:-status}; MODE=${2:-}; GO=${3:-}
RW=0; WD=; LOCKED=0; APPLYING=0; DONE=0
log() { printf '%s\n' "[native] $*"; }
fail() { log "ERROR $1"; exit "${2:-1}"; }
hash() { md5sum "$1" 2>/dev/null | awk '{print $1}'; }
owned_hash() { awk -v path="$1" '$2 == path {print $1}' "$D/owned.md5" 2>/dev/null; }
elf_arm() {
    # Minimal BusyBox 1.19 od has -b, but lacks the desktop -A/-t options.
    [ "$(head -c 6 "$1" 2>/dev/null | od -b | awk 'NR == 1 {for (i=2; i<=NF; i++) printf "%s", $i}')" = 177105114106001001 ] &&
    [ "$(dd if="$1" bs=1 skip=18 count=2 2>/dev/null | od -b | awk 'NR == 1 {for (i=2; i<=NF; i++) printf "%s", $i}')" = 050000 ]
}
boot_id() { cat /proc/sys/kernel/random/boot_id 2>/dev/null; }
valid_id() { case "$1" in ''|*[!a-zA-Z0-9-]*) return 1 ;; *) return 0 ;; esac; }
status() {
    if [ -f "$D/installed" ]; then
        if [ "$(hash "$BDS")" = "$(owned_hash "$BDS")" ]; then log 'INSTALLED'; else log 'WRAPPER_CHANGED'; fi
    else log 'NOT_INSTALLED'; fi
    if [ -f "$D/armed" ]; then read -r _m _id _boot < "$D/armed"; log "ARMED ${_m:-unknown}"; else log 'ARMED none'; fi
    if [ -f "$D/query-ok" ]; then log 'QUERY_PROOF present'; else log 'QUERY_PROOF missing'; fi
}
verify_payload() {
    [ -f "$P/MANIFEST.md5" ] || fail NO_MANIFEST
    for _f in bds-dispatch.sh monitor.sh libvietnav-native.so; do
        _want=$(awk -v f="$_f" '$2 == f {print $1}' "$P/MANIFEST.md5")
        [ -n "$_want" ] && [ "$(hash "$P/$_f")" = "$_want" ] || fail "PAYLOAD_CORRUPT $_f"
    done
    elf_arm "$P/libvietnav-native.so" || fail NOT_ARM_LIBRARY
    sh -n "$P/bds-dispatch.sh" && sh -n "$P/monitor.sh" || fail INVALID_SHELL
}
whitelist() {
    case "$1" in "$BDS"|"$SO"|"$PREV"|"$D/monitor.sh"|"$D/owned.md5"|"$D/runtime.md5"|"$D/installed"|"$D/armed"|"$D/latest-query"|"$D/query-ok") return 0 ;; *) return 1 ;; esac
}
undo() {
    [ -f "$TXN/prepared" ] || { rm -rf "$TXN"; return 0; }
    md5sum -c "$TXN/SNAPSHOTS.md5" > /dev/null 2>&1 || { log 'ERROR BAD_TRANSACTION_BACKUP'; return 1; }
    # Validate every path before restoring any file.
    while read -r _i _path _exists; do
        case "$_i:$_exists" in *[!0-9:]*|:*|*:) return 1 ;; esac
        whitelist "$_path" || return 1
        case "$_exists" in 0|1) ;; *) return 1 ;; esac
    done < "$TXN/list"
    _bad=0
    while read -r _i _path _exists; do
        if [ "$_exists" = 1 ]; then
            cp -p "$TXN/f$_i" "$_path.vn-restore" && mv -f "$_path.vn-restore" "$_path" || _bad=1
        else
            rm -f "$_path" || _bad=1
        fi
    done < "$TXN/list"
    sync
    [ "$_bad" = 0 ] || return 1
    rm -rf "$TXN"
    log 'Transaction restored'
}
finish() {
    if [ "$APPLYING" = 1 ] && [ "$DONE" != 1 ]; then undo || log 'ERROR RESTORE_INCOMPLETE - keep USB and backups'; fi
    [ -n "$WD" ] && printf '%s\n' "$WD" > "$WDOG" 2>/dev/null
    if [ "$RW" = 1 ]; then sync; mount -o remount,ro / 2>/dev/null || log 'WARN ROOT_STILL_RW'; fi
    [ "$LOCKED" = 1 ] && rm -rf "$LOCK"
    sync
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
lock() {
    mkdir "$LOCK" 2>/dev/null || fail BUSY
    LOCKED=1
}
writable() {
    [ "$RW" = 1 ] && return
    mount -o remount,rw / || fail ROOT_NOT_WRITABLE
    RW=1
    if [ -f "$WDOG" ]; then
        WD=$(cat "$WDOG" 2>/dev/null)
        case "$WD" in 0|1) printf '1\n' > "$WDOG" || fail WATCHDOG_WRITE ;; *) WD=; fail WATCHDOG_UNKNOWN ;; esac
    fi
}
snapshot() {
    mkdir -p "$TXN" || fail TRANSACTION_CREATE
    : > "$TXN/list" || fail TRANSACTION_LIST
    _i=0
    for _path in "$BDS" "$SO" "$PREV" "$D/monitor.sh" "$D/owned.md5" "$D/runtime.md5" "$D/installed" "$D/latest-query" "$D/query-ok" "$D/armed"; do
        [ ! -L "$_path" ] || fail "SYMLINK $_path"
        if [ -f "$_path" ]; then
            cp -p "$_path" "$TXN/f$_i" || fail SNAPSHOT_COPY
            printf '%s %s 1\n' "$_i" "$_path" >> "$TXN/list" || fail SNAPSHOT_LIST
        elif [ -e "$_path" ]; then fail "UNEXPECTED_FILE $_path"
        else
            : > "$TXN/f$_i.absent" || fail SNAPSHOT_ABSENT
            printf '%s %s 0\n' "$_i" "$_path" >> "$TXN/list" || fail SNAPSHOT_LIST
        fi
        _i=$((_i + 1))
    done
    md5sum "$TXN"/f* "$TXN/list" > "$TXN/SNAPSHOTS.md5" || fail SNAPSHOT_HASH
    : > "$TXN/prepared" || fail TRANSACTION_PREPARE
    sync
    APPLYING=1
    rm -f "$D/armed" || fail DISARM
}
put() { # validated source, target, mode; atomic replacement on target filesystem
    cp -p "$1" "$2.vn-new" && chmod "$3" "$2.vn-new" && mv -f "$2.vn-new" "$2" || fail "WRITE_FAILED $2"
}
recover() {
    [ -d "$TXN" ] || return 0
    # A different installer must not be overwritten by a stale journal.
    _current=$(hash "$BDS")
    _ours=$(hash "$P/bds-dispatch.sh")
    [ "$_current" = "$BASE_MD5" ] || [ "$_current" = "$_ours" ] || fail WRAPPER_CHANGED_RECOVERY
    writable
    undo || fail TRANSACTION_RECOVERY_FAILED
}
check_car() {
    [ -d /jci/sm ] && [ -d /data_persist ] || fail NOT_CMU
    [ ! -L "$D" ] && [ ! -L "$BDS" ] && [ ! -L "$REAL" ] && [ ! -L "$SO" ] && [ ! -L "$PREV" ] || fail SYMLINK
    [ -x "$REAL" ] && elf_arm "$REAL" || fail NO_ORIGINAL_ARM_BDS
    [ -f /jci/bds/libtpms-v3.so ] && elf_arm /jci/bds/libtpms-v3.so || fail TPMS_NATIVE_NOT_INSTALLED
    [ -f "$BTS" ] && [ "$(head -c 4 "$BTS")" = BTSB ] || fail NO_TPMS_BLE_PACK
    [ "$(wc -c < "$BTS")" -gt 40000 ] || fail SHORT_BLE_PACK
    [ ! -e /data_persist/tpms/bds-off ] && [ ! -e /data_persist/tpms/disabled ] || fail TPMS_SWITCHED_OFF
    _boot=$(boot_id); valid_id "$_boot" || fail NO_BOOT_ID
    if [ -f "$D/installed" ]; then
        md5sum -c "$D/owned.md5" > /dev/null 2>&1 || fail OWNED_FILES_CHANGED
        [ "$(hash "$PREV")" = "$BASE_MD5" ] || fail BAD_TPMS_BACKUP
    else
        [ "$(hash "$BDS")" = "$BASE_MD5" ] || fail TPMS_WRAPPER_UNSUPPORTED
        [ ! -e "$PREV" ] && [ ! -e "$SO" ] || fail NATIVE_FILES_ALREADY_EXIST
    fi
}
collect() {
    _tag=$(date +%Y%m%d-%H%M%S)-$$
    _out=$HERE/native-hud-logs/$_tag
    mkdir -p "$_out" || fail USB_NOT_WRITABLE
    status > "$_out/STATUS.txt"
    if [ -d "$D/logs" ]; then cp -R "$D/logs" "$_out/trials" || fail COPY_LOGS; fi
    [ ! -f /tmp/vietnav-native/native.log ] || cp /tmp/vietnav-native/native.log "$_out/native-live.log" || fail COPY_LIVE_LOG
    for _f in runtime.md5 query-ok latest-query; do
        [ ! -f "$D/$_f" ] || cp "$D/$_f" "$_out/$_f" || fail COPY_METADATA
    done
    log "LOGS_SAVED $_out"
}
case "$CMD" in
    status) status; exit 0 ;;
    collect) collect; exit 0 ;;
    arm) case "$MODE" in query|advertise) ;; *) fail INVALID_MODE 2 ;; esac; [ "$GO" = --yes ] || fail USE_ARM_MODE_YES 2 ;;
    remove|disarm) [ "$MODE" = --yes ] || fail USE_COMMAND_YES 2 ;;
    *) fail INVALID_COMMAND 2 ;;
esac
[ "$(id -u)" = 0 ] || fail ROOT_REQUIRED
[ -d /jci/sm ] && [ -d /data_persist ] || fail NOT_CMU
lock
[ ! -L "$D" ] || fail SYMLINK
mkdir -p "$D" || fail STATE_CREATE
if [ "$CMD" = disarm ]; then
    rm -f "$D/armed" "$D/latest-query" || fail DISARM
    log 'DISARMED - no future native trial; current process ends at restart'
    exit 0
fi
recover
if [ "$CMD" = remove ]; then
    if [ ! -f "$D/installed" ]; then log 'ALREADY_REMOVED'; exit 0; fi
    # A damaged library must not prevent restoring a known original wrapper.
    [ ! -L "$BDS" ] && [ "$(hash "$BDS")" = "$(owned_hash "$BDS")" ] || fail OWNED_FILES_CHANGED
    [ "$(hash "$PREV")" = "$BASE_MD5" ] || fail BAD_TPMS_BACKUP
    writable
    snapshot
    put "$PREV" "$BDS" 755
    [ "$(hash "$BDS")" = "$BASE_MD5" ] || fail RESTORE_VERIFY
    rm -f "$SO" "$PREV" "$D/installed" "$D/owned.md5" "$D/armed" "$D/latest-query" "$D/query-ok" || fail REMOVE_FAILED
    DONE=1
    rm -rf "$TXN"
    log 'REMOVED - power cycle to return to TPMS; logs kept'
    exit 0
fi
verify_payload
check_car
if [ "$MODE" = advertise ]; then
    [ -f "$D/query-ok" ] && cmp -s "$D/query-ok" "$D/runtime.md5" || fail QUERY_REQUIRED
    md5sum -c "$D/query-ok" > /dev/null 2>&1 || fail QUERY_STALE
fi
# No second trial while the same physical boot already ran native.
[ ! -d /tmp/vietnav-native/used ] || fail RESTART_BEFORE_REARM
writable
snapshot
if [ ! -f "$D/installed" ]; then
    put "$BDS" "$PREV" 755
    [ "$(hash "$PREV")" = "$BASE_MD5" ] || fail BACKUP_VERIFY
fi
put "$P/libvietnav-native.so" "$SO" 644
put "$P/monitor.sh" "$D/monitor.sh" 644
md5sum "$SO" "$BTS" "$REAL" "$D/monitor.sh" > "$D/runtime.md5.vn-new" || fail RUNTIME_HASH
mv -f "$D/runtime.md5.vn-new" "$D/runtime.md5" || fail RUNTIME_HASH_COMMIT
if [ "$MODE" = advertise ]; then
    cmp -s "$D/query-ok" "$D/runtime.md5" || fail QUERY_STALE_PAYLOAD
fi
put "$P/bds-dispatch.sh" "$BDS" 755
md5sum "$BDS" "$SO" "$PREV" "$D/monitor.sh" > "$D/owned.md5.vn-new" || fail OWNER_HASH
mv -f "$D/owned.md5.vn-new" "$D/owned.md5" || fail OWNER_HASH_COMMIT
printf '0.1.0-native-trial\n' > "$D/installed.vn-new" && mv -f "$D/installed.vn-new" "$D/installed" || fail INSTALL_MARKER
ID=$(date +%Y%m%d-%H%M%S)-$$
valid_id "$ID" || fail BAD_TRIAL_ID
mkdir -p "$D/logs" || fail LOG_DIR
mkdir "$D/logs/$ID" || fail LOG_ID_COLLISION
printf '%s\n' "$MODE" > "$D/logs/$ID/mode"
if [ "$MODE" = query ]; then
    rm -f "$D/query-ok"
    printf '%s\n' "$ID" > "$D/latest-query.vn-new" && mv -f "$D/latest-query.vn-new" "$D/latest-query" || fail LATEST_QUERY
fi
printf '%s %s %s\n' "$MODE" "$ID" "$(boot_id)" > "$D/armed.vn-new" || fail ARM_WRITE
sync
mv -f "$D/armed.vn-new" "$D/armed" || fail ARM_COMMIT
sync
DONE=1
rm -rf "$TXN"
log "ARMED $MODE - power cycle; one native start, then TPMS next startup"
