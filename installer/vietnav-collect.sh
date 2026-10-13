#!/bin/sh
# vietnav-collect.sh - read-only diagnostics pack for the car session.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
# Gathers everything needed to adjudicate the street-name question and the
# firmware-74.00.331 compatibility question (see docs/vietmap-hud-gap.md):
# firmware, sm configs, AAP attribute XMLs, process list, mod files and any
# nav16 logs, and which of the other kits on this car are in place (the
# wireless-CarPlay gate, the TPMS bds wrapper) - read only. Writes one
# tarball next to itself on the stick (the stick mounts read-only, so it is
# remounted rw first). Changes nothing on the unit. BusyBox ash.

set -u

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
STAGE=/tmp/vietnav-collect
OUT="$HERE/vietnav-collect-$(date +%Y%m%d-%H%M).tgz"

mount -o rw,remount "$HERE" 2>/dev/null || true
rm -rf "$STAGE"; mkdir -p "$STAGE" || { echo "[vietnav] cannot stage"; exit 1; }

grab() { # grab <src> <name>  - copy if present, note if not
    [ -e "$1" ] && cp -a "$1" "$STAGE/$2" 2>/dev/null \
        || echo "absent: $1" >> "$STAGE/MISSING.txt"
}

grab /jci/version.ini                     version.ini
grab /jci/version                         jci_version_dir.txt
grab /jci/sm/sm.conf                      sm.conf
grab /jci/sm/sm_WCP.conf                  sm_WCP.conf
grab /etc/aap_system_attributes.xml       aap_system_attributes.xml
grab /etc/aap_system_attributes_UCP.xml   aap_system_attributes_UCP.xml
grab /etc/devmgr_config_master.xml        devmgr_config_master.xml
[ -d /data_persist/oem-aa-mod ] && cp -a /data_persist/oem-aa-mod "$STAGE/" \
    || echo "absent: /data_persist/oem-aa-mod (mod not installed)" >> "$STAGE/MISSING.txt"

[ -d /data_persist/vietnav ] && cp -a /data_persist/vietnav "$STAGE/vietnav-state"

ps 2>/dev/null | grep -E "aap|AAPA|blmj|jcinavi|jciCARPLAY|sm -f" | grep -v grep > "$STAGE/ps-aap.txt"
# the other kits on this car, read only: which sm config this boot runs,
# the wireless-CarPlay gate, the TPMS bds wrapper and boot hook
{
    echo "sm: $(ps 2>/dev/null | grep 'sm -f' | grep -v grep | head -n 1)"
    if grep -q "wcp-gate.sh" /jci/scripts/get_board_type.sh 2>/dev/null; then
        echo "wireless-CarPlay gate: installed, trial count $(cat /data_persist/wcp-trial 2>/dev/null || echo none)"
    else
        echo "wireless-CarPlay gate: not installed"
    fi
    if grep -q "TPMS bds wrapper" /jci/bds/bds 2>/dev/null; then echo "TPMS bds wrapper: installed"; else echo "TPMS bds wrapper: no"; fi
    if grep -q "tpms-boot" /jci/scripts/stage_wifi.sh 2>/dev/null; then echo "TPMS boot hook: installed"; else echo "TPMS boot hook: no"; fi
} > "$STAGE/other-kits.txt"
mount | grep -E "/mnt/sd|data_persist" > "$STAGE/mounts.txt"
# anything the debug build already logged (nav16 frames, bridge logs)
for f in /tmp/*nav16* /tmp/carplay_bridge.log /tmp/vietnav-install.log /tmp/vietnav-rollback.log; do
    [ -e "$f" ] && cp -a "$f" "$STAGE/" 2>/dev/null
done

tar -czf "$OUT" -C /tmp "$(basename "$STAGE")" 2>/dev/null || { echo "[vietnav] tar failed"; exit 1; }
rm -rf "$STAGE"
echo "[vietnav] collected: $OUT ($(wc -c < "$OUT") bytes)"
exit 0
