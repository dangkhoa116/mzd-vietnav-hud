#!/bin/sh
# vietnav-rollback.sh [aa|cp|all] - remove what vietnav-install.sh changed.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
#   aa  removes our jciAAPA/aap_service lines from sm.conf and sm_WCP.conf
#       and restores the /etc AAP attribute XMLs from their .orig backups
#   cp  removes our jciCARPLAY lines (LD_PRELOAD + LD_LIBRARY_PATH) and puts
#       NaviSupported back to FALSE - only if the install changed it
#
# Only our own lines go: they are matched whole, so another mod's lines in
# the same file are never touched. reset_board goes back to "yes" only where
# the install recorded that it changed it in sm.conf; sm_WCP.conf's
# reset_board belongs to the wireless-CarPlay kit and stays as it is.
#
# /data_persist/oem-aa-mod and /data_persist/cp-hud-mod stay on the unit
# (inert without the LD_PRELOAD lines; delete by hand for the space).
# Sanity-checked; fails closed; files are renamed into place. BusyBox ash.

set -u

TARGET=""
for a in "$@"; do
    case "$a" in
        aa|cp|all) TARGET=$a ;;
        -h|--help) sed -n '2,18p' "$0" | sed 's/^#//; s/^ //'; exit 0 ;;
        *)         echo "unknown option: $a (use: aa | cp | all)" >&2; exit 2 ;;
    esac
done
TARGET=${TARGET:-all}

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
LOG=/tmp/vietnav-rollback.log
TAG="[vietnav]"
WDOG="/sys/class/gpio/Watchdog Disable/value"
SM=/jci/sm/sm.conf
SMW=/jci/sm/sm_WCP.conf
STATE=/data_persist/vietnav
MASTER=/etc/devmgr_config_master.xml

# the exact lines vietnav-install.sh inserts
AA_L1='            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-blmjciaapa.so"/>'
AA_L2='            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-aap_service.so"/>'
CP_L1='            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/cp-hud-mod/libpatch-blmjcicarplay.so"/>'
CP_L2='            <environ_var env_name="LD_LIBRARY_PATH" env_value="/jci/lib:/usr/lib"/>'

WD=0; RW=0
log() { echo "$TAG $*" | tee -a "$LOG"; }
die() { log "ERROR: $*"; exit 1; }
finish() {
    [ "$WD" = 1 ] && echo 0 > "$WDOG" 2>/dev/null
    if [ "$RW" = 1 ]; then sync; mount -o remount,ro / 2>/dev/null; fi
    cp "$LOG" "$HERE/vietnav-rollback.log" 2>/dev/null
    sync
}
trap finish EXIT
want() { [ "$TARGET" = "all" ] || [ "$TARGET" = "$1" ]; }

: > "$LOG" 2>/dev/null || LOG=/dev/null
mount -o rw,remount "$HERE" 2>/dev/null || true      # the stick, for the log copy
[ "$(id -u)" = "0" ] || die "must run as root"
[ -f "$SM" ] || die "not a CMU (no $SM)"
if [ -e "$WDOG" ]; then echo 1 > "$WDOG" 2>/dev/null && WD=1; fi
mount -o remount,rw / || die "remount rw of / failed - nothing changed"
RW=1

# --- strip_env <conf> <service> <line1> [line2] ------------------------------------
# Removes our exact lines from the conf (only directly under that service's
# <service> line, where the install put them) and, for sm.conf, puts back a
# reset_board the install recorded. Commits only when the result is the
# current file minus exactly those lines.
strip_env() {
    _conf=$1; _svc=$2; _l1=$3; _l2=${4:-}
    [ -f "$_conf" ] || return 0
    _rb=no
    if [ "$_conf" = "$SM" ] && grep -qx "$(basename "$_conf") $_svc" "$STATE/reset_board" 2>/dev/null; then
        _rb=yes
    fi
    _new="$_conf.vietnav-new"
    awk -v svc="name=\"$_svc\"" -v l1="$_l1" -v l2="$_l2" -v rb="$_rb" '
        in_svc && ($0 == l1 || (l2 != "" && $0 == l2)) { n++; next }
        { in_svc = 0 }
        /<service[ \t]/ && index($0, svc) {
            if (rb == "yes") sub(/reset_board="no"/, "reset_board=\"yes\"")
            in_svc = 1
        }
        { print }
        END { print n + 0 > "/tmp/vietnav.removed" }' "$_conf" > "$_new" \
        || { rm -f "$_new"; die "awk failed on $_conf"; }
    _n=$(cat /tmp/vietnav.removed 2>/dev/null); _n=${_n:-0}
    rm -f /tmp/vietnav.removed
    if [ "$_n" = 0 ] && [ "$_rb" = no ]; then
        rm -f "$_new"
        log "$(basename "$_conf"): $_svc - nothing of ours"
        return 0
    fi
    _old=$(wc -l < "$_conf"); _cnt=$(wc -l < "$_new")
    # line 1 is ours alone (it names our .so), so none may be left anywhere
    if [ "$_cnt" = "$((_old - _n))" ] && ! grep -q -x -F -e "$_l1" "$_new"; then
        mv -f "$_new" "$_conf" || { rm -f "$_new"; die "could not replace $_conf"; }
        sync
        log "$(basename "$_conf"): $_svc -$_n line(s) ($_old->$_cnt)$([ $_rb = yes ] && echo ', reset_board back to yes')"
        if [ "$_rb" = yes ]; then
            grep -vx "$(basename "$_conf") $_svc" "$STATE/reset_board" > "$STATE/reset_board.new"
            mv -f "$STATE/reset_board.new" "$STATE/reset_board"
        fi
    else
        rm -f "$_new"
        die "$(basename "$_conf"): sanity check failed for $_svc ($_old->$_cnt, removed $_n), left untouched (backup: /data_persist/$(basename "$_conf").bak_vietnav)"
    fi
}

restart_svc() {
    smctl -r -n "$1" >/dev/null 2>&1 && log "restarted $1" \
        || log "WARN: smctl could not restart $1 - power-cycle the unit"
}

# ============================ Android Auto ======================================
if want aa; then
    log "--- rollback Android Auto ---"
    for CONF in "$SM" "$SMW"; do
        strip_env "$CONF" jciAAPA "$AA_L1"
        strip_env "$CONF" aap_service "$AA_L2"
    done
    for XML in aap_system_attributes.xml aap_system_attributes_UCP.xml; do
        if [ -f "/etc/$XML.orig" ]; then
            cp "/etc/$XML.orig" "/etc/$XML.vietnav-new" && mv -f "/etc/$XML.vietnav-new" "/etc/$XML" \
                || die "could not restore /etc/$XML"
            log "restored /etc/$XML"
        fi
    done
    sync
    restart_svc jciAAPA
    restart_svc aap_service
fi

# ============================ CarPlay bridge =====================================
if want cp; then
    log "--- rollback CarPlay bridge ---"
    for CONF in "$SM" "$SMW"; do
        strip_env "$CONF" jciCARPLAY "$CP_L1" "$CP_L2"
    done
    NS=$(cat "$STATE/navisupported" 2>/dev/null)
    if [ "$NS" = FALSE ] && [ -f "$MASTER" ] \
            && grep -q '<name>NaviSupported</name><value>TRUE</value>' "$MASTER"; then
        sed 's#<name>NaviSupported</name><value>TRUE</value>#<name>NaviSupported</name><value>FALSE</value>#' \
            "$MASTER" > "$MASTER.vietnav-new" && mv -f "$MASTER.vietnav-new" "$MASTER" \
            || { rm -f "$MASTER.vietnav-new"; die "could not update $MASTER"; }
        log "NaviSupported back to FALSE"
    elif [ -n "$NS" ]; then
        log "NaviSupported left as it is (the install did not change it)"
    else
        log "NaviSupported left as it is (no record of the install changing it)"
    fi
    rm -f "$STATE/navisupported"
    sync
    restart_svc jciCARPLAY
fi

log "DONE ($TARGET). /data_persist payload folders were left in place (inert); delete by hand if wanted."
exit 0
