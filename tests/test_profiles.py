"""Model profiles: driver choice by name, CRC order and per-model decoding.

Only the Longtail Duo frames are captured. The frames for other models here are
built by the library itself from the TENWAYS app's request key lists; they test
the code paths, not real bikes.
"""
import pytest

from tenways_ble import TenwaysBike, TenwaysUnsupportedError, profile_for
from tenways_ble.profiles import AGO, AGO_AIR, CGO009, CGO009_D, CGO600, CGO600_D, CGO800, DM, HELMET, LONGTAIL_DUO
from tenways_ble.protocol import (
    CLEAR_TRIP_WRITE,
    STATUS_REQUEST,
    TYPE_READ,
    TYPE_WRITE,
    build_clear_trip_write,
    build_frame,
    build_read_request,
    decode_device_info,
    decode_status,
    parse_frame,
)

from .test_client import FakeClient


@pytest.mark.parametrize(("name", "profile"), [
    ("Longtail Duo", LONGTAIL_DUO),
    ("Longtail Duo_D", LONGTAIL_DUO),
    ("CGO009_D", CGO009_D),
    ("CGO009", CGO009),
    ("CGO009L", AGO),  # the app's default driver
    ("CGO800", CGO800),
    ("CGO800 Plus", CGO800),
    ("CGO800S", CGO800),
    ("AGO", AGO),
    ("AGOX", AGO),
    ("AGOT", AGO),
    ("CARGO", AGO),
    ("something else", AGO),
    (None, AGO),
    ("AGO AIR", AGO_AIR),
    ("Wayfarer_B", AGO_AIR),
    ("AGOX_D", AGO_AIR),
    ("AGOT_D", AGO_AIR),
    ("CGO COMPACT_D", AGO_AIR),
    ("CGO600", CGO600),
    ("CGO600 Pro", CGO600),
    ("CGO600_D", CGO600_D),
    ("DM 123", DM),
    ("TW smart-helmet-01", HELMET),
])
def test_profile_for_follows_the_app(name, profile):
    assert profile_for(name) is profile


def test_only_king_meter_profiles_are_supported():
    for profile in (LONGTAIL_DUO, CGO009_D, CGO009, CGO800, AGO):
        assert profile.supported and profile.status_keys
    for profile in (AGO_AIR, CGO600, CGO600_D, DM, HELMET):
        assert not profile.supported and profile.reason
    assert [p for p in (LONGTAIL_DUO, CGO009_D, CGO009, CGO800, AGO) if p.tested] == [LONGTAIL_DUO]


def test_crc_low_first_frames():
    high = build_read_request(LONGTAIL_DUO.status_keys)
    low = build_read_request(LONGTAIL_DUO.status_keys, crc_low_first=True)
    assert high == STATUS_REQUEST
    assert low[:-3] == high[:-3] and low[-3:-1] == high[-3:-1][::-1]
    # Both orders parse.
    assert parse_frame(low) == parse_frame(high)
    assert build_clear_trip_write() == CLEAR_TRIP_WRITE
    assert build_clear_trip_write(crc_low_first=True)[-3:-1] == CLEAR_TRIP_WRITE[-3:-1][::-1]


def _reply(profile, values, crc_low_first=False):
    payload = b"".join(bytes((key, len(value))) + value for key, value in values.items())
    return build_frame(TYPE_READ, len(profile.status_keys), payload, crc_low_first=crc_low_first)


def test_cgo800_status_whole_km_and_low_crc():
    values = {
        0x05: b"SN1", 0x06: b"\x00\x00", 0x07: b"\x01\x2c", 0x08: b"\x00\x96",
        0x09: b"\x00\x00\x00\x64", 0x0A: b"\x00\x00\x0e\x10", 0x0B: b"\x00\x28",
        0x0C: b"\x00\x00\x04\xd2", 0x0F: b"\x50", 0x11: b"\x01", 0x23: b"\x00\x00",
    }
    status = decode_status(_reply(CGO800, values, crc_low_first=True), CGO800)
    assert status.odometer_km == 1234.0  # whole km on the CGO800
    assert (status.trip_km, status.ride_time_s, status.max_speed_kmh) == (10.0, 3600, 30.0)
    assert status.battery_percent == 80 and status.light_on is True


def test_cgo009_assist_level_and_lenient_sizes():
    values = {
        0x06: b"\x00\x00", 0x07: b"\x00\xc8", 0x08: b"\x00\x64", 0x09: b"\x00\x0a",  # trip in 2 bytes
        0x11: b"\x00", 0x12: b"\x03", 0x0A: b"\x00\x00\x00\x3c", 0x0B: b"\x00\x1e",
        0x0C: b"\x00\x00\x01\x00", 0x0F: b"\x40", 0x23: b"\x00\x00", 0x4F: b"\x01", 0x50: b"\x00",
    }
    status = decode_status(_reply(CGO009, values), CGO009)
    assert (status.trip_km, status.odometer_km, status.raw_12) == (1.0, 25.6, 3)


def test_device_info_per_model():
    cgo800 = build_frame(TYPE_READ, 2, b"\x04\x05" + b"1.4.0" + b"\x05\x03SN8", crc_low_first=True)
    info = decode_device_info(cgo800, CGO800)
    assert (info.firmware, info.serial) == ("1.4.0", "SN8")
    ago = build_frame(TYPE_READ, 2, b"\x04\x03\x01\x02\x03" + b"\x05\x03SN1")
    assert (decode_device_info(ago, AGO).firmware, decode_device_info(ago, AGO).serial) == ("1.2.3", "SN1")


class RecordingClient(FakeClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.responses = []

    async def write_gatt_char(self, uuid, data, response=None):
        self.responses.append(response)
        await super().write_gatt_char(uuid, data, response)


async def test_cgo800_bike_sends_low_crc_requests():
    values = {
        0x05: b"SN1", 0x06: b"\x00\x00", 0x07: b"\x00\x00", 0x08: b"\x00\x00",
        0x09: b"\x00\x00\x00\x00", 0x0A: b"\x00\x00\x00\x00", 0x0B: b"\x00\x00",
        0x0C: b"\x00\x00\x00\x07", 0x0F: b"\x32", 0x11: b"\x00", 0x23: b"\x00\x00",
    }
    request = build_read_request(CGO800.status_keys, crc_low_first=True)
    fake = RecordingClient(replies={request: _reply(CGO800, values, crc_low_first=True)})
    status = await TenwaysBike(fake, name="CGO800 Plus").read_status()
    assert fake.writes == [request] and status.odometer_km == 7.0
    assert fake.responses == [False]


async def test_names_ending_in_d_write_with_response():
    fake = RecordingClient(replies={})
    bike = TenwaysBike(fake, name="CGO009_D", response_timeout=0.05)
    with pytest.raises(TimeoutError):
        await bike.reset_trip()
    assert fake.responses == [True]
    fake = RecordingClient(replies={})
    with pytest.raises(TimeoutError):
        await TenwaysBike(fake, response_timeout=0.05).reset_trip()
    assert fake.responses == [False]  # the Longtail Duo, as captured


async def test_unsupported_model_sends_nothing():
    fake = RecordingClient()
    bike = TenwaysBike(fake, name="AGO AIR")
    with pytest.raises(TenwaysUnsupportedError, match="encrypted"):
        await bike.read_status()
    with pytest.raises(TenwaysUnsupportedError):
        await bike.reset_trip(wait_for_reply=False)
    assert fake.writes == []


def test_default_is_the_longtail_duo():
    assert TenwaysBike("E8:88:6C:31:B3:0D").profile is LONGTAIL_DUO
    assert TYPE_WRITE == CLEAR_TRIP_WRITE[0]
