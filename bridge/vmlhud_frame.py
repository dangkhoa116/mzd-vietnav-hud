"""VIETMAP HUD frames. SDK 3.4.3 uses two 4-byte MD5 sums, not a 16-byte digest.

See docs/vietmap-hud-sdk.md. The first UID is runtime state, not the serial.
Frozen vectors and cross-codec checks are in tests/test_vmlhud_bridge.py.
"""
import hashlib
import struct
import time

MAGIC = bytes.fromhex('a55a37c3')
MAGIC_LEGACY = bytes.fromhex('a55a37c5')
DEFAULT_UID = bytes.fromhex('f7fd157502da528ef0fc3139722ce9e2')
LEN_ADDEND = 13
TRAILER_LEN = 8
MD5_LEN = TRAILER_LEN  # Compatibility name: wire checksum size, not MD5 digest size.
HEADER_LEN = 13
MAX_FRAME = 65536
CMD_NAV, CMD_HEARTBEAT, CMD_HUD_INFO = 0, 2, 14


class FrameError(ValueError):
    pass


def _sum(data, uid):
    if len(uid) != 16:
        raise FrameError('UID must contain 16 bytes')
    words = struct.unpack('>4I', hashlib.md5(data + uid).digest())
    return struct.pack('>I', sum(words) & 0xffffffff)


def _crc(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc


def build(cmd, payload=b'', timestamp=None, *, uid=bytes(16), protocol='new'):
    if not 0 <= cmd <= 255:
        raise FrameError('command outside byte range')
    if timestamp is None:
        timestamp = int(time.time())
    if protocol == 'legacy':
        body = struct.pack('>IB', len(payload) + 5, cmd) + payload
        result = MAGIC_LEGACY + body + struct.pack('>H', _crc(body))
    elif protocol == 'new':
        body = MAGIC + struct.pack('>IIB', len(payload) + 13, timestamp & 0xffffffff, cmd) + payload
        result = body + _sum(body, uid) + _sum(body, DEFAULT_UID)
    else:
        raise FrameError('unknown protocol')
    if len(result) > MAX_FRAME:
        raise FrameError('frame exceeds size bound')
    return result


def parse(frame, verify_md5=True, *, uid=None):
    if len(frame) < 8 or frame[:4] not in (MAGIC, MAGIC_LEGACY):
        raise FrameError('short frame or unknown magic')
    legacy = frame[:4] == MAGIC_LEGACY
    length = int.from_bytes(frame[4:8], 'big')
    if length < (5 if legacy else 13) or len(frame) != length + (6 if legacy else 8) or len(frame) > MAX_FRAME:
        raise FrameError('frame length mismatch')
    valid_uid = None
    if legacy:
        cmd, timestamp, payload = frame[8], None, frame[9:-2]
        if verify_md5 and _crc(frame[4:-2]) != int.from_bytes(frame[-2:], 'big'):
            raise FrameError('CRC mismatch')
    else:
        cmd, timestamp, payload = frame[12], int.from_bytes(frame[8:12], 'big'), frame[13:-8]
        if verify_md5 and _sum(frame[:-8], DEFAULT_UID) != frame[-4:]:
            raise FrameError('default checksum mismatch')
        if uid is not None:
            valid_uid = _sum(frame[:-8], uid) == frame[-8:-4]
            if verify_md5 and not valid_uid:
                raise FrameError('runtime UID checksum mismatch')
    return dict(cmd=cmd, timestamp=timestamp, payload=payload, length=length,
                frame_len=len(frame), protocol='legacy' if legacy else 'new', uid_valid=valid_uid)


def split_stream(buf):
    out, i = [], 0
    while i + 4 <= len(buf):
        if buf[i:i + 4] not in (MAGIC, MAGIC_LEGACY):
            i += 1
            continue
        if i + 8 > len(buf):
            break
        legacy = buf[i:i + 4] == MAGIC_LEGACY
        length = int.from_bytes(buf[i + 4:i + 8], 'big')
        total = length + (6 if legacy else 8)
        if length < (5 if legacy else 13) or total > MAX_FRAME:
            i += 1
            continue
        if i + total > len(buf):
            break
        try:
            out.append(parse(buf[i:i + total]))
        except FrameError:
            i += 1
        else:
            i += total
    return out, buf[i:]
