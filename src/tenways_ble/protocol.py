"""King Meter frame protocol used by the TENWAYS Longtail Duo.

Sans-I/O: this module only builds and parses bytes. Everything here was
derived from an Android HCI capture of the official TENWAYS app.

Frame layout (both directions)::

    [type][0x00][len][count][payload ...][crc_hi][crc_lo][0x45]

``type`` is 0x62 (read) or 0x63 (write), ``len`` counts count + payload, and
``crc`` is CRC-16/MODBUS over type..payload, transmitted high byte first.
``count`` is the number of keys: a read request lists ``count`` field keys,
its reply carries ``count`` TLV entries ``[key][size][value]`` with
big-endian values, and a write carries one TLV entry (count 1). It is not a
command code: the status request is 0x0B because it asks for eleven keys.

Read requests and two writes are built: the clock sync
(:func:`build_clock_write`) and clearing the trip (:data:`CLEAR_TRIP_WRITE`).
Nothing else is ever generated.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

TYPE_READ = 0x62
TYPE_WRITE = 0x63
FRAME_TYPES = (TYPE_READ, TYPE_WRITE)
HEADER_BYTE = 0x00
END_BYTE = 0x45
OVERHEAD = 6  # type, 0x00, len, crc_hi, crc_lo, end
MAX_FRAME = 0xFF + OVERHEAD

INFO_KEYS = (0x04, 0x05, 0x4F, 0x70)
STATUS_KEYS = (0x06, 0x07, 0x08, 0x09, 0x11, 0x0A, 0x0B, 0x0C, 0x0F, 0x23, 0x4F)
WRITE_COUNT = 1  # a write sets one key

# Legacy names: the byte they name is the key count, not a command code.
CMD_INFO = len(INFO_KEYS)
CMD_STATUS = len(STATUS_KEYS)
CMD_CLOCK = WRITE_COUNT

# Fields confirmed against the TENWAYS app; a reply without them is rejected.
STATUS_REQUIRED = {0x07: 2, 0x08: 2, 0x09: 4, 0x0A: 4, 0x0C: 4, 0x0F: 1}
# Plausible or unknown fields; absent or malformed values become None.
STATUS_OPTIONAL = {0x06: 2, 0x0B: 2, 0x11: 1, 0x23: 2, 0x4F: 1}


class TenwaysProtocolError(ValueError):
    """Raised for frames that fail validation."""


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_frame(frame_type: int, count: int, payload: bytes = b"") -> bytes:
    """Frame ``payload`` (keys or TLV entries) with its key ``count``."""
    if frame_type not in FRAME_TYPES:
        raise ValueError(f"invalid frame type {frame_type:#04x}")
    if len(payload) + 1 > 0xFF:
        raise ValueError("payload too long")
    body = bytes((frame_type, HEADER_BYTE, len(payload) + 1, count)) + payload
    return body + crc16_modbus(body).to_bytes(2, "big") + bytes((END_BYTE,))


def build_read_request(keys: tuple[int, ...] | int, legacy_keys: tuple[int, ...] | None = None) -> bytes:
    """Read request for ``keys``; the count byte is ``len(keys)``.

    The old form ``build_read_request(cmd, keys)`` still works; ``cmd`` must
    then equal ``len(keys)``.
    """
    if legacy_keys is not None:
        if keys != len(legacy_keys):
            raise ValueError(f"count {keys!r} does not match {len(legacy_keys)} keys")
        keys = legacy_keys
    return build_frame(TYPE_READ, len(keys), bytes(keys))


KEY_CLOCK = 0x3C
# First byte of the clock value in the app's frame. Its meaning is unknown (it is
# not the weekday); it is sent unchanged, as captured.
CLOCK_FLAGS = 0x02


def build_clock_write(moment: datetime) -> bytes:
    """Frame that sets the bike's clock to the wall-clock fields of ``moment``.

    Layout from a capture of the TENWAYS app: flags, year-2000, month, day,
    hour, minute, second. Pass local time; the bike has no time zone or
    daylight saving of its own.
    """
    if not 2000 <= moment.year <= 2255:
        raise ValueError(f"year out of range: {moment.year}")
    value = bytes((
        CLOCK_FLAGS, moment.year - 2000, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
    ))
    return build_frame(TYPE_WRITE, WRITE_COUNT, bytes((KEY_CLOCK, len(value))) + value)


KEY_CLEAR_TRIP = 0x2D
# The app's "clear trip" write: key 0x2D, one byte 0x01. Taken from the app's
# driver for the Longtail Duo and confirmed on a Duo: trip distance, trip time,
# maximum and average speed drop to 0, the odometer stays.
CLEAR_TRIP_WRITE = build_frame(TYPE_WRITE, WRITE_COUNT, bytes((KEY_CLEAR_TRIP, 1, 0x01)))

STATUS_REQUEST = build_read_request(STATUS_KEYS)
INFO_REQUEST = build_read_request(INFO_KEYS)


@dataclass(frozen=True, slots=True)
class Frame:
    type: int
    count: int  # number of keys or TLV entries
    payload: bytes

    @property
    def cmd(self) -> int:
        """Legacy alias of :attr:`count`."""
        return self.count


def parse_frame(raw: bytes) -> Frame:
    """Validate one complete frame: header, length, CRC and end byte."""
    if len(raw) < OVERHEAD + 1:
        raise TenwaysProtocolError("frame too short")
    if raw[0] not in FRAME_TYPES:
        raise TenwaysProtocolError(f"invalid frame type {raw[0]:#04x}")
    if raw[1] != HEADER_BYTE:
        raise TenwaysProtocolError(f"invalid header byte {raw[1]:#04x}")
    if raw[2] == 0 or len(raw) != raw[2] + OVERHEAD:
        raise TenwaysProtocolError("frame length mismatch")
    if raw[-1] != END_BYTE:
        raise TenwaysProtocolError("missing end byte")
    if crc16_modbus(raw[:-3]) != int.from_bytes(raw[-3:-1], "big"):
        raise TenwaysProtocolError("CRC mismatch")
    return Frame(raw[0], raw[3], bytes(raw[4:-3]))


def parse_tlv(payload: bytes) -> dict[int, bytes]:
    fields: dict[int, bytes] = {}
    pos = 0
    while pos < len(payload):
        if pos + 2 > len(payload):
            raise TenwaysProtocolError("truncated TLV header")
        key, size = payload[pos], payload[pos + 1]
        value = payload[pos + 2:pos + 2 + size]
        if len(value) != size:
            raise TenwaysProtocolError(f"truncated TLV field {key:#04x}")
        if key in fields:
            raise TenwaysProtocolError(f"duplicate TLV field {key:#04x}")
        fields[key] = value
        pos += 2 + size
    return fields


def _crc_ok(frame: bytes) -> bool:
    try:
        parse_frame(frame)
    except TenwaysProtocolError:
        return False
    return True


class FrameAssembler:
    """Split a notification byte stream into candidate frames.

    Handles frames spread over several notifications, several frames in one
    notification and garbage between frames. Returned frames are delimited
    by their length byte only; validate them with :func:`parse_frame`.
    """

    def __init__(self, max_buffer: int = 4 * MAX_FRAME) -> None:
        self._buf = bytearray()
        self._max_buffer = max_buffer

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        frames: list[bytes] = []
        while True:
            self._resync()
            if len(self._buf) < 3:
                break
            total = self._buf[2] + OVERHEAD
            if len(self._buf) < total:
                # Still incomplete, but a false header (e.g. a bogus length byte)
                # must not hide a valid frame that already arrived behind it.
                if self._skip_to_valid_frame():
                    continue
                break
            candidate = bytes(self._buf[:total])
            if candidate[-1] != END_BYTE:
                # Wrong length byte: drop this start byte and search again.
                del self._buf[0]
                continue
            if not _crc_ok(candidate) and self._skip_to_valid_frame():
                # A false candidate that swallows a valid frame.
                continue
            frames.append(candidate)
            del self._buf[:total]
        if len(self._buf) > self._max_buffer:
            self._buf.clear()
        return frames

    def _skip_to_valid_frame(self) -> bool:
        """Drop bytes up to the next CRC-valid, complete frame inside the buffer."""
        buf = self._buf
        for i in range(1, len(buf) - 2):
            if buf[i] not in FRAME_TYPES or buf[i + 1] != HEADER_BYTE:
                continue
            total = buf[i + 2] + OVERHEAD
            if i + total <= len(buf) and buf[i + total - 1] == END_BYTE and _crc_ok(bytes(buf[i:i + total])):
                del buf[:i]
                return True
        return False

    def _resync(self) -> None:
        start = 0
        while start < len(self._buf):
            if self._buf[start] in FRAME_TYPES and (
                start + 1 >= len(self._buf) or self._buf[start + 1] == HEADER_BYTE
            ):
                break
            start += 1
        if start:
            del self._buf[:start]


@dataclass(frozen=True, slots=True)
class TenwaysStatus:
    """Telemetry from a status reply (eleven keys)."""

    battery_percent: int
    max_speed_kmh: float
    average_speed_kmh: float
    odometer_km: float
    ride_time_s: int
    trip_km: float
    # Plausible but not yet confirmed while riding.
    speed_kmh: float | None = None
    # Raw values; see the light_on, remaining_range_km and power_w properties.
    raw_0b: int | None = None
    raw_11: int | None = None
    raw_23: int | None = None
    raw_4f: int | None = None
    fields: Mapping[int, bytes] = field(default_factory=dict, repr=False)

    @property
    def light_on(self) -> bool | None:
        """Light switch (field 0x11, `lightControl` in the app); 0 = off."""
        return None if self.raw_11 is None else self.raw_11 != 0

    @property
    def remaining_range_km(self) -> int | None:
        """Remaining range (field 0x0B, `remainingRange` in the app).

        The app treats a value with a low byte >= 0x80 (such as 655 = 0x028F,
        read with assist level 0) as 0, i.e. no range; this returns None then.
        The unit is not stated in the app; km fits the observed 43-60 at 68 %.
        """
        raw = self.fields.get(0x0B)
        if self.raw_0b is None or raw is None or max(raw) >= 0x80:
            return None
        return self.raw_0b

    @property
    def power_w(self) -> int | None:
        """Power (field 0x23, `power` in the app); the app ignores values above 3000.

        Probably motor power in W; confirmed only at 0 while parked.
        """
        if self.raw_23 is None or self.raw_23 > 3000:
            return None
        return self.raw_23


@dataclass(frozen=True, slots=True)
class TenwaysDeviceInfo:
    """Device information reply (four keys)."""

    firmware: str | None
    serial: str | None
    fields: Mapping[int, bytes] = field(default_factory=dict, repr=False)


def _reply_fields(raw: bytes, count: int) -> dict[int, bytes]:
    frame = parse_frame(raw)
    if frame.type != TYPE_READ:
        raise TenwaysProtocolError(f"unexpected frame type {frame.type:#04x}")
    if frame.count != count:
        raise TenwaysProtocolError(f"unexpected key count {frame.count}, expected {count}")
    return parse_tlv(frame.payload)


def _number(fields: Mapping[int, bytes], key: int, size: int) -> int | None:
    value = fields.get(key)
    if value is None or len(value) != size:
        return None
    return int.from_bytes(value, "big")


def decode_status(raw: bytes) -> TenwaysStatus:
    fields = _reply_fields(raw, len(STATUS_KEYS))
    for key, size in STATUS_REQUIRED.items():
        if len(fields.get(key, b"")) != size:
            raise TenwaysProtocolError(f"missing or malformed status field {key:#04x}")
    req = {key: int.from_bytes(fields[key], "big") for key in STATUS_REQUIRED}
    if req[0x0F] > 100:
        raise TenwaysProtocolError(f"battery out of range: {req[0x0F]}")
    opt = {key: _number(fields, key, size) for key, size in STATUS_OPTIONAL.items()}
    return TenwaysStatus(
        battery_percent=req[0x0F],
        max_speed_kmh=req[0x07] / 10,
        average_speed_kmh=req[0x08] / 10,
        odometer_km=req[0x0C] / 10,
        ride_time_s=req[0x0A],
        trip_km=req[0x09] / 10,
        speed_kmh=opt[0x06] / 10 if opt[0x06] is not None else None,
        raw_0b=opt[0x0B],
        raw_11=opt[0x11],
        raw_23=opt[0x23],
        raw_4f=opt[0x4F],
        fields=fields,
    )


def decode_device_info(raw: bytes) -> TenwaysDeviceInfo:
    fields = _reply_fields(raw, len(INFO_KEYS))
    version = fields.get(0x04)
    serial = fields.get(0x70, b"").rstrip(b"\0").decode("ascii", "replace")
    return TenwaysDeviceInfo(
        firmware=".".join(str(b) for b in version) if version and len(version) == 3 else None,
        serial=serial or None,
        fields=fields,
    )
