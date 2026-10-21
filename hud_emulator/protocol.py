"""VIETMAP LIVE 3.4.3 HUD wire codec; see docs/hud-emulator.md for evidence.

No vehicle writes here. Runtime UID validation is optional and reported separately.
"""
from dataclasses import dataclass
import hashlib
import struct

MAGIC_NEW = bytes.fromhex('a55a37c3')
MAGIC_LEGACY = bytes.fromhex('a55a37c5')
# Public protocol constant in SDK __const, not a device serial or account token.
DEFAULT_UID = bytes.fromhex('f7fd157502da528ef0fc3139722ce9e2')
MAX_FRAME = 65536


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS, carried high byte first by this SDK."""
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc


def md5_sum(data: bytes, uid: bytes) -> bytes:
    if len(uid) != 16:
        raise ValueError('UID must be 16 bytes')
    words = struct.unpack('>4I', hashlib.md5(data + uid).digest())
    return struct.pack('>I', sum(words) & 0xffffffff)


@dataclass(frozen=True)
class Frame:
    protocol: str
    command: int
    payload: bytes
    timestamp: int | None = None
    uid_valid: bool | None = None


def encode(command: int, payload: bytes, *, protocol='new', timestamp=0,
           uid=bytes(16)) -> bytes:
    if not 0 <= command <= 255:
        raise ValueError('command outside byte range')
    if protocol == 'legacy':
        body = struct.pack('>IB', len(payload) + 5, command) + payload
        result = MAGIC_LEGACY + body + struct.pack('>H', crc16(body))
    elif protocol == 'new':
        body = MAGIC_NEW + struct.pack('>IIB', len(payload) + 13, timestamp, command) + payload
        result = body + md5_sum(body, uid) + md5_sum(body, DEFAULT_UID)
    else:
        raise ValueError('unknown protocol')
    if len(result) > MAX_FRAME:
        raise ValueError('frame too large')
    return result


def decode(raw: bytes, *, uid: bytes | None = None) -> Frame:
    if len(raw) < 11:
        raise ValueError('short frame')
    length = int.from_bytes(raw[4:8], 'big')
    if raw[:4] == MAGIC_LEGACY:
        if length < 5 or len(raw) != length + 6 or len(raw) > MAX_FRAME:
            raise ValueError('legacy length mismatch')
        if crc16(raw[4:-2]) != int.from_bytes(raw[-2:], 'big'):
            raise ValueError('CRC mismatch')
        return Frame('legacy', raw[8], raw[9:-2])
    if raw[:4] == MAGIC_NEW:
        if length < 13 or len(raw) != length + 8 or len(raw) > MAX_FRAME:
            raise ValueError('new length mismatch')
        body = raw[:-8]
        if md5_sum(body, DEFAULT_UID) != raw[-4:]:
            raise ValueError('default checksum mismatch')
        valid = None if uid is None else md5_sum(body, uid) == raw[-8:-4]
        if valid is False:
            raise ValueError('runtime UID checksum mismatch')
        return Frame('new', raw[12], raw[13:-8], int.from_bytes(raw[8:12], 'big'), valid)
    raise ValueError('unknown magic')


class StreamDecoder:
    """Reassemble BLE writes; discard corrupt frames and bound retained memory."""
    def __init__(self, *, uid=None):
        self.buffer = bytearray()
        self.uid = uid
        self.errors = 0

    def feed(self, chunk: bytes) -> list[Frame]:
        if len(chunk) > MAX_FRAME:
            self.buffer.clear()
            self.errors += 1
            return []
        self.buffer.extend(chunk)
        result = []
        while len(self.buffer) >= 4:
            magic = bytes(self.buffer[:4])
            if magic not in (MAGIC_NEW, MAGIC_LEGACY):
                del self.buffer[0]
                continue
            if len(self.buffer) < 8:
                break
            length = int.from_bytes(self.buffer[4:8], 'big')
            extra, minimum = (8, 13) if magic == MAGIC_NEW else (6, 5)
            size = length + extra
            if length < minimum or size > MAX_FRAME:
                self.errors += 1
                del self.buffer[0]
                continue
            if len(self.buffer) < size:
                break
            try:
                result.append(decode(bytes(self.buffer[:size]), uid=self.uid))
            except ValueError:
                self.errors += 1
                del self.buffer[0]
            else:
                del self.buffer[:size]
        return result


def _road(raw: bytes) -> str:
    # Legacy SDK can truncate in the middle of UTF-8; preserve that as U+FFFD.
    return raw.split(b'\0', 1)[0].decode('utf-8', errors='replace')


def event(frame: Frame) -> dict:
    p = frame.payload
    out = dict(protocol=frame.protocol, command=frame.command, timestamp=frame.timestamp,
               uid_valid=frame.uid_valid)
    if frame.command == 0:
        if frame.protocol == 'legacy':
            if len(p) != 175:
                raise ValueError('legacy navigation must be 175 bytes')
            next_road, current_road = _road(p[5:85]), _road(p[85:165])
            tail = p[165:]
        else:
            if len(p) < 17:
                raise ValueError('short navigation')
            next_len = p[5]
            current_offset = 6 + next_len
            if current_offset >= len(p):
                raise ValueError('next road length exceeds payload')
            current_len = p[current_offset]
            tail_offset = current_offset + 1 + current_len
            if tail_offset + 10 != len(p):
                raise ValueError('road lengths/tail mismatch')
            next_road = _road(p[6:current_offset])
            current_road = _road(p[current_offset + 1:tail_offset])
            tail = p[tail_offset:]
        direction = p[0]
        hours, minute, third = struct.unpack('>HBB', tail[:4])
        out.update(type='navigation', active=direction != 255, direction_raw=direction,
                   turn_distance_m=int.from_bytes(p[1:5], 'big'), next_road=next_road,
                   current_road=current_road, remaining_hours=hours,
                   remaining_minutes=minute, remaining_time_third_raw=third,
                   remaining_distance_m=int.from_bytes(tail[4:8], 'big'),
                   speed_raw=int.from_bytes(tail[8:10], 'big'))
        # The variable-format SDK writes total-minutes low byte into its third
        # time field (0x4a6c..0x4a70); do not mislabel it as seconds.
        if frame.protocol == 'legacy':
            out['remaining_seconds'] = hours * 3600 + minute * 60 + third
    elif frame.command == 1:
        if len(p) != 4:
            raise ValueError('camera payload must be 4 bytes')
        out.update(type='camera', camera_type_raw=p[0],
                   distance_m=int.from_bytes(p[1:3], 'big'), speed_limit_raw=p[3])
    elif frame.command == 2:
        if len(p) not in (1, 2):
            raise ValueError('unexpected heartbeat size')
        out.update(type='heartbeat', speed_raw=int.from_bytes(p, 'big'))
    elif frame.command == 14:
        out.update(type='hud_info_request' if p == b'\0' else 'hud_info',
                   text=p.decode('utf-8', errors='replace'))
    else:
        out.update(type='unknown', payload_hex=p.hex())
    return out
