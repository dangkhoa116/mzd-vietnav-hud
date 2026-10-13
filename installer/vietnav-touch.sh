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
#     CAI DAT  -> vietnav-install.sh   (needs vietnav-payload/ on the stick)
#     GO BO    -> vietnav-rollback.sh  (offered when already installed)
#     THU THAP -> vietnav-collect.sh   (read-only diagnostics pack)
#   Fails closed: no dialog binary, no /jci, or the trigger firing early in
#   boot -> does nothing. Never reboots the unit by itself.
#
# BusyBox ash. Read it before you run it.

set -u

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
DIALOG=/jci/tools/jci-dialog
TOK=data_persist/oem-aa-mod/libpatch
WDOG="/sys/class/gpio/Watchdog Disable/value"
TAG="[vietnav]"

# --- fail-closed preconditions ---------------------------------------------------
[ -x "$DIALOG" ] || exit 0            # no dialog -> not a touch install
[ -f /jci/sm/sm.conf ] || exit 0      # boot race: /jci not mounted yet
feed() { [ -w "$WDOG" ] && echo 1 > "$WDOG" 2>/dev/null; return 0; }

say() { # say <text> [ok-label]
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --OKDialog --title="VIETNAV HUD" --text="$1" \
        ${2:+--ok-label="$2"} > /dev/null 2>&1
}

installed() {
    grep -q "$TOK" /jci/sm/sm.conf 2>/dev/null \
        || grep -q "$TOK" /jci/sm/sm_WCP.conf 2>/dev/null
}
have_payload() { [ -f "$HERE/vietnav-payload/libpatch-blmjciaapa.so" ]; }

# --- the menu --------------------------------------------------------------------
feed
if installed; then
    TITLE="DA CAI\n\nGo bo mod AA-HUD?"
    OK="GO BO"; CANCEL="THU THAP"
else
    TITLE="VIETNAV HUD\n\nCai dat dan rang AA len HUD?"
    OK="CAI DAT"; CANCEL="THU THAP"
fi
killall -q jci-dialog 2>/dev/null || true
"$DIALOG" --3-button-dialog --title="VIETNAV HUD" \
    --text="$TITLE" \
    --ok-label="$OK" --cancel-label="$CANCEL" --button3-label="HUY" \
    > /dev/null 2>&1
choice=$?
case "$choice" in
    0)
        if installed; then
            feed
            if sh "$HERE/vietnav-rollback.sh"; then
                say "DA GO BO\n\nKet qua: /tmp/vietnav-rollback.log" "OK"
            else
                say "GO BO LOI\n\nXem /tmp/vietnav-rollback.log" "OK"
            fi
        elif have_payload; then
            feed
            if sh "$HERE/vietnav-install.sh"; then
                say "DA CAI\n\nCay dien thoai Android\nva mo dan duong de kiem tra HUD.\nLog: /tmp/vietnav-install.log" "OK"
            else
                say "CAI DAT LOI\n\nXem /tmp/vietnav-install.log" "OK"
            fi
        else
            say "KHONG CO PAYLOAD\n\nvietnav-payload/ thieu .so.\nXay lai dia: build-kit.py\n(Che do THU THAP van dung duoc.)" "OK"
        fi
        ;;
    1)
        feed
        sh "$HERE/vietnav-collect.sh" > /tmp/vietnav-collect.out 2>&1
        OUT=$(tail -1 /tmp/vietnav-collect.out)
        say "THU THAP XONG\n\n$OUT" "OK"
        ;;
    *)  # HUY or the dialog was killed
        exit 0
        ;;
esac
exit 0
