#!/bin/sh
# Independent native trial keeper + bounded watchdog, never loaded into bds.
# AGPL-3.0-or-later. Fixed paths; argv values are validated before path use.
D=/data_persist/vietnav-native
PID=${1:-} START=${2:-} BOOT=${3:-} ID=${4:-} MODE=${5:-}
case "$PID:$START" in *[!0-9:]*|:*|*:) exit 1 ;; esac
case "$ID" in ''|*[!a-zA-Z0-9-]*) exit 1 ;; esac
case "$MODE" in query|advertise) ;; *) exit 1 ;; esac
OUT=$D/logs/$ID
LOG=/tmp/vietnav-native/native.log
PULSE=/tmp/tpms/v3.pulse
mkdir -p "$OUT" || exit 1
identity() {
    [ "$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)" = "$BOOT" ] || return 1
    [ "$(awk '{print $22}' /proc/$PID/stat 2>/dev/null)" = "$START" ]
}
same() {
    identity || return 1
    grep -qa '/jci/bds/bds.real' /proc/$PID/cmdline 2>/dev/null
}
keep() {
    if [ -f "$LOG" ]; then
        cmp -s "$LOG" "$OUT/native.log" 2>/dev/null || {
            cp "$LOG" "$OUT/native.log.new" 2>/dev/null && mv -f "$OUT/native.log.new" "$OUT/native.log"
        }
    fi
    if [ "$MODE" = query ] && grep -q 'VML RESULT peripheral capability present; query only' "$OUT/native.log" 2>/dev/null; then
        # Do not re-authorize a query cancelled by a later installer action.
        [ "$(cat "$D/latest-query" 2>/dev/null)" = "$ID" ] || return
        cp "$OUT/runtime.md5" "$D/query-ok.new" 2>/dev/null && mv -f "$D/query-ok.new" "$D/query-ok"
    fi
}
# Result/abort means the native experiment has intentionally stopped.
finished() { grep -qE 'VML RESULT|VML ABORT|# ABORT|FILTER STOPPED' "$LOG" 2>/dev/null; }
# The dispatcher forks us immediately before exec. Allow that exec to complete
# without mistaking its still-running shell for a dead/reused native process.
WAIT=0
while ! same; do
    identity || exit 0
    [ "$WAIT" -lt 10 ] || exit 0
    WAIT=$((WAIT + 1))
    sleep 1
done
I=0; LAST=; STALE=0
while same; do
    keep
    finished && { printf '%s\n' 'native experiment finished' > "$OUT/finished"; sync; exit 0; }
    CURRENT="$(cat "$PULSE" 2>/dev/null) $(wc -c < "$LOG" 2>/dev/null)"
    I=$((I + 1))
    # 15 s ticks: allow 90 s startup, then three unchanged samples (45 s).
    if [ "$I" -ge 6 ] && [ "$CURRENT" = "$LAST" ]; then STALE=$((STALE + 1)); else STALE=0; fi
    if [ "$STALE" -ge 3 ]; then
        same || exit 0
        printf '%s\n' 'native watchdog: no pulse/log progress; one-start token already consumed' > "$OUT/watchdog"
        keep
        sync
        # PID + start-time + command-line checked immediately before the kill.
        same && kill "$PID" 2>/dev/null
        exit 0
    fi
    LAST=$CURRENT
    sleep 15
 done
keep
sync
