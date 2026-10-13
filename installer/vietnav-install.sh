#!/bin/sh
# vietnav-install.sh - install the patched oem-aa-mod for Vietnamese cars.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
# Runs as root (from the TouchTune touch UI, or a terminal). Does what
# oem-aa-mod's docs/installation.md describes, nothing more:
#
#   1. copies libpatch-*.so + libpatch.conf to /data_persist/oem-aa-mod/
#   2. adds an <environ_var LD_PRELOAD> to the jciAAPA and aap_service
#      blocks of every sm config that has them (sm.conf / sm_WCP.conf)
#   3. backs up and replaces /etc/aap_system_attributes*.xml
#   4. restarts jciAAPA + aap_service via smctl (or asks for a power cycle)
#
# Idempotent; keeps first-generation backups (*.bak_vietnav, *.orig).
# Fails closed: sanity-checks every file edit and leaves the unit untouched
# on any surprise. BusyBox ash.

set -u

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
PAYLOAD="$HERE/vietnav-payload"
DEST=/data_persist/oem-aa-mod
LOG=/tmp/vietnav-install.log
TAG="[vietnav]"
WDOG="/sys/class/gpio/Watchdog Disable/value"

log() { echo "$TAG $*" | tee -a "$LOG"; }
die() { echo "$TAG ERROR: $*" | tee -a "$LOG"; mount -o remount,ro / 2>/dev/null; exit 1; }
feed() { [ -w "$WDOG" ] && echo 1 > "$WDOG" 2>/dev/null; return 0; }

[ "$(id -u)" = "0" ] || die "must run as root"
[ -f /jci/sm/sm.conf ] || die "not a CMU (no /jci/sm/sm.conf)"
: > "$LOG" || die "cannot write $LOG"

# --- payload -----------------------------------------------------------------
for f in libpatch-blmjciaapa.so libpatch-aap_service.so libpatch.conf \
         aap_system_attributes.xml aap_system_attributes_UCP.xml; do
    [ -f "$PAYLOAD/$f" ] || die "missing payload file: vietnav-payload/$f
(rebuild the stick: python installer/build-kit.py — see patches/oem-aa-mod/README.md)"
done
# Optional: the HUD-merge shim (only useful with the nav SD card).
SVC=""; [ -f "$PAYLOAD/libpatch-svcjcinavi.so" ] && SVC=libpatch-svcjcinavi.so

FW=$(grep -m1 -o '74\.[0-9][0-9][0-9]' /jci/version.ini 2>/dev/null || echo "?")
log "firmware: ${FW:-unknown} (tested line: 74.00.324)"

# --- 1) binaries to /data_persist ----------------------------------------------
mount -o remount,rw / 2>/dev/null
feed
mkdir -p "$DEST" || die "cannot mkdir $DEST"
for f in libpatch-blmjciaapa.so libpatch-aap_service.so libpatch.conf $SVC; do
    cp "$PAYLOAD/$f" "$DEST/$f" || die "copy failed: $f"
    chmod 0644 "$DEST/$f"
done
sync
log "payload -> $DEST ($(ls "$DEST" | wc -l) files)"

# --- 2) sm.conf LD_PRELOAD for jciAAPA + aap_service ---------------------------
PRE_AAPA='            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-blmjciaapa.so"/>'
PRE_AAP='            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-aap_service.so"/>'
TOK=data_persist/oem-aa-mod/libpatch
for CONF in /jci/sm/sm.conf /jci/sm/sm_WCP.conf; do
    [ -f "$CONF" ] || continue
    grep -q 'name="jciAAPA"' "$CONF" || { log "$(basename "$CONF"): no jciAAPA block, skipped"; continue; }
    BAK="/data_persist/$(basename "$CONF").bak_vietnav"
    [ -f "$BAK" ] || { cp -a "$CONF" "$BAK"; log "backup -> $BAK"; }
    if grep -q "$TOK" "$CONF"; then
        log "$(basename "$CONF"): LD_PRELOAD already present, skipped"
    else
        feed
        # insert right after each service opening tag; aap_service is optional
        awk -v paapa="$PRE_AAPA" -v paap="$PRE_AAP" '
            /<service .*name="jciAAPA"/   { print; print paapa; next }
            /<service .*name="aap_service"/ { print; print paap; next }
            1
        ' "$CONF" > /tmp/vietnav.sm.new || die "awk failed on $CONF"
        old=$(wc -l < "$CONF"); new=$(wc -l < /tmp/vietnav.sm.new)
        ins=$(grep -c "$TOK" /tmp/vietnav.sm.new)
        want=$((old + ins - $(grep -c "$TOK" "$CONF")))
        if [ "$ins" -ge 1 ] && [ "$new" = "$want" ]; then
            cp /tmp/vietnav.sm.new "$CONF"
            log "$(basename "$CONF"): inserted $ins environ_var line(s) ($old->$new)"
        else
            rm -f /tmp/vietnav.sm.new
            die "$(basename "$CONF"): sanity check failed ($old->$new, tok=$ins), left untouched"
        fi
        rm -f /tmp/vietnav.sm.new
    fi
    # a shim fault must not reboot-loop the unit
    sed -i '/name="jciAAPA"/ s/reset_board="yes"/reset_board="no"/' "$CONF"
done

# --- 3) AAP system attribute XMLs ----------------------------------------------
for XML in aap_system_attributes.xml aap_system_attributes_UCP.xml; do
    [ -f "/etc/$XML" ] || { log "WARN: /etc/$XML absent, skipped"; continue; }
    [ -f "/etc/$XML.orig" ] || cp -a "/etc/$XML" "/etc/$XML.orig"
    cp "$PAYLOAD/$XML" "/etc/$XML" || die "copy failed: $XML"
done
sync
log "system attribute XMLs updated (backups: /etc/*.xml.orig)"

# --- 4) restart the two services ------------------------------------------------
feed
for SVC_NAME in jciAAPA aap_service; do
    if smctl -r -n "$SVC_NAME" >/dev/null 2>&1; then
        log "restarted $SVC_NAME"
    else
        log "WARN: smctl could not restart $SVC_NAME - a power cycle (ignition off) will do it"
    fi
done
sync
mount -o remount,ro / 2>/dev/null
log "DONE. Plug in an Android phone and start navigation; the HUD should show arrow + distance."
log "(Street name: see docs/vietmap-hud-gap.md for the known VIETMAP LIVE gap.)"
exit 0
