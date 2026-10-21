#!/bin/sh
# vietnav-touch.sh - the touch installer: no keyboard, no typing.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
# Started as root from Mazda's own update dialog through the TouchTune
# update trigger (github.com/Miatafy/TouchTune, GPL-3.0) - the same trigger
# the other kits on this car use. install-patches.sh (the launcher shared by
# all kits on the stick) hands over to this.
#
# WHAT IT DOES
#   Menu (3 buttons; screens in Vietnamese / English, with the status
#   and the dangkhoa116 credit):
#     CAI DAT  -> which target? AA / CARPLAY / CA HAI (what the payload has),
#                 then CAI DAT / HUY to confirm
#     GO BO    -> (when installed) GO BO / HUY to confirm, then removes the
#                 installed target(s)
#     THU THAP -> vietnav-collect.sh (read-only diagnostics pack)
#   It runs the same vietnav-install.sh --yes / vietnav-rollback.sh as the
#   terminal; they log to the stick (vietnav-install.log, -rollback.log),
#   and so does this (vietnav-touch.log).
#   Fails closed: no dialog binary, no /jci, or the trigger firing early in
#   boot -> does nothing. Never reboots the unit by itself.
#
# BusyBox ash. Read it before you run it.

set -u

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
DIALOG=/jci/tools/jci-dialog
AA_TOK=data_persist/oem-aa-mod/libpatch
CP_TOK=data_persist/cp-hud-mod/libpatch
# the same CarPlay bridge from another installer: CAI DAT replaces it
OLDCP_TOK=data_persist/oem-carplay/libpatch
# The version in a vietnav-install.sh (VIETNAV_VERSION="x.y.z"), empty if none.
ver() { sed -n 's/^VIETNAV_VERSION="\([0-9.]*\)".*/\1/p' "$1" 2>/dev/null | head -n 1; }
KV=$(ver "$HERE/vietnav-install.sh")
TITLE="VIETNAV HUD${KV:+ $KV}"

# Log to the stick when it takes a write (it mounts read-only).
mount -o rw,remount "$HERE" 2>/dev/null || true
if : >> "$HERE/vietnav-touch.log" 2>/dev/null; then
    exec >> "$HERE/vietnav-touch.log" 2>&1
fi
log() { printf '%s\n' "[vietnav-touch] $1"; }
# The stick is FAT and gets pulled out without warning: sync on every way out.
trap 'sync' EXIT

log "=== VIETNAV HUD touch installer ${KV:-(no version)} ==="

# --- fail-closed preconditions ---------------------------------------------------
[ -x "$DIALOG" ] || { log "no jci-dialog - not a touch install, nothing done"; exit 0; }
[ -f /jci/sm/sm.conf ] || { log "the car is not up (/jci not there yet) - nothing done"; exit 0; }

ask3() { # ask3 <title> <text> <ok> <cancel> <b3> -> exit code
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --3-button-dialog --title="$1" --text="$2" \
        --ok-label="$3" --cancel-label="$4" --button3-label="$5" \
        > /dev/null 2>&1
}
ask2() {         # ask2 <title> <text> <ok> <cancel> -> exit code
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --question --title="$1" --text="$2" \
        --ok-label="$3" --cancel-label="$4" > /dev/null 2>&1
}
say() {          # final message, one OK button, waits for the tap
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --info --title="$TITLE" --text="$1" > /dev/null 2>&1
}
popup() {        # "working..." box while a script runs
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --info --title="$TITLE" --text="$1" --no-cancel > /dev/null 2>&1 &
}

aa_installed() {
    grep -q "$AA_TOK" /jci/sm/sm.conf 2>/dev/null \
        || grep -q "$AA_TOK" /jci/sm/sm_WCP.conf 2>/dev/null
}
cp_installed() {
    grep -q "$CP_TOK" /jci/sm/sm.conf 2>/dev/null \
        || grep -q "$CP_TOK" /jci/sm/sm_WCP.conf 2>/dev/null
}
oldcp_installed() {
    grep -q "$OLDCP_TOK" /jci/sm/sm.conf 2>/dev/null \
        || grep -q "$OLDCP_TOK" /jci/sm/sm_WCP.conf 2>/dev/null
}
have_aa() { [ -f "$HERE/vietnav-payload/libpatch-blmjciaapa.so" ] && [ -f "$HERE/vietnav-payload/aap_system_attributes.xml" ]; }
have_cp() { [ -f "$HERE/vietnav-payload/libpatch-blmjcicarplay.so" ]; }

# --- the menu --------------------------------------------------------------------
# Every screen: Vietnamese / English, at most 5 lines of ~50 characters
# (jci-dialog shows no more), the credit on the last line where it fits.
CREDIT="- by dangkhoa116 -"
tname() {        # aa | cp | all -> what the screen says
    case "$1" in
        aa)  echo "AA" ;;
        cp)  echo "CARPLAY" ;;
        *)   echo "AA + CARPLAY" ;;
    esac
}

INST=""; aa_installed && INST="aa"; cp_installed && INST="${INST}${INST:+ }cp"
# the installed version: written by vietnav-install.sh since 0.9.0
IV=$(cat /data_persist/vietnav/version 2>/dev/null)
log "installed: ${INST:-none}${IV:+ ($IV)}"
# which running services have a shim loaded (after the power cycle: all of
# jciAAPA, aap_service, jciCARPLAY that were installed) - log only
for _m in /proc/[0-9]*/maps; do
    grep -q 'libpatch-' "$_m" 2>/dev/null || continue
    _p=${_m%/maps}
    log "shim running in pid ${_p#/proc/}: $(tr '\000' ' ' < "$_p/cmdline" 2>/dev/null | cut -c1-90)"
done

case "$INST" in
    "aa cp") ST="DA CAI AA + CARPLAY / installed${IV:+ $IV}" ;;
    aa)      ST="DA CAI AA / installed${IV:+ $IV}" ;;
    cp)      ST="DA CAI CARPLAY / installed${IV:+ $IV}" ;;
    *)       ST="CHUA CAI / not installed" ;;
esac
OLDCP=0
if [ -z "$INST" ] && oldcp_installed; then
    OLDCP=1
    ST="CHUA CAI, CO CARPLAY HUD CU / old CP HUD"
    log "old CarPlay bridge (/data_persist/oem-carplay) in the sm configs"
fi
if [ -n "$INST" ]; then
    OK="GO BO"; DO="GO BO = remove"
else
    OK="CAI DAT"; DO="CAI DAT = install"
fi

ask3 "$TITLE" "Trang thai / Status:\n$ST\n$DO   THU THAP = collect logs\nHUY = cancel\n$CREDIT" \
    "$OK" "THU THAP" "HUY"
choice=$?
log "choice: $choice"

if [ "$choice" = "1" ]; then          # THU THAP
    popup "Dang thu thap... Dung rut USB.\nCollecting logs... do not remove the USB."
    if sh "$HERE/vietnav-collect.sh" > /tmp/vietnav-collect.out 2>&1; then
        cat /tmp/vietnav-collect.out
        # just the file name: a dialog line holds ~50 characters
        F=$(sed -n 's#.*collected: .*/\([^ /]*\) .*#\1#p' /tmp/vietnav-collect.out | tail -n 1)
        say "THU THAP XONG / LOGS COLLECTED\n\nDa luu tren USB / saved on the USB:\n${F:-vietnav-collect-*.tgz}\n$CREDIT"
    else
        cat /tmp/vietnav-collect.out
        say "THU THAP LOI / COLLECT FAILED\n\nMang USB ve, xem / bring the USB home, see:\nvietnav-touch.log"
    fi
    exit 0
fi
[ "$choice" = "0" ] || exit 0         # HUY / dialog killed

# --- CAI DAT or GO BO -------------------------------------------------------------
if [ -z "$INST" ]; then
    # pick a target
    if have_aa && have_cp; then
        ask3 "CAI NAO? / WHICH ONE?" "AA = Android Auto\nCARPLAY = iPhone (CarPlay)\nCA HAI = ca hai / both\n\n$CREDIT" \
            "AA" "CARPLAY" "CA HAI"
        t=$?
        case "$t" in
            0) T=aa ;;
            1) T=cp ;;
            2) T=all ;;
            *) exit 0 ;;
        esac
    elif have_aa; then T=aa
    elif have_cp; then T=cp
    else
        say "KHONG CO PAYLOAD / NO PAYLOAD\n\nThieu file .so / missing .so files\nXay lai USB / rebuild the stick: build-kit.py\nTHU THAP van dung duoc / logs still work"
        exit 0
    fi
    # nothing is changed before this second tap
    NOTE=""
    [ "$OLDCP" = 1 ] && [ "$T" != aa ] && NOTE="Thay CARPLAY HUD cu / replaces the old one"
    ask2 "$TITLE" "CAI DAT `tname $T`?\nInstall `tname $T`?\n$NOTE\nHUY = cancel" "CAI DAT" "HUY"
    [ "$?" = 0 ] || { log "install not confirmed"; exit 0; }
    log "install: $T"
    popup "Dang cai dat `tname $T`... Dung rut USB.\nInstalling `tname $T`... do not remove the USB."
    sh "$HERE/vietnav-install.sh" "$T" --yes
    rc=$?
    if [ "$rc" = 0 ]; then
        say "DA CAI / INSTALLED: `tname $T`\nTat may, doi 10 phut, roi mo dan duong.\nPower-cycle the car, then start navigation.\nLog: vietnav-install.log\n$CREDIT"
    elif [ "$rc" = 3 ]; then
        say "KHONG HO TRO / NOT SUPPORTED\nPhan mem xe nay chua duoc kiem tra.\nThis unit's software was not tested.\nKhong thay doi gi / nothing changed.\nLog: vietnav-install.log"
    elif [ "$rc" = 4 ]; then
        say "XE DA CO MOD KHAC / ANOTHER MOD IS IN\nMot mod khac dang dung cho nay.\nAnother mod uses the same service.\nKhong thay doi gi / nothing changed.\nBam THU THAP, mang USB ve / collect logs"
    else
        say "CAI DAT LOI / INSTALL FAILED\n\nMang USB ve, xem / bring the USB home, see:\nvietnav-install.log"
    fi
else
    # rollback: which target
    case "$INST" in
        "aa cp"|"cp aa") T=all ;;
        aa) T=aa ;;
        cp) T=cp ;;
    esac
    ask2 "$TITLE" "GO BO `tname $T`?\nRemove `tname $T`?\n\nHUY = cancel" "GO BO" "HUY"
    [ "$?" = 0 ] || { log "rollback not confirmed"; exit 0; }
    log "rollback: $T"
    popup "Dang go `tname $T`... Dung rut USB.\nRemoving `tname $T`... do not remove the USB."
    if sh "$HERE/vietnav-rollback.sh" "$T"; then
        say "DA GO BO / REMOVED: `tname $T`\n\nLog: vietnav-rollback.log\n\n$CREDIT"
    else
        say "GO BO LOI / REMOVE FAILED\n\nMang USB ve, xem / bring the USB home, see:\nvietnav-rollback.log"
    fi
fi
exit 0
