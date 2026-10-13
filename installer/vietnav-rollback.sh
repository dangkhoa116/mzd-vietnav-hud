#!/bin/sh
# vietnav-rollback.sh [aa|cp|all] - remove what vietnav-install.sh changed.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
#   aa  restores the sm configs (removes our jciAAPA/aap_service lines) and
#       the /etc AAP attribute XMLs from their .orig backups
#   cp  removes our jciCARPLAY lines (LD_PRELOAD + the LD_LIBRARY_PATH that
#       was inserted with it) and sets NaviSupported back to FALSE
#
# /data_persist/oem-aa-mod and /data_persist/cp-hud-mod stay on the unit
# (inert without the LD_PRELOAD lines; delete by hand for the space).
# Sanity-checked; fails closed. BusyBox ash.

set -u

TARGET=${1:-all}
LOG=/tmp/vietnav-rollback.log
TAG="[vietnav]"
AA_TOK=data_persist/oem-aa-mod/libpatch
CP_TOK=data_persist/cp-hud-mod/libpatch
CP_LDLP='            <environ_var env_name="LD_LIBRARY_PATH" env_value="/jci/lib:/usr/lib"/>'
MASTER=/etc/devmgr_config_master.xml
WDOG="/sys/class/gpio/Watchdog Disable/value"

log() { echo "$TAG $*" | tee -a "$LOG"; }
die() { echo "$TAG ERROR: $*" | tee -a "$LOG"; mount -o remount,ro / 2>/dev/null; exit 1; }
feed() { [ -w "$WDOG" ] && echo 1 > "$WDOG" 2>/dev/null; return 0; }
want() { [ "$TARGET" = "all" ] || [ "$TARGET" = "$1" ]; }

[ "$(id -u)" = "0" ] || die "must run as root"
[ -f /jci/sm/sm.conf ] || die "not a CMU (no /jci/sm/sm.conf)"
: > "$LOG" || die "cannot write $LOG"
mount -o remount,rw / 2>/dev/null

# --- helper: strip our lines from one conf ---------------------------------------
# strip_env <conf> <token> [paired-line]
#  - counts the token lines first (n), then produces a file with exactly the
#    token lines removed (plus the paired line when it directly follows one),
#  - commits only when the resulting line count matches the prediction.
strip_env() {
    _conf=$1; _tok=$2; _pair=${3:-}
    [ -f "$_conf" ] || return 0
    _n=$(grep -c "$_tok" "$_conf" 2>/dev/null || echo 0)
    [ "$_n" -gt 0 ] || { log "$(basename "$_conf"): nothing to remove"; return 0; }
    feed
    _pairn=0
    if [ -n "$_pair" ]; then
        _pairn=$(awk -v tok="$_tok" -v pair="$_pair" '
            $0 ~ tok { getline nxt; if (nxt == pair) c++ } END { print c + 0 }
        ' "$_conf")
    fi
    _old=$(wc -l < "$_conf")
    awk -v tok="$_tok" -v pair="${_pair:-__none__}" '
        $0 ~ tok {
            if ((getline nxt) > 0 && nxt != pair) print nxt
            next
        }
        { print }
    ' "$_conf" > /tmp/vietnav.sm.new || die "awk failed on $_conf"
    _new=$(wc -l < /tmp/vietnav.sm.new)
    _want=$((_old - _n - _pairn))
    if [ "$_new" = "$_want" ] && ! grep -q "$_tok" /tmp/vietnav.sm.new; then
        cp /tmp/vietnav.sm.new "$_conf"
        log "$(basename "$_conf"): removed $((_n + _pairn)) line(s) ($_old->$_new)"
    else
        rm -f /tmp/vietnav.sm.new
        die "$(basename "$_conf"): sanity check failed ($_old->$_new, want $_want), left untouched (backup: /data_persist/$(basename "$_conf").bak_vietnav)"
    fi
    rm -f /tmp/vietnav.sm.new
}

restart_svc() {
    feed
    smctl -r -n "$1" >/dev/null 2>&1 && log "restarted $1" \
        || log "WARN: smctl could not restart $1 - power-cycle the unit"
}

# ============================ Android Auto ======================================
if want aa; then
    log "--- rollback Android Auto ---"
    for CONF in /jci/sm/sm.conf /jci/sm/sm_WCP.conf; do
        strip_env "$CONF" "$AA_TOK"
    done
    for XML in aap_system_attributes.xml aap_system_attributes_UCP.xml; do
        if [ -f "/etc/$XML.orig" ]; then
            cp -a "/etc/$XML.orig" "/etc/$XML"
            log "restored /etc/$XML"
        fi
    done
    restart_svc jciAAPA
    restart_svc aap_service
fi

# ============================ CarPlay bridge =====================================
if want cp; then
    log "--- rollback CarPlay bridge ---"
    for CONF in /jci/sm/sm.conf /jci/sm/sm_WCP.conf; do
        strip_env "$CONF" "$CP_TOK" "$CP_LDLP"
    done
    if [ -f "$MASTER" ] && grep -q '<name>NaviSupported</name><value>TRUE</value>' "$MASTER"; then
        sed -i 's#<name>NaviSupported</name><value>TRUE</value>#<name>NaviSupported</name><value>FALSE</value>#' "$MASTER"
        log "set NaviSupported=FALSE in $MASTER"
    fi
    restart_svc jciCARPLAY
fi

sync
mount -o remount,ro / 2>/dev/null
log "DONE ($TARGET). /data_persist payload folders were left in place (inert); delete by hand if wanted."
exit 0
