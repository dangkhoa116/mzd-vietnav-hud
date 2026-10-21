#!/bin/sh
# vietnav-install.sh [aa|cp|all] [--yes] - install the HUD navigation mods.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
# Runs as root (from the touch menu, or a terminal). Without --yes it is a
# dry run: it checks everything and prints the plan, and changes nothing.
#
#   aa  = oem-aa-mod (Android Auto -> HUD, GAL 1.6):
#         .so + libpatch.conf -> /data_persist/oem-aa-mod/, LD_PRELOAD
#         into the jciAAPA + aap_service blocks of sm.conf AND sm_WCP.conf,
#         /etc AAP attribute XML swap, service restarts.
#   cp  = CarPlay bridge (KidMixer mazda-carplay-hud, ilshyma build with the
#         km/h + Vietnamese-fold fixes):
#         .so -> /data_persist/cp-hud-mod/, LD_PRELOAD + LD_LIBRARY_PATH into
#         the jciCARPLAY block of sm.conf AND sm_WCP.conf (the bridge runs in
#         both; the wireless-CarPlay gate can boot either one - a trial that
#         runs out, or its rollback, goes back to sm.conf), NaviSupported=TRUE
#         in /etc/devmgr_config_master.xml (what makes the iPhone send the
#         iAP2 maneuver stream), service restart.
#
# Living next to the other kits on this car:
#   - every check runs BEFORE anything is written: a payload file whose md5
#     is not the one in vietnav-payload/PAYLOAD-SOURCES.md, or a service
#     block that already carries an environ_var from another mod, stops the
#     whole install with nothing changed;
#   - the unit's binaries the shims hook into (blmjciaapa.so, aap_service,
#     blmjcicarplay.so, libdevmgr_interface.so) must be the builds the mods
#     were checked on (74.00.324A = 74.00.331, by md5); any other build
#     exits 3 with nothing changed;
#   - if a write fails half-way, everything this run changed in the sm
#     configs, /etc and its own records is put back from the copies it took
#     just before (/data_persist/vietnav/txn), so the unit is never left
#     half-installed;
#   - one run at a time: install and rollback share a lock (/tmp/vietnav.lock);
#   - it adds lines only; reset_board="no" is set on the touched services
#     (a crashing shim must not boot-loop the unit) and recorded, so the
#     rollback can put back exactly what it changed in sm.conf. sm_WCP.conf's
#     reset_board belongs to the wireless-CarPlay kit and is never put back;
#   - nothing of the wireless-CarPlay kit (get_board_type.sh) or of the
#     TPMS add-on (bds, stage_wifi.sh, /data/integration) is touched;
#   - every file is written next to its target and renamed into place, so a
#     power cut leaves the old file or the new one, never half of one.
#
# Idempotent; keeps first-generation backups (/data_persist/*.bak_vietnav,
# /etc/*.orig). What it changed is recorded in /data_persist/vietnav/.
# BusyBox ash.

set -u

TARGET=""; GO=0
for a in "$@"; do
    case "$a" in
        aa|cp|all) TARGET=$a ;;
        --yes)     GO=1 ;;
        -h|--help) awk 'NR > 1 && !/^#/ { exit } NR > 1 { sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
        *)         echo "unknown option: $a (use: aa | cp | all, --yes)" >&2; exit 2 ;;
    esac
done
TARGET=${TARGET:-all}

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
PAYLOAD="$HERE/vietnav-payload"
LOG=/tmp/vietnav-install.log
TAG="[vietnav]"
# The kit version (x.y.z): the same as VERSION in the repo - build-kit.py
# refuses a kit where they differ. The touch menu reads it from here.
VIETNAV_VERSION="0.9.0"
WDOG="/sys/class/gpio/Watchdog Disable/value"
SM=/jci/sm/sm.conf
SMW=/jci/sm/sm_WCP.conf
AA_DIR=/data_persist/oem-aa-mod
CP_DIR=/data_persist/cp-hud-mod
STATE=/data_persist/vietnav
MASTER=/etc/devmgr_config_master.xml

AA_L1='            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-blmjciaapa.so"/>'
AA_L2='            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-aap_service.so"/>'
CP_L1='            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/cp-hud-mod/libpatch-blmjcicarplay.so"/>'
CP_L2='            <environ_var env_name="LD_LIBRARY_PATH" env_value="/jci/lib:/usr/lib"/>'

# The unit's own binaries the shims hook into. The shims patch fixed places
# in them (the aap_service shim calls addresses inside aap_service; the
# CarPlay bridge reads the message layout of the 74.00.324A ipoddev), so
# they install only on these builds - byte-identical on 74.00.324A (EU) and
# 74.00.331 (ADR). Any other build: nothing is changed, exit 3.
AA_HOSTS="/jci/aapa/blmjciaapa.so=486628ae7b5be7c80527968a0b85ae38
/usr/bin/aap_service=964e9af092d8ef2d0eddcd881b26c0e2"
CP_HOSTS="/jci/carplay/blmjcicarplay.so=0a4e3a67de3d6499a4d537c66bf30ff9
/usr/lib/libdevmgr_interface.so=e914face2f2f93d0928a7e132a04f9d8"

TXN=$STATE/txn
LOCK=/tmp/vietnav.lock
WD=0; RW=0; LOCKED=0; APPLYING=0; DONE=0
log() { echo "$TAG $*" | tee -a "$LOG"; }
die() { log "ERROR: $*"; exit 1; }
finish() {
    if [ "$APPLYING" = 1 ] && [ "$DONE" != 1 ]; then undo_apply; fi
    [ "$WD" = 1 ] && echo 0 > "$WDOG" 2>/dev/null
    if [ "$RW" = 1 ]; then
        sync
        mount -o remount,ro / 2>/dev/null \
            || log "WARN: / did not go back to read-only (busy?) - it will at the next start"
    fi
    [ "$LOCKED" = 1 ] && rm -rf "$LOCK"
    cp "$LOG" "$HERE/vietnav-install.log" 2>/dev/null
    sync
}
trap finish EXIT

# one install/rollback at a time (the touch trigger can fire more than once)
lock() {
    if ! mkdir "$LOCK" 2>/dev/null; then
        _p=$(cat "$LOCK/pid" 2>/dev/null)
        if [ -n "$_p" ] && kill -0 "$_p" 2>/dev/null; then
            die "another vietnav install/rollback is running (pid $_p) - nothing changed"
        fi
        rm -rf "$LOCK"                        # left by a run that was killed
        mkdir "$LOCK" 2>/dev/null || die "cannot take the lock $LOCK - nothing changed"
    fi
    echo $$ > "$LOCK/pid"
    LOCKED=1
}

# snap <file>...: keep a copy (or a note that it did not exist) so a failed
# apply can put it back
snap() {
    for _f in "$@"; do
        _k=$(echo "$_f" | tr '/' '%')
        if [ -f "$_f" ]; then
            cp -a "$_f" "$TXN/$_k" || die "copy of $_f before the change failed - nothing changed"
        else
            : > "$TXN/$_k.absent"
        fi
        echo "$_f" >> "$TXN/list"
    done
}
undo_apply() {             # from the EXIT trap: log only, never die here
    log "the install stopped half-way - putting back what it changed"
    _bad=0
    while read -r _f; do
        _k=$(echo "$_f" | tr '/' '%')
        if [ -f "$TXN/$_k" ]; then
            if cmp -s "$TXN/$_k" "$_f"; then continue; fi
            if cp -a "$TXN/$_k" "$_f.vietnav-new" && mv -f "$_f.vietnav-new" "$_f"; then
                log "  put back $_f"
            else
                rm -f "$_f.vietnav-new"; _bad=1; log "  COULD NOT put back $_f (copy kept in $TXN)"
            fi
        elif [ -f "$TXN/$_k.absent" ] && [ -e "$_f" ]; then
            rm -f "$_f" && log "  removed $_f" || { _bad=1; log "  COULD NOT remove $_f"; }
        fi
    done < "$TXN/list"
    sync
    if [ "$_bad" = 0 ]; then
        rm -rf "$TXN"; log "  the unit is as it was before this run"
    else
        log "  NOT everything could be put back - bring the logs home before driving on it"
    fi
}

# verify <file>...: each payload file must have the md5 build-kit recorded
SUMS="$PAYLOAD/PAYLOAD-SOURCES.md"
verify() {
    [ -f "$SUMS" ] || die "vietnav-payload/PAYLOAD-SOURCES.md missing - rebuild the stick, nothing changed"
    command -v md5sum >/dev/null 2>&1 || die "no md5sum on this unit - cannot check the payload, nothing changed"
    for _f in "$@"; do
        _want=$(awk -F'|' -v f="$_f" '{ n = $2; m = $3; gsub(/[ `]/, "", n); gsub(/[ `]/, "", m) }
                                      n == f { print m; exit }' "$SUMS")
        [ -n "$_want" ] || die "no checksum for $_f in PAYLOAD-SOURCES.md - rebuild the stick, nothing changed"
        _got=$(md5sum "$PAYLOAD/$_f" | cut -d' ' -f1)
        [ "$_got" = "$_want" ] \
            || die "vietnav-payload/$_f is damaged (md5 $_got, expected $_want) - rebuild the stick, nothing changed"
    done
    log "  payload md5 ok: $*"
}
# host_check <path=md5 lines>: the unit's binaries must be a checked build
host_check() {
    for _h in $1; do
        _f=${_h%%=*}; _want=${_h#*=}
        [ -f "$_f" ] || unsupported "$_f is not on this unit"
        _got=$(md5sum "$_f" | cut -d' ' -f1)
        [ "$_got" = "$_want" ] \
            || unsupported "$_f is a build this mod was not checked on (md5 $_got)"
        log "  unit binary ok: $_f"
    done
}
unsupported() { log "ERROR: $* - nothing changed (checked: 74.00.324A / 74.00.331)"; exit 3; }
want() { [ "$TARGET" = "all" ] || [ "$TARGET" = "$1" ]; }

: > "$LOG" 2>/dev/null || LOG=/dev/null
mount -o rw,remount "$HERE" 2>/dev/null || true      # the stick, for the log copy
[ "$(id -u)" = "0" ] || die "must run as root"
[ -f "$SM" ] || die "not a CMU (no $SM)"
[ "$GO" = 1 ] && lock

FW=$(sed -n 's/^JCI_SW_VER=//p' /jci/version.ini 2>/dev/null | tr -d '"\r')
log "vietnav $VIETNAV_VERSION target=$TARGET dry-run=$([ $GO = 1 ] && echo no || echo yes) firmware=${FW:-unknown}"
log "  (the shims install only on the unit binaries checked on 74.00.324A / .331)"

# --- what is in one <service> block ----------------------------------------------
# svc_state <conf> <service> <our-line1> [our-line2] -> prints one of
#   absent | duplicate | selfclosing | foreign | partial | ours | clean
# "foreign": the block has an environ_var that is not one of our lines.
svc_state() {
    awk -v svc="name=\"$2\"" -v l1="$3" -v l2="${4:-}" '
        !on && /<service[ \t]/ && index($0, svc) {
            n++; on = 1
            if ($0 ~ /\/>[ \t]*$/) { self = 1; on = 0 }
            next
        }
        on && /<environ_var/ { if ($0 == l1 || (l2 != "" && $0 == l2)) ours++; else foreign++ }
        on && /<\/service>/ { on = 0 }
        END {
            if (n == 0) print "absent"
            else if (n > 1) print "duplicate"
            else if (self) print "selfclosing"
            else if (foreign) print "foreign"
            else if (ours && ours < (l2 != "" ? 2 : 1)) print "partial"
            else if (ours) print "ours"
            else print "clean"
        }' "$1"
}

# --- insert our lines right after the <service ...> line --------------------------
# insert_env <conf> <service> <line1> [line2]
# Writes <conf>.vietnav-new next to it, proves that it differs from the
# original by exactly our lines and the service's reset_board, then renames
# it into place. reset_board yes->no is recorded for sm.conf.
insert_env() {
    _conf=$1; _svc=$2; _l1=$3; _l2=${4:-}
    _new="$_conf.vietnav-new"
    _bak="/data_persist/$(basename "$_conf").bak_vietnav"
    [ -f "$_bak" ] || { cp -a "$_conf" "$_bak" || die "backup of $_conf failed"; log "backup -> $_bak"; }
    _rb=no
    grep "<service .*name=\"$_svc\"" "$_conf" | grep -q 'reset_board="yes"' && _rb=yes
    awk -v svc="name=\"$_svc\"" -v l1="$_l1" -v l2="$_l2" '
        /<service[ \t]/ && index($0, svc) {
            sub(/reset_board="yes"/, "reset_board=\"no\"")
            print; print l1; if (l2 != "") print l2; next
        }
        { print }' "$_conf" > "$_new" || { rm -f "$_new"; die "awk failed on $_conf"; }
    # what the result must be, minus our lines
    sed "/<service .*name=\"$_svc\"/ s/reset_board=\"yes\"/reset_board=\"no\"/" "$_conf" > /tmp/vietnav.want
    # awk, not grep -x: the car's BusyBox 1.19 grep has no -x
    awk -v l1="$_l1" -v l2="$_l2" '$0 != l1 && (l2 == "" || $0 != l2)' "$_new" > /tmp/vietnav.got
    _old=$(wc -l < "$_conf"); _cnt=$(wc -l < "$_new")
    _add=1; [ -n "$_l2" ] && _add=2
    if cmp -s /tmp/vietnav.want /tmp/vietnav.got && [ "$_cnt" = "$((_old + _add))" ] \
            && [ "$(svc_state "$_new" "$_svc" "$_l1" "$_l2")" = ours ]; then
        rm -f /tmp/vietnav.want /tmp/vietnav.got
        mv -f "$_new" "$_conf" || { rm -f "$_new"; die "could not replace $_conf"; }
        sync
        log "$(basename "$_conf"): $_svc +$_add line(s) ($_old->$_cnt), reset_board was $_rb"
        if [ "$_rb" = yes ] && [ "$_conf" = "$SM" ]; then
            echo "$(basename "$_conf") $_svc" >> "$STATE/reset_board"
        fi
    else
        rm -f "$_new" /tmp/vietnav.want /tmp/vietnav.got
        die "$(basename "$_conf"): sanity check failed for $_svc ($_old->$_cnt), left untouched"
    fi
}

# put <src> <dst>: copy next to the target, then rename into place
put() {
    cp "$1" "$2.vietnav-new" && mv -f "$2.vietnav-new" "$2" || { rm -f "$2.vietnav-new"; die "copy failed: $2"; }
}

# ============================ checks (nothing is written here) ===================
PLAN=""          # "conf|service|line1|line2" per insertion still to do
plan_svc() { # plan_svc <conf> <service> <l1> [l2]
    _st=$(svc_state "$1" "$2" "$3" "${4:-}")
    case "$_st" in
        clean)  PLAN="$PLAN
$1|$2|$3|${4:-}"; log "  $(basename "$1"): $2 -> add" ;;
        ours)   log "  $(basename "$1"): $2 -> already in place" ;;
        absent) die "$(basename "$1") has no $2 service - unexpected firmware, nothing changed" ;;
        foreign) die "$(basename "$1"): $2 already has an environ_var from another mod - nothing changed. Remove that mod first (or install by hand)." ;;
        *)      die "$(basename "$1"): $2 block is $_st - nothing changed" ;;
    esac
}
CONFS=""
for c in "$SM" "$SMW"; do [ -f "$c" ] && CONFS="$CONFS $c"; done

if want aa; then
    for f in libpatch-blmjciaapa.so libpatch-aap_service.so libpatch.conf \
             aap_system_attributes.xml aap_system_attributes_UCP.xml; do
        [ -f "$PAYLOAD/$f" ] || die "missing payload file: vietnav-payload/$f (rebuild the stick)"
    done
    log "--- Android Auto (oem-aa-mod) ---"
    verify libpatch-blmjciaapa.so libpatch-aap_service.so libpatch.conf \
           aap_system_attributes.xml aap_system_attributes_UCP.xml
    [ -f "$PAYLOAD/libpatch-svcjcinavi.so" ] && verify libpatch-svcjcinavi.so
    host_check "$AA_HOSTS"
    for c in $CONFS; do
        plan_svc "$c" jciAAPA "$AA_L1"
        plan_svc "$c" aap_service "$AA_L2"
    done
fi
if want cp; then
    [ -f "$PAYLOAD/libpatch-blmjcicarplay.so" ] \
        || die "missing payload file: vietnav-payload/libpatch-blmjcicarplay.so (rebuild the stick)"
    log "--- CarPlay bridge (mazda-carplay-hud) ---"
    verify libpatch-blmjcicarplay.so
    host_check "$CP_HOSTS"
    for c in $CONFS; do
        plan_svc "$c" jciCARPLAY "$CP_L1" "$CP_L2"
    done
    if [ ! -f "$MASTER" ]; then
        log "  WARN: $MASTER absent - the iPhone may not stream maneuvers"
    elif grep -q '<name>NaviSupported</name><value>FALSE</value>' "$MASTER"; then
        log "  NaviSupported FALSE -> TRUE"
    elif grep -q '<name>NaviSupported</name><value>TRUE</value>' "$MASTER"; then
        log "  NaviSupported already TRUE"
    else
        log "  WARN: no NaviSupported entry in the expected form in $MASTER - left as it is"
    fi
fi

if [ "$GO" != 1 ]; then
    log "DRY RUN - nothing changed. Re-run with --yes to install."
    exit 0
fi

# ============================ apply ===============================================
touch /data_persist/.vietnav-w 2>/dev/null && rm -f /data_persist/.vietnav-w || die "/data_persist is not writable"
mkdir -p "$STATE" || die "cannot create $STATE"
if [ -e "$WDOG" ]; then echo 1 > "$WDOG" 2>/dev/null && WD=1; fi
mount -o remount,rw / || die "remount rw of / failed - nothing changed"
RW=1

# copies of everything the apply may change, for undo_apply
rm -rf "$TXN"; mkdir -p "$TXN" || die "cannot create $TXN - nothing changed"
: > "$TXN/list"
for c in $CONFS; do snap "$c"; done
snap "$STATE/reset_board" "$STATE/navisupported" "$STATE/version"
if want aa; then
    for XML in aap_system_attributes.xml aap_system_attributes_UCP.xml; do
        snap "/etc/$XML" "/etc/$XML.orig"
    done
fi
want cp && snap "$MASTER"
APPLYING=1

if want aa; then
    mkdir -p "$AA_DIR" || die "cannot mkdir $AA_DIR"
    for f in libpatch-blmjciaapa.so libpatch-aap_service.so libpatch.conf; do
        put "$PAYLOAD/$f" "$AA_DIR/$f"
        chmod 0644 "$AA_DIR/$f"
    done
    if [ -f "$PAYLOAD/libpatch-svcjcinavi.so" ]; then
        put "$PAYLOAD/libpatch-svcjcinavi.so" "$AA_DIR/libpatch-svcjcinavi.so"
        chmod 0644 "$AA_DIR/libpatch-svcjcinavi.so"
    fi
    sync
    log "payload -> $AA_DIR"
fi
if want cp; then
    mkdir -p "$CP_DIR" || die "cannot mkdir $CP_DIR"
    put "$PAYLOAD/libpatch-blmjcicarplay.so" "$CP_DIR/libpatch-blmjcicarplay.so"
    chmod 0644 "$CP_DIR/libpatch-blmjcicarplay.so"
    sync
    log "payload -> $CP_DIR"
fi

# the sm configs - the .so files are in place before any service points at them
OLDIFS=$IFS
set -f
IFS='
'
for p in $PLAN; do
    IFS='|'
    set -- $p
    IFS=$OLDIFS
    insert_env "$1" "$2" "$3" "${4:-}"
    IFS='
'
done
IFS=$OLDIFS
set +f

if want aa; then
    for XML in aap_system_attributes.xml aap_system_attributes_UCP.xml; do
        [ -f "/etc/$XML" ] || { log "WARN: /etc/$XML absent, skipped"; continue; }
        [ -f "/etc/$XML.orig" ] || cp -a "/etc/$XML" "/etc/$XML.orig" || die "backup of /etc/$XML failed"
        put "$PAYLOAD/$XML" "/etc/$XML"
    done
    sync
    log "AAP attribute XMLs updated (backups: /etc/*.xml.orig)"
fi

if want cp && [ -f "$MASTER" ]; then
    MBAK=/data_persist/devmgr_config_master.xml.bak_vietnav
    [ -f "$MBAK" ] || cp -a "$MASTER" "$MBAK" || die "backup of $MASTER failed"
    if [ ! -f "$STATE/navisupported" ]; then
        if grep -q '<name>NaviSupported</name><value>FALSE</value>' "$MASTER"; then
            echo FALSE > "$STATE/navisupported"
        else
            echo unchanged > "$STATE/navisupported"
        fi
    fi
    if grep -q '<name>NaviSupported</name><value>FALSE</value>' "$MASTER"; then
        sed 's#<name>NaviSupported</name><value>FALSE</value>#<name>NaviSupported</name><value>TRUE</value>#' \
            "$MASTER" > "$MASTER.vietnav-new" && mv -f "$MASTER.vietnav-new" "$MASTER" \
            || { rm -f "$MASTER.vietnav-new"; die "could not update $MASTER"; }
        log "set NaviSupported=TRUE (backup: $MBAK)"
    fi
fi
# what is on the car now - the touch menu shows it in its status line
echo "$VIETNAV_VERSION" > "$STATE/version" || die "could not write $STATE/version"
sync
DONE=1                     # every write is in: nothing below can undo them
rm -rf "$TXN"

restart_svc() {
    if smctl -r -n "$1" >/dev/null 2>&1; then
        log "restarted $1"
    else
        log "WARN: smctl could not restart $1 - a power cycle (ignition off) will do it"
    fi
}
if want aa; then restart_svc jciAAPA; restart_svc aap_service; fi
if want cp; then restart_svc jciCARPLAY; fi

log "DONE ($TARGET)."
log "AA:      Android phone + navigation -> arrow + distance on the HUD."
log "CarPlay: iPhone + navigation (Apple Maps / VIETMAP LIVE) -> same."
exit 0
