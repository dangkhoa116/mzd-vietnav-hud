#!/bin/sh
# vietnav-rollback.sh - remove what vietnav-install.sh changed.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
# Restores the sm configs (removes only OUR environ_var lines, with a
# sanity check), puts the /etc XMLs back from their .orig backups, and
# leaves /data_persist/oem-aa-mod on the unit (harmless without the
# LD_PRELOAD lines; delete by hand if you want the space). BusyBox ash.

set -u

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
LOG=/tmp/vietnav-rollback.log
TAG="[vietnav]"
TOK=data_persist/oem-aa-mod/libpatch
WDOG="/sys/class/gpio/Watchdog Disable/value"

log() { echo "$TAG $*" | tee -a "$LOG"; }
die() { echo "$TAG ERROR: $*" | tee -a "$LOG"; mount -o remount,ro / 2>/dev/null; exit 1; }
feed() { [ -w "$WDOG" ] && echo 1 > "$WDOG" 2>/dev/null; return 0; }

[ "$(id -u)" = "0" ] || die "must run as root"
[ -f /jci/sm/sm.conf ] || die "not a CMU (no /jci/sm/sm.conf)"
: > "$LOG" || die "cannot write $LOG"
mount -o remount,rw / 2>/dev/null

# --- sm configs: drop our LD_PRELOAD lines ------------------------------------
for CONF in /jci/sm/sm.conf /jci/sm/sm_WCP.conf; do
    [ -f "$CONF" ] || continue
    n=$(grep -c "$TOK" "$CONF" 2>/dev/null || echo 0)
    [ "$n" -gt 0 ] || { log "$(basename "$CONF"): nothing to remove"; continue; }
    feed
    grep -v "$TOK" "$CONF" > /tmp/vietnav.sm.new || die "grep failed on $CONF"
    old=$(wc -l < "$CONF"); new=$(wc -l < /tmp/vietnav.sm.new)
    if [ "$new" = "$((old - n))" ] && ! grep -q "$TOK" /tmp/vietnav.sm.new; then
        cp /tmp/vietnav.sm.new "$CONF"
        log "$(basename "$CONF"): removed $n line(s) ($old->$new)"
    else
        rm -f /tmp/vietnav.sm.new
        die "$(basename "$CONF"): sanity check failed, left untouched (backup: /data_persist/$(basename "$CONF").bak_vietnav)"
    fi
    rm -f /tmp/vietnav.sm.new
done

# --- /etc XMLs back from .orig --------------------------------------------------
for XML in aap_system_attributes.xml aap_system_attributes_UCP.xml; do
    if [ -f "/etc/$XML.orig" ]; then
        cp -a "/etc/$XML.orig" "/etc/$XML"
        log "restored /etc/$XML"
    fi
done

# --- restart ---------------------------------------------------------------------
feed
for SVC_NAME in jciAAPA aap_service; do
    smctl -r -n "$SVC_NAME" >/dev/null 2>&1 && log "restarted $SVC_NAME" \
        || log "WARN: smctl could not restart $SVC_NAME - power-cycle the unit"
done
sync
mount -o remount,ro / 2>/dev/null
log "DONE. $DEST was left in place (inert); delete it by hand if wanted."
exit 0
