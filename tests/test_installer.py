"""Runs the VIETNAV installer scripts against a fake CMU, and checks that they
live next to the other touch kits on this car (wireless CarPlay, TPMS).

    python tests/test_installer.py
    VIETNAV_REAL_SM=<dir with sm.conf + sm_WCP.conf> python tests/test_installer.py

Every absolute car path in the scripts is rewritten into a temp folder;
mount, smctl, id, killall, ps and jci-dialog are stubs that log. The scripts
run under BusyBox ash when BUSYBOX points at one (busybox-w32 on Windows),
otherwise under the sh in PATH. VIETNAV_REAL_SM runs the install/rollback
round trip on the car's own sm configs too (never commit those: JCI files).
"""
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
FOREIGN = '            <environ_var env_name="LD_PRELOAD" env_value="/data_persist/other-mod/libother.so"/>'

DIALOG_STUB = '''#!/bin/sh
echo "jci-dialog $*" >> "@T@/stub.log"
case "$*" in *--info*) exit 0 ;; esac
N=`head -n 1 "@T@/dialog.seq" 2>/dev/null`
tail -n +2 "@T@/dialog.seq" > "@T@/dialog.seq.new" 2>/dev/null
mv "@T@/dialog.seq.new" "@T@/dialog.seq"
exit ${N:-2}
'''
STUB = '#!/bin/sh\necho "%s $*" >> "@T@/stub.log"\n%s\n'


def rewrite(text, t):
    for a in ("/jci/", "/etc/", "/data_persist", "/tmp/", "/sys/class/gpio"):
        text = text.replace(a, "@T@" + a)
    text = text.replace("-C /tmp ", "-C @T@/tmp ")
    return text.replace("@T@", t)


def car_line(line, t):
    """One of the install's lines as it reads after the path rewrite."""
    return rewrite(line, t)


class Car:
    def __init__(self, wcp_conf=False, sm=None, smw=None):
        self.t = tempfile.mkdtemp(prefix="vietnav-car-").replace("\\", "/")
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
                self.write("usb/" + name, rewrite(f.read(), self.t).encode())
        self.stub("bin/id", "id", "echo 0")
        self.stub("bin/mount", "mount", '[ -f "@T@/mount-fails" ] && exit 1; exit 0')
        self.stub("bin/smctl", "smctl", "exit 0")
        self.stub("bin/killall", "killall", "exit 0")
        self.stub("bin/ps", "ps", 'echo "  120 root  /jci/sm/sm -f /jci/sm/sm_WCP.conf"')
        self.write("jci/tools/jci-dialog", DIALOG_STUB.replace("@T@", self.t).encode())
        os.chmod(os.path.join(self.t, "jci/tools/jci-dialog"), 0o755)

    def write(self, rel, data):
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

    def stub(self, rel, name, body):
        self.write(rel, (STUB % (name, body)).replace("@T@", self.t).encode())
        os.chmod(os.path.join(self.t, rel), 0o755)

    def run(self, script, *args):
        e = dict(os.environ)
        e["PATH"] = self.t + "/bin" + os.pathsep + e.get("PATH", "")
        p = subprocess.run(SH + [self.t + "/" + script] + list(args), capture_output=True,
                           text=True, env=e, timeout=120)
        return p.returncode, p.stdout + p.stderr

    def seq(self, *codes):
        self.write("dialog.seq", ("\n".join(str(c) for c in codes) + "\n").encode())

    def stublog(self):
        return (self.read("stub.log") or b"").decode()

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
          "chua cai" in c.stublog(), c.stublog())
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

    # --- collect: tarball on the stick, other kits named
    c = Car(wcp_conf=True)
    rc, out = c.run("usb/vietnav-collect.sh")
    tgz = [f for f in os.listdir(os.path.join(c.t, "usb")) if f.startswith("vietnav-collect-")]
    check("collect: tarball written to the stick", rc == 0 and len(tgz) == 1, out)
    if tgz:
        listing = subprocess.run(["tar", "-tzf", tgz[0]], cwd=os.path.join(c.t, "usb"),
                                 capture_output=True, text=True).stdout
        check("collect: notes the other kits", "other-kits.txt" in listing, listing)

    # --- real sm configs, when given
    real = os.environ.get("VIETNAV_REAL_SM")
    if real:
        sm0 = open(os.path.join(real, "sm.conf"), "rb").read()
        smw0 = open(os.path.join(real, "sm_WCP.conf"), "rb").read()
        c = Car(sm=sm0, smw=smw0)
        rc, out = c.run("usb/vietnav-install.sh", "all", "--yes")
        check("real confs: install", rc == 0 and under(c.conf("sm.conf"), "jciCARPLAY",
                                                       [car_line(CP_L1, c.t), car_line(CP_L2, c.t)]), out)
        rc, out = c.run("usb/vietnav-rollback.sh", "all")
        check("real confs: sm.conf back byte for byte", rc == 0 and c.read("jci/sm/sm.conf") == sm0, out)


def launcher_tests():
    def kits(c, names):
        for n in names:
            c.write("usb/%s-touch.sh" % n, ('#!/bin/sh\necho "payload %s" >> "%s/stub.log"\n' % (n, c.t)).encode())

    c = Car()
    os.remove(os.path.join(c.t, "usb/vietnav-touch.sh"))
    kits(c, ["vietnav"])
    c.seq(0)
    c.run("usb/install-patches.sh")
    check("launcher: one kit runs straight, no question",
          "payload vietnav" in c.stublog() and "jci-dialog" not in c.stublog(), c.stublog())

    c = Car()
    kits(c, ["tpms", "vietnav"])
    c.seq(1)
    c.run("usb/install-patches.sh")
    check("launcher: two kits, 2nd button runs the 2nd", "payload vietnav" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(2)
    before = c.tree()
    c.run("usb/install-patches.sh")
    check("launcher: HUY runs nothing", "payload" not in c.stublog() and c.tree() == before, c.stublog())

    c = Car()
    kits(c, ["tpms", "wcp", "vietnav"])
    c.seq(2, 0)
    c.run("usb/install-patches.sh")
    check("launcher: three kits, TIEP then the 3rd", "payload vietnav" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(1)
    c.run("usb/install-patches.sh")
    check("launcher: three kits, CARPLAY on the first screen", "payload wcp" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(2, 1, 0)
    c.run("usb/install-patches.sh")
    check("launcher: VE LAI goes back to the first screen", "payload tpms" in c.stublog(), c.stublog())
    c.write("stub.log", b"")
    c.seq(2, 2)
    c.run("usb/install-patches.sh")
    check("launcher: HUY on the second screen runs nothing", "payload" not in c.stublog(), c.stublog())

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
    c.seq(0, 2)                       # CAI DAT, CA HAI
    rc, out = c.run("usb/install-patches.sh")
    time.sleep(0.5)
    tlog = (c.read("usb/vietnav-touch.log") or b"").decode()
    check("touch: CAI DAT -> CA HAI installs both",
          under(c.conf("sm.conf"), "jciAAPA", [car_line(AA_L1, c.t)]) and
          under(c.conf("sm_WCP.conf"), "jciCARPLAY", [car_line(CP_L1, c.t), car_line(CP_L2, c.t)]),
          out + tlog)
    check("touch: log on the stick", "install: all" in tlog, tlog)
    check("touch: says done", "DA CAI (all)" in c.stublog(), c.stublog())
    c.seq(0)                          # GO BO
    c.run("usb/install-patches.sh")
    check("touch: GO BO puts sm.conf back", c.read("jci/sm/sm.conf") == sm0, c.stublog())


def build_kit_tests():
    spec = importlib.util.spec_from_file_location("build_kit", os.path.join(INST, "build-kit.py"))
    bk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bk)
    ours = os.path.join(INST, "install-patches.sh")
    wcp_payload = b"#!/bin/sh\n# install-patches.sh - Wireless CarPlay TOUCH installer payload.\nsh wcp-enable.sh\n"
    old_tpms = b"#!/bin/sh\n# install-patches.sh - the touch launcher for this stick.\nexec sh tpms-touch.sh\n"

    def stick(files):
        d = tempfile.mkdtemp(prefix="vietnav-stick-")
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

    newer = shared.replace(b"# mzd-touch-launcher: 1", b"# mzd-touch-launcher: 9")
    d = stick({"install-patches.sh": newer})
    err = bk.place_launcher(d, ours)
    check("build-kit: a newer shared launcher is kept", err is None and rd(d, "install-patches.sh") == newer, err)

    d = stick({"install-patches.sh": wcp_payload, "wcp-touch.sh": b"something else"})
    err = bk.place_launcher(d, ours)
    check("build-kit: a clash is refused, nothing written",
          err is not None and rd(d, "install-patches.sh") == wcp_payload, err)


def main():
    print("shell:", " ".join(SH))
    install_tests()
    launcher_tests()
    touch_tests()
    build_kit_tests()
    print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)) if FAILED else "all tests passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
