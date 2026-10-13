#!/bin/sh
# vietnav-touch.sh - the touch installer: no keyboard, no typing.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
# Started as root from Mazda's own update dialog through the TouchTune
# update trigger (github.com/Miatafy/TouchTune, GPL-3.0) - the same trigger
# the other kits on this car use. install-patches.sh hands over to this.
#
# WHAT IT DOES
#   Menu (3 buttons, Vietnamese):
#     CAI DAT  -> which target? AA / CARPLAY / CA HAI (what the payload has)
#     GO BO    -> (when installed) removes the installed target(s)
#     THU THAP -> vietnav-collect.sh (read-only diagnostics pack)
#   Fails closed: no dialog binary, no /jci, or the trigger firing early in
#   boot -> does nothing. Never reboots the unit by itself.
#
# BusyBox ash. Read it before you run it.

set -u

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
DIALOG=/jci/tools/jci-dialog
AA_TOK=data_persist/oem-aa-mod/libpatch
CP_TOK=data_persist/cp-hud-mod/libpatch
WDOG="/sys/class/gpio/Watchdog Disable/value"

# --- fail-closed preconditions ---------------------------------------------------
[ -x "$DIALOG" ] || exit 0            # no dialog -> not a touch install
[ -f /jci/sm/sm.conf ] || exit 0      # boot race: /jci not mounted yet
feed() { [ -w "$WDOG" ] && echo 1 > "$WDOG" 2>/dev/null; return 0; }

ask3() { # ask3 <title> <text> <ok> <cancel> <b3> -> exit code
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --3-button-dialog --title="$1" --text="$2" \
        --ok-label="$3" --cancel-label="$4" --button3-label="$5" \
        > /dev/null 2>&1
}
say() {
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --OKDialog --title="VIETNAV HUD" --text="$1" > /dev/null 2>&1
}

aa_installed() {
    grep -q "$AA_TOK" /jci/sm/sm.conf 2>/dev/null \
        || grep -q "$AA_TOK" /jci/sm/sm_WCP.conf 2>/dev/null
}
cp_installed() {
    grep -q "$CP_TOK" /jci/sm/sm.conf 2>/dev/null \
        || grep -q "$CP_TOK" /jci/sm/sm_WCP.conf 2>/dev/null
}
have_aa() { [ -f "$HERE/vietnav-payload/libpatch-blmjciaapa.so" ]; }
have_cp() { [ -f "$HERE/vietnav-payload/libpatch-blmjcicarplay.so" ]; }

# --- the menu --------------------------------------------------------------------
feed

INST=""; aa_installed && INST="aa"; cp_installed && INST="${INST}${INST:+ }cp"

if [ -n "$INST" ]; then
    TITLE="DA CAI: ${INST}"
    OK="GO BO"
else
    TITLE="VIETNAV HUD - chua cai"
    OK="CAI DAT"
fi

ask3 "VIETNAV HUD" "$TITLE" "$OK" "THU THAP" "HUY"
choice=$?

if [ "$choice" = "1" ]; then          # THU THAP
    feed
    sh "$HERE/vietnav-collect.sh" > /tmp/vietnav-collect.out 2>&1
    say "THU THAP XONG\n\n$(tail -1 /tmp/vietnav-collect.out)"
    exit 0
fi
[ "$choice" = "0" ] || exit 0         # HUY / dialog killed

# --- CAI DAT or GO BO -------------------------------------------------------------
if [ -z "$INST" ]; then
    # pick a target
    if have_aa && have_cp; then
        ask3 "CAI NAO?" "AA = Android Auto\nCARPLAY = iPhone\nCA HAI = ca hai" "AA" "CARPLAY" "CA HAI"
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
        say "KHONG CO PAYLOAD\n\nvietnav-payload/ thieu file .so.\nXay lai dia: build-kit.py\n(Che do THU THAP van dung duoc.)"
        exit 0
    fi
    feed
    if sh "$HERE/vietnav-install.sh" "$T"; then
        say "DA CAI ($T)\n\nAA: cam Android + mo dan duong.\nCARPLAY: ket noi iPhone + mo dan duong.\nLog: /tmp/vietnav-install.log"
    else
        say "CAI DAT LOI\n\nXem /tmp/vietnav-install.log"
    fi
else
    # rollback: which target
    case "$INST" in
        "aa cp"|"cp aa") T=all ;;
        aa) T=aa ;;
        cp) T=cp ;;
    esac
    feed
    if sh "$HERE/vietnav-rollback.sh" "$T"; then
        say "DA GO BO ($T)\n\nKet qua: /tmp/vietnav-rollback.log"
    else
        say "GO BO LOI\n\nXem /tmp/vietnav-rollback.log"
    fi
fi
exit 0
