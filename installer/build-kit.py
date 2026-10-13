"""Builds the mzd-vietnav-hud kit for the car's USB stick (TouchTune touch install).

    python installer/build-kit.py            -> installer/dist/
    python installer/build-kit.py E:\\        -> straight onto the stick

Stick root afterwards:
    install-patches.sh  vietnav-touch.sh  vietnav-install.sh
    vietnav-rollback.sh vietnav-collect.sh VIETNAV-STEPS.txt  VIETNAV-STEPS.vi.txt
    vietnav-payload/   (libpatch .so files + libpatch.conf + AAP XMLs)
    + the TouchTune trigger (jci-autoupdate, LAUNCHER.NAME, TOUCHTUNE.ID,
      LICENSE, NOTICE, <payload>.up) copied when not on the stick yet.

Files are copied byte for byte (LF endings) and checked for CR bytes, which
BusyBox sh would choke on. Without the built .so files the kit still builds:
the touch menu then offers COLLECT only and vietnav-install.sh refuses with
its own message (same policy as the TPMS kit's optional ble.bts).
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

ROOT_FILES = {
    "install-patches.sh": os.path.join(HERE, "install-patches.sh"),
    "vietnav-touch.sh": os.path.join(HERE, "vietnav-touch.sh"),
    "vietnav-install.sh": os.path.join(HERE, "vietnav-install.sh"),
    "vietnav-rollback.sh": os.path.join(HERE, "vietnav-rollback.sh"),
    "vietnav-collect.sh": os.path.join(HERE, "vietnav-collect.sh"),
    "VIETNAV-STEPS.txt": os.path.join(HERE, "VIETNAV-STEPS.txt"),
    "VIETNAV-STEPS.vi.txt": os.path.join(HERE, "VIETNAV-STEPS.vi.txt"),
}

# The payload: the built oem-aa-mod shims + its attribute XMLs + our VN
# config. Point VIETNAV_AA_MOD at an oem-aa-mod checkout with
# mazda/build/release/ populated (make; see its docs/build.md).
AA_MOD = os.environ.get("VIETNAV_AA_MOD") or os.path.join(
    os.path.expanduser("~"), "Downloads", "mzd", "hud-dev", "oem-aa-mod")
RELEASE = os.path.join(AA_MOD, "mazda", "build", "release")
RES = os.path.join(AA_MOD, "resources")
PAYLOAD_FILES = {
    "libpatch-blmjciaapa.so": os.path.join(RELEASE, "libpatch-blmjciaapa.so"),
    "libpatch-aap_service.so": os.path.join(RELEASE, "libpatch-aap_service.so"),
    "libpatch.conf": os.path.join(HERE, "libpatch.conf.vn"),
    "aap_system_attributes.xml": os.path.join(RES, "aap_system_attributes.xml"),
    "aap_system_attributes_UCP.xml": os.path.join(RES, "aap_system_attributes_UCP.xml"),
}
# Optional (only useful with the nav SD card / hud_transport=svcnavi).
OPTIONAL_PAYLOAD = {
    "libpatch-svcjcinavi.so": os.path.join(RELEASE, "libpatch-svcjcinavi.so"),
}

# TouchTune's own trigger files (GPL-3.0, Miatafy) are not in this repo; they
# come from the wireless-CarPlay all-in-one folder, as they are.
TOUCHTUNE = os.environ.get("VIETNAV_TOUCHTUNE") or os.path.join(
    os.path.expanduser("~"), "Downloads", "mzd-wireless-carplay-v1.0.3-ALL-IN-ONE")
TOUCHTUNE_FILES = ("jci-autoupdate", "LAUNCHER.NAME", "TOUCHTUNE.ID", "LICENSE", "NOTICE")

# This launcher marks itself, so another kit's payload already on the stick
# can be told apart and kept (renamed, never overwritten).
LAUNCHER_MARK = b"the touch launcher for this stick"

BINARY_EXT = (".png", ".jpg", ".gif", ".bts", ".so")


def check(src, dst):
    if dst.endswith(BINARY_EXT):
        return None
    with open(src, "rb") as f:
        if b"\r" in f.read() and not dst.endswith((".txt", ".xml", ".conf")):
            return "%s has CR bytes - fix line endings first" % src
    return None


def copy(src, dst):
    with open(src, "rb") as f:
        data = f.read()
    # .txt and .xml are text that the car parses or shows: normalise to LF.
    if dst.endswith((".txt", ".xml", ".conf")):
        data = data.replace(b"\r\n", b"\n")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(data)


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "dist")

    payload = dict(PAYLOAD_FILES)
    missing_so = [n for n in ("libpatch-blmjciaapa.so", "libpatch-aap_service.so")
                  if not os.path.isfile(payload[n])]
    for n, src in OPTIONAL_PAYLOAD.items():
        if os.path.isfile(src):
            payload[n] = src
    payload = {n: s for n, s in payload.items() if os.path.isfile(s)}

    # Check everything first, so a bad file never leaves a half-built stick.
    errors = [e for name, src in list(ROOT_FILES.items()) + list(payload.items())
              for e in [check(src, name)] if e]
    if errors:
        sys.exit("!! " + "\n!! ".join(errors) + "\nnothing written")
    os.makedirs(dest, exist_ok=True)

    # Another kit's touch payload already on the stick keeps working: it
    # becomes other-touch.sh, which our launcher offers next to VIETNAV.
    old = os.path.join(dest, "install-patches.sh")
    if os.path.isfile(old):
        with open(old, "rb") as f:
            body = f.read()
        if LAUNCHER_MARK not in body:
            keep = os.path.join(dest, "other-touch.sh")
            if os.path.exists(keep):
                sys.exit("!! %s is not ours and %s already exists - sort the "
                         "stick out by hand; nothing written" % (old, keep))
            os.rename(old, keep)
            print("kept the other kit's touch payload as other-touch.sh")

    # TouchTune's trigger: copied when the stick does not have it yet.
    up = [f for f in os.listdir(TOUCHTUNE) if f.endswith(".up")] if os.path.isdir(TOUCHTUNE) else []
    if os.path.isdir(TOUCHTUNE) and len(up) == 1:
        # the .up file's name is a whole shell command, longer than Windows'
        # 260-character path limit allows unless the path is marked long
        def longp(p):
            p = os.path.abspath(p)
            return "\\\\?\\" + p if os.name == "nt" and not p.startswith("\\\\") else p
        for f in TOUCHTUNE_FILES + (up[0],):
            if not os.path.exists(longp(os.path.join(dest, f))):
                shutil.copyfile(longp(os.path.join(TOUCHTUNE, f)), longp(os.path.join(dest, f)))
    else:
        print("note: no TouchTune trigger at %s - the touch install will not "
              "start from this stick (the terminal one still works)" % TOUCHTUNE)

    for name, src in ROOT_FILES.items():
        copy(src, os.path.join(dest, name))

    if missing_so:
        print("note: %s not built at %s - the stick will offer COLLECT only "
              "and vietnav-install.sh will refuse. Build oem-aa-mod first "
              "(its docs/build.md) and point VIETNAV_AA_MOD at it."
              % (", ".join(missing_so), RELEASE))

    # The payload goes to vietnav-payload.new first and replaces the folder
    # only when it is whole: writing straight into a folder just deleted on
    # a FAT stick can be refused by Windows.
    kit = os.path.join(dest, "vietnav-payload")
    new = kit + ".new"
    if os.path.isdir(new):
        shutil.rmtree(new)
    for name, src in payload.items():
        copy(src, os.path.join(new, name))
    for attempt in range(10):
        try:
            if os.path.isdir(kit):
                shutil.rmtree(kit)
            os.rename(new, kit)
            break
        except OSError:
            if attempt == 9:
                raise
            time.sleep(0.5)
    print("kit written to %s (%d files + %d payload)"
          % (dest, len(ROOT_FILES), len(payload)))


if __name__ == "__main__":
    main()
