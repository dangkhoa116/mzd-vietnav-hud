# vmlhud_frame.py - khung gói tin VIETMAP LIVE <-> HUD roi (DJBTManager).
#
# Ban tham chieu, test duoc tren PC. Dung de dung daemon cau noi tren CMU sau
# khi da bat duoc mot phien BLE that de chot offset payload.
#
# Khung (xem docs/vietmap-hud-sdk.md), rut ra tu disassembly sendParamData:andCMD::
#
#   offset  dai  noi dung
#   0       4    magic co dinh A5 5A 37 C3
#   4       4    length = len(payload) + 13, big-endian   (hang so binary tinh ra)
#   8       4    timestamp = unix giay, big-endian
#   12      1    CMD
#   13      n    payload
#   13+n    16   MD5 cua bytes[0 : 13+n]  (magic..payload, KHONG gom md5)
#
# Chi phan khung la da xac nhan tu static analysis. Noi dung payload dan duong
# (offset tung truong) CHUA chot - phai bat phien that; xem vmlhud_nav.py.

import hashlib
import struct

MAGIC = bytes((0xA5, 0x5A, 0x37, 0xC3))
LEN_ADDEND = 13          # length field = len(payload) + 13 (quan sat tu binary)
MD5_LEN = 16
HEADER_LEN = 13          # magic(4) + len(4) + ts(4) + cmd(1)

# Cac ma lenh da thay (docs/vietmap-hud-sdk.md)
CMD_NAV = 0x00           # sendNavigationInformation...
CMD_HEARTBEAT = 0x02     # sendHeartBeat (mang toc do hien tai)
CMD_HUD_INFO = 0x0E      # getHUDInfo


class FrameError(ValueError):
    pass


def build(cmd, payload=b"", timestamp=None):
    """Dung mot khung hoan chinh, da co MD5. timestamp None -> thoi gian hien tai."""
    if not 0 <= cmd <= 0xFF:
        raise FrameError("cmd ngoai [0,255]: %r" % cmd)
    if timestamp is None:
        import time
        timestamp = int(time.time())
    length = len(payload) + LEN_ADDEND
    head = MAGIC + struct.pack(">I", length) + struct.pack(">I", timestamp & 0xFFFFFFFF)
    head += bytes((cmd,))
    body = head + payload
    return body + hashlib.md5(body).digest()


def parse(frame, verify_md5=True):
    """Tach mot khung -> dict(cmd, timestamp, payload, length). Nem FrameError neu hong."""
    if len(frame) < HEADER_LEN + MD5_LEN:
        raise FrameError("khung qua ngan: %d byte" % len(frame))
    if frame[:4] != MAGIC:
        raise FrameError("sai magic: %s" % frame[:4].hex())
    (length,) = struct.unpack(">I", frame[4:8])
    (timestamp,) = struct.unpack(">I", frame[8:12])
    cmd = frame[12]
    payload_len = length - LEN_ADDEND
    if payload_len < 0:
        raise FrameError("length %d < %d" % (length, LEN_ADDEND))
    end_payload = HEADER_LEN + payload_len
    if end_payload + MD5_LEN > len(frame):
        raise FrameError(
            "thieu byte: can %d, co %d" % (end_payload + MD5_LEN, len(frame)))
    payload = frame[HEADER_LEN:end_payload]
    got_md5 = frame[end_payload:end_payload + MD5_LEN]
    if verify_md5:
        want = hashlib.md5(frame[:end_payload]).digest()
        if got_md5 != want:
            raise FrameError("MD5 sai: %s != %s" % (got_md5.hex(), want.hex()))
    return {
        "cmd": cmd,
        "timestamp": timestamp,
        "payload": payload,
        "length": length,
        "frame_len": end_payload + MD5_LEN,
    }


def split_stream(buf):
    """Tach nhieu khung lien tiep tu mot bo dem BLE. Tra (ds_khung, phan_du)."""
    out = []
    i = 0
    n = len(buf)
    while i + HEADER_LEN + MD5_LEN <= n:
        if buf[i:i + 4] != MAGIC:
            i += 1                      # tim magic ke tiep
            continue
        (length,) = struct.unpack(">I", buf[i + 4:i + 8])
        frame_len = HEADER_LEN + (length - LEN_ADDEND) + MD5_LEN
        if length - LEN_ADDEND < 0 or i + frame_len > n:
            break                       # chua du mot khung
        try:
            out.append(parse(buf[i:i + frame_len]))
            i += frame_len
        except FrameError:
            i += 1
    return out, buf[i:]
