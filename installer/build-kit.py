"""Builds the mzd-vietnav-hud kit for the car's USB stick (TouchTune touch install).

    python installer/build-kit.py            -> installer/dist/
    python installer/build-kit.py E:\\        -> straight onto the stick

Stick root afterwards:
    install-patches.sh  vietnav-touch.sh  vietnav-install.sh
    vietnav-rollback.sh vietnav-collect.sh VIETNAV-STEPS.txt  VIETNAV-STEPS.vi.txt
    vietnav-payload/   (both mods' binaries + configs + PAYLOAD-SOURCES.md)
    + the TouchTune trigger (jci-autoupdate, LAUNCHER.NAME, TOUCHTUNE.ID,
      LICENSE, NOTICE, <payload>.up) copied when not on the stick yet.

Payload sources (override with env vars; defaults point at the local
checkout locations):
    VIETNAV_AA_MOD          oem-aa-mod source checkout with built .so
                            (patches/oem-aa-mod/*.patch applied first)
    VIETNAV_AA_MOD_RELEASE  extracted oem-aa-mod release dir (preferred when
                            the checkout has no build/) - upstream binaries
    VIETNAV_CP_HUD          the CarPlay bridge .so to ship (expected: the
                            ilshyma build with the km/h + VN-fold fixes)

Files are copied byte for byte (LF endings) and checked for CR bytes, which
BusyBox sh would choke on. A mod whose binaries are missing is dropped from
the kit (the touch menu then does not offer it) instead of failing the build.
"""
import hashlib
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOME = os.path.expanduser("~")

ROOT_FILES = {
    "install-patches.sh": os.path.join(HERE, "install-patches.sh"),
    "vietnav-touch.sh": os.path.join(HERE, "vietnav-touch.sh"),
    "vietnav-install.sh": os.path.join(HERE, "vietnav-install.sh"),
    "vietnav-rollback.sh": os.path.join(HERE, "vietnav-rollback.sh"),
    "vietnav-collect.sh": os.path.join(HERE, "vietnav-collect.sh"),
    "VIETNAV-STEPS.txt": os.path.join(HERE, "VIETNAV-STEPS.txt"),
    "VIETNAV-STEPS.vi.txt": os.path.join(HERE, "VIETNAV-STEPS.vi.txt"),
}

DEFAULTS = os.path.join(HOME, "Downloads", "mzd", "hud-dev")


def pick_aa_sources():
    """(dir, origin) for the oem-aa-mod binaries + resources."""
    checkout = os.environ.get("VIETNAV_AA_MOD") or os.path.join(DEFAULTS, "oem-aa-mod")
    release = os.environ.get("VIETNAV_AA_MOD_RELEASE") or os.path.join(
        DEFAULTS, "oem-aa-mod-release", "0.10.0", "oem-aa-mod-0.10.0")
    if os.path.isdir(os.path.join(checkout, "mazda", "build", "release")):
        return (os.path.join(checkout, "mazda", "build", "release"),
                os.path.join(checkout, "resources"),
                "oem-aa-mod source build (patches/oem-aa-mod applied)")
    if os.path.isdir(release):
        return (release, os.path.join(release, "resources"),
                "oem-aa-mod upstream release 0.10.0 (github releases, SHA256SUMS verified)")
    return (None, None, None)


def pick_cp_source():
    """path to the CarPlay bridge .so, or None."""
    direct = os.environ.get("VIETNAV_CP_HUD")
    if direct and os.path.isfile(direct):
        return direct
    default = os.path.join(DEFAULTS, "mazda-hud-toolkit", "files",
                           "libpatch-blmjcicarplay-splim.so")
    return default if os.path.isfile(default) else None


def payload_map():
    """name -> (src, origin) for every payload file that is available."""
    out = {}
    aa_bin, aa_res, aa_origin = pick_aa_sources()
    if aa_bin:
        for n in ("libpatch-blmjciaapa.so", "libpatch-aap_service.so",
                  "libpatch-svcjcinavi.so"):
            p = os.path.join(aa_bin, n)
            if os.path.isfile(p):
                out[n] = (p, aa_origin)
        for n in ("aap_system_attributes.xml", "aap_system_attributes_UCP.xml"):
            p = os.path.join(aa_res, n)
            if os.path.isfile(p):
                out[n] = (p, aa_origin)
    out["libpatch.conf"] = (os.path.join(HERE, "libpatch.conf.vn"),
                            "mzd-vietnav-hud (this repo)")
    cp = pick_cp_source()
    if cp:
        out["libpatch-blmjcicarplay.so"] = (
            cp, "mazda-carplay-hud (KidMixer) via mazda-hud-toolkit ilshyma build "
                "(km/h fix + VN fold), AGPL-3.0")
    return out


# TouchTune's own trigger files (GPL-3.0, Miatafy) are not in this repo; they
# come from the wireless-CarPlay all-in-one folder, as they are.
TOUCHTUNE = os.environ.get("VIETNAV_TOUCHTUNE") or os.path.join(
    HOME, "Downloads", "mzd-wireless-carplay-v1.0.3-ALL-IN-ONE")
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
    # .txt/.xml/.conf are text the car parses or shows: normalise to LF.
    if dst.endswith((".txt", ".xml", ".conf")):
        data = data.replace(b"\r\n", b"\n")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(data)


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "dist")
    payload = payload_map()

    # Check everything first, so a bad file never leaves a half-built stick.
    errors = [e for name, src in list(ROOT_FILES.items()) + [(n, s) for n, (s, _) in payload.items()]
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

    # What the menu can offer.
    have_aa = "libpatch-blmjciaapa.so" in payload and "libpatch-aap_service.so" in payload
    have_cp = "libpatch-blmjcicarplay.so" in payload
    if not have_aa:
        print("note: oem-aa-mod binaries not found (VIETNAV_AA_MOD / "
              "VIETNAV_AA_MOD_RELEASE) - the stick will NOT offer the AA mod")
    if not have_cp:
        print("note: CarPlay bridge .so not found (VIETNAV_CP_HUD) - the stick "
              "will NOT offer the CarPlay mod")
    if not have_aa and not have_cp:
        print("note: COLLECT (diagnostics) mode still works on this stick")

    # The payload goes to vietnav-payload.new first and replaces the folder
    # only when it is whole: writing straight into a folder just deleted on
    # a FAT stick can be refused by Windows.
    kit = os.path.join(dest, "vietnav-payload")
    new = kit + ".new"
    if os.path.isdir(new):
        shutil.rmtree(new)
    for name, (src, origin) in payload.items():
        copy(src, os.path.join(new, name))
    with open(os.path.join(new, "PAYLOAD-SOURCES.md"), "w", newline="\n") as f:
        f.write("# Payload provenance\n\n")
        f.write("| file | md5 | source |\n|---|---|---|\n")
        for name, (src, origin) in sorted(payload.items()):
            f.write("| %s | `%s` | %s |\n" % (name, md5(src), origin))
        f.write("\nBinaries ship as published by their upstream projects"
                " (AGPL-3.0); sources: oem-aa-mod and mazda-carplay-hud on GitHub.\n")
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
    print("kit written to %s (%d files + %d payload, AA=%s CP=%s)"
          % (dest, len(ROOT_FILES), len(payload) + 1, have_aa, have_cp))


if __name__ == "__main__":
    main()
