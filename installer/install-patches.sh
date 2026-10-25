#!/bin/sh
# install-patches.sh - the shared touch launcher for this stick.
# Copyright (c) 2026 Dang Khoa (dangkhoa116). MIT License.
# SPDX-License-Identifier: MIT
# mzd-touch-launcher: 11
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
#   utils-touch.sh    MZD Utils (v10)
#   other-touch.sh    SpeedMap menu (legacy payload filename)
#   cmu-logs.sh       shared read-only diagnostic collector
#
# First screen: CAI DAT / Log / HUY. Log collects all available diagnostics
# to one USB folder, without running a kit. HUY does not collect diagnostics.
# After CAI DAT, one payload runs directly. More: jci-dialog asks - it has
# three buttons at most. When the stick carries at least two of the three
# standard kits, the chooser always shows all three buttons in the same
# places, over a line per kit saying whether it is installed on the car
# (read only); a kit whose payload is not on the stick is not hidden - tapping
# its button says so on screen and comes back to the chooser. The cancel
# lives one screen deeper: every kit's own menu opens with a HUY (a
# foreign payload gets a BAT DAU / HUY confirm first). After TPMS or
# VIETNAV finishes (and its last message is tapped away), LAM TIEP / XONG
# asks whether to pick another kit - unless the payload exited 75, which
# means "the unit is restarting now" (TPMS does after an install or
# removal): then the session ends, so no kit can start under a restart. A
# foreign payload (the CarPlay kit, which restarts the unit) ends it too. Sticks with an extra
# kit (Utils, "other") get the plain chooser built from what is actually
# there: two or three kits on one screen, four or five on two (TIEP).
# Utils is one of ours, like TPMS. The kit builders replace
# this file only with the same or a newer "mzd-touch-launcher" version and
# never overwrite a payload. Each payload checks for itself that the car
# is up.
#
# BusyBox ash.

HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || HERE=$(dirname "$0")
DIALOG=/jci/tools/jci-dialog

N=0; K1=""; K2=""; K3=""; K4=""; K5=""
for k in tpms wcp vietnav utils other; do
    [ -f "$HERE/$k-touch.sh" ] || continue
    N=$((N + 1))
    eval "K$N=$k"
done

# No dialog to ask with: the car is not up yet (the
# trigger also fires early in boot). Run none of them.
[ -x "$DIALOG" ] || exit 0

have() { [ -f "$HERE/$1-touch.sh" ]; }

label() {
    case "$1" in
        tpms)    echo "TPMS" ;;
        wcp)     echo "CARPLAY" ;;
        vietnav) echo "VIETNAV" ;;
        utils)   echo "UTILS" ;;
        *)       echo "SpeedMap" ;;
    esac
}

# state <kit>: what is on the car now, read only, by the same marks each
# kit checks for itself
state() {
    case "$1" in
        tpms)
            if grep -q "TPMS bds wrapper, production" /jci/bds/bds 2>/dev/null; then
                if [ -f /data_persist/tpms/bds-off ]; then echo "DA CAI, DANG TAT / off"
                else echo "DA CAI / installed"; fi
            elif grep -q "tpms-v3 trial wrapper" /jci/bds/bds 2>/dev/null; then
                echo "BAN THU / trial armed"
            else
                echo "CHUA CAI / not installed"
            fi ;;
        wcp)
            if grep -q "wcp-gate.sh" /jci/scripts/get_board_type.sh 2>/dev/null; then
                case "`cat /data_persist/wcp-trial 2>/dev/null`" in
                    999999) echo "DA CAI / installed" ;;
                    "")     echo "TAT / off" ;;
                    *)      echo "CHAY THU / trial" ;;
                esac
            else
                echo "CHUA CAI / not installed"
            fi ;;
        vietnav)
            s=""
            grep -q "data_persist/oem-aa-mod/libpatch" /jci/sm/sm.conf /jci/sm/sm_WCP.conf 2>/dev/null && s="AA"
            grep -q "data_persist/cp-hud-mod/libpatch" /jci/sm/sm.conf /jci/sm/sm_WCP.conf 2>/dev/null \
                && s="${s}${s:+ + }CARPLAY"
            if [ -n "$s" ]; then echo "DA CAI $s / installed"; else echo "CHUA CAI / not installed"; fi ;;
        utils)
            if grep -q "^# mzd-utils begin$" /jci/scripts/stage_wifi.sh 2>/dev/null; then
                echo "DA CAI / installed"
            elif [ -d /data_persist/mzd-utils ]; then
                echo "DA GO / removed"
            else
                echo "CHUA CAI / not installed"
            fi ;;
    esac
}
desc() {
    case "$1" in
        tpms)    echo "TPMS (ap suat lop): `state tpms`" ;;
        wcp)     echo "CARPLAY (khong day): `state wcp`" ;;
        vietnav) echo "VIETNAV (HUD): `state vietnav`" ;;
        utils)   echo "UTILS (tat FM): `state utils`" ;;
        *)       echo "SpeedMap (canh bao giao thong / traffic alerts)" ;;
    esac
}

# how many of the three standard kits are on the stick
NS=0
for k in tpms wcp vietnav; do
    have "$k" && NS=$((NS + 1))
done
# all the payloads present are standard kits -> fixed three-button face
FIXED=0
if [ "$NS" -ge 2 ] && [ "$N" = "$NS" ]; then
    FIXED=1
fi

# legend: each standard kit with its state on the car; a kit that is not
# on the stick says so instead. Built again for every round of the
# chooser, so after LAM TIEP it shows what the last kit changed.
legend() {
    TEXT=""
    for k in tpms wcp vietnav; do
        if have "$k"; then
            TEXT="$TEXT`desc \"$k\"`\\n"
        elif [ "$FIXED" = 1 ]; then
            TEXT="$TEXT`label \"$k\"` - KHONG CO tren USB / not on this stick\\n"
        fi
    done
    i=1
    while [ "$i" -le "$N" ]; do
        eval "k=\$K$i"
        [ "$k" = utils ] && TEXT="$TEXT`desc utils`\\n"
        [ "$k" = other ] && TEXT="${TEXT}SpeedMap (canh bao giao thong / traffic alerts)\\n"
        i=$((i + 1))
    done
}

# jci-dialog is the car's own (/jci/tools): a 680x354 box, buttons left to
# right ok=0, cancel=1, button3=2. --text is split at each literal \n into
# at most 5 lines of at most 63 characters, never wrapped, centred in 24 px
# Sans: keep a line under ~50 characters or it runs off the box. An option
# it does not know makes it exit 255 at once, showing nothing.
ask3() { # ask3 <text> <ok> <cancel> <b3> [title] -> exit code 0/1/other
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --3-button-dialog --title="${5:-USB: chon bo cai / choose a kit}" \
        --text="$1" --ok-label="$2" --cancel-label="$3" --button3-label="$4" \
        > /dev/null 2>&1
}
ask2() { # ask2 <text> <ok> <cancel> -> exit code 0/1/other
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --question --title="USB: chon bo cai / choose a kit" \
        --text="$1" --ok-label="$2" --cancel-label="$3" \
        > /dev/null 2>&1
}
say() { # a note with one OK button; waits for the tap
    killall -q jci-dialog 2>/dev/null || true
    "$DIALOG" --info --title="USB: chon bo cai / choose a kit" \
        --text="$1" > /dev/null 2>&1
}

# Dedicated collection entry. Never enter a kit or change the watchdog on
# this route. The progress dialog is replaced only after collection returns.
if [ "$N" = 1 ]; then
    FIRST="CAI DAT = mo `label \"$K1\"` / open `label \"$K1\"`."
    FTITLE="USB: `label \"$K1\"`"
else
    FIRST="CAI DAT = chon bo cai / choose a kit."
    FTITLE=""
fi
ask3 "$FIRST\\nLog = lay log / collect logs.\\nCMU + TPMS + SpeedMap.\\nHUY = thoat / cancel." "CAI DAT" "Log" "HUY" "$FTITLE"
case "$?" in
    0) ;;
    1)
        if [ ! -f "$HERE/cmu-logs.sh" ]; then
            say "USB thieu tep / Missing file:\\ncmu-logs.sh\\nChep lai bo Log / Copy the Log kit again."
            exit 1
        fi
        # The car mounts the stick read-only; the menu log below is written
        # before cmu-logs.sh runs, so make it writable here.
        mount -o rw,remount "$HERE" 2>/dev/null || true
        killall -q jci-dialog 2>/dev/null || true
        "$DIALOG" --info --title="USB: Log" \
            --text="Dang lay log... / Collecting logs...\\nCMU + TPMS + SpeedMap.\\nDung rut USB / Do not remove USB.\\nDoi bao xong / Wait for completion." --no-cancel > /dev/null 2>&1 &
        if sh "$HERE/cmu-logs.sh" "$HERE" >> "$HERE/cmu-logs-menu.log" 2>&1; then
            sync
            say "Da luu log / Logs saved.\\nCMU + TPMS + SpeedMap.\\nThu muc / Folder: cmu-logs-*\\nBam OK, rut USB / Tap OK, remove USB.\\nMang ve may / Bring USB to your PC."
            exit 0
        fi
        sync
        say "Lay log chua xong / Collection incomplete.\\nMang USB ve may / Bring USB to your PC.\\nXem / See: cmu-logs-menu.log."
        exit 1 ;;
    *) exit 0 ;;
esac
[ "$N" = 0 ] && { say "Khong co bo cai / No kits on this USB."; exit 0; }
[ "$N" = 1 ] && exec sh "$HERE/$K1-touch.sh"

# settle: a payload may end on an --info box left running in the
# background (TPMS does: "ignition off, wait for a dark screen..."), and
# every question here starts with killall jci-dialog. So wait until that
# box is tapped away before asking anything. After ~10 minutes give up and
# end, leaving the message on screen.
settle() {
    w=0
    while ps 2>/dev/null | grep -q '[j]ci-dialog'; do
        [ "$w" -lt 600 ] || exit 0
        w=$((w + 1))
        sleep 1
    done
}

# run <kit>: our own payloads open their own menu (HUY included), never
# restart the unit, and the chooser may come back after them. A foreign
# payload may start working the moment it is called and may restart the
# unit (the CarPlay kit does, after a good install or rollback), so it gets
# a confirm first and then the session is its own: exec, no way back.
# One of ours that exits 75 has asked for a restart: end here, at once.
# Returns 0 when a kit ran, 1 when nothing ran.
run() {
    case "$1" in
        tpms|vietnav|utils) ;;
        *)
            ask2 "`label \"$1\"`: BAT DAU bay gio?\nStart the `label \"$1\"` kit now?" "BAT DAU" "HUY"
            [ "$?" = 0 ] || return 1
            exec sh "$HERE/$1-touch.sh"
            ;;
    esac
    sh "$HERE/$1-touch.sh"
    [ "$?" = 75 ] && exit 0
    settle
    return 0
}

# pick <kit>: a standard kit that is not on the stick is reported on
# screen, not hidden. Returns 0 when a kit ran, 1 when nothing ran.
pick() {
    if ! have "$1"; then
        say "`label \"$1\"`: KHONG CO tren USB.\nThe kit is not on this stick."
        return 1
    fi
    run "$1"
}

ROUND=0
while :; do
    # A person taps the chooser a few times at most. A dialog that answers
    # by itself (GUI not ready, a broken binary) must not spin this loop or
    # run kits over and over.
    ROUND=$((ROUND + 1))
    [ "$ROUND" -le 6 ] || exit 0
    legend
    if [ "$FIXED" = 1 ]; then
        # the standard face: same three buttons, whether or not all three
        # kits are on the stick; cancel is inside each kit's own menu
        ask3 "$TEXT" "TPMS" "CARPLAY" "VIETNAV"
        case "$?" in
            0) pick tpms ;;
            1) pick wcp ;;
            2) pick vietnav ;;
            *) exit 0 ;;
        esac
    elif [ "$N" = 2 ]; then
        ask3 "${TEXT}HUY = Cancel" "`label \"$K1\"`" "`label \"$K2\"`" "HUY"
        case "$?" in 0) run "$K1" ;; 1) run "$K2" ;; *) exit 0 ;; esac
    elif [ "$N" = 3 ]; then
        # three real payloads (one of them not a standard kit): one screen
        ask3 "$TEXT" "`label \"$K1\"`" "`label \"$K2\"`" "`label \"$K3\"`"
        case "$?" in 0) run "$K1" ;; 1) run "$K2" ;; 2) run "$K3" ;; *) exit 0 ;; esac
    else
        # five kits fill the five lines jci-dialog shows: no hint line then
        if [ "$N" = 4 ]; then MORE="${TEXT}TIEP = more"; else MORE="$TEXT"; fi
        ask3 "$MORE" "`label \"$K1\"`" "`label \"$K2\"`" "TIEP"
        case "$?" in
            0) run "$K1" ;;
            1) run "$K2" ;;
            2)
                if [ "$N" = 4 ]; then
                    ask3 "${TEXT}HUY = Cancel" "`label \"$K3\"`" "`label \"$K4\"`" "HUY"
                    case "$?" in 0) run "$K3" ;; 1) run "$K4" ;; *) exit 0 ;; esac
                elif [ "$N" = 5 ]; then
                    # cancel lives in each kit's own menu, as on the standard face
                    ask3 "$TEXT" "`label \"$K3\"`" "`label \"$K4\"`" "`label \"$K5\"`"
                    case "$?" in 0) run "$K3" ;; 1) run "$K4" ;; 2) run "$K5" ;; *) exit 0 ;; esac
                fi
                ;;
            *) exit 0 ;;
        esac
    fi || continue          # nothing ran (missing kit, declined confirm)
    # a kit has run and returned: pick another one, or done?
    ask2 "LAM TIEP = chon bo cai khac / pick another kit\\nXONG = ket thuc / done" "LAM TIEP" "XONG"
    [ "$?" = 0 ] || exit 0
done
