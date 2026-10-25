#!/bin/sh
# cmu-logs.sh - read-only diagnostics for all kits on the shared stick.
# Copyright (c) 2026 Dang Khoa (dangkhoa116). MIT License.
# SPDX-License-Identifier: MIT
# Usage: sh cmu-logs.sh /tmp/mnt/sda1
# Writes only to USB; does not start services, query sensors, change log
# settings, clear caches or run a second CPU gauge. Missing files are normal.
# Text tails are bounded; native archives are streamed, never extracted to disk.

set -u
USB=${1:-}
[ -n "$USB" ] && [ -d "$USB" ] || { echo "USB folder missing" >&2; exit 1; }
mount -o rw,remount "$USB" 2>/dev/null || true
STAMP=`date +%Y%m%d-%H%M%S 2>/dev/null` || STAMP=unknown-time
OUT="$USB/cmu-logs-$STAMP"
N=0
while [ -e "$OUT" ]; do N=$((N + 1)); OUT="$USB/cmu-logs-$STAMP-$N"; done
mkdir "$OUT" || exit 1
trap 'sync' EXIT
FAILED=0
MAN="$OUT/manifest.txt"
printf '%s\n' 'CMU diagnostics v1' 'Text tails: 512 KiB each; system archives: 4 MiB decoded each, up to 10.' \
    'Absent files are recorded. Older reset reports can be reused across boots.' \
    'No UART payloads, raw crash dumps, network settings or map databases collected.' > "$MAN" || exit 1

# Drop sensitive lines before redacting identifiers. Existing producer logs
# are not trusted to have removed contacts, network credentials or positions.
# The range is written with literal ends: the car's BusyBox 1.19.2 tr does
# not expand a range between octal escapes and kept only " -~" of it.
redact() {
    LC_ALL=C tr -cd '\11\12\15 -~' |
    sed -e 's/"lat":[ ]*[-0-9.eE]*/"lat":"[redacted]"/g' \
        -e 's/"lon":[ ]*[-0-9.eE]*/"lon":"[redacted]"/g' \
        -e 's/"lng":[ ]*[-0-9.eE]*/"lng":"[redacted]"/g' |
    grep -vi -e ssid -e 'wpa' -e password -e passwd -e 'link.key' -e linkkey \
        -e 'pairing.key' -e 'phone' -e contact -e 'bluetooth.*key' -e 'btsnoop' \
        -e 'dhcp' -e 'serialnumber' -e 'serial number' -e 'nmea' \
        -e 'latitude' -e 'longitude' \
        -e 'ssid=' -e ' BD_ADDR' -e ' BDS\[' -e ' BCA\[' -e 'BTHF' -e 'BTMUSIC' |
    sed -e 's/[0-9A-Fa-f][0-9A-Fa-f]\(:[0-9A-Fa-f][0-9A-Fa-f]\)\{5\}/[MAC]/g' \
        -e 's/[0-9A-Fa-f]\{32\}/[HEX]/g'
}
note() { printf '%s\n' "$*" >> "$MAN" || FAILED=1; }
save() { # source, relative destination; only known text files
    if [ ! -f "$1" ] || [ -L "$1" ]; then note "absent/skipped $1"; return; fi
    mkdir -p "$OUT/`dirname "$2"`" || { FAILED=1; return; }
    note "source $1 -> $2; last 512 KiB before filtering"
    tail -c 524288 "$1" 2>/dev/null | redact > "$OUT/$2" || FAILED=1
    note "saved-text checksum `cksum "$OUT/$2" 2>/dev/null`"
}
capture() { # destination, command and arguments
    DST=$1; shift
    "$@" 2>&1 | redact > "$OUT/$DST" || FAILED=1
}

# Capture the incident before reading archived logs. No D-Bus or device access.
snapshot() {
    TAG=$1
    {
        echo "--- uptime"; cat /proc/uptime
        echo "--- clock"; date
        echo "--- firmware"; grep -e 'MAZ_CMU' -e 'CPUGAUGE' /jci/version.ini 2>/dev/null
        echo "--- memory"; cat /proc/meminfo
        echo "--- cpu ticks"; cat /proc/stat
        echo "--- load"; cat /proc/loadavg
        echo "--- processes"; ps
        echo "--- process memory and CPU ticks"
        for P in /proc/[0-9]*; do
            read NAME < "$P/comm" 2>/dev/null || continue
            case "$NAME" in opera|BdsMainThread|bds.real|lua|jci_cpu_gauge|vim_app|sm|aap_service|carplayd)
                echo "--- pid ${P##*/} $NAME"
                grep -e '^Name:' -e '^State:' -e '^Vm' -e '^Threads:' "$P/status" 2>/dev/null
                cat "$P/stat" 2>/dev/null ;;
            esac
        done
        echo "--- service profiles (disk policy, may differ from loaded policy)"
        for C in /jci/sm/sm.conf /jci/sm/sm_WCP.conf; do
            cksum "$C" 2>/dev/null
            grep -e '<services ' -e 'name="Opera"' -e 'name="bds"' -e 'name="jciLDS"' "$C" 2>/dev/null
        done
        echo "--- boot hook files (mode matters)"
        ls -l /jci/scripts/stage_wifi.sh /jci/bds/bds /jci/bds/bds.real /data_persist/tpms/tpms-boot.sh /data_persist/mzd-utils/service/utils-boot.sh 2>/dev/null
        echo "--- storage"; df /tmp /data /data_persist
        echo "--- reset report inventory"; ls -l /data/*.out 2>/dev/null
        echo "--- crash dump inventory (contents not collected)"
        ls -l /data_persist/log/dumps/ 2>/dev/null | tail -n 30
        echo "--- saved log inventory"; ls -l /data_persist/log/saved_logs/ 2>/dev/null | tail -n 30
        echo "--- native log inventory"; ls -l /var/log/running_log/ 2>/dev/null
        echo "--- stock gauge state"
        ls -l /data/integration/cpugauge_off_flag 2>/dev/null
    } | redact > "$OUT/incident-$TAG.txt" || FAILED=1
}
snapshot before
capture kernel.txt dmesg
save /tmp/smevents.txt smevents.txt
for R in meminfo ps_info free_info top_info df_info thread_info dmesg; do
    save "/data/$R.out" "reset-reports/$R.out"
done
save /jci/scripts/stage_wifi.sh state/stage-wifi.txt
save /data/integration/developer_mode_GuiConfig.js state/screen-loader.txt

# Explicit lists avoid copying service packs, UART captures, credentials,
# maps or arbitrary files. Previous-start logs are kept alongside live logs.
for F in v3.log v3b.log v3.pulse v3.mute boot.log mem.log hmi.log hmi.log.1 tpmsd.log; do
    save "/tmp/tpms/$F" "tpms/live-$F"
    save "/data_persist/tpms/log/$F" "tpms/flash-$F"
    save "/data_persist/tpms/log/$F.prev" "tpms/flash-$F.prev"
done
for F in wrapper.log wrapper.log.old v3-watchdog.log cfg map route disabled bds-off keep-next keep-logs; do
    save "/data_persist/tpms/$F" "tpms/$F"
done
save /tmp/tpms/data.json tpms/data.json
save /tmp/tpms/bds-off tpms/boot-bds-off
save /tmp/tpms/bds-when tpms/boot-bds-when
save /tmp/tpms/ldcheck.txt tpms/ldcheck.txt
save /data_persist/tpms-install.log tpms/install.log
save /data_persist/tpms-rollback.log tpms/rollback.log

# SpeedMap: collect existing evidence directly, without its deep sensor/bus
# probes. Coordinates in data.json are dropped by the privacy filter.
for F in drive.log drive.log.1 hmi.log hmi.log.1 boot.log update.log update.json data.json; do
    save "/tmp/speedmap/$F" "speedmap/live-$F"
done
for F in health.log health.log.1 cfg disabled; do
    save "/data_persist/speedmap/$F" "speedmap/$F"
done
for F in hmi.log hmi.log.1 boot.log drive.log drive.log.1; do
    save "/data_persist/speedmap/log/$F" "speedmap/flash-$F"
    save "/data_persist/speedmap/log/$F.prev" "speedmap/flash-$F.prev"
done

# Utils: the watcher's log (every SetLastMode it saw, what it stored) and its
# state, which live in /tmp and so belong to this boot only; what the previous
# shutdown stored; the setting and the kill switch. Backups are not copied.
for F in service.log fm.state lastmode.prev; do
    save "/tmp/mzd-utils/$F" "utils/live-$F"
done
for F in cfg disabled lastmode.last; do
    save "/data_persist/mzd-utils/$F" "utils/$F"
done
mkdir -p "$OUT/utils" || FAILED=1
capture utils/files.txt ls -l /data_persist/mzd-utils /data_persist/mzd-utils/service /data_persist/mzd-utils/hmi

# Touch/install logs for every kit; no full configuration/backups are copied.
for F in tpms-touch.log tpms-install.log speedmap-touch.log wcp-touch.log utils-touch.log \
         vietnav-touch.log vietnav-install.log vietnav-rollback.log \
         speedmap-install.log speedmap-fix.log install.log; do
    save "$USB/$F" "touch/$F"
done
for F in wcp-install.log wcp-rollback.log vietnav-install.log vietnav-rollback.log; do
    save "/data_persist/$F" "other/$F"
done

# Native log is a mixed/binary stream. Keep only diagnostic messages, never
# raw syslog archives. Decoding output stops at 4 MiB per archive. Corrupt
# archives are recorded; there is no retry or unbounded archive traversal.
mkdir -p "$OUT/native" || exit 1
native_filter() {
    redact | grep -i -e CPUGAUGE -e 'CPU utilization' -e 'Memory utilization' \
        -e 'Dropping cache' -e 'VIP Rebooted' -e 'missing messages' \
        -e 'reboot' -e 'reset_board' -e resetboard -e watchdog -e 'out of memory' \
        -e oom -e 'killed process' -e lowmem -e 'low memory' -e segfault \
        -e 'abnormally' -e coredump -e 'not responding' -e heartbeat \
        -e 'StoppedService' -e 'stopped!' -e SIGSEGV -e SIGABRT -e SIGKILL \
        -e 'opera' -e 'speedmap' -e 'tpms' -e 'mzd-utils' | tail -n 1500
}
if [ -f /var/log/running_log/log ] && [ ! -L /var/log/running_log/log ]; then
    note 'native live: last 4 MiB, diagnostic lines only'
    tail -c 4194304 /var/log/running_log/log | native_filter > "$OUT/native/live.txt" || FAILED=1
else note 'native live absent'; fi
for I in 0 1 2 3 4 5 6 7 8 9; do
    A="/var/log/running_log/log_000$I.tar.gz"
    [ -f "$A" ] && [ ! -L "$A" ] || continue
    SIZE=`wc -c < "$A" 2>/dev/null`
    if [ "${SIZE:-0}" -gt 8388608 ]; then note "skip oversized archive $A ($SIZE bytes)"; continue; fi
    note "archive $A; checksum `cksum "$A" 2>/dev/null`; first 4 MiB decoded"
    tar -xzOf "$A" 2> "$OUT/native/.archive-errors" | head -c 4194304 |
        native_filter > "$OUT/native/archive-$I.txt" || FAILED=1
    redact < "$OUT/native/.archive-errors" > "$OUT/native/archive-$I-errors.txt" || FAILED=1
    rm -f "$OUT/native/.archive-errors"
    [ ! -s "$OUT/native/archive-$I-errors.txt" ] || note "archive $I: see decoder errors (corrupt or bounded stream)"
done
snapshot after
{
    echo 'CMU / TPMS / SpeedMap / CarPlay / VIETNAV / Utils diagnostics'
    echo 'Compare incident-before/after and native/ with reset-reports/.'
    echo 'Reset reports/archives may predate this boot; compare checksums and uptime.'
    echo 'Missing or filtered events do not rule out a fault. No cause inferred.'
    echo 'Text is filtered and size-limited; manifest.txt records collection scope.'
    echo "write_failure=$FAILED"
} > "$OUT/00-summary.txt" || FAILED=1
sync
echo "Saved: $OUT"
[ "$FAILED" = 0 ]
