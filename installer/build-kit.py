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

The stick can also carry the TPMS and wireless-CarPlay touch kits:
install-patches.sh is a launcher shared by all kits (see place_launcher), and
the other kits' payloads (tpms-touch.sh, wcp-touch.sh, ...) are never touched.
"""
import hashlib
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOME = os.path.expanduser("~")

LAUNCHER = os.path.join(HERE, "install-patches.sh")
ROOT_FILES = {
    "vietnav-touch.sh": os.path.join(HERE, "vietnav-touch.sh"),
    "vietnav-install.sh": os.path.join(HERE, "vietnav-install.sh"),
    "vietnav-rollback.sh": os.path.join(HERE, "vietnav-rollback.sh"),
    "vietnav-collect.sh": os.path.join(HERE, "vietnav-collect.sh"),
    "VIETNAV-STEPS.txt": os.path.join(HERE, "VIETNAV-STEPS.txt"),
    "VIETNAV-STEPS.vi.txt": os.path.join(HERE, "VIETNAV-STEPS.vi.txt"),
}

DEFAULTS = os.path.join(HOME, "Downloads", "mzd", "hud-dev")


def sha256sums_note(d):
    """Checks the .so files in d against a SHA256SUMS file next to them (or
    one folder up), and says what was found. Never claims a check that did
    not happen."""
    for sums in (os.path.join(d, "SHA256SUMS"), os.path.join(os.path.dirname(d), "SHA256SUMS")):
        if not os.path.isfile(sums):
            continue
        want = {}
        with open(sums) as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2:
                    want[os.path.basename(parts[1].lstrip("*"))] = parts[0].lower()
        for n in os.listdir(d):
            if n.endswith(".so") and n in want:
                with open(os.path.join(d, n), "rb") as f:
                    if hashlib.sha256(f.read()).hexdigest() != want[n]:
                        sys.exit("!! %s does not match %s - nothing written" % (n, sums))
        return "SHA256SUMS checked"
    return "no SHA256SUMS found, not checked"


def patch_applied(checkout):
    h = os.path.join(checkout, "mazda", "patches", "blmjciaapa", "hud", "hud_nav16.h")
    try:
        with open(h, "rb") as f:
            return b"road[256]" in f.read()
    except OSError:
        return False


def pick_aa_sources():
    """(dir, origin) for the oem-aa-mod binaries + resources."""
    checkout = os.environ.get("VIETNAV_AA_MOD") or os.path.join(DEFAULTS, "oem-aa-mod")
    release = os.environ.get("VIETNAV_AA_MOD_RELEASE") or os.path.join(
        DEFAULTS, "oem-aa-mod-release", "0.10.0", "oem-aa-mod-0.10.0")
    if os.path.isdir(os.path.join(checkout, "mazda", "build", "release")):
        return (os.path.join(checkout, "mazda", "build", "release"),
                os.path.join(checkout, "resources"),
                "oem-aa-mod source build (%s)" % (
                    "road-budget patch applied" if patch_applied(checkout)
                    else "WITHOUT the road-budget patch"))
    if os.path.isdir(release):
        return (release, os.path.join(release, "resources"),
                "oem-aa-mod upstream release 0.10.0 (%s)" % sha256sums_note(release))
    return (None, None, None)


def pick_cp_source():
    """path to the CarPlay bridge .so, or None."""
    direct = os.environ.get("VIETNAV_CP_HUD")
    if direct and os.path.isfile(direct):
        return direct
    default = os.path.join(DEFAULTS, "mazda-hud-toolkit", "files",
                           "libpatch-blmjcicarplay-splim.so")
    return default if os.path.isfile(default) else None


AA_REQUIRED = ("libpatch-blmjciaapa.so", "libpatch-aap_service.so", "libpatch.conf",
               "aap_system_attributes.xml", "aap_system_attributes_UCP.xml")


def payload_map():
    """name -> (src, origin) for every payload file that is available."""
    out = {}
    aa_bin, aa_res, aa_origin = pick_aa_sources()
    if aa_bin:
        aa = {}
        for n in ("libpatch-blmjciaapa.so", "libpatch-aap_service.so",
                  "libpatch-svcjcinavi.so"):
            p = os.path.join(aa_bin, n)
            if os.path.isfile(p):
                aa[n] = (p, aa_origin)
        for n in ("aap_system_attributes.xml", "aap_system_attributes_UCP.xml"):
            p = os.path.join(aa_res, n)
            if os.path.isfile(p):
                aa[n] = (p, aa_origin)
        # vietnav-install.sh needs all of these; a partial set is not shipped,
        # so the touch menu never offers an AA install that would fail.
        missing = [n for n in AA_REQUIRED if n not in aa and n != "libpatch.conf"]
        if missing:
            print("note: oem-aa-mod set incomplete (%s missing) - AA not shipped"
                  % ", ".join(missing))
        else:
            out.update(aa)
    out["libpatch.conf"] = (os.path.join(HERE, "libpatch.conf.vn"),
                            "mzd-vietnav-hud (this repo)")
    cp = pick_cp_source()
    if cp:
        if os.environ.get("VIETNAV_CP_HUD"):
            # A build supplied through the env is ours (mazda-carplay-hud +
            # patches/carplay-hud), not the stock ilshyma one.
            origin = ("mazda-carplay-hud + patches/carplay-hud (this repo), "
                      "VIETNAV_CP_HUD build, AGPL-3.0")
        else:
            origin = ("mazda-carplay-hud (KidMixer) via mazda-hud-toolkit ilshyma build "
                      "(km/h fix + VN fold), AGPL-3.0")
        out["libpatch-blmjcicarplay.so"] = (cp, origin)
    return out


# TouchTune's own trigger files (GPL-3.0, Miatafy) are not in this repo; they
# come from the wireless-CarPlay all-in-one folder, as they are.
TOUCHTUNE = os.environ.get("VIETNAV_TOUCHTUNE") or os.path.join(
    HOME, "Downloads", "mzd-wireless-carplay-v1.0.3-ALL-IN-ONE")
TOUCHTUNE_FILES = ("jci-autoupdate", "LAUNCHER.NAME", "TOUCHTUNE.ID", "LICENSE", "NOTICE")

# --- the shared touch launcher ----------------------------------------------
# install-patches.sh is the same file in every kit (TPMS, VIETNAV, ...): it
# only picks one of the *-touch.sh payloads on the stick. Keep this block in
# step with the TPMS kit's build-kit.py.
SHARED_MARK = re.compile(rb"^# mzd-touch-launcher: (\d+)$", re.M)
# The first launchers (TPMS, VIETNAV) said this and knew one other kit only.
OLD_MARK = b"the touch launcher for this stick"


def launcher_version(body):
    m = SHARED_MARK.search(body)
    return int(m.group(1)) if m else None


def place_launcher(dest, ours_path):
    """Puts the shared launcher at dest/install-patches.sh without losing any
    kit's payload. Returns None, or an error string (nothing written then)."""
    with open(ours_path, "rb") as f:
        ours = f.read()
    old = os.path.join(dest, "install-patches.sh")
    plan = []                                   # renames, done only if all is well
    # An older stick of ours kept the CarPlay payload as other-touch.sh.
    other = os.path.join(dest, "other-touch.sh")
    wcp = os.path.join(dest, "wcp-touch.sh")
    if os.path.isfile(other) and not os.path.exists(wcp):
        with open(other, "rb") as f:
            if b"wcp-enable.sh" in f.read():
                plan.append((other, wcp))
    if os.path.isfile(old):
        with open(old, "rb") as f:
            body = f.read()
        v = launcher_version(body)
        if v is not None:
            if v > launcher_version(ours):
                print("note: the stick has a newer shared launcher (v%d) - kept" % v)
                ours = None
        elif OLD_MARK not in body:
            # Another kit's own payload (the CarPlay kit's, typically): keep it.
            keep = wcp if b"wcp-enable.sh" in body else other
            leaving = [src for src, _ in plan]
            if (os.path.exists(keep) and keep not in leaving) or any(dst == keep for _, dst in plan):
                return ("%s is another kit's payload and %s already exists - sort "
                        "the stick out by hand" % (old, keep))
            plan.append((old, keep))
    for src, dst in plan:
        os.rename(src, dst)
        print("kept %s as %s" % (os.path.basename(src), os.path.basename(dst)))
    if ours is not None:
        with open(old, "wb") as f:
            f.write(ours)
    return None


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


def version():
    """VERSION, and the error if vietnav-install.sh does not carry the same one."""
    with open(os.path.join(REPO, "VERSION")) as f:
        v = f.read().strip()
    with open(ROOT_FILES["vietnav-install.sh"], encoding="utf-8") as f:
        m = re.search(r'^VIETNAV_VERSION="([^"]*)"$', f.read(), re.M)
    if not re.match(r"^\d+\.\d+\.\d+$", v):
        return v, "VERSION is %r, not x.y.z" % v
    if not m or m.group(1) != v:
        return v, "vietnav-install.sh VIETNAV_VERSION is %s, VERSION is %s" % (m and m.group(1), v)
    return v, None


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "dist")
    payload = payload_map()

    # Check everything first, so a bad file never leaves a half-built stick.
    errors = [e for name, src in list(ROOT_FILES.items()) + [("install-patches.sh", LAUNCHER)]
              + [(n, s) for n, (s, _) in payload.items()]
              for e in [check(src, name)] if e]
    ver, err = version()
    if err:
        errors.append(err)
    if errors:
        sys.exit("!! " + "\n!! ".join(errors) + "\nnothing written")
    os.makedirs(dest, exist_ok=True)

    # The shared launcher goes in first: it is the only file another kit
    # might also own, and it fails before anything is written.
    err = place_launcher(dest, LAUNCHER)
    if err:
        sys.exit("!! " + err + "; nothing written")

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
    have_aa = all(n in payload for n in AA_REQUIRED)
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
            # md5 of the file as it is on the stick (text files are LF-normalised)
            f.write("| %s | `%s` | %s |\n" % (name, md5(os.path.join(new, name)), origin))
        f.write("\nThe binaries are AGPL-3.0; their sources are oem-aa-mod and"
                " mazda-carplay-hud on GitHub (plus this repo's patches/ for a"
                " patched source build).\n")
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
    print("kit %s written to %s (%d files + %d payload, AA=%s CP=%s)"
          % (ver, dest, len(ROOT_FILES) + 1, len(payload) + 1, have_aa, have_cp))


if __name__ == "__main__":
    main()
