import pytest

from tenways_ble import protocol
from tenways_ble.protocol import (
    FrameAssembler,
    TenwaysProtocolError,
    build_frame,
    crc16_modbus,
    decode_device_info,
    decode_status,
    parse_frame,
)

from .frames import CLOCK_REPLY, CLOCK_WRITE, INFO_REPLY, INFO_REQUEST, STATUS_REPLY, STATUS_REQUEST


def reframe(frame_type: int, cmd: int, payload: bytes) -> bytes:
    """Build a frame with a correct CRC around a modified payload."""
    return build_frame(frame_type, cmd, payload)


def test_status_request_matches_capture():
    assert protocol.STATUS_REQUEST == STATUS_REQUEST


def test_info_request_matches_capture():
    assert protocol.INFO_REQUEST == INFO_REQUEST


def test_request_crc():
    assert crc16_modbus(STATUS_REQUEST[:-3]) == 0x8491


def test_reply_crc():
    assert crc16_modbus(STATUS_REPLY[:-3]) == 0x83D3


@pytest.mark.parametrize("frame", [STATUS_REQUEST, STATUS_REPLY, INFO_REQUEST, INFO_REPLY, CLOCK_WRITE, CLOCK_REPLY])
def test_all_recorded_frames_validate(frame):
    parse_frame(frame)


def test_status_reply_decodes():
    status = decode_status(STATUS_REPLY)
    assert status.battery_percent == 68
    assert status.odometer_km == 120.1
    assert status.trip_km == 120.1
    assert status.max_speed_kmh == 44.7
    assert status.average_speed_kmh == 12.6
    assert status.ride_time_s == 34116
    assert status.speed_kmh == 0.0
    assert (status.raw_0b, status.raw_11, status.raw_23, status.raw_4f) == (655, 0, 0, 1)


def test_info_reply_decodes():
    info = decode_device_info(INFO_REPLY)
    assert info.firmware == "2.20.16"
    assert info.serial == "YJ250319A002340"


def test_corrupted_byte_fails_crc():
    bad = bytearray(STATUS_REPLY)
    bad[12] ^= 1
    with pytest.raises(TenwaysProtocolError, match="CRC"):
        decode_status(bytes(bad))


def test_truncated_frame_rejected():
    with pytest.raises(TenwaysProtocolError):
        decode_status(STATUS_REPLY[:-4] + b"\x45")


def test_wrong_type_rejected():
    bad = bytearray(STATUS_REPLY)
    bad[0] = 0x30
    with pytest.raises(TenwaysProtocolError, match="type"):
        parse_frame(bytes(bad))


def test_write_type_not_accepted_as_status():
    frame = reframe(protocol.TYPE_WRITE, protocol.CMD_STATUS, parse_frame(STATUS_REPLY).payload)
    with pytest.raises(TenwaysProtocolError, match="type"):
        decode_status(frame)


def test_wrong_header_byte_rejected():
    bad = bytearray(STATUS_REPLY)
    bad[1] = 0x01
    with pytest.raises(TenwaysProtocolError, match="header"):
        parse_frame(bytes(bad))


def test_wrong_length_rejected():
    bad = bytearray(STATUS_REPLY)
    bad[2] -= 1
    with pytest.raises(TenwaysProtocolError, match="length"):
        parse_frame(bytes(bad))


def test_missing_end_byte_rejected():
    with pytest.raises(TenwaysProtocolError, match="end"):
        parse_frame(STATUS_REPLY[:-1] + b"\x00")


def test_duplicate_tlv_rejected():
    payload = parse_frame(STATUS_REPLY).payload + bytes.fromhex("0f 01 44")
    with pytest.raises(TenwaysProtocolError, match="duplicate"):
        decode_status(reframe(protocol.TYPE_READ, protocol.CMD_STATUS, payload))


def test_truncated_tlv_rejected():
    payload = parse_frame(STATUS_REPLY).payload + bytes.fromhex("23 04 00")
    with pytest.raises(TenwaysProtocolError, match="truncated"):
        decode_status(reframe(protocol.TYPE_READ, protocol.CMD_STATUS, payload))


def test_wrong_command_rejected():
    with pytest.raises(TenwaysProtocolError, match="command"):
        decode_status(INFO_REPLY)


def test_missing_required_field_rejected():
    payload = parse_frame(STATUS_REPLY).payload.replace(bytes.fromhex("0f 01 44"), b"")
    with pytest.raises(TenwaysProtocolError, match="0x0f"):
        decode_status(reframe(protocol.TYPE_READ, protocol.CMD_STATUS, payload))


def test_malformed_required_field_rejected():
    payload = parse_frame(STATUS_REPLY).payload.replace(bytes.fromhex("0f 01 44"), bytes.fromhex("0f 02 00 44"))
    with pytest.raises(TenwaysProtocolError, match="0x0f"):
        decode_status(reframe(protocol.TYPE_READ, protocol.CMD_STATUS, payload))


def test_battery_out_of_range_rejected():
    payload = parse_frame(STATUS_REPLY).payload.replace(bytes.fromhex("0f 01 44"), bytes.fromhex("0f 01 65"))
    with pytest.raises(TenwaysProtocolError, match="battery"):
        decode_status(reframe(protocol.TYPE_READ, protocol.CMD_STATUS, payload))


def test_missing_optional_fields_keep_required_values():
    payload = parse_frame(STATUS_REPLY).payload
    for chunk in ("06 02 00 00", "0b 02 02 8f", "11 01 00", "23 02 00 00", "4f 01 01"):
        payload = payload.replace(bytes.fromhex(chunk), b"")
    status = decode_status(reframe(protocol.TYPE_READ, protocol.CMD_STATUS, payload))
    assert status.battery_percent == 68
    assert status.odometer_km == 120.1
    assert status.speed_kmh is None
    assert status.raw_0b is None


def test_malformed_optional_field_becomes_none():
    payload = parse_frame(STATUS_REPLY).payload.replace(bytes.fromhex("0b 02 02 8f"), bytes.fromhex("0b 01 02"))
    status = decode_status(reframe(protocol.TYPE_READ, protocol.CMD_STATUS, payload))
    assert status.raw_0b is None
    assert status.battery_percent == 68


def test_assembler_single_frame():
    assert FrameAssembler().feed(STATUS_REPLY) == [STATUS_REPLY]


@pytest.mark.parametrize("size", [1, 7, 20])
def test_assembler_fragmented_frame(size):
    assembler = FrameAssembler()
    out = []
    for i in range(0, len(STATUS_REPLY), size):
        out += assembler.feed(STATUS_REPLY[i:i + size])
    assert out == [STATUS_REPLY]


def test_assembler_multiple_frames_in_one_chunk():
    assert FrameAssembler().feed(INFO_REPLY + STATUS_REPLY + CLOCK_REPLY) == [INFO_REPLY, STATUS_REPLY, CLOCK_REPLY]


def test_assembler_partial_then_rest_with_next_frame():
    assembler = FrameAssembler()
    assert assembler.feed(STATUS_REPLY[:30]) == []
    assert assembler.feed(STATUS_REPLY[30:] + INFO_REPLY[:10]) == [STATUS_REPLY]
    assert assembler.feed(INFO_REPLY[10:]) == [INFO_REPLY]


def test_assembler_resyncs_after_garbage():
    assembler = FrameAssembler()
    assert assembler.feed(b"\x00\xff\x45" + STATUS_REPLY[20:40] + STATUS_REPLY) == [STATUS_REPLY]


def test_assembler_recovers_from_bad_length_byte():
    bad = bytearray(STATUS_REPLY)
    bad[2] = 0x05
    assert FrameAssembler().feed(bytes(bad) + INFO_REPLY) == [INFO_REPLY]


def test_assembler_buffer_is_bounded():
    assembler = FrameAssembler(max_buffer=64)
    assembler.feed(b"\x62\x00\xff" + b"\x00" * 100)
    assert assembler.feed(STATUS_REPLY) == [STATUS_REPLY]


def test_build_frame_refuses_unknown_type():
    with pytest.raises(ValueError):
        build_frame(0x30, protocol.CMD_STATUS)
