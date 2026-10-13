#!/bin/sh
# install-patches.sh - the shared touch launcher for this stick.
# Copyright (c) 2026 Dang Khoa (dangkhoa116). MIT License.
# SPDX-License-Identifier: MIT
# mzd-touch-launcher: 2
#
# TouchTune's update trigger (github.com/Miatafy/TouchTune, GPL-3.0, by
# Miatafy) runs a file of this name from the stick root, as root, when
# INSTALL is tapped on Mazda's update dialog. Several touch kits can share
# one stick; this file is the same in every kit and only chooses. Each kit
# keeps its own payload next to it:
#
#   tpms-touch.sh     TPMS add-on
#   wcp-touch.sh      wireless-CarPlay kit (its own install-patches.sh,
#                     renamed by the kit builders, otherwise untouched)
#   vietnav-touch.sh  VIETNAV HUD
#   other-touch.sh    any other kit's launcher, kept the same way
#
# One payload: straight to it. More: jci-dialog asks - and jci-dialog has
# three buttons at most. So with three kits the chooser shows all three
# and the cancel lives one screen deeper: every kit's own menu opens with
# a HUY (a foreign payload gets a BAT DAU / HUY confirm first), and after
# a kit finishes, LAM TIEP / XONG asks whether to pick another kit. Only
# a fourth kit needs a second screen (behind TIEP). The kit builders
# replace this file only with the same or a newer "mzd-touch-launcher"
# version and never overwrite a payload. Each payload checks for itself
# that the car is up.
#
# BusyBox ash.

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
DIALOG=/jci/tools/jci-dialog

N=0; K1=""; K2=""; K3=""; K4=""
for k in tpms wcp vietnav other; do
    [ -f "$HERE/$k-touch.sh" ] || continue
    N=$((N + 1))
    eval "K$N=$k"
done

[ "$N" = 0 ] && exit 0
[ "$N" = 1 ] && exec sh "$HERE/$K1-touch.sh"
# Several kits and no dialog to ask with: the car is not up yet (the
# trigger also fires early in boot). Run none of them.
[ -x "$DIALOG" ] || exit 0

label() {
    case "$1" in
        tpms)    echo "TPMS" ;;
        wcp)     echo "CARPLAY" ;;
        vietnav) echo "VIETNAV" ;;
        *)       echo "KHAC" ;;
    esac
}
desc() {
    case "$1" in
        tpms)    echo "TPMS = ap suat lop / tyre pressure" ;;
        wcp)     echo "CARPLAY = CarPlay khong day / wireless CarPlay" ;;
        vietnav) echo "VIETNAV = dan duong len HUD / navigation on the HUD" ;;
        *)       echo "KHAC = bo cai khac / another kit" ;;
    esac
}

# the legend lists only the kits that are actually on the stick ("\n" is
# jci-dialog's own line break, the way every dialog on this car uses it)
TEXT=""
i=1
while [ "$i" -le "$N" ]; do
    eval "k=\$K$i"
    TEXT="$TEXT`desc \"$k\"`\\n"
    i=$((i + 1))
done

ask3() { # ask3 <text> <ok> <cancel> <b3> -> exit code 0/1/other
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --3-button-dialog --title="USB: chon bo cai / choose a kit" \
        --text="$1" --ok-label="$2" --cancel-label="$3" --button3-label="$4" \
        > /dev/null 2>&1
}
ask2() { # ask2 <text> <ok> <cancel> -> exit code 0/1/other
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --question --title="USB: chon bo cai / choose a kit" \
        --text="$1" --ok-label="$2" --cancel-label="$3" \
        > /dev/null 2>&1
}

# run <kit>: our own payloads open their own menu (HUY included) and start
# right away; a foreign payload may start working the moment it is called,
# so it gets a confirm first. Waits for the kit to finish.
run() {
    case "$1" in
        tpms|vietnav) ;;
        *)
            ask2 "`label \"$1\"`: BAT DAU bay gio?\nStart the `label \"$1\"` kit now?" "BAT DAU" "HUY"
            [ "$?" = 0 ] || return 0
            ;;
    esac
    sh "$HERE/$1-touch.sh"
}

while :; do
    if [ "$N" = 2 ]; then
        ask3 "$TEXT\\nHUY = Cancel" "`label \"$K1\"`" "`label \"$K2\"`" "HUY"
        case "$?" in 0) run "$K1" ;; 1) run "$K2" ;; *) exit 0 ;; esac
    elif [ "$N" = 3 ]; then
        # all three kits on one screen; the cancel is inside each kit's menu
        ask3 "$TEXT" "`label \"$K1\"`" "`label \"$K2\"`" "`label \"$K3\"`"
        case "$?" in 0) run "$K1" ;; 1) run "$K2" ;; 2) run "$K3" ;; *) exit 0 ;; esac
    else
        ask3 "$TEXT\\nTIEP = more" "`label \"$K1\"`" "`label \"$K2\"`" "TIEP"
        case "$?" in
            0) run "$K1" ;;
            1) run "$K2" ;;
            2)
                if [ "$N" = 4 ]; then
                    ask3 "$TEXT\\nHUY = Cancel" "`label \"$K3\"`" "`label \"$K4\"`" "HUY"
                    case "$?" in 0) run "$K3" ;; 1) run "$K4" ;; *) exit 0 ;; esac
                fi
                ;;
            *) exit 0 ;;
        esac
    fi
    # a kit has run and returned: pick another one, or done?
    ask2 "LAM TIEP = chon bo cai khac / pick another kit\\nXONG = ket thuc / done" "LAM TIEP" "XONG"
    [ "$?" = 0 ] || exit 0
done
