#!/bin/sh
# install-patches.sh - the touch launcher for this stick.
# Copyright (c) 2026 dangkhoa116. AGPL-3.0 (see repo LICENSE).
#
# TouchTune's update trigger (github.com/Miatafy/TouchTune, GPL-3.0) runs a
# file of this name from the stick root, as root, when INSTALL is tapped on
# Mazda's update dialog. One stick can carry two touch kits: if another kit's
# launcher was already here, the kit builder kept it as other-touch.sh, and
# this chooser offers both.
#
# BusyBox ash.

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
DIALOG=/jci/tools/jci-dialog

if [ -f "$HERE/other-touch.sh" ] && [ -x "$DIALOG" ]; then
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --3-button-dialog --title="VIETNAV HUD" \
        --text="Chon / Choose:\n\nVIETNAV = dan rang Viet len HUD\nKHAC = bo cai dat khac tren dia\nHUY = Cancel" \
        --ok-label="VIETNAV" --cancel-label="KHAC" --button3-label="HUY" \
        > /dev/null 2>&1
    case "$?" in
        0) exec sh "$HERE/vietnav-touch.sh" ;;
        1) exec sh "$HERE/other-touch.sh" ;;
        *) exit 0 ;;
    esac
fi
exec sh "$HERE/vietnav-touch.sh"
