"""King Meter frame protocol used by the TENWAYS Longtail Duo.

Sans-I/O: this module only builds and parses bytes. Everything here was
derived from an Android HCI capture of the official TENWAYS app.

Frame layout (both directions)::

    [type][0x00][len][cmd][payload ...][crc_hi][crc_lo][0x45]

``type`` is 0x62 (read) or 0x63 (write), ``len`` counts cmd + payload, and
``crc`` is CRC-16/MODBUS over type..payload, transmitted high byte first.
A read request lists field keys; the reply carries TLV entries
``[key][size][value]`` with big-endian values.

Only read requests are built. Write commands (0x63) are parsed but never
generated.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

TYPE_READ = 0x62
TYPE_WRITE = 0x63
FRAME_TYPES = (TYPE_READ, TYPE_WRITE)
HEADER_BYTE = 0x00
END_BYTE = 0x45
OVERHEAD = 6  # type, 0x00, len, crc_hi, crc_lo, end
MAX_FRAME = 0xFF + OVERHEAD

CMD_INFO = 0x04
CMD_STATUS = 0x0B

INFO_KEYS = (0x04, 0x05, 0x4F, 0x70)
STATUS_KEYS = (0x06, 0x07, 0x08, 0x09, 0x11, 0x0A, 0x0B, 0x0C, 0x0F, 0x23, 0x4F)

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


def build_frame(frame_type: int, cmd: int, payload: bytes = b"") -> bytes:
    if frame_type not in FRAME_TYPES:
        raise ValueError(f"invalid frame type {frame_type:#04x}")
    if len(payload) + 1 > 0xFF:
        raise ValueError("payload too long")
    body = bytes((frame_type, HEADER_BYTE, len(payload) + 1, cmd)) + payload
    return body + crc16_modbus(body).to_bytes(2, "big") + bytes((END_BYTE,))


def build_read_request(cmd: int, keys: tuple[int, ...]) -> bytes:
    return build_frame(TYPE_READ, cmd, bytes(keys))


STATUS_REQUEST = build_read_request(CMD_STATUS, STATUS_KEYS)
INFO_REQUEST = build_read_request(CMD_INFO, INFO_KEYS)


@dataclass(frozen=True, slots=True)
class Frame:
    type: int
    cmd: int
    payload: bytes


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
                break
            candidate = bytes(self._buf[:total])
            if candidate[-1] != END_BYTE:
                # Wrong length byte: drop this start byte and search again.
                del self._buf[0]
                continue
            frames.append(candidate)
            del self._buf[:total]
        if len(self._buf) > self._max_buffer:
            self._buf.clear()
        return frames

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
    """Telemetry from a status reply (command 0x0B)."""

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
    """Device information reply (command 0x04)."""

    firmware: str | None
    serial: str | None
    fields: Mapping[int, bytes] = field(default_factory=dict, repr=False)


def _reply_fields(raw: bytes, cmd: int) -> dict[int, bytes]:
    frame = parse_frame(raw)
    if frame.type != TYPE_READ:
        raise TenwaysProtocolError(f"unexpected frame type {frame.type:#04x}")
    if frame.cmd != cmd:
        raise TenwaysProtocolError(f"unexpected command {frame.cmd:#04x}")
    return parse_tlv(frame.payload)


def _number(fields: Mapping[int, bytes], key: int, size: int) -> int | None:
    value = fields.get(key)
    if value is None or len(value) != size:
        return None
    return int.from_bytes(value, "big")


def decode_status(raw: bytes) -> TenwaysStatus:
    fields = _reply_fields(raw, CMD_STATUS)
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
    fields = _reply_fields(raw, CMD_INFO)
    version = fields.get(0x04)
    serial = fields.get(0x70, b"").rstrip(b"\0").decode("ascii", "replace")
    return TenwaysDeviceInfo(
        firmware=".".join(str(b) for b in version) if version and len(version) == 3 else None,
        serial=serial or None,
        fields=fields,
    )
