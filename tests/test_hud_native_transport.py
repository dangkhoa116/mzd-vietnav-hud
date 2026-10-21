"""Real preload/PTY integration: fake controller + iPhone, exact bds byte check.

No radio, firmware or car writes. The generated TPMS copy is isolated in /tmp.
"""
import errno
import importlib.util
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hud_emulator.protocol import decode, encode
spec = importlib.util.spec_from_file_location('vn_prepare', ROOT / 'native/prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
TPMS = ROOT.parent / 'mzd-connect-tpms/tpms/v3/v3.c'
capture_spec = importlib.util.spec_from_file_location('vn_capture', ROOT / 'native/decode_capture.py')
capture = importlib.util.module_from_spec(capture_spec)
capture_spec.loader.exec_module(capture)


def cc(op, data=b'', status=0):
    return bytes([4, 14, 4 + len(data), 1]) + struct.pack('<H', op) + bytes([status]) + data


def acl(att, handle=0x41):
    l2 = struct.pack('<HH', len(att), 4) + att
    return b'\2' + struct.pack('<HH', handle | 0x2000, len(l2)) + l2


class NativeTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='vietnav-hci-')
        cls.build = Path(cls.work.name)
        prepare.prepare(TPMS, cls.build)
        cls.library = cls.build / 'preload-host.so'
        toolchain = os.environ.get('VIETNAV_TEST_ARM_TOOLCHAIN')
        cls.prefix = []
        compiler = 'gcc'
        if toolchain:
            toolchain = Path(toolchain).resolve()
            compiler = str(toolchain / 'bin/arm-cortexa9_neon-linux-gnueabi-gcc')
            cls.library = cls.build / 'preload-arm.so'
        existing_library = os.environ.get('VIETNAV_TEST_LIBRARY')
        if existing_library:
            cls.library = Path(existing_library).resolve()
        if toolchain:
            cls.prefix = [os.environ.get('VIETNAV_TEST_QEMU', 'qemu-arm'),
                          '-L', os.environ.get('VIETNAV_TEST_ARM_SYSROOT',
                                               str(toolchain / 'arm-cortexa9_neon-linux-gnueabi/sysroot')),
                          '-E', 'LD_PRELOAD=' + str(cls.library)]
        if not existing_library:
            subprocess.run([compiler, '-std=gnu99', '-shared', '-fPIC', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fno-builtin', '-o', str(cls.library), str(cls.build / 'v3.c'),
                            str(cls.build / 'hud_native.c'), '-ldl'], check=True)
        cls.child = cls.build / 'bds-child'
        subprocess.run([compiler, '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'tests/native_bds_child.c'), '-lrt', '-o', str(cls.child)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def simulate(self, mode, *, supported=True, refuse=False):
        with tempfile.TemporaryDirectory(prefix='vietnav-trip-') as folder:
            trip = Path(folder)
            master, slave = pty.openpty()
            serial = os.ttyname(slave)
            output, log = trip / 'bds.bin', trip / 'native.log'
            env = dict(os.environ)
            env.update(LD_PRELOAD=str(self.library), TPMS_UART=serial, TPMS_LOG=str(log),
                       TPMS_V3_ARMMS='1', TPMS_V3_QUIETMS='1', TPMS_FIFO=str(trip / 'none'),
                       VIETNAV_NATIVE_TRIAL_MS='10000')
            if mode:
                env['VIETNAV_NATIVE_MODE'] = mode
            else:
                env.pop('VIETNAV_NATIVE_MODE', None)
            if self.prefix:
                env.pop('LD_PRELOAD', None)
            process = subprocess.Popen(self.prefix + [str(self.child), serial, str(output), '3400'],
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.close(slave)
            buf = bytearray()
            golden = bytearray()
            commands, notifications, att_seen = [], bytearray(), []
            queries = [bytes.fromhex(x) for x in ('020002', '100100ffff0028',
                       '08070011000328', '120a000100')]
            request = encode(14, b'\0', timestamp=12345678)
            nav_payload = bytes.fromhex('080000012c') + b'\x04Road\x03Old' + bytes.fromhex('00010203000030390032')
            nav = encode(0, nav_payload)
            sent_phone = False
            disconnected = False

            def send(raw, *, normal=False):
                os.write(master, raw)
                if normal:
                    golden.extend(raw)

            def handle(packet):
                nonlocal sent_phone, disconnected
                if packet[0] == 1:
                    op = int.from_bytes(packet[1:3], 'little')
                    commands.append(op)
                    if op == 0x0c1a:
                        send(cc(op), normal=True)
                        # Real bds data interleaved with our HCI traffic.
                        send(bytes.fromhex('04ff03010203') * 20 + acl(b'private classic', 0x42)
                             + bytes.fromhex('03010002aabb'), normal=True)
                    elif op == 0x1002:
                        bits = bytearray(64)
                        for bit in (205, 207, 208, 209):
                            bits[bit // 8] |= 1 << (bit % 8)
                        send(cc(op, bytes(bits)))
                    elif op == 0x1004:
                        send(cc(op, bytes.fromhex('01010300000000000000')))
                    elif op == 0x2002:
                        send(cc(op, bytes.fromhex('1b000f')))
                    elif op == 0x2003:
                        send(cc(op, bytes(8)))
                    elif op == 0x201c:
                        send(cc(op, bytes.fromhex('ff0f000000000000') if supported else bytes(8)))
                    elif op == 0x2006 and refuse:
                        send(cc(op, status=0x11))
                    elif op == 0x0406:
                        send(bytes.fromhex('040f0400010604'))
                        send(bytes.fromhex('04050400410013'))
                    else:
                        send(cc(op))
                        if op == 0x200a and packet[-1] == 1:
                            # LE Connection Complete, role peripheral, no address in logs.
                            send(bytes.fromhex('043e1301004100010001020304050650000000f40100'))
                            sent_phone = True
                            send(acl(queries.pop(0)))
                elif packet[0] == 2:
                    att = packet[9:]
                    att_seen.append(att)
                    # One completion is ours, one is bds's. Only bds's survives.
                    send(bytes.fromhex('041309024100010042000200'))
                    golden.extend(bytes.fromhex('0413050142000200'))
                    if att[0] == 0x1b:
                        notifications.extend(att[3:])
                        if len(notifications) >= 8:
                            length = int.from_bytes(notifications[4:8], 'big') + 8
                            if len(notifications) == length:
                                for off in range(0, len(nav), 20):
                                    send(acl(b'\x52\x0c\0' + nav[off:off + 20]))
                                send(bytes.fromhex('04050400410013'))
                                disconnected = True
                    elif queries:
                        send(acl(queries.pop(0)))
                    elif att[0] == 0x13:
                        for off in range(0, len(request), 20):
                            send(acl(b'\x52\x0c\0' + request[off:off + 20]))

            try:
                deadline = time.monotonic() + 6
                while process.poll() is None and time.monotonic() < deadline:
                    ready, _, _ = select.select([master], [], [], 0.1)
                    if not ready:
                        continue
                    try:
                        data = os.read(master, 4096)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            time.sleep(0.001)
                            continue
                        raise
                    buf.extend(data)
                    while len(buf) >= 4:
                        self.assertIn(buf[0], (1, 2), bytes(buf).hex())
                        size = 4 + buf[3] if buf[0] == 1 else (5 + int.from_bytes(buf[3:5], 'little') if len(buf) >= 5 else 99999)
                        if len(buf) < size:
                            break
                        packet = bytes(buf[:size]); del buf[:size]
                        handle(packet)
                stdout, stderr = process.communicate(timeout=2)
                self.assertEqual(process.returncode, 0, stderr.decode())
                self.assertEqual(output.read_bytes(), bytes(golden), 'bds stream changed')
                self.assertFalse(stdout)
                self.assertFalse(stderr, stderr.decode())
                text = log.read_text()
                self.assertNotIn('private classic', text)
                self.assertNotIn(b'private classic'.hex(' '), text)
                return commands, notifications, text, sent_phone, disconnected
            finally:
                if process.poll() is None:
                    process.kill(); process.communicate()
                os.close(master)

    def test_full_preload_to_advertising_gatt_and_info_reply(self):
        ops, data, log, phone, down = self.simulate('advertise')
        self.assertTrue(phone)
        self.assertTrue(down)
        self.assertIn(0x2006, ops)
        self.assertNotIn(0x200c, ops)  # no TPMS scanner in this mode
        self.assertNotIn(0x200d, ops)  # no TPMS central connection
        self.assertEqual(decode(bytes(data), uid=bytes(16)).payload,
                         b'MODEL:VIETNAV,HW:0,FW:0,PROTOCOL:2.0')
        self.assertIn('VML FRAME CMD 00', log)
        self.assertIn('VML disconnected', log)
        records = list(capture.records(log.splitlines()))
        nav = next(record for record in records if record['type'] == 'navigation')
        self.assertEqual((nav['next_road'], nav['turn_distance_m']), ('Road', 300))
        self.assertTrue(nav['session_seen'])

    def test_query_and_unsupported_never_advertise(self):
        for mode, supported in (('query', True), ('advertise', False)):
            ops, _, log, phone, _ = self.simulate(mode, supported=supported)
            self.assertIn(0x201c, ops)
            self.assertNotIn(0x2006, ops)
            self.assertNotIn(0x200a, ops)
            self.assertFalse(phone)
            self.assertIn('VML RESULT', log)

    def test_controller_rejection_does_not_enable_advertising(self):
        ops, _, log, _, _ = self.simulate('advertise', refuse=True)
        self.assertIn(0x2006, ops)
        self.assertNotIn(0x200a, ops)
        self.assertIn('rejected advertising command', log)

    def test_unset_mode_is_inert(self):
        ops, _, _, _, _ = self.simulate(None)
        self.assertEqual(ops, [0x0c1a])

    def test_changed_tpms_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'bad.c'
            src.write_bytes(TPMS.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'reviewed revision'):
                prepare.prepare(src, Path(folder) / 'out')


if __name__ == '__main__':
    unittest.main()
