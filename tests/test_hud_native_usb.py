"""Native USB integration against an isolated filesystem; no real mount/kill."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
USB = ROOT / 'native/usb'
BUSYBOX = os.environ.get('VIETNAV_TEST_BUSYBOX')
SH = [str(Path(BUSYBOX).resolve()), 'sh'] if BUSYBOX else ['/bin/sh']


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def write(path, content, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        path.unlink()
    path.write_bytes(content.encode() if isinstance(content, str) else bytes(content))
    if executable:
        path.chmod(0o755)


class FakeCMU(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vn-usb-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.usb = self.root / 'usb'
        self.d = self.root / 'data_persist/vietnav-native'
        self.bds = self.root / 'jci/bds/bds'
        self.real = self.root / 'jci/bds/bds.real'
        self.prev = self.root / 'jci/bds/bds.vietnav-prev'
        self.so = self.root / 'jci/bds/libvietnav-native.so'
        self.bts = self.root / 'data_persist/tpms/ble.bts'
        self.boot = self.root / 'proc/sys/kernel/random/boot_id'
        self.native_tmp = self.root / 'tmp/vietnav-native'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.root / 'tmp').mkdir()
        if BUSYBOX:
            binary = str(Path(BUSYBOX).resolve())
            # A standalone shell can bypass mount stubs: refuse it before any
            # installer runs. This probe only resolves a command, never runs it.
            write(self.bin / 'mount', '#!/bin/sh\nexit 0\n', True)
            resolved = subprocess.check_output(SH + ['-c', 'command -v mount'],
                                               env={**os.environ, 'PATH': str(self.bin)}, text=True).strip()
            self.assertEqual(resolved, str(self.bin / 'mount'), 'BusyBox must honor PATH stubs')
            applets = subprocess.check_output([binary, '--list'], text=True).splitlines()
            for applet in applets:
                if applet != 'mount':
                    (self.bin / applet).symlink_to(binary)
        self.original = '#!/bin/sh\nprintf "TPMS:%s\\n" "$*"\n'
        write(self.bds, self.original, True)
        self.base = md5(self.bds)
        elf = bytearray(64)
        elf[:6] = b'\x7fELF\x01\x01'
        elf[18:20] = b'\x28\x00'
        write(self.real, elf, True)
        write(self.root / 'jci/bds/libtpms-v3.so', elf)
        write(self.bts, b'BTSB' + b'\0' * 41000)
        write(self.boot, 'boot-a\n')
        write(self.root / 'jci/sm/sm.conf', 'unchanged\n')
        write(self.root / 'sys/class/gpio/Watchdog Disable/value', '0\n')
        for name in ('mount', 'sync'):
            write(self.bin / name, '#!/bin/sh\nexit 0\n', True)
        write(self.bin / 'id', '#!/bin/sh\necho 0\n', True)
        # Fault injection affects a single cp/mv, then allows transactional undo.
        for name in ('cp', 'mv'):
            utility = shlex.join([str(Path(BUSYBOX).resolve()), name]) if BUSYBOX else '/usr/bin/' + name
            # Replace applet symlinks rather than writing through to BusyBox.
            (self.bin / name).unlink(missing_ok=True)
            write(self.bin / name, '#!/bin/sh\n'
                  'for last do :; done\n'
                  'if [ "$last" = "${FAIL_TARGET:-}" ] && [ ! -f "$FAULT_DONE" ]; then\n'
                  '  : > "$FAULT_DONE"\n'
                  '  [ "${CRASH:-0}" = 1 ] || exit 44\n'
                  f'  {utility} "$@" || exit $?\n'
                  '  kill -KILL "$PPID"\n  exit 0\nfi\n'
                  f'exec {utility} "$@"\n', True)
        self.env = {**os.environ, 'PATH': str(self.bin) + ('' if BUSYBOX else ':/usr/bin:/bin'),
                    'FAULT_DONE': str(self.root / 'fault-done')}
        for name in ('native-control.sh', 'install-patches.sh'):
            write(self.usb / name, self.render((USB / name).read_text()), True)
        self.payload = self.usb / 'native-hud-payload'
        for name in ('bds-dispatch.sh', 'monitor.sh'):
            write(self.payload / name, self.render((USB / name).read_text()), True)
        write(self.payload / 'libvietnav-native.so', elf)
        self.manifest()

    def render(self, text):
        # Single pass: never recursively substitute the /tmp in our fake root.
        text = re.sub(r'(?<![\w/])/(data_persist|jci|proc|tmp|sys)(?=[/\s"\'])',
                      lambda m: str(self.root) + m[0], text)
        return text.replace('__BASE_MD5__', self.base)

    def manifest(self):
        write(self.payload / 'MANIFEST.md5', ''.join(
            f'{md5(self.payload / f)}  {f}\n'
            for f in ('bds-dispatch.sh', 'monitor.sh', 'libvietnav-native.so')))

    def control(self, *args, ok=True, env=None):
        result = subprocess.run(SH + [str(self.usb / 'native-control.sh'), *args],
                                env={**self.env, **(env or {})}, text=True, capture_output=True, timeout=10)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def install(self):
        self.control('arm', 'query', '--yes')

    def prove_query(self):
        shutil.copyfile(self.d / 'runtime.md5', self.d / 'query-ok')

    def assert_restored(self):
        self.assertEqual(self.bds.read_text(), self.original)
        self.assertFalse(self.prev.exists())
        self.assertFalse(self.so.exists())
        self.assertFalse((self.d / 'installed').exists())
        self.assertFalse((self.d / 'armed').exists())
        self.assertEqual((self.root / 'sys/class/gpio/Watchdog Disable/value').read_text(), '0\n')

    def test_roundtrip_preserves_tpms_and_keeps_logs(self):
        protected = [self.real, self.bts, self.root / 'jci/bds/libtpms-v3.so',
                     self.root / 'jci/sm/sm.conf']
        before = [p.read_bytes() for p in protected]
        self.install()
        self.assertEqual(self.prev.read_text(), self.original)
        self.assertTrue((self.d / 'armed').read_text().startswith('query '))
        self.control('collect')
        self.assertEqual(len(list((self.usb / 'native-hud-logs').iterdir())), 1)
        self.control('remove', '--yes')
        self.assert_restored()
        self.assertEqual([p.read_bytes() for p in protected], before)
        self.assertTrue((self.d / 'logs').is_dir())
        self.control('remove', '--yes')

    def test_advertise_requires_query(self):
        self.assertIn('QUERY_REQUIRED', self.control('arm', 'advertise', '--yes', ok=False))
        self.assert_restored()
        self.install()
        self.assertIn('QUERY_REQUIRED', self.control('arm', 'advertise', '--yes', ok=False))
        self.prove_query()
        self.control('arm', 'advertise', '--yes')
        self.assertTrue((self.d / 'armed').read_text().startswith('advertise '))

    def test_changed_runtime_rejects_proof(self):
        self.install()
        self.prove_query()
        with self.bts.open('ab') as out:
            out.write(b'changed')
        self.assertIn('QUERY_STALE', self.control('arm', 'advertise', '--yes', ok=False))

    def test_new_payload_cannot_reuse_old_proof_and_rolls_back(self):
        self.install()
        self.prove_query()
        before = (self.so.read_bytes(), (self.d / 'armed').read_bytes())
        with (self.payload / 'libvietnav-native.so').open('ab') as out:
            out.write(b'new version')
        self.manifest()
        self.assertIn('QUERY_STALE_PAYLOAD', self.control('arm', 'advertise', '--yes', ok=False))
        self.assertEqual((self.so.read_bytes(), (self.d / 'armed').read_bytes()), before)
        self.assertFalse((self.d / 'txn').exists())

    def test_corrupt_payload_never_installs(self):
        write(self.payload / 'monitor.sh', 'corrupted')
        self.assertIn('PAYLOAD_CORRUPT', self.control('arm', 'query', '--yes', ok=False))
        self.assert_restored()

    def test_preflight_guards(self):
        cases = [(self.bds, 'foreign wrapper', 'TPMS_WRAPPER_UNSUPPORTED'),
                 (self.real, b'bad ELF', 'NO_ORIGINAL_ARM_BDS'),
                 (self.bts, b'BTSBshort', 'SHORT_BLE_PACK'),
                 (self.bts, b'BAD!' + bytes(41000), 'NO_TPMS_BLE_PACK'),
                 (self.boot, '', 'NO_BOOT_ID')]
        for path, bad, error in cases:
            with self.subTest(error=error):
                original = path.read_bytes()
                write(path, bad)
                self.assertIn(error, self.control('arm', 'query', '--yes', ok=False))
                write(path, original)
                self.assertFalse(self.prev.exists())
        write(self.root / 'data_persist/tpms/disabled', '1')
        self.assertIn('TPMS_SWITCHED_OFF', self.control('arm', 'query', '--yes', ok=False))

    def test_symlink_refused(self):
        self.so.symlink_to(self.root / 'outside')
        self.assertIn('SYMLINK', self.control('arm', 'query', '--yes', ok=False))

    def test_foreign_wrapper_not_overwritten_on_remove(self):
        self.install()
        write(self.bds, 'foreign')
        self.assertIn('OWNED_FILES_CHANGED', self.control('remove', '--yes', ok=False))
        self.assertEqual(self.bds.read_text(), 'foreign')
        self.assertEqual(self.prev.read_text(), self.original)

    def test_remove_works_with_damaged_library_and_missing_payload(self):
        self.install()
        write(self.so, 'damaged')
        shutil.rmtree(self.payload)
        self.control('remove', '--yes')
        self.assert_restored()

    def test_install_write_failure_restores_bytes(self):
        self.assertIn('WRITE_FAILED', self.control('arm', 'query', '--yes', ok=False,
                      env={'FAIL_TARGET': str(self.bds)}))
        self.assert_restored()

    def test_power_cut_journal_recovered_before_next_action(self):
        self.control('arm', 'query', '--yes', ok=False,
                     env={'FAIL_TARGET': str(self.bds), 'CRASH': '1'})
        self.assertTrue((self.d / 'txn/prepared').exists())
        shutil.rmtree(self.root / 'tmp/vietnav-native.lock')  # volatile at reboot
        write(self.root / 'sys/class/gpio/Watchdog Disable/value', '0\n')  # GPIO reset on power-up
        write(self.boot, 'boot-b\n')
        # Undo interrupted first install; remove sees there was no prior install.
        self.control('remove', '--yes')
        self.assert_restored()

    def test_disarm_cancels_latest_query_and_same_boot_rearm_blocked(self):
        self.install()
        self.control('disarm', '--yes')
        self.assertFalse((self.d / 'armed').exists())
        self.assertFalse((self.d / 'latest-query').exists())
        (self.native_tmp / 'used').mkdir(parents=True)
        self.assertIn('RESTART_BEFORE_REARM', self.control('arm', 'query', '--yes', ok=False))

    def dispatcher_ready(self):
        self.install()
        # Host child records inherited variables; no real ARM code is executed.
        write(self.real, '#!/bin/sh\nunset LD_PRELOAD\nprintf "NATIVE:%s:%s:%s\\n" '
              '"$VIETNAV_NATIVE_MODE" "$VIETNAV_NATIVE_TRIAL_MS" "$*"\n'
              'printf "%s\\n" "$TPMS_V3_BTS" "$TPMS_LOG"\n', True)
        write(self.d / 'monitor.sh', '#!/bin/sh\nexit 0\n')
        write(self.d / 'runtime.md5', ''.join(f'{md5(p)}  {p}\n' for p in
              (self.so, self.bts, self.real, self.d / 'monitor.sh')))
        # Actual PID identity read goes through a controlled awk stub for exec.
        write(self.bin / 'awk', '#!/bin/sh\ncase "$*" in *\'/proc/\'*/stat*) echo 123 ;; '
              '*) exec /usr/bin/awk "$@" ;; esac\n', True)

    def dispatch(self):
        return subprocess.run(SH + [str(self.bds), 'arg1', 'two words'],
                              env=self.env, text=True, capture_output=True, timeout=10)

    def test_dispatcher_same_boot_tpms_then_next_boot_native_once(self):
        self.dispatcher_ready()
        first = self.dispatch()
        self.assertIn('TPMS:arg1 two words', first.stdout)
        self.assertTrue((self.d / 'armed').exists())
        write(self.boot, 'boot-b\n')
        trial = self.dispatch()
        self.assertEqual(trial.returncode, 0, trial.stderr)
        self.assertIn('NATIVE:query:180000:arg1 two words', trial.stdout)
        self.assertIn(str(self.bts), trial.stdout)
        self.assertFalse((self.d / 'armed').exists())
        self.assertIn('TPMS:', self.dispatch().stdout)
        shutil.rmtree(self.native_tmp)
        write(self.boot, 'boot-c\n')
        self.assertIn('TPMS:', self.dispatch().stdout)
        self.assertFalse((self.root / 'data_persist/tpms/bds-off').exists())

    def test_dispatcher_corruption_and_off_switch_fall_back(self):
        self.dispatcher_ready()
        write(self.boot, 'boot-b\n')
        before = self.so.read_bytes()
        write(self.so, 'corrupt')
        self.assertIn('TPMS:', self.dispatch().stdout)
        self.assertTrue((self.d / 'armed').exists())
        write(self.so, before)
        write(self.root / 'data_persist/tpms/bds-off', '1')
        self.assertIn('TPMS:', self.dispatch().stdout)
        self.assertFalse((self.native_tmp / 'used').exists())

    def test_dispatcher_invalid_token_falls_back(self):
        self.dispatcher_ready()
        write(self.boot, 'boot-b\n')
        for token in ('bad x boot-a', 'query ../escape boot-a', 'query id boot-a extra', 'query id '):
            write(self.d / 'armed', token + '\n')
            self.assertIn('TPMS:', self.dispatch().stdout)

    def monitor(self, text, latest='trial-one', mode='query', identity=True, exec_pending=False):
        pid = '99999999'  # never a real PID; kill additionally replaced in this test
        write(self.root / f'proc/{pid}/stat', ' '.join(['0'] * 21 + ['123']) + '\n')
        write(self.root / f'proc/{pid}/cmdline', str(self.real) if identity and not exec_pending else 'shell-or-foreign')
        write(self.native_tmp / 'native.log', text)
        write(self.d / 'latest-query', latest)
        write(self.d / 'logs/trial-one/runtime.md5', 'query-evidence\n')
        sleep = '#!/bin/sh\n'
        if exec_pending:
            sleep += f'echo "{self.real}" > "{self.root}/proc/{pid}/cmdline"\n'
        write(self.bin / 'sleep', sleep + 'exit 0\n', True)
        write(self.bin / 'testkill', f'#!/bin/sh\necho "$*" >> "{self.root}/killed"\n', True)
        body = self.render((USB / 'monitor.sh').read_text()).replace('kill "$PID"', 'testkill "$PID"')
        write(self.root / 'monitor.sh', body)
        result = subprocess.run(SH + [str(self.root / 'monitor.sh'), pid, '123', 'boot-a',
                                 'trial-one', mode], env=self.env, capture_output=True, text=True,
                                timeout=60 if BUSYBOX else 5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_monitor_saves_log_and_authorizes_exact_latest_query(self):
        self.monitor('VML RESULT peripheral capability present; query only\n')
        self.assertEqual((self.d / 'query-ok').read_text(), 'query-evidence\n')
        self.assertTrue((self.d / 'logs/trial-one/finished').exists())

    def test_monitor_does_not_authorize_failed_cancelled_or_advertise(self):
        for text, latest, mode in [('VML ABORT unsupported\n', 'trial-one', 'query'),
                                    ('VML RESULT peripheral capability present; query only\n', '', 'query'),
                                    ('VML RESULT peripheral capability present; query only\n', 'trial-one', 'advertise')]:
            self.monitor(text, latest, mode)
            self.assertFalse((self.d / 'query-ok').exists())

    def test_monitor_watchdog_kills_only_verified_identity(self):
        self.monitor('waiting\n')
        self.assertEqual((self.root / 'killed').read_text(), '99999999\n')
        (self.root / 'killed').unlink()
        self.monitor('waiting\n', identity=False)
        self.assertFalse((self.root / 'killed').exists())

    def test_monitor_waits_for_dispatcher_exec_before_tracking(self):
        self.monitor('VML RESULT peripheral capability present; query only\n', exec_pending=True)
        self.assertTrue((self.d / 'logs/trial-one/finished').exists())

    def menu(self, answers):
        write(self.root / 'answers', '\n'.join(map(str, answers)) + '\n')
        dialog = '#!/bin/sh\n'
        dialog += f'printf "%s\\n" "$@" >> "{self.root}/dialogs"\n'
        dialog += 'case "$*" in *--info*) exit 0 ;; esac\n'
        dialog += f'N=$(head -n 1 "{self.root}/answers")\n'
        dialog += f'tail -n +2 "{self.root}/answers" > "{self.root}/answers.new"\n'
        dialog += f'mv "{self.root}/answers.new" "{self.root}/answers"\n'
        dialog += 'exit "${N:-3}"\n'
        write(self.root / 'jci/tools/jci-dialog', dialog, True)
        result = subprocess.run(SH + [str(self.usb / 'install-patches.sh')],
                                env=self.env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in (self.root / 'dialogs').read_text().splitlines():
            if line.startswith('--text='):
                parts = line[7:].split('\\n')
                self.assertLessEqual(len(parts), 5)
                self.assertLessEqual(max(map(len, parts)), 50, parts)

    def test_menu_cancel_never_changes_system(self):
        self.menu([0, 1])
        self.assert_restored()

    def test_menu_query_then_remove(self):
        self.menu([0, 0])
        self.assertTrue((self.d / 'armed').exists())
        self.menu([2, 1, 0])
        self.assert_restored()

    def test_menu_collect_and_advertise_guard(self):
        self.menu([2, 0])
        self.assertTrue((self.usb / 'native-hud-logs').exists())
        self.menu([1, 0])
        self.assert_restored()


class KitBuilder(unittest.TestCase):
    def test_actual_artifact_packaging_and_empty_usb_guard(self):
        spec = importlib.util.spec_from_file_location('native_kit', USB / 'build_kit.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        build_dir = ROOT / 'out/native-build'
        tpms = ROOT.parent / 'mzd-connect-tpms'
        touchtune = ROOT.parent / 'tpms-build/TouchTune'
        if not all(p.exists() for p in (build_dir / 'ARM-CHECKS.json', tpms, touchtune)):
            self.skipTest('local ARM artifact/TPMS/TouchTune needed for packaging integration')
        with tempfile.TemporaryDirectory() as temp:
            dest, archive = Path(temp) / 'stick', Path(temp) / 'kit.zip'
            module.build(dest, archive, build_dir, tpms, touchtune)
            with zipfile.ZipFile(archive) as output:
                self.assertIsNone(output.testzip())
                self.assertIn('install-patches.sh', output.namelist())
                self.assertEqual(len([n for n in output.namelist() if n.endswith('.up')]), 1)
                self.assertNotIn('patches/', output.namelist())
            expected = json.loads((build_dir / 'ARM-CHECKS.json').read_text())['sha256']
            self.assertEqual(hashlib.sha256((dest / 'native-hud-payload/libvietnav-native.so').read_bytes()).hexdigest(), expected)
            self.assertNotIn('__BASE_MD5__', (dest / 'native-control.sh').read_text())
            with self.assertRaisesRegex(ValueError, 'empty'):
                module.build(dest, Path(temp) / 'other.zip', build_dir, tpms, touchtune)


if __name__ == '__main__':
    unittest.main()
