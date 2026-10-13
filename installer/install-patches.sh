#!/bin/sh
# install-patches.sh - the shared touch launcher for this stick.
# Copyright (c) 2026 Dang Khoa (dangkhoa116). MIT License.
# SPDX-License-Identifier: MIT
# mzd-touch-launcher: 1
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
# One payload: straight to it. More: jci-dialog asks (3 buttons at most,
# so a 3rd/4th kit is on a second screen). The kit builders replace this
# file only with the same or a newer "mzd-touch-launcher" version and never
# overwrite a payload. Each payload checks for itself that the car is up.
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
ask() { # ask <text> <ok> <cancel> <b3> -> exit code 0/1/other
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --3-button-dialog --title="USB: chon bo cai / choose a kit" \
        --text="$1" --ok-label="$2" --cancel-label="$3" --button3-label="$4" \
        > /dev/null 2>&1
}
run() { exec sh "$HERE/$1-touch.sh"; }

TEXT="TPMS = ap suat lop / tyre pressure\nCARPLAY = CarPlay khong day / wireless CarPlay\nVIETNAV = dan duong len HUD / navigation on the HUD\nKHAC = bo cai khac / another kit"

while :; do
    if [ "$N" = 2 ]; then
        ask "$TEXT\nHUY = Cancel" "`label $K1`" "`label $K2`" "HUY"
        case "$?" in 0) run "$K1" ;; 1) run "$K2" ;; *) exit 0 ;; esac
    fi
    ask "$TEXT\nTIEP = more" "`label $K1`" "`label $K2`" "TIEP"
    case "$?" in
        0) run "$K1" ;;
        1) run "$K2" ;;
        2) ;;
        *) exit 0 ;;
    esac
    if [ "$N" = 4 ]; then
        ask "$TEXT\nHUY = Cancel" "`label $K3`" "`label $K4`" "HUY"
        case "$?" in 0) run "$K3" ;; 1) run "$K4" ;; *) exit 0 ;; esac
    fi
    ask "$TEXT\nVE LAI = back, HUY = Cancel" "`label $K3`" "VE LAI" "HUY"
    case "$?" in
        0) run "$K3" ;;
        1) continue ;;
        *) exit 0 ;;
    esac
done
