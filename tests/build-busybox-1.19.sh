#!/bin/sh
# build-busybox-1.19.sh <dir> - builds BusyBox 1.19.2, the version on the
# car's CMU, with the applets the installer scripts use, for
# test_installer.py:
#
#     sh tests/build-busybox-1.19.sh /tmp/bb119
#     env -i HOME="$HOME" PATH=/tmp/bb119/bin BUSYBOX=/tmp/bb119/bin/busybox \
#         "$(command -v python3)" tests/test_installer.py
#
# PATH holds only the applets, so the scripts (and the stubs) meet the car's
# grep / awk / sed, not the host's GNU tools. No mount/umount applet: the
# test stubs them, and a real one could remount the host.
#
# Two build-only changes for a current glibc, no applet behaves differently:
# libbb.h includes <sys/resource.h>, and date's stime() goes through
# clock_settime().

set -eu
D=${1:?usage: build-busybox-1.19.sh <dir>}
V=busybox-1.19.2
MD5=50267054345f1a0b77fe65f6e0e5ba29     # busybox.net's signed release note

mkdir -p "$D"
cd "$D"
[ -f $V.tar.bz2 ] || curl -sSfL -o $V.tar.bz2 https://busybox.net/downloads/$V.tar.bz2
echo "$MD5  $V.tar.bz2" | md5sum -c - >/dev/null || { echo "$V.tar.bz2: md5 mismatch" >&2; exit 1; }
rm -rf "$V"
tar xjf $V.tar.bz2
cd "$V"

sed -i 's|#include <sys/stat.h>|#include <sys/stat.h>\n#include <sys/resource.h>|' include/libbb.h
sed -i '0,/^#include "libbb.h"/s//#include "libbb.h"\n\/* glibc >= 2.31 has no stime() *\/\nstatic int stime_shim(const time_t *t) { struct timespec ts = { *t, 0 }; return clock_settime(CLOCK_REALTIME, \&ts); }\n#define stime stime_shim/' coreutils/date.c

make allnoconfig >/dev/null
for o in ASH ASH_BASH_COMPAT ASH_BUILTIN_ECHO ASH_BUILTIN_PRINTF ASH_BUILTIN_TEST \
         ASH_ALIAS ASH_GETOPTS ASH_CMDCMD SH_MATH_SUPPORT SH_MATH_SUPPORT_64 \
         FEATURE_SH_IS_ASH AWK FEATURE_AWK_LIBM BASENAME CAT CHMOD CMP CP CUT DATE \
         DIRNAME ECHO FEATURE_FANCY_ECHO ENV FIND FEATURE_FIND_TYPE FEATURE_FIND_NAME \
         FEATURE_FIND_MAXDEPTH FEATURE_FIND_EXEC FEATURE_FIND_PATH FEATURE_FIND_NOT \
         GREP FEATURE_GREP_EGREP_ALIAS FEATURE_GREP_FGREP_ALIAS FEATURE_GREP_CONTEXT \
         HEAD FEATURE_FANCY_HEAD ID KILL KILLALL MD5SUM MKDIR MV PRINTF PS RM RMDIR \
         SED SEQ SLEEP FEATURE_FANCY_SLEEP SORT SYNC TAIL FEATURE_FANCY_TAIL TAR \
         FEATURE_TAR_CREATE FEATURE_SEAMLESS_GZ GZIP GUNZIP TEE TEST TOUCH TR TRUE \
         FALSE WC WHICH DMESG LS LN XARGS EXPR UNIQ OD READLINK MKTEMP LONG_OPTS; do
    sed -i "s/^# CONFIG_$o is not set/CONFIG_$o=y/" .config
done
yes "" | make oldconfig >/dev/null
make -j"$(nproc)" >/dev/null 2>&1 || { make 2>&1 | grep -E "error|undefined" >&2; exit 1; }

mkdir -p "$D/bin"
cp busybox "$D/bin/busybox"
for a in $(./busybox --list); do
    ln -sf busybox "$D/bin/$a"
done
echo "built $D/bin/busybox ($(./busybox --list | wc -l) applets)"
