#!/bin/sh
# vietnav-install.sh [aa|cp|all] - install the HUD navigation mods.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
# Runs as root (from the TouchTune touch UI, or a terminal).
#
#   aa  = oem-aa-mod (Android Auto -> HUD, GAL 1.6):
#         .so + libpatch.conf -> /data_persist/oem-aa-mod/, LD_PRELOAD
#         into the jciAAPA + aap_service blocks of every sm config that has
#         them, /etc AAP attribute XML swap, service restarts.
#   cp  = CarPlay bridge (KidMixer mazda-carplay-hud, ilshyma build with the
#         km/h + Vietnamese-fold fixes):
#         .so -> /data_persist/cp-hud-mod/, LD_PRELOAD + LD_LIBRARY_PATH into
#         the jciCARPLAY block of the ONE config the unit actually boots
#         (get_board_type.sh -> sm_WCP.conf on WCP hardware, else sm.conf),
#         NaviSupported=TRUE in /etc/devmgr_config_master.xml (this is what
#         makes the iPhone send the iAP2 maneuver stream), service restart.
#
# Idempotent; keeps first-generation backups (*.bak_vietnav, *.orig). Fails
# closed: sanity-checks every edit and leaves the unit untouched on any
# surprise, including an LD_PRELOAD another mod already placed in the same
# service block. BusyBox ash.

set -u

TARGET=${1:-all}
HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
PAYLOAD="$HERE/vietnav-payload"
LOG=/tmp/vietnav-install.log
TAG="[vietnav]"
WDOG="/sys/class/gpio/Watchdog Disable/value"
AA_DIR=/data_persist/oem-aa-mod
CP_DIR=/data_persist/cp-hud-mod
MASTER=/etc/devmgr_config_master.xml

log() { echo "$TAG $*" | tee -a "$LOG"; }
die() { echo "$TAG ERROR: $*" | tee -a "$LOG"; mount -o remount,ro / 2>/dev/null; exit 1; }
feed() { [ -w "$WDOG" ] && echo 1 > "$WDOG" 2>/dev/null; return 0; }
want() { [ "$TARGET" = "all" ] || [ "$TARGET" = "$1" ]; }

[ "$(id -u)" = "0" ] || die "must run as root"
[ -f /jci/sm/sm.conf ] || die "not a CMU (no /jci/sm/sm.conf)"
: > "$LOG" || die "cannot write $LOG"

FW=$(grep -m1 -o '74\.[0-9][0-9][0-9]' /jci/version.ini 2>/dev/null || echo "?")
log "target=$TARGET firmware: ${FW:-unknown} (tested line: 74.00.324)"

# --- helper: insert environ_var lines into one <service> block -------------------
# insert_env <conf> <svc-regex> <line1> [line2]
# Idempotent, refuses when the block already carries a foreign LD_PRELOAD,
# sanity-checks the line count before committing, then disarms reset_board.
insert_env() {
    _conf=$1; _svc=$2; _l1=$3; _l2=${4:-}
    _bak="/data_persist/$(basename "$_conf").bak_vietnav"
    [ -f "$_bak" ] || { cp -a "$_conf" "$_bak"; log "backup -> $_bak"; }
    if sed -n "/$_svc/,/<\/service>/p" "$_conf" | grep -q 'env_name="LD_PRELOAD"'; then
        log "$(basename "$_conf"): $_svc already has an LD_PRELOAD - SKIP (another mod? install by hand)"
        return 0
    fi
    _tok=$(echo "$_l1" | sed 's/.*env_value="//; s/".*//')
    if grep -q "$_tok" "$_conf"; then
        log "$(basename "$_conf"): $_svc LD_PRELOAD already ours, skipped"
        return 0
    fi
    feed
    awk -v svc="$_svc" -v l1="$_l1" -v l2="$_l2" '
        $0 ~ svc { print; print l1; if (l2 != "") print l2; next }
        1
    ' "$_conf" > /tmp/vietnav.sm.new || die "awk failed on $_conf"
    _old=$(wc -l < "$_conf"); _new=$(wc -l < /tmp/vietnav.sm.new)
    _add=1; [ -n "$_l2" ] && _add=2
    if grep -q "$_tok" /tmp/vietnav.sm.new && [ "$_new" = "$((_old + _add))" ]; then
        cp /tmp/vietnav.sm.new "$_conf"
        log "$(basename "$_conf"): inserted into $_svc ($_old->$_new lines)"
    else
        rm -f /tmp/vietnav.sm.new
        die "$(basename "$_conf"): sanity check failed ($_old->$_new), left untouched"
    fi
    rm -f /tmp/vietnav.sm.new
    sed -i "/$_svc/ s/reset_board=\"yes\"/reset_board=\"no\"/" "$_conf"
}

restart_svc() {
    feed
    if smctl -r -n "$1" >/dev/null 2>&1; then
        log "restarted $1"
    else
        log "WARN: smctl could not restart $1 - a power cycle (ignition off) will do it"
    fi
}

# ============================ Android Auto ======================================
if want aa; then
    for f in libpatch-blmjciaapa.so libpatch-aap_service.so libpatch.conf \
             aap_system_attributes.xml aap_system_attributes_UCP.xml; do
        [ -f "$PAYLOAD/$f" ] || die "missing payload file: vietnav-payload/$f (rebuild the stick)"
    done
    log "--- Android Auto (oem-aa-mod) ---"
    mount -o remount,rw / 2>/dev/null
    mkdir -p "$AA_DIR" || die "cannot mkdir $AA_DIR"
    for f in libpatch-blmjciaapa.so libpatch-aap_service.so libpatch.conf; do
        cp "$PAYLOAD/$f" "$AA_DIR/$f" || die "copy failed: $f"
        chmod 0644 "$AA_DIR/$f"
    done
    if [ -f "$PAYLOAD/libpatch-svcjcinavi.so" ]; then
        cp "$PAYLOAD/libpatch-svcjcinavi.so" "$AA_DIR/" && chmod 0644 "$AA_DIR/libpatch-svcjcinavi.so"
    fi
    sync
    log "payload -> $AA_DIR"

    for CONF in /jci/sm/sm.conf /jci/sm/sm_WCP.conf; do
        [ -f "$CONF" ] || continue
        grep -q 'name="jciAAPA"' "$CONF" || { log "$(basename "$CONF"): no jciAAPA block, skipped"; continue; }
        insert_env "$CONF" '<service .*name="jciAAPA"' \
            '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-blmjciaapa.so"/>'
        insert_env "$CONF" '<service .*name="aap_service"' \
            '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-aap_service.so"/>'
    done

    for XML in aap_system_attributes.xml aap_system_attributes_UCP.xml; do
        [ -f "/etc/$XML" ] || { log "WARN: /etc/$XML absent, skipped"; continue; }
        [ -f "/etc/$XML.orig" ] || cp -a "/etc/$XML" "/etc/$XML.orig"
        cp "$PAYLOAD/$XML" "/etc/$XML" || die "copy failed: $XML"
    done
    sync
    log "AAP attribute XMLs updated (backups: /etc/*.xml.orig)"
    restart_svc jciAAPA
    restart_svc aap_service
fi

# ============================ CarPlay bridge =====================================
if want cp; then
    [ -f "$PAYLOAD/libpatch-blmjcicarplay.so" ] \
        || die "missing payload file: vietnav-payload/libpatch-blmjcicarplay.so (rebuild the stick)"
    log "--- CarPlay bridge (mazda-carplay-hud) ---"
    mount -o remount,rw / 2>/dev/null
    mkdir -p "$CP_DIR" || die "cannot mkdir $CP_DIR"
    cp "$PAYLOAD/libpatch-blmjcicarplay.so" "$CP_DIR/libpatch-blmjcicarplay.so" \
        || die "copy failed: libpatch-blmjcicarplay.so"
    chmod 0644 "$CP_DIR/libpatch-blmjcicarplay.so"
    sync
    log "payload -> $CP_DIR"

    # WCP hardware boots sm -f sm_WCP.conf; otherwise sm.conf (KidMixer logic).
    if [ -x /jci/scripts/get_board_type.sh ]; then
        /jci/scripts/get_board_type.sh >/dev/null 2>&1; BT=$?
    else
        BT=""
    fi
    if [ "$BT" = "2" ] && [ -f /jci/sm/sm_WCP.conf ]; then
        CONF=/jci/sm/sm_WCP.conf
        log "WCP hardware (get_board_type.sh=2) -> patching sm_WCP.conf"
    else
        CONF=/jci/sm/sm.conf
        log "wired/standard hardware -> patching sm.conf"
    fi
    grep -q 'name="jciCARPLAY"' "$CONF" || die "no jciCARPLAY block in $CONF"
    insert_env "$CONF" '<service .*name="jciCARPLAY"' \
        '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/cp-hud-mod/libpatch-blmjcicarplay.so"/>' \
        '            <environ_var env_name="LD_LIBRARY_PATH" env_value="/jci/lib:/usr/lib"/>'

    # NaviSupported=TRUE is what makes the iPhone stream maneuvers over iAP2.
    if [ -f "$MASTER" ]; then
        MBAK=/data_persist/devmgr_config_master.xml.bak_vietnav
        [ -f "$MBAK" ] || cp -a "$MASTER" "$MBAK"
        if grep -q '<name>NaviSupported</name><value>FALSE</value>' "$MASTER"; then
            sed -i 's#<name>NaviSupported</name><value>FALSE</value>#<name>NaviSupported</name><value>TRUE</value>#' "$MASTER"
            log "set NaviSupported=TRUE in $MASTER (backup: $MBAK)"
        else
            log "NaviSupported already TRUE (or absent) in $MASTER"
        fi
    else
        log "WARN: $MASTER absent - iPhone may not stream maneuvers"
    fi
    sync
    restart_svc jciCARPLAY
fi

sync
mount -o remount,ro / 2>/dev/null
log "DONE ($TARGET)."
log "AA:      Android phone + navigation -> arrow + distance on the HUD."
log "CarPlay: iPhone + navigation (Apple Maps / VIETMAP LIVE) -> same."
log "(Street name for VIETMAP LIVE on AA: see docs/vietmap-hud-gap.md.)"
exit 0
