"""Runs the VIETNAV installer scripts against a fake CMU, and checks that they
live next to the other touch kits on this car (wireless CarPlay, TPMS).

    python tests/test_installer.py
    VIETNAV_REAL_SM=<dir with sm.conf + sm_WCP.conf> python tests/test_installer.py

Every absolute car path in the scripts is rewritten into a temp folder;
mount, smctl, id, killall, ps and jci-dialog are stubs that log. The scripts
run under BusyBox ash when BUSYBOX points at one (busybox-w32 on Windows),
otherwise under the sh in PATH. VIETNAV_REAL_SM runs the install/rollback
round trip on the car's own sm configs too (never commit those: JCI files).
For the car's own tools, build BusyBox 1.19.2 with tests/build-busybox-1.19.sh
and run with PATH holding only its applets (see that script).
"""
import atexit
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INST = os.path.join(REPO, "installer")
BUSYBOX = os.environ.get("BUSYBOX")
with open(os.path.join(REPO, "VERSION")) as _f:
    VERSION = _f.read().strip()
SH = [BUSYBOX, "sh"] if BUSYBOX else ["sh"]

# A made-up sm.conf in the car's format: one line per <service ...>, children
# indented, </service> closes. Not Mazda's file.
def sm_conf(wcp=False):
    rb = "no" if wcp else "yes"
    arg = ' args="wcp"' if wcp else ""
    return ("""<?xml version="1.0"?>
<sm>
    <services>
        <service type="process" name="aap_service" path="/usr/bin/aap_service" autorun="yes" retry_count="0" reset_board="%(rb)s" stop_timeout="30000">
            <dependency type="service" value="devicemanager"/>
        </service>

        <service type="jci_service" name="jciCARPLAY" path="/jci/carplay/blmjcicarplay.so" autorun="yes" reset_board="%(rb)s" retry_count="0"%(arg)s ping_timeout="90000">
            <dependency type="service" value="carplayd"/>
        </service>

        <service type="jci_service" name="jciAAPA" path="/jci/aapa/blmjciaapa.so" autorun="yes" reset_board="%(rb)s" retry_count="0" ping_timeout="30000">
            <dependency type="service" value="aap_service"/>
            <dependency type="service" value="jciCARPLAY"/>
        </service>

        <service type="process" name="bds" path="/jci/bds/bds" autorun="yes" reset_board="%(rb)s">
            <dependency type="service" value="dbus"/>
        </service>
    </services>
</sm>
""" % {"rb": rb, "arg": arg}).encode()


MASTER = b"<cfg><item><name>NaviSupported</name><value>FALSE</value></item></cfg>\n"
XML_STOCK = b"<aap>stock</aap>\n"
XML_MOD = b"<aap>oem-aa-mod</aap>\n"
GATE = b"#!/bin/sh\n# wcp-gate.sh - wireless CarPlay gate\nexit 2\n"
TPMS_BDS = b"#!/bin/sh\n# TPMS bds wrapper, production\nexec /jci/bds/bds.real \"$@\"\n"
STAGE_WIFI = b"#!/bin/sh\n[ -f /data_persist/tpms/tpms-boot.sh ] && sh x &   # tpms-boot\n"

AA_L1 = '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-blmjciaapa.so"/>'
AA_L2 = '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-aa-mod/libpatch-aap_service.so"/>'
CP_L1 = '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/cp-hud-mod/libpatch-blmjcicarplay.so"/>'
CP_L2 = '            <environ_var env_name="LD_LIBRARY_PATH" env_value="/jci/lib:/usr/lib"/>'
# the same CarPlay bridge put in by another installer (a 74.00.324A car)
OLDCP_L1 = '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/oem-carplay/libpatch-blmjcicarplay.so"/>'
FOREIGN = '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/other-mod/libother.so"/>'

# Behaves like the car's /jci/tools/jci-dialog where it matters: only its
# own options (anything else: exit 255, nothing shown), and its text layout
# (split at a literal \n, at most 5 lines, ~50 characters fit the box).
# Breaking either is logged as DIALOG-BAD. A --no-cancel info box is a
# background popup; every other dialog takes the next answer from dialog.seq.
DIALOG_STUB = r'''#!/bin/sh
echo "jci-dialog $*" >> "@T@/stub.log"
T=""
for a in "$@"; do
    case "$a" in
        --info|--warning|--error|--question|--confirm|--3-button-dialog|--no-cancel|--help) ;;
        --title=*|--ok-label=*|--cancel-label=*|--button3-label=*) ;;
        --text=*) T=${a#--text=} ;;
        *) echo "DIALOG-BAD option $a" >> "@T@/stub.log"; exit 255 ;;
    esac
done
T=${T%\\n}
printf '%s\n' "$T" | sed 's/\\n/\
/g' | awk '{ if (length($0) > 52) print "DIALOG-BAD long line: " $0 }
           END { if (NR > 5) print "DIALOG-BAD " NR " lines" }' >> "@T@/stub.log"
case "$*" in *--info*--no-cancel*) exit 0 ;; esac
N=`head -n 1 "@T@/dialog.seq" 2>/dev/null`
tail -n +2 "@T@/dialog.seq" > "@T@/dialog.seq.new" 2>/dev/null
mv "@T@/dialog.seq.new" "@T@/dialog.seq"
exit ${N:-2}
'''
STUB = '#!/bin/sh\necho "%s $*" >> "@T@/stub.log"\n%s\n'

# The car's grep is BusyBox 1.19.2: only these options (no -x, no long
# options). Anything else prints its usage and fails, as on the car - logged
# as GREP-BAD so a test can catch it.
GREP_OPTS = "HhnlLoqvsriwFEcmABCef"
GREP_STUB = r'''#!/bin/sh
skip=
for a in "$@"; do
    if [ -n "$skip" ]; then skip=; continue; fi
    case "$a" in
        --) break ;;
        --*) echo "GREP-BAD grep $*" >> "@T@/stub.log"; echo "grep: unrecognized option '$a'" >&2; exit 2 ;;
        -?*) o=${a#-}
             while [ -n "$o" ]; do
                 c=${o%"${o#?}"}; o=${o#?}
                 case "@OPTS@" in *"$c"*) ;; *)
                     echo "GREP-BAD grep $*" >> "@T@/stub.log"
                     echo "grep: invalid option -- '$c'" >&2; exit 2 ;; esac
                 case "$c" in [mABCef]) [ -z "$o" ] && skip=1; break ;; esac
             done ;;
        *) break ;;
    esac
done
exec @GREP@ "$@"
'''


def rewrite(text, t):
    for a in ("/jci/", "/etc/", "/usr/", "/data_persist", "/tmp/", "/sys/class/gpio"):
        text = text.replace(a, "@T@" + a)
    text = text.replace("-C /tmp ", "-C @T@/tmp ")
    return text.replace("@T@", t)


def car_line(line, t):
    """One of the install's lines as it reads after the path rewrite."""
    return rewrite(line, t)


# The unit binaries the installer checks by md5 before it installs. Made-up
# bytes stand in for Mazda's files; the installer's md5 list is pointed at
# them (host_sums), so a test can swap one for "another build".
HOSTS = {
    "jci/aapa/blmjciaapa.so": b"\x7fELF blmjciaapa 324A/331",
    "usr/bin/aap_service": b"\x7fELF aap_service 324A/331",
    "jci/carplay/blmjcicarplay.so": b"\x7fELF blmjcicarplay 324A/331",
    "usr/lib/libdevmgr_interface.so": b"\x7fELF libdevmgr_interface 324A/331",
}


def host_sums(text, t):
    """vietnav-install.sh's unit-binary md5 list, pointed at the fake files."""
    for rel, body in HOSTS.items():
        text = re.sub(re.escape(t + "/" + rel) + "=[0-9a-f]{32}",
                      t + "/" + rel + "=" + hashlib.md5(body).hexdigest(), text)
    return text


class Car:
    def __init__(self, wcp_conf=False, sm=None, smw=None):
        self.t = scratch("vietnav-car-").replace("\\", "/")
        for d in ("jci/sm", "jci/scripts", "jci/bds", "jci/tools", "etc", "data_persist",
                  "data/integration", "tmp", "bin", "usb/vietnav-payload",
                  "sys/class/gpio/Watchdog Disable"):
            os.makedirs(os.path.join(self.t, d), exist_ok=True)
        self.write("jci/sm/sm.conf", sm if sm is not None else sm_conf(False))
        self.write("jci/sm/sm_WCP.conf", smw if smw is not None else sm_conf(wcp_conf))
        self.write("jci/version.ini", b'[VersionInfo]\nJCI_SW_VER="MAZ_CMU-150_74.00.331"\n')
        self.write("etc/devmgr_config_master.xml", MASTER)
        for x in ("aap_system_attributes.xml", "aap_system_attributes_UCP.xml"):
            self.write("etc/" + x, XML_STOCK)
            self.write("usb/vietnav-payload/" + x, XML_MOD)
        for so in ("libpatch-blmjciaapa.so", "libpatch-aap_service.so", "libpatch-svcjcinavi.so",
                   "libpatch-blmjcicarplay.so"):
            self.write("usb/vietnav-payload/" + so, b"\x7fELF" + so.encode())
        self.write("usb/vietnav-payload/libpatch.conf", b"hud = true\n")
        self.write_sums()
        # the other kits, as they leave the car
        self.write("jci/scripts/get_board_type.sh", GATE)
        self.write("data_persist/wcp-trial", b"999999\n")
        self.write("jci/bds/bds", TPMS_BDS)
        self.write("jci/scripts/stage_wifi.sh", STAGE_WIFI)
        self.write("data/integration/developer_mode_GuiConfig.js", b"// tpms-loader\n")
        self.write("sys/class/gpio/Watchdog Disable/value", b"0\n")
        for name in ("vietnav-install.sh", "vietnav-rollback.sh", "vietnav-collect.sh",
                     "vietnav-touch.sh", "install-patches.sh"):
            with open(os.path.join(INST, name), encoding="utf-8") as f:
                self.write("usb/" + name, host_sums(rewrite(f.read(), self.t), self.t).encode())
        for rel, body in HOSTS.items():
            self.write(rel, body)
        self.stub("bin/id", "id", "echo 0")
        self.stub("bin/mount", "mount", '[ -f "@T@/mount-fails" ] && exit 1\n'
                  'case "$*" in *remount,ro*) [ -f "@T@/mount-ro-fails" ] && exit 1 ;; esac\nexit 0')
        self.stub("bin/smctl", "smctl", "exit 0")
        self.stub("bin/killall", "killall", "exit 0")
        # dialog-open: how many more ps calls still see a payload's box up
        self.stub("bin/ps", "ps",
                  'n=`cat "@T@/dialog-open" 2>/dev/null`\n'
                  'if [ "${n:-0}" -gt 0 ]; then echo "  300 root  /jci/tools/jci-dialog --info";'
                  ' echo $((n - 1)) > "@T@/dialog-open"; fi\n'
                  'echo "  120 root  /jci/sm/sm -f /jci/sm/sm_WCP.conf"')
        real = BUSYBOX + " grep" if BUSYBOX else shutil.which("grep")
        self.write("bin/grep", GREP_STUB.replace("@T@", self.t).replace("@OPTS@", GREP_OPTS)
                   .replace("@GREP@", real).encode())
        os.chmod(os.path.join(self.t, "bin/grep"), 0o755)
        self.write("jci/tools/jci-dialog", DIALOG_STUB.replace("@T@", self.t).encode())
        os.chmod(os.path.join(self.t, "jci/tools/jci-dialog"), 0o755)

    def write(self, rel, data):
        if rel == "stub.log":
            self.stublog()          # keep any DIALOG-BAD before it is cleared
        p = os.path.join(self.t, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def read(self, rel):
        p = os.path.join(self.t, rel)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    def write_sums(self):
        """vietnav-payload/PAYLOAD-SOURCES.md as build-kit writes it."""
        d = os.path.join(self.t, "usb/vietnav-payload")
        rows = ["| file | md5 | source |", "|---|---|---|"]
        for n in sorted(os.listdir(d)):
            if n != "PAYLOAD-SOURCES.md":
                with open(os.path.join(d, n), "rb") as f:
                    rows.append("| %s | `%s` | test |" % (n, hashlib.md5(f.read()).hexdigest()))
        self.write("usb/vietnav-payload/PAYLOAD-SOURCES.md", ("\n".join(rows) + "\n").encode())

    def stub(self, rel, name, body):
        self.write(rel, (STUB % (name, body)).replace("@T@", self.t).encode())
        os.chmod(os.path.join(self.t, rel), 0o755)

    def run(self, script, *args):
        if script == "usb/install-patches.sh":
            # v11 opens the shared CAI DAT / Log / HUY screen before the
            # kit chooser. Existing sequences below describe the kit flow.
            self.write("dialog.seq", b"0\n" + (self.read("dialog.seq") or b""))
        e = dict(os.environ)
        e["PATH"] = self.t + "/bin" + os.pathsep + e.get("PATH", "")
        p = subprocess.run(SH + [self.t + "/" + script] + list(args), capture_output=True,
                           text=True, env=e, timeout=120)
        self.stublog()
        return p.returncode, p.stdout + p.stderr

    def seq(self, *codes):
        self.write("dialog.seq", ("\n".join(str(c) for c in codes) + "\n").encode())

    def stublog(self):
        log = (self.read("stub.log") or b"").decode()
        BAD_DIALOGS.update(l for l in log.splitlines() if l.startswith("DIALOG-BAD"))
        BAD_GREPS.update(l for l in log.splitlines() if l.startswith("GREP-BAD"))
        return log

    def conf(self, name):
        return self.read("jci/sm/" + name).decode()

    def tree(self, skip=("usb/", "tmp/", "stub.log", "dialog.seq")):
        out = {}
        for root, _, files in os.walk(self.t):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), self.t).replace("\\", "/")
                if not rel.startswith(skip):
                    out[rel] = self.read(rel)
        return out


FAILED = []
SCRATCH = []


def scratch(prefix):
    """A temp folder that goes away when the run ends (VIETNAV_KEEP=1 keeps them)."""
    d = tempfile.mkdtemp(prefix=prefix)
    SCRATCH.append(d)
    return d


@atexit.register
def _cleanup():
    if not os.environ.get("VIETNAV_KEEP"):
        for d in SCRATCH:
            shutil.rmtree(d, ignore_errors=True)
BAD_DIALOGS = set()
BAD_GREPS = set()


def check(name, ok, info=""):
    print("%-62s %s" % (name, "ok" if ok else "FAIL"))
    if not ok:
        FAILED.append(name)
        if info:
            print("    " + str(info).replace("\n", "\n    ")[:2000])


def under(conf, service, lines):
    """True when `lines` sit directly under <service ... name="service" ...>."""
    rows = conf.splitlines()
    for i, r in enumerate(rows):
        if "<service " in r and 'name="%s"' % service in r:
            return rows[i + 1:i + 1 + len(lines)] == lines
    return False


def svc_line(conf, service):
    return next(r for r in conf.splitlines() if "<service " in r and 'name="%s"' % service in r)


def guard(c):
    out = subprocess.run(SH + ["-c", "command -v mount"], capture_output=True, text=True,
                         env=dict(os.environ, PATH=c.t + "/bin" + os.pathsep + os.environ["PATH"])).stdout.strip()
    if not out.endswith("/bin/mount") or os.path.basename(c.t) not in out:
        sys.exit("refusing to run: `mount` resolves to %r, not the stub" % out)


OTHER_KITS = ("jci/scripts/get_board_type.sh", "data_persist/wcp-trial", "jci/bds/bds",
              "jci/scripts/stage_wifi.sh", "data/integration/developer_mode_GuiConfig.js")


def install_tests():
    # --- dry run
    c = Car(wcp_conf=True)
    guard(c)
    before = c.tree()
    rc, out = c.run("usb/vietnav-install.sh", "all")
    check("dry run: changes nothing", rc == 0 and c.tree() == before and "DRY RUN" in out, out)
    check("dry run: reads the firmware version", "MAZ_CMU-150_74.00.331" in out, out)

    # --- install both, on a car whose sm_WCP.conf the CarPlay kit already set
    sm0, smw0 = c.conf("sm.conf"), c.conf("sm_WCP.conf")
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    t = c.t
    sm, smw = c.conf("sm.conf"), c.conf("sm_WCP.conf")
    L = lambda s: car_line(s, t)
    check("install all: succeeds", rc == 0 and "DONE (all)" in out, out)
    for name, conf in (("sm.conf", sm), ("sm_WCP.conf", smw)):
        check("install: %s jciAAPA preload" % name, under(conf, "jciAAPA", [L(AA_L1)]), conf)
        check("install: %s aap_service preload" % name, under(conf, "aap_service", [L(AA_L2)]), conf)
        check("install: %s jciCARPLAY preload + lib path (both confs)" % name,
              under(conf, "jciCARPLAY", [L(CP_L1), L(CP_L2)]), conf)
    check("install: touched services get reset_board=no",
          all('reset_board="no"' in svc_line(sm, s) for s in ("jciAAPA", "aap_service", "jciCARPLAY")), sm)
    check("install: an untouched service keeps reset_board=yes", 'reset_board="yes"' in svc_line(sm, "bds"), sm)
    rec = (c.read("data_persist/vietnav/reset_board") or b"").decode().split("\n")
    check("install: reset_board changes recorded for sm.conf only",
          sorted(r for r in rec if r) == ["sm.conf aap_service", "sm.conf jciAAPA", "sm.conf jciCARPLAY"], rec)
    check("install: NaviSupported TRUE", b"<value>TRUE</value>" in c.read("etc/devmgr_config_master.xml"))
    check("install: XMLs swapped, originals kept",
          c.read("etc/aap_system_attributes.xml") == XML_MOD and c.read("etc/aap_system_attributes.xml.orig") == XML_STOCK)
    check("install: watchdog enabled again", c.read("sys/class/gpio/Watchdog Disable/value").strip() == b"0")
    log = c.stublog()
    check("install: rootfs remounted rw then ro",
          "mount -o remount,rw /" in log and "mount -o remount,ro /" in log.split("mount -o remount,rw /")[-1], log)
    check("install: log kept on the stick", b"DONE" in (c.read("usb/vietnav-install.log") or b""))
    check("install: no temp file left next to a target",
          not [p for p in c.tree() if p.endswith(".vietnav-new")], list(c.tree()))
    check("install: the other kits' files untouched",
          all(c.read(p) == before[p] for p in OTHER_KITS))

    # --- again: nothing changes
    snap = c.tree()
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    after = c.tree()
    check("install again: idempotent", rc == 0 and all(after[p] == snap[p] for p in snap
                                                       if p.startswith(("jci/", "etc/"))), out)

    # --- rollback: back to what it was, byte for byte
    rc, out = c.run("usb/vietnav-rollback.sh", "all")
    check("rollback all: succeeds", rc == 0 and "DONE (all)" in out, out)
    check("rollback: sm.conf byte-identical to the original", c.conf("sm.conf") == sm0, c.conf("sm.conf"))
    check("rollback: sm_WCP.conf byte-identical (CarPlay kit's reset_board kept)",
          c.conf("sm_WCP.conf") == smw0, c.conf("sm_WCP.conf"))
    check("rollback: NaviSupported back to FALSE", c.read("etc/devmgr_config_master.xml") == MASTER)
    check("rollback: XMLs restored", c.read("etc/aap_system_attributes_UCP.xml") == XML_STOCK)
    check("rollback: watchdog enabled again", c.read("sys/class/gpio/Watchdog Disable/value").strip() == b"0")
    check("rollback: the other kits' files untouched", all(c.read(p) == before[p] for p in OTHER_KITS))
    rc, out = c.run("usb/vietnav-rollback.sh", "all")
    check("rollback again: harmless", rc == 0 and c.conf("sm.conf") == sm0, out)

    # --- stock sm_WCP.conf (no CarPlay kit): its reset_board is left at "no"
    c = Car(wcp_conf=False)
    smw0 = c.conf("sm_WCP.conf")
    c.run("usb/vietnav-install.sh", "all", "--yes")
    c.run("usb/vietnav-rollback.sh", "all")
    want = smw0
    for s in ("jciAAPA", "aap_service", "jciCARPLAY"):
        line = svc_line(want, s)
        want = want.replace(line, line.replace('reset_board="yes"', 'reset_board="no"'))
    check("stock sm_WCP.conf: only our lines go, reset_board stays no", c.conf("sm_WCP.conf") == want,
          c.conf("sm_WCP.conf"))

    # --- another mod already in jciAAPA: refuse everything, change nothing
    for which in ("sm.conf", "sm_WCP.conf"):
        c = Car(wcp_conf=True)
        conf = c.conf(which)
        line = svc_line(conf, "jciAAPA")
        c.write("jci/sm/" + which, conf.replace(line, line + "\n" + FOREIGN).encode())
        before = c.tree()
        rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
        check("foreign environ_var in %s: install refused" % which,
              rc != 0 and "another mod" in out, out)
        check("foreign environ_var in %s: nothing changed (no half install)" % which,
              c.tree() == before, sorted(set(c.tree()) ^ set(before)))

    # --- another mod's lines elsewhere in the same file survive both ways
    c = Car(wcp_conf=True)
    conf = c.conf("sm.conf")
    line = svc_line(conf, "bds")
    c.write("jci/sm/sm.conf", conf.replace(line, line + "\n" + FOREIGN).encode())
    sm0 = c.conf("sm.conf")
    c.run("usb/vietnav-install.sh", "all", "--yes")
    rc, out = c.run("usb/vietnav-rollback.sh", "all")
    check("another mod's line in bds survives install + rollback", c.conf("sm.conf") == sm0, out)

    # --- NaviSupported already TRUE: rollback leaves it TRUE
    c = Car()
    true_master = MASTER.replace(b"FALSE", b"TRUE")
    c.write("etc/devmgr_config_master.xml", true_master)
    c.run("usb/vietnav-install.sh", "cp", "--yes")
    c.run("usb/vietnav-rollback.sh", "cp")
    check("NaviSupported TRUE before install stays TRUE after rollback",
          c.read("etc/devmgr_config_master.xml") == true_master)

    # --- the CarPlay kit's rollback puts its own sm backups back (pre-vietnav):
    # the touch menu sees "not installed" and CAI DAT puts the lines back
    c = Car(wcp_conf=True)
    sm0, smw0 = c.read("jci/sm/sm.conf"), c.read("jci/sm/sm_WCP.conf")
    c.run("usb/vietnav-install.sh", "all", "--yes")
    c.write("jci/sm/sm.conf", sm0)
    c.write("jci/sm/sm_WCP.conf", smw0)
    c.seq(2)
    c.run("usb/install-patches.sh")
    check("after a CarPlay-kit rollback the menu says not installed",
          "--title=VIETNAV HUD %s --text=Trang thai / Status:" % VERSION in c.stublog()
          and "CHUA CAI / not installed" in c.stublog(), c.stublog())
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    check("...and installing again puts the lines back",
          rc == 0 and under(c.conf("sm.conf"), "jciAAPA", [car_line(AA_L1, c.t)]), out)
    rc, out = c.run("usb/vietnav-rollback.sh", "all")
    check("...and the rollback after that is still exact",
          rc == 0 and c.read("jci/sm/sm.conf") == sm0 and c.read("jci/sm/sm_WCP.conf") == smw0, out)

    # --- an install from before this fix (CarPlay only in sm_WCP.conf) rolls back
    c = Car(wcp_conf=True)
    smw0 = c.conf("sm_WCP.conf")
    line = svc_line(smw0, "jciCARPLAY")
    c.write("jci/sm/sm_WCP.conf", smw0.replace(
        line, line + "\n" + car_line(CP_L1, c.t) + "\n" + car_line(CP_L2, c.t)).encode())
    rc, out = c.run("usb/vietnav-rollback.sh", "cp")
    check("an older install's lines roll back", rc == 0 and c.conf("sm_WCP.conf") == smw0, out)

    # --- a failed remount of / changes nothing
    c = Car()
    c.write("mount-fails", b"")
    before = c.tree()
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    check("remount failure: install stops, nothing changed",
          rc != 0 and {k: v for k, v in c.tree().items() if k != "mount-fails"} ==
          {k: v for k, v in before.items() if k != "mount-fails"}, out)

    # --- a damaged payload file (or no checksums) stops the install
    for what, spoil in (("a damaged .so", lambda c: c.write("usb/vietnav-payload/libpatch-blmjciaapa.so", b"\x7fELF bad")),
                        ("a damaged XML", lambda c: c.write("usb/vietnav-payload/aap_system_attributes.xml", b"<x/>\n")),
                        ("no PAYLOAD-SOURCES.md", lambda c: os.remove(os.path.join(c.t, "usb/vietnav-payload/PAYLOAD-SOURCES.md")))):
        c = Car()
        spoil(c)
        before = c.tree()
        rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
        check("payload check: %s stops the install, nothing changed" % what,
              rc != 0 and c.tree() == before and "nothing changed" in out, out)
    c = Car()
    rc, out = c.run("usb/vietnav-install.sh", "cp", "--yes")
    check("payload check: md5 ok is logged", rc == 0 and "payload md5 ok: libpatch-blmjcicarplay.so" in out, out)

    # --- a write that fails half-way: everything this run changed goes back
    c = Car(wcp_conf=True)
    keep = {p: c.read(p) for p in ("jci/sm/sm.conf", "jci/sm/sm_WCP.conf", "etc/devmgr_config_master.xml",
                                   "etc/aap_system_attributes.xml", "etc/aap_system_attributes_UCP.xml")}
    os.makedirs(os.path.join(c.t, "etc/devmgr_config_master.xml.vietnav-new"))   # the last write fails
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    st = os.path.join(c.t, "data_persist/vietnav")
    check("half-way failure: sm configs, /etc and records put back",
          rc != 0 and all(c.read(p) == b for p, b in keep.items())
          and not os.path.exists(os.path.join(c.t, "etc/aap_system_attributes.xml.orig"))
          and not os.path.exists(os.path.join(st, "reset_board"))
          and not os.path.exists(os.path.join(st, "navisupported"))
          and not os.path.exists(os.path.join(st, "txn"))
          and "the unit is as it was before this run" in out, out)
    os.rmdir(os.path.join(c.t, "etc/devmgr_config_master.xml.vietnav-new"))
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    rc2, out2 = c.run("usb/vietnav-rollback.sh", "all")
    check("half-way failure: a later install + rollback round trip is exact",
          rc == 0 and rc2 == 0 and all(c.read(p) == b for p, b in keep.items()), out + out2)

    # --- another mod puts its line above ours after the install: rollback
    # still takes ours out of the block, leaves theirs, says so if it cannot
    other = '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/aa-mod/libaawl.so"/>'
    c = Car(wcp_conf=True)
    c.run("usb/vietnav-install.sh", "all", "--yes")
    for name in ("sm.conf", "sm_WCP.conf"):
        rows = c.conf(name).splitlines()
        i = next(n for n, l in enumerate(rows) if 'name="jciAAPA"' in l)
        rows.insert(i + 1, other)
        c.write("jci/sm/" + name, ("\n".join(rows) + "\n").encode())
    rc, out = c.run("usb/vietnav-rollback.sh", "all")
    both = c.conf("sm.conf") + c.conf("sm_WCP.conf")
    check("rollback: our lines go even below another mod's line, theirs stay",
          rc == 0 and "oem-aa-mod" not in both and "cp-hud-mod" not in both
          and both.count("libaawl.so") == 2, out)

    # --- one run at a time
    c = Car()
    p = subprocess.Popen(SH + ["-c", 'echo $$ > "%s/holder.pid"; exec sleep 30' % c.t])
    for _ in range(50):
        if c.read("holder.pid"):
            break
        time.sleep(0.1)
    os.makedirs(os.path.join(c.t, "tmp/vietnav.lock"))
    c.write("tmp/vietnav.lock/pid", c.read("holder.pid"))
    before = c.tree()
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    rc2, out2 = c.run("usb/vietnav-rollback.sh", "all")
    p.kill(); p.wait()
    check("lock: a running install/rollback blocks another, nothing changed",
          rc != 0 and rc2 != 0 and c.tree() == before and "another vietnav" in out, out + out2)
    c.write("tmp/vietnav.lock/pid", b"999999\n")          # a run that was killed
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    check("lock: a stale lock is taken over, and released after",
          rc == 0 and not os.path.exists(os.path.join(c.t, "tmp/vietnav.lock")), out)

    # --- / that will not go back to read-only is reported
    c = Car()
    c.write("mount-ro-fails", b"")
    rc, out = c.run("usb/vietnav-install.sh", "aa", "--yes")
    rc2, out2 = c.run("usb/vietnav-rollback.sh", "aa")
    check("read-only remount failure is logged (install and rollback)",
          rc == 0 and rc2 == 0 and "did not go back to read-only" in out
          and "did not go back to read-only" in out2, out + out2)

    # --- collect: tarball on the stick, other kits named
    c = Car(wcp_conf=True)
    rc, out = c.run("usb/vietnav-collect.sh")
    tgz = [f for f in os.listdir(os.path.join(c.t, "usb")) if f.startswith("vietnav-collect-")]
    check("collect: tarball written to the stick", rc == 0 and len(tgz) == 1, out)
    if tgz:
        listing = subprocess.run(["tar", "-tzf", tgz[0]], cwd=os.path.join(c.t, "usb"),
                                 capture_output=True, text=True).stdout
        check("collect: notes the other kits", "other-kits.txt" in listing, listing)
        check("collect: which shims run, the unit binaries' md5, the shim log lines",
              all(n in listing for n in ("shims-running.txt", "unit-md5.txt", "shim-log-lines.txt")),
              listing)
        md5s = subprocess.run(["tar", "-xzOf", tgz[0], "vietnav-collect/unit-md5.txt"],
                              cwd=os.path.join(c.t, "usb"), capture_output=True, text=True).stdout
        check("collect: unit md5 list has the four checked binaries",
              all(hashlib.md5(HOSTS[r]).hexdigest() in md5s for r in HOSTS), md5s)

    # --- real sm configs, when given
    real = os.environ.get("VIETNAV_REAL_SM")
    if real:
        sm0 = open(os.path.join(real, "sm.conf"), "rb").read()
        smw0 = open(os.path.join(real, "sm_WCP.conf"), "rb").read()
        c = Car()
        # car paths in the confs (another mod's lines) rewritten as the scripts are
        here = lambda b: rewrite(b.decode(), c.t).encode()
        sm0, smw0 = here(sm0), here(smw0)
        c.write("jci/sm/sm.conf", sm0)
        c.write("jci/sm/sm_WCP.conf", smw0)
        rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
        check("real confs: install", rc == 0 and under(c.conf("sm.conf"), "jciCARPLAY",
                                                       [car_line(CP_L1, c.t), car_line(CP_L2, c.t)]), out)
        rc, out = c.run("usb/vietnav-rollback.sh", "all")
        check("real confs: sm.conf back byte for byte", rc == 0 and c.read("jci/sm/sm.conf") == sm0, out)
        # sm_WCP.conf's reset_board is the CarPlay kit's and stays "no"
        def rb_no(conf):
            return "\n".join(re.sub(r'reset_board="yes"', 'reset_board="no"', r)
                             if "<service " in r and re.search(r'name="(jciAAPA|aap_service|jciCARPLAY)"', r)
                             else r for r in conf.split("\n"))
        check("real confs: sm_WCP.conf back, but for its reset_board",
              c.conf("sm_WCP.conf") == rb_no(smw0.decode()), out)


def oldcp_tests():
    """A car that already runs the same CarPlay bridge from another installer
    (/data_persist/oem-carplay): CAI DAT replaces it, GO BO puts it back."""
    def old_car(extra_first=None, extra_last=None):
        c = Car(wcp_conf=True)
        for name in ("sm.conf", "sm_WCP.conf"):
            rows = c.conf(name).split("\n")
            i = next(k for k, r in enumerate(rows) if 'name="jciCARPLAY"' in r)
            add = [car_line(OLDCP_L1, c.t), car_line(CP_L2, c.t)]
            if extra_first: add.insert(0, extra_first)
            if extra_last: add.append(extra_last)
            rows[i + 1:i + 1] = add
            c.write("jci/sm/" + name, "\n".join(rows).encode())
        return c

    c = old_car()
    L = lambda x: car_line(x, c.t)
    sm0, smw0 = c.read("jci/sm/sm.conf"), c.read("jci/sm/sm_WCP.conf")
    rc, out = c.run("usb/vietnav-install.sh", "cp")
    check("old bridge: the dry run says it will replace it",
          rc == 0 and out.count("replace the same bridge from another installer") == 2, out)
    rc, out = c.run("usb/vietnav-install.sh", "cp", "--yes")
    sm, smw = c.conf("sm.conf"), c.conf("sm_WCP.conf")
    check("old bridge: install cp succeeds", rc == 0 and "DONE (cp)" in out, out)
    check("old bridge: ours in both confs, the old line gone",
          all(under(x, "jciCARPLAY", [L(CP_L1), L(CP_L2)]) and "oem-carplay" not in x for x in (sm, smw)), sm + smw)
    check("old bridge: only that line changed (+ reset_board in sm.conf)",
          sm.count("\n") == sm0.decode().count("\n") and smw.count("\n") == smw0.decode().count("\n")
          and 'reset_board="no"' in svc_line(sm, "jciCARPLAY"), sm)
    check("old bridge: the takeover is recorded",
          sorted((c.read("data_persist/vietnav/takeover") or b"").decode().split()) ==
          sorted("sm.conf jciCARPLAY sm_WCP.conf jciCARPLAY".split()))
    rc, out = c.run("usb/vietnav-install.sh", "cp", "--yes")
    check("old bridge: installing again changes nothing",
          rc == 0 and c.conf("sm.conf") == sm and c.conf("sm_WCP.conf") == smw, out)
    rc, out = c.run("usb/vietnav-rollback.sh", "cp")
    check("old bridge: GO BO puts the old bridge back, byte for byte",
          rc == 0 and c.read("jci/sm/sm.conf") == sm0 and c.read("jci/sm/sm_WCP.conf") == smw0, out)
    check("old bridge: ...and forgets the takeover", c.read("data_persist/vietnav/takeover") is None)

    c = old_car()
    sm0, smw0 = c.read("jci/sm/sm.conf"), c.read("jci/sm/sm_WCP.conf")
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    rc2, out2 = c.run("usb/vietnav-rollback.sh", "all")
    check("old bridge: install all + rollback all is exact",
          rc == 0 and rc2 == 0 and c.read("jci/sm/sm.conf") == sm0 and c.read("jci/sm/sm_WCP.conf") == smw0, out + out2)

    for what, kw in (("a third line in the block", {"extra_last": FOREIGN}),
                     ("the old lines not right under <service>", {"extra_first": FOREIGN})):
        c = old_car(**kw)
        before = c.tree()
        rc, out = c.run("usb/vietnav-install.sh", "cp", "--yes")
        check("old bridge: %s -> exit 4, nothing changed" % what, rc == 4 and c.tree() == before, out)

    # the touch menu says so, and says what CAI DAT will do
    c = old_car()
    c.seq(0, 1, 0, 0)                 # CAI DAT, CARPLAY, CAI DAT, OK
    c.run("usb/vietnav-touch.sh")
    time.sleep(0.3)
    log = c.stublog()
    check("old bridge: touch shows it, CAI DAT replaces it",
          "CHUA CAI, CO CARPLAY HUD CU / old CP HUD" in log and "Thay CARPLAY HUD cu / replaces the old one" in log
          and "DA CAI / INSTALLED: CARPLAY" in log and under(c.conf("sm.conf"), "jciCARPLAY", [car_line(CP_L1, c.t), car_line(CP_L2, c.t)]), log)
    c = old_car(extra_last=FOREIGN)
    c.seq(0, 1, 0, 0)
    c.run("usb/vietnav-touch.sh")
    time.sleep(0.3)
    check("old bridge: another mod in the way -> XE DA CO MOD KHAC",
          "XE DA CO MOD KHAC / ANOTHER MOD IS IN" in c.stublog() and "CAI DAT LOI" not in c.stublog(), c.stublog())


def launcher_tests():
    def kits(c, names):
        for n in names:
            c.write("usb/%s-touch.sh" % n, ('#!/bin/sh\necho "payload %s" >> "%s/stub.log"\n' % (n, c.t)).encode())

    c = Car()
    os.remove(os.path.join(c.t, "usb/vietnav-touch.sh"))
    kits(c, ["vietnav"])
    c.seq(0)
    c.run("usb/install-patches.sh")
    check("launcher: one kit opens directly after the shared first screen",
          "payload vietnav" in c.stublog() and "CAI DAT = mo VIETNAV" in c.stublog()
          and c.stublog().count("--3-button-dialog") == 1, c.stublog())

    c = Car()
    kits(c, ["vietnav", "other"])
    c.seq(1, 0)
    c.run("usb/install-patches.sh")
    check("launcher: two kits (one not standard), 2nd button runs the 2nd",
          "payload other" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(2)
    before = c.tree()
    c.run("usb/install-patches.sh")
    check("launcher: HUY runs nothing", "payload" not in c.stublog() and c.tree() == before, c.stublog())

    # two of the three standard kits: fixed three-button face, the missing
    # kit is reported on screen, not hidden
    c = Car()
    kits(c, ["tpms", "vietnav"])
    c.seq(1, 9, 9)
    c.run("usb/install-patches.sh")
    check("launcher: missing standard kit is reported, not run",
          "KHONG CO tren USB" in c.stublog() and "payload" not in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(1, 7, 0)
    c.run("usb/install-patches.sh")
    check("launcher: after the report it is back at the chooser",
          "KHONG CO tren USB" in c.stublog() and "payload tpms" in c.stublog(), c.stublog())

    c = Car()
    kits(c, ["tpms", "wcp", "vietnav"])
    c.seq(2)
    c.run("usb/install-patches.sh")
    check("launcher: three kits, the 3rd is on the one screen",
          "payload vietnav" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(1, 0)
    c.run("usb/install-patches.sh")
    check("launcher: CARPLAY (foreign) asks BAT DAU first, then runs",
          "payload wcp" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(1, 1, 9)
    c.run("usb/install-patches.sh")
    check("launcher: CARPLAY confirm HUY runs nothing",
          "payload" not in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(2, 0, 0, 1)
    c.run("usb/install-patches.sh")
    check("launcher: LAM TIEP reopens the chooser, XONG leaves",
          "payload vietnav" in c.stublog() and "payload tpms" in c.stublog(), c.stublog())

    # the chooser says what each kit has on the car
    def chooser(c):
        c.write("stub.log", b"")
        c.seq(9)
        c.run("usb/install-patches.sh")
        # the whole call: its --text spans several log lines, up to the labels
        log = c.stublog()
        i = log.rfind("--3-button-dialog")
        return log[i:log.find("--ok-label=", i)] if i >= 0 else ""

    c = Car()
    kits(c, ["tpms", "wcp", "vietnav"])
    face = chooser(c)
    check("launcher: chooser shows each kit's state (fixture car)",
          "TPMS (ap suat lop): DA CAI / installed" in face
          and "CARPLAY (khong day): DA CAI / installed" in face
          and "VIETNAV (HUD): CHUA CAI / not installed" in face, face)
    rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
    face = chooser(c)
    check("launcher: VIETNAV shows DA CAI AA + CARPLAY after an install",
          rc == 0 and "VIETNAV (HUD): DA CAI AA + CARPLAY / installed" in face, face)
    c.run("usb/vietnav-rollback.sh", "cp")
    face = chooser(c)
    check("launcher: ... and DA CAI AA after the CarPlay part is removed",
          "VIETNAV (HUD): DA CAI AA / installed" in face, face)

    # after LAM TIEP the chooser reads the car again
    c = Car()
    kits(c, ["tpms", "wcp", "vietnav"])
    c.write("usb/vietnav-touch.sh", ('#!/bin/sh\necho "payload vietnav" >> "%s/stub.log"\n'
                                     'echo "data_persist/oem-aa-mod/libpatch" >> "%s/jci/sm/sm.conf"\n'
                                     % (c.t, c.t)).encode())
    c.seq(2, 0, 9)
    c.run("usb/install-patches.sh")
    faces = [f.split("--ok-label=")[0] for f in c.stublog().split("--3-button-dialog")[2:]]
    check("launcher: after LAM TIEP the chooser shows the new state",
          len(faces) == 2 and "VIETNAV (HUD): CHUA CAI" in faces[0]
          and "VIETNAV (HUD): DA CAI AA / installed" in faces[1], c.stublog())

    c = Car()
    kits(c, ["tpms", "wcp", "vietnav"])
    c.write("jci/bds/bds", b"#!/bin/sh\n# tpms-v3 trial wrapper\n")
    c.write("data_persist/wcp-trial", b"1\n")
    face = chooser(c)
    check("launcher: trial states (TPMS trial, CarPlay trial)",
          "TPMS (ap suat lop): BAN THU / trial armed" in face
          and "CARPLAY (khong day): CHAY THU / trial" in face, face)
    c.write("jci/bds/bds", TPMS_BDS)
    c.write("data_persist/tpms/bds-off", b"3 bad starts\n")
    os.remove(os.path.join(c.t, "data_persist/wcp-trial"))
    face = chooser(c)
    check("launcher: switched-off states (TPMS bds-off, CarPlay no trial left)",
          "TPMS (ap suat lop): DA CAI, DANG TAT / off" in face
          and "CARPLAY (khong day): TAT / off" in face, face)
    c.write("jci/bds/bds", b"\x7fELF stock bds")
    c.write("jci/scripts/get_board_type.sh", b"#!/bin/sh\nexit 0\n")
    face = chooser(c)
    check("launcher: stock car says CHUA CAI for TPMS and CarPlay",
          "TPMS (ap suat lop): CHUA CAI / not installed" in face
          and "CARPLAY (khong day): CHUA CAI / not installed" in face, face)

    # the CarPlay kit restarts the unit: after it, no LAM TIEP
    c = Car()
    kits(c, ["tpms", "wcp", "vietnav"])
    c.seq(1, 0, 0, 0)
    c.run("usb/install-patches.sh")
    log = c.stublog()
    check("launcher: after CARPLAY the session ends (no LAM TIEP)",
          log.count("payload wcp") == 1 and "LAM TIEP" not in log[log.find("payload wcp"):], log)

    # TPMS ends on a background --info box: it stays until tapped away,
    # nothing is killed or asked before that
    c = Car()
    kits(c, ["tpms", "vietnav"])
    c.write("usb/tpms-touch.sh", ('#!/bin/sh\necho "payload tpms" >> "%s/stub.log"\n'
                                  'echo 3 > "%s/dialog-open"\n' % (c.t, c.t)).encode())
    c.seq(0, 1)
    c.run("usb/install-patches.sh")
    after = c.stublog().split("payload tpms")[1]
    check("launcher: a payload's last message is left until tapped",
          after.count("ps ") == 4 and "killall" not in after[:after.rfind("ps ")]
          and "LAM TIEP" in after, c.stublog())

    # a dialog that answers by itself does not spin the chooser
    c = Car()
    kits(c, ["tpms", "vietnav"])
    c.seq(*([1] * 40))
    rc, out = c.run("usb/install-patches.sh")
    check("launcher: chooser shown 6 times at most, then ends",
          rc == 0 and c.stublog().count("--3-button-dialog") == 7, c.stublog())

    c = Car()
    kits(c, ["tpms", "wcp", "vietnav", "other"])
    c.seq(2, 1, 0)
    c.run("usb/install-patches.sh")
    check("launcher: four kits, TIEP then the 4th (confirm BAT DAU)",
          "payload other" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(2, 2)
    c.run("usb/install-patches.sh")
    check("launcher: HUY on the second screen runs nothing",
          "payload" not in c.stublog(), c.stublog())

    c = Car()
    kits(c, ["tpms", "wcp", "vietnav"])
    os.remove(os.path.join(c.t, "jci/tools/jci-dialog"))
    c.run("usb/install-patches.sh")
    check("launcher: several kits, car not up -> runs nothing", "payload" not in c.stublog(), c.stublog())


def touch_tests():
    c = Car(wcp_conf=True)
    sm0 = c.read("jci/sm/sm.conf")
    os.remove(os.path.join(c.t, "usb/install-patches.sh"))
    with open(os.path.join(INST, "install-patches.sh"), encoding="utf-8") as f:
        c.write("usb/install-patches.sh", rewrite(f.read(), c.t).encode())
    # a second tap confirms; HUY there changes nothing
    before = c.tree()
    c.seq(0, 2, 1)                    # CAI DAT, CA HAI, then HUY on the confirm
    c.run("usb/install-patches.sh")
    check("touch: HUY on the install confirm changes nothing",
          c.tree() == before and "CAI DAT AA + CARPLAY?" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(0, 2, 0)                    # CAI DAT, CA HAI, CAI DAT (confirm)
    rc, out = c.run("usb/install-patches.sh")
    time.sleep(0.5)
    tlog = (c.read("usb/vietnav-touch.log") or b"").decode()
    check("touch: CAI DAT -> CA HAI installs both",
          under(c.conf("sm.conf"), "jciAAPA", [car_line(AA_L1, c.t)]) and
          under(c.conf("sm_WCP.conf"), "jciCARPLAY", [car_line(CP_L1, c.t), car_line(CP_L2, c.t)]),
          out + tlog)
    check("touch: log on the stick", "install: all" in tlog, tlog)
    check("touch: says done, both languages, with the credit",
          "DA CAI / INSTALLED: AA + CARPLAY" in c.stublog()
          and "Power-cycle the car, then start navigation" in c.stublog()
          and "- by dangkhoa116 -" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(9)
    c.run("usb/install-patches.sh")
    check("touch: menu shows the status and the credit once installed",
          "DA CAI AA + CARPLAY / installed" in c.stublog()
          and "GO BO = remove" in c.stublog() and "- by dangkhoa116 -" in c.stublog(), c.stublog())
    check("touch: ...under the stick's kit version, with the installed one",
          "--title=VIETNAV HUD %s " % VERSION in c.stublog()
          and "DA CAI AA + CARPLAY / installed " + VERSION in c.stublog()
          and c.read("data_persist/vietnav/version") == (VERSION + "\n").encode(), c.stublog())
    check("touch: the logs name the version",
          "touch installer " + VERSION in (c.read("usb/vietnav-touch.log") or b"").decode()
          and "vietnav %s target=" % VERSION in (c.read("usb/vietnav-install.log") or b"").decode())
    installed = c.read("jci/sm/sm.conf")
    c.seq(0, 1)                       # GO BO, then HUY on the confirm
    c.run("usb/install-patches.sh")
    check("touch: HUY on the remove confirm changes nothing",
          c.read("jci/sm/sm.conf") == installed and "GO BO AA + CARPLAY?" in c.stublog(), c.stublog())
    c.seq(0, 0)                       # GO BO, GO BO (confirm)
    c.run("usb/install-patches.sh")
    check("touch: GO BO puts sm.conf back", c.read("jci/sm/sm.conf") == sm0, c.stublog())
    check("touch: ...and forgets the installed version", c.read("data_persist/vietnav/version") is None)


def build_kit_tests():
    spec = importlib.util.spec_from_file_location("build_kit", os.path.join(INST, "build-kit.py"))
    bk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bk)
    ours = os.path.join(INST, "install-patches.sh")
    wcp_payload = b"#!/bin/sh\n# install-patches.sh - Wireless CarPlay TOUCH installer payload.\nsh wcp-enable.sh\n"
    old_tpms = b"#!/bin/sh\n# install-patches.sh - the touch launcher for this stick.\nexec sh tpms-touch.sh\n"

    def stick(files):
        d = scratch("vietnav-stick-")
        for n, b in files.items():
            with open(os.path.join(d, n), "wb") as f:
                f.write(b)
        return d

    def rd(d, n):
        p = os.path.join(d, n)
        return open(p, "rb").read() if os.path.exists(p) else None

    shared = open(ours, "rb").read()
    d = stick({"install-patches.sh": old_tpms, "tpms-touch.sh": b"tpms", "wcp-touch.sh": wcp_payload})
    err = bk.place_launcher(d, ours)
    check("build-kit: TPMS stick - launcher replaced, payloads kept",
          err is None and rd(d, "install-patches.sh") == shared and rd(d, "tpms-touch.sh") == b"tpms"
          and rd(d, "wcp-touch.sh") == wcp_payload, err)

    d = stick({"install-patches.sh": wcp_payload})
    err = bk.place_launcher(d, ours)
    check("build-kit: CarPlay kit's payload kept as wcp-touch.sh",
          err is None and rd(d, "wcp-touch.sh") == wcp_payload and rd(d, "install-patches.sh") == shared, err)

    d = stick({"install-patches.sh": old_tpms.replace(b"tpms", b"vietnav"), "other-touch.sh": wcp_payload})
    err = bk.place_launcher(d, ours)
    check("build-kit: an older VIETNAV stick's other-touch.sh becomes wcp-touch.sh",
          err is None and rd(d, "wcp-touch.sh") == wcp_payload and rd(d, "other-touch.sh") is None, err)

    newer = re.sub(rb"# mzd-touch-launcher: \d+", b"# mzd-touch-launcher: 99", shared)
    assert newer != shared
    d = stick({"install-patches.sh": newer})
    err = bk.place_launcher(d, ours)
    check("build-kit: a newer shared launcher is kept", err is None and rd(d, "install-patches.sh") == newer, err)

    d = stick({"install-patches.sh": wcp_payload, "wcp-touch.sh": b"something else"})
    err = bk.place_launcher(d, ours)
    check("build-kit: a clash is refused, nothing written",
          err is not None and rd(d, "install-patches.sh") == wcp_payload, err)

    v, err = bk.version()
    check("build-kit: VERSION and vietnav-install.sh agree", err is None and v == VERSION, err)
    d = scratch("vietnav-ver-")
    odd = os.path.join(d, "vietnav-install.sh")
    with open(bk.ROOT_FILES["vietnav-install.sh"], encoding="utf-8") as f:
        body = f.read()
    with open(odd, "w", encoding="utf-8", newline="\n") as f:
        f.write(body.replace('VIETNAV_VERSION="%s"' % VERSION, 'VIETNAV_VERSION="0.0.1"'))
    real = bk.ROOT_FILES["vietnav-install.sh"]
    bk.ROOT_FILES["vietnav-install.sh"] = odd
    try:
        v, err = bk.version()
    finally:
        bk.ROOT_FILES["vietnav-install.sh"] = real
    check("build-kit: a kit whose versions differ is refused", err is not None and "0.0.1" in err, err)


def host_tests():
    """The shims hook fixed places in the unit's binaries: another build of
    any of them stops the install (exit 3) before anything is changed."""
    c = Car(wcp_conf=True)
    rc, out = c.run("usb/vietnav-install.sh", "all")
    check("unit check: the checked builds pass (dry run)",
          rc == 0 and out.count("unit binary ok") == 4, out)
    for rel, target in (("usr/bin/aap_service", "aa"), ("jci/carplay/blmjcicarplay.so", "cp")):
        c = Car(wcp_conf=True)
        c.write(rel, HOSTS[rel] + b" another build")
        before = c.tree()
        rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
        check("unit check: another %s -> exit 3, nothing changed" % os.path.basename(rel),
              rc == 3 and c.tree() == before and "not checked on" in out, out)
        rc, out = c.run("usb/vietnav-install.sh", target)
        check("unit check: the dry run (%s) says so too" % target, rc == 3, out)
        other = "cp" if target == "aa" else "aa"
        rc, out = c.run("usb/vietnav-install.sh", other)
        check("unit check: the other mod (%s) still passes its own check" % other, rc == 0, out)
    c = Car(wcp_conf=True)
    os.remove(os.path.join(c.t, "usr/lib/libdevmgr_interface.so"))
    before = c.tree()
    rc, out = c.run("usb/vietnav-install.sh", "cp", "--yes")
    check("unit check: a missing libdevmgr_interface.so -> exit 3, nothing changed",
          rc == 3 and c.tree() == before and "not on this unit" in out, out)
    # the touch menu tells the driver, in both languages
    c = Car(wcp_conf=True)
    c.write("usr/bin/aap_service", b"another build")
    before = c.tree()
    c.seq(0, 2, 0, 0)                 # CAI DAT, CA HAI, CAI DAT, OK
    c.run("usb/install-patches.sh")
    time.sleep(0.3)
    log = c.stublog()
    check("unit check: touch shows KHONG HO TRO / NOT SUPPORTED, nothing changed",
          "KHONG HO TRO / NOT SUPPORTED" in log and "CAI DAT LOI" not in log and c.tree() == before, log)


def main():
    print("shell:", " ".join(SH))
    install_tests()
    oldcp_tests()
    host_tests()
    launcher_tests()
    touch_tests()
    build_kit_tests()
    check("jci-dialog: every call is one the car's binary shows in full",
          not BAD_DIALOGS, "\n".join(sorted(BAD_DIALOGS)))
    check("grep: every call is one the car's BusyBox 1.19 grep takes",
          not BAD_GREPS, "\n".join(sorted(BAD_GREPS)))
    print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)) if FAILED else "all tests passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
