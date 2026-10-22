#!/bin/sh
# Dedicated VIETNAV native trial stick, AGPL-3.0-or-later.
# TouchTune is only the bootstrap. No touch-while-driving patch is installed.
set -u
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || exit 1
DIALOG=/jci/tools/jci-dialog
TITLE='VIETNAV HUD - THU BLE'
[ -x "$DIALOG" ] && [ -f /jci/sm/sm.conf ] || exit 0
mount -o rw,remount "$HERE" 2>/dev/null || true
if : >> "$HERE/native-touch.log" 2>/dev/null; then
    exec >> "$HERE/native-touch.log" 2>&1
fi
trap 'sync' EXIT
ask3() {
    "$DIALOG" --3-button-dialog --title="$TITLE" --text="$1" \
        --ok-label="$2" --cancel-label="$3" --button3-label="$4"
}
ask2() {
    "$DIALOG" --question --title="$TITLE" --text="$1" --ok-label="$2" --cancel-label=HUY
}
say() { "$DIALOG" --info --title="$TITLE" --text="$1"; }
run() {
    sh "$HERE/native-control.sh" "$@" > /tmp/vietnav-native-control.out 2>&1
    RC=$?
    cat /tmp/vietnav-native-control.out
    [ "$RC" = 0 ] && return 0
    if grep -qE 'QUERY_REQUIRED|QUERY_STALE' /tmp/vietnav-native-control.out; then
        say 'CHUA CO KET QUA KIEM TRA BLE HOP LE\nChon KIEM TRA, tat/mo xe de thu.\nSau do khoi dong lai, cam USB lan nua.\nNeu van loi: chon KHAC > LUU LOG.'
    elif grep -q RESTART_BEFORE_REARM /tmp/vietnav-native-control.out; then
        say 'LAN THU VUA CHAY TRONG PHIEN NAY\nTat xe, mo cua, cho man hinh tat.\nDoi them 30 giay, mo xe, cam lai USB.'
    else
        say 'CHUA HOAN TAT\nChon KHAC > LUU LOG, mang USB ve.\nXem native-touch.log tren USB.\nNeu bao RESTORE_INCOMPLETE: giu ban sao.'
    fi
    return 1
}
STATE=$(sh "$HERE/native-control.sh" status)
printf '%s\n' "$STATE"
if printf '%s' "$STATE" | grep -q 'QUERY_PROOF present'; then
    NOTE='Da co log kiem tra; co the thu KET NOI.'
else NOTE='Can KIEM TRA truoc khi thu KET NOI.'; fi
ask3 "Thu nhan dan duong VietMap qua BLE.\n$NOTE\nHUD thu rieng; TPMS nghi trong lan thu.\nKHAC: luu log, huy lich thu, go bo.\n- by dangkhoa116 -" 'KIEM TRA' 'KET NOI' 'KHAC'
CHOICE=$?
case "$CHOICE" in
    0) MODE=query; NAME='KIEM TRA BLE' ;;
    1) MODE=advertise; NAME='KET NOI VIETMAP' ;;
    2)
        ask3 'Luu ket qua thu vao USB hoac go bo.\nGO BO: khoi phuc wrapper TPMS cu.\nHUY LICH: bo lan thu chua chay.\nKhong tu khoi dong lai xe.' 'LUU LOG' 'GO BO' 'HUY LICH'
        case "$?" in
            0) run collect && say 'DA LUU LOG TREN USB\nThu muc: native-hud-logs\nGui thu muc nay va native-touch.log.' ;;
            1)
                ask2 'Go ban thu HUD va tra wrapper TPMS?\nCan tat/mo xe sau khi go.\nLog van duoc giu de thu thap.' 'GO BO'
                [ "$?" = 0 ] || exit 0
                run remove --yes && say 'DA GO BAN THU HUD\nRut USB, tat xe, mo cua.\nCho man hinh tat, doi them 30 giay.\nMo xe lai de chay TPMS.'
                ;;
            2) run disarm --yes && say 'DA HUY LICH THU\nLan dang chay ket thuc khi khoi dong lai.\nLog van duoc giu de thu thap.' ;;
        esac
        exit 0 ;;
    *) exit 0 ;;
esac
ask2 "$NAME o lan khoi dong ke tiep?\nLan thu nay khong doc cam bien TPMS.\nLan khoi dong sau nua ve TPMS.\nHUY: khong thay doi." 'DAT LICH'
[ "$?" = 0 ] || exit 0
if run arm "$MODE" --yes; then
    if [ "$MODE" = query ]; then
        say 'DA DAT LICH KIEM TRA\nRut USB, tat xe, mo cua.\nCho man hinh tat, doi them 30 giay.\nMo xe, doi 2 phut. Khoi dong lai xe,\ncam USB: KHAC > LUU LOG / KET NOI.'
    else
        say 'DA DAT LICH KET NOI\nRut USB, tat/mo xe nhu buoc kiem tra.\nSau 60-90 giay, mo VietMap > HUD.\nTim VIETMAP-HUD, bat dau dan duong.\nSau khi thu: KHAC > LUU LOG.'
    fi
fi
