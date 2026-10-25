#!/usr/bin/env python3
# Copyright (c) 2026 Dang Khoa (dangkhoa116). MIT License.
"""Read-only shared Log menu/collector against a fake CMU (Linux/WSL).

Only fixture paths are visible to scripts. Mutating commands are absolute
stubs, including when run under BusyBox ash's standalone command resolution.
"""
import io
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory(prefix="cmu-log-test-") as td:
        base = Path(td)
        usb = base / "usb"
        usb.mkdir()

        def put(name, text, executable=False):
            p = base / name.lstrip("/")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            if executable:
                p.chmod(0o755)
            return p

        def read(name):
            return (base / name).read_text()

        put("proc/uptime", "123.45 456.78\n")
        put("proc/meminfo", "MemTotal: 764068 kB\nMemFree: 30000 kB\n")
        put("proc/stat", "cpu 100 0 200 300 10 0 0 0\ncpu0 50 0 100 150 5 0 0 0\n")
        put("proc/loadavg", "1.00 2.00 3.00 1/100 123\n")
        put("proc/825/comm", "opera\n")
        put("proc/825/status", "Name:\topera\nVmRSS:\t123456 kB\nThreads:\t24\n")
        put("proc/825/stat", "825 (opera) S 1 0 0 0\n")
        put("jci/version.ini", "MAZ_CMU-150_74.00.331\n")
        put("jci/scripts/stage_wifi.sh", "#!/bin/sh\n# tpms-boot\n# speedmap-boot\n", True)
        put("jci/sm/sm.conf", '<service name="Opera" reset_board="yes"/>\n')
        put("jci/bds/bds", "stock bds\n")
        put("data/integration/developer_mode_GuiConfig.js", "// both loaders\n")
        put("data/meminfo.out", "old reset: free 22000\n")
        put("tmp/smevents.txt", "Opera stopped!\n")
        put("tmp/tpms/v3.log", "# alive state 5\npeer aa:bb:cc:dd:ee:ff\nlink key secret-key\n")
        put("tmp/tpms/data.json", '{"connected":true,"tyres":{"fl":{"p":2.5}}}\n')
        put("data_persist/tpms/log/mem.log.prev", "99 free 22000 opera 180000\n")
        put("tmp/speedmap/drive.log", "distance 12 speed 55\n")
        put("tmp/speedmap/hmi.log", "open settings\n")
        put("data_persist/speedmap/health.log", "rss 123456 free 30000\n")
        put("data_persist/speedmap/health.log.1", "previous health\n")
        put("tmp/speedmap/data.json", '{"seq":5,"lat":10.987654,"lon":106.987654,"ok":true}\n')
        put("data_persist/speedmap/update.cfg", "password=never-collect\n")
        put("data_persist/tpms/btsnoop.log", "never-collect-uart\n")
        put("var/log/running_log/log", "CPUGAUGE CPU utilization is 95%\nVIP Rebooted -- Missing Messages\n"
            "phone secret-phone CPU utilization\nSSID secret-wifi opera\n"
            "Name=plain unrelated\nMAC aa:bb:cc:dd:ee:ff opera\n")
        archive = base / "var/log/running_log/log_0000.tar.gz"
        payload = b"CPUGAUGE Memory utilization is 95%\nOut of memory: killed process opera\n"
        with tarfile.open(archive, "w:gz") as tar:
            item = tarfile.TarInfo("log")
            item.size = len(payload)
            tar.addfile(item, io.BytesIO(payload))
        put("var/log/running_log/log_0001.tar.gz", "corrupt archive\n")
        huge = base / "var/log/running_log/log_0002.tar.gz"
        with huge.open("wb") as f:
            f.truncate(8388609)
        # Bounds must preserve the recent end; unsupported arbitrary files
        # and directories are not traversed.
        put("tmp/tpms/boot.log", "x" * 600000 + "\nTAIL-END\n")
        put("tmp/tpms/v3b.log", "target outside fixture\n")
        (base / "tmp/tpms/v3b.log").unlink()
        (base / "tmp/tpms/v3b.log").symlink_to(base / "data_persist/speedmap/update.cfg")

        calls = base / "calls"
        for command, body in {
            # The car mounts the stick read-only: run() makes it so, and
            # only a rw remount of it makes it writable again.
            "mount": 'echo "mount $*" >> "$CALLS"\n'
                     'case "$*" in *rw,remount*) for L; do :; done; chmod u+w "$L" ;; esac\nexit 0',
            "killall": 'echo "killall $*" >> "$CALLS"; exit 0',
            "sync": 'exit 0',
            "dmesg": 'printf "early OOM killed opera\\nSerialNumber: secret-serial\\n"',
            "ps": 'echo "825 cmu S /jci/opera/opera"',
            "df": 'echo "fake storage"',
            "date": 'echo 19700101-000200',
        }.items():
            put("bin/" + command, "#!/bin/sh\n" + body + "\n", True)
        dialog = put("jci/tools/jci-dialog", '''#!/bin/sh
printf '%s\n' "$*" >> "$CALLS"
case "$*" in *--3-button-dialog*|*--question*)
    code=`head -n 1 "$SEQ"`; sed '1d' "$SEQ" > "$SEQ.new"; mv "$SEQ.new" "$SEQ"
    exit "${code:-255}" ;;
esac
exit 0
''', True)

        def rewrite(source):
            text = source.read_text()
            # One substitution pass: inserted fixture path is never rewritten.
            paths = ("/data_persist", "/data/", "/jci/", "/tmp/tpms", "/tmp/speedmap",
                     "/tmp/smevents.txt", "/var/log/", "/proc/")
            text = re.sub("|".join(map(re.escape, paths)), lambda m: td + m[0], text)
            text = re.sub(r'(?<![\w/.-])(mount|killall|sync|dmesg|ps|df|date)(?=\s)',
                          lambda m: str(base / "bin" / m[0]), text)
            return text

        for name in ("cmu-logs.sh", "install-patches.sh"):
            assert b"\r" not in (HERE / name).read_bytes()
            # BusyBox 1.19.2 on the car: tr does not expand "\40-\176"
            # (newer BusyBox does, so the runs below cannot catch it).
            assert not re.search(r"\btr\b[^\n]*\\[0-7]+-\\[0-7]", (HERE / name).read_text()), name
            put("usb/" + name, rewrite(HERE / name), True)
        for kit in ("tpms", "wcp", "vietnav", "other"):
            put("usb/" + kit + "-touch.sh", '#!/bin/sh\necho "payload ' + kit + '" >> "$CALLS"\n', True)

        def car_files():
            return {str(p.relative_to(base)): p.read_bytes() for p in base.rglob("*")
                    if p.is_file() and not p.is_symlink() and not str(p.relative_to(base)).startswith(("usb/", "bin/"))
                    and p.name not in ("calls", "sequence", "sequence.new")}

        before = car_files()
        env = dict(os.environ, CALLS=str(calls), SEQ=str(base / "sequence"))

        def run(choices, shell="/bin/sh"):
            put("sequence", choices)
            calls.write_text("")
            cmd = [shell, str(usb / "install-patches.sh")]
            if shell == "busybox":
                cmd.insert(1, "sh")
            usb.chmod(0o555)
            try:
                return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=45)
            finally:
                usb.chmod(0o755)

        r = run("2\n")
        assert r.returncode == 0 and not list(usb.glob("cmu-logs-*")), r
        assert "payload" not in calls.read_text()
        assert car_files() == before
        print("PASS: root HUY collects nothing and changes no car files")

        r = run("1\n", "busybox")
        assert r.returncode == 0, (r.stdout, r.stderr)
        folders = [p for p in usb.glob("cmu-logs-*") if p.is_dir()]
        assert len(folders) == 1
        out = folders[0]
        alltext = "\n".join(p.read_text() for p in out.rglob("*") if p.is_file())
        assert "payload" not in calls.read_text() and "Da luu log" in calls.read_text()
        assert car_files() == before
        for name in ("tpms/live-v3.log", "tpms/flash-mem.log.prev", "speedmap/live-drive.log",
                     "speedmap/live-hmi.log", "speedmap/health.log", "speedmap/health.log.1",
                     "incident-before.txt", "incident-after.txt", "reset-reports/meminfo.out"):
            assert (out / name).is_file(), name
        assert "123456" in (out / "incident-before.txt").read_text()
        assert re.search(r"-rwx\S* .*stage_wifi\.sh", (out / "incident-before.txt").read_text())
        assert "CPU utilization" in (out / "native/live.txt").read_text()
        assert "VIP Rebooted" in alltext and "Memory utilization" in alltext
        assert '"seq":5' in (out / "speedmap/live-data.json").read_text()
        for secret in ("secret-key", "secret-phone", "secret-wifi", "secret-serial", "never-collect",
                       "aa:bb:cc:dd:ee:ff", "10.987654", "106.987654"):
            assert secret not in alltext, secret
        assert "TAIL-END" in (out / "tpms/live-boot.log").read_text()
        assert (out / "tpms/live-boot.log").stat().st_size <= 524288
        assert "skip oversized archive" in (out / "manifest.txt").read_text()
        print("PASS: BusyBox Log collects CMU + TPMS + SpeedMap, native archives and prior RAM logs")
        print("PASS: bounds, missing/corrupt archives, symlinks, privacy; no car file changes")

        r = run("1\n")
        assert r.returncode == 0 and len([p for p in usb.glob("cmu-logs-*") if p.is_dir()]) == 2
        print("PASS: repeat collection never overwrites an existing package")

        # Four kits: install -> more -> SpeedMap -> confirm. No collector.
        r = run("0\n2\n1\n0\n")
        assert r.returncode == 0 and "payload other" in calls.read_text(), calls.read_text()
        assert "--cancel-label=SpeedMap" in calls.read_text()
        assert "KHAC" not in calls.read_text()
        assert len([p for p in usb.glob("cmu-logs-*") if p.is_dir()]) == 2
        print("PASS: SpeedMap button routes to its existing payload without collecting")

        # The first screen names what CAI DAT does: a choice with several kits,
        # the one kit itself when it is alone on the stick.
        assert "choose a kit." in calls.read_text() and "open TPMS" not in calls.read_text()
        for kit in ("wcp", "vietnav", "other"):
            (usb / (kit + "-touch.sh")).unlink()
        r = run("0\n")
        first = [c for c in calls.read_text().splitlines() if "--3-button-dialog" in c][0]
        assert r.returncode == 0 and "payload tpms" in calls.read_text(), calls.read_text()
        assert "CAI DAT = mo TPMS / open TPMS." in first and "choose a kit" not in first, first
        assert "--title=USB: TPMS " in first, first
        assert "--cancel-label=Log" in first
        for kit in ("wcp", "vietnav", "other"):
            put("usb/" + kit + "-touch.sh", '#!/bin/sh\necho "payload ' + kit + '" >> "$CALLS"\n', True)
        print("PASS: TPMS alone: the first screen says CAI DAT opens it, and it does")

        put("usb/utils-touch.sh", '#!/bin/sh\necho "payload utils" >> "$CALLS"\n', True)
        r = run("0\n2\n1\n1\n")
        assert r.returncode == 0 and "payload utils" in calls.read_text(), calls.read_text()
        assert "--cancel-label=UTILS" in calls.read_text()
        for kit in ("tpms", "wcp", "vietnav", "other"):
            (usb / (kit + "-touch.sh")).unlink()
        r = run("0\n")
        assert r.returncode == 0 and "payload utils" in calls.read_text(), calls.read_text()
        assert "CAI DAT = mo UTILS / open UTILS." in calls.read_text()
        assert "--title=USB: UTILS " in calls.read_text()
        (usb / "utils-touch.sh").unlink()
        for kit in ("tpms", "wcp", "vietnav", "other"):
            put("usb/" + kit + "-touch.sh", '#!/bin/sh\necho "payload ' + kit + '" >> "$CALLS"\n', True)
        print("PASS: five kits route to Utils; Utils alone opens directly with the correct title")

        (usb / "cmu-logs.sh").unlink()
        r = run("1\n")
        assert r.returncode == 1 and "Missing file:" in calls.read_text() and "cmu-logs.sh" in calls.read_text()
        assert "payload" not in calls.read_text()
        put("usb/cmu-logs.sh", "#!/bin/sh\nexit 1\n", True)
        r = run("1\n")
        assert r.returncode == 1 and "Collection incomplete" in calls.read_text()
        assert "Da luu log" not in calls.read_text() and "payload" not in calls.read_text()
        print("PASS: missing/failing collector reports failure and runs no kit")

        dialog.unlink()
        r = run("0\n")
        assert r.returncode == 0 and not calls.read_text()
        print("PASS: early boot without dialog runs nothing")


if __name__ == "__main__":
    main()
