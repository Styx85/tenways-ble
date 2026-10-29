"""TenwaysBike against a fake BleakClient replaying recorded frames."""
import asyncio
from types import SimpleNamespace

import pytest
from bleak import BleakClient

from tenways_ble import (
    TenwaysBike,
    TenwaysError,
    TenwaysProtocolError,
    TenwaysTimeoutError,
    TenwaysUnsupportedError,
)
from tenways_ble.const import TENWAYS_NOTIFY_UUID, TENWAYS_WRITE_UUID

from .frames import INFO_REPLY, INFO_REQUEST, STATUS_REPLY, STATUS_REQUEST


class FakeClient(BleakClient):
    """Answers recorded requests with notifications of ``chunk`` bytes."""

    def __init__(self, replies=None, chunk=20, has_service=True):
        self.replies = {STATUS_REQUEST: STATUS_REPLY, INFO_REQUEST: INFO_REPLY} if replies is None else replies
        self.chunk = chunk
        self.writes = []
        self.connected = True
        self.notify = None
        chars = (TENWAYS_WRITE_UUID, TENWAYS_NOTIFY_UUID) if has_service else ()
        self._services = SimpleNamespace(get_characteristic=lambda uuid: uuid if uuid in chars else None)

    @property
    def is_connected(self):
        return self.connected

    @property
    def services(self):
        return self._services

    async def start_notify(self, uuid, callback, **kwargs):
        self.notify = callback

    async def stop_notify(self, uuid):
        self.notify = None

    async def write_gatt_char(self, uuid, data, response=None):
        if not self.connected:
            raise EOFError("disconnected")
        self.writes.append(bytes(data))
        reply = self.replies.get(bytes(data), b"")
        loop = asyncio.get_running_loop()
        for i in range(0, len(reply), self.chunk):
            loop.call_soon(self.notify, None, bytearray(reply[i:i + self.chunk]))


async def test_read_status_over_fragmented_notifications():
    fake = FakeClient(chunk=20)
    bike = TenwaysBike(fake)
    status = await bike.read_status()
    assert status.battery_percent == 68
    assert status.odometer_km == 120.1
    assert fake.writes == [STATUS_REQUEST]


async def test_read_device_info():
    info = await TenwaysBike(FakeClient()).read_device_info()
    assert (info.firmware, info.serial) == ("2.20.16", "YJ250319A002340")


async def test_sequential_requests_share_subscription():
    fake = FakeClient()
    bike = TenwaysBike(fake)
    await bike.read_device_info()
    await bike.read_status()
    await bike.read_status()
    assert fake.writes == [INFO_REQUEST, STATUS_REQUEST, STATUS_REQUEST]


async def test_concurrent_requests_are_serialised():
    fake = FakeClient()
    bike = TenwaysBike(fake)
    status, info = await asyncio.gather(bike.read_status(), bike.read_device_info())
    assert status.battery_percent == 68
    assert info.serial == "YJ250319A002340"


async def test_timeout_when_bike_does_not_answer():
    bike = TenwaysBike(FakeClient(replies={}), response_timeout=0.05)
    with pytest.raises(TenwaysTimeoutError):
        await bike.read_status()


async def test_corrupted_reply_is_not_accepted():
    bad = bytearray(STATUS_REPLY)
    bad[12] ^= 1
    bike = TenwaysBike(FakeClient(replies={STATUS_REQUEST: bytes(bad)}), response_timeout=0.05)
    with pytest.raises(TenwaysTimeoutError):
        await bike.read_status()


async def test_reply_for_other_command_is_ignored():
    bike = TenwaysBike(FakeClient(replies={STATUS_REQUEST: INFO_REPLY}), response_timeout=0.05)
    with pytest.raises(TenwaysTimeoutError):
        await bike.read_status()


async def test_disconnected_client_raises():
    fake = FakeClient()
    fake.connected = False
    with pytest.raises(TenwaysError, match="not connected"):
        await TenwaysBike(fake).read_status()


async def test_disconnect_during_request_fails_fast():
    bike = TenwaysBike(FakeClient(replies={}), response_timeout=5)
    task = asyncio.create_task(bike.read_status())
    await asyncio.sleep(0.01)
    bike._on_disconnect(None)
    with pytest.raises(TenwaysError, match="disconnected"):
        await asyncio.wait_for(task, 1)


async def test_device_without_king_meter_service():
    with pytest.raises(TenwaysUnsupportedError):
        await TenwaysBike(FakeClient(has_service=False)).read_status()


def test_protocol_error_is_value_error():
    assert issubclass(TenwaysProtocolError, ValueError)


class StalledWriteClient(FakeClient):
    async def write_gatt_char(self, uuid, data, response=None):
        await asyncio.sleep(3600)


async def test_stalled_write_times_out_and_releases_lock():
    bike = TenwaysBike(StalledWriteClient(), response_timeout=0.05)
    with pytest.raises(TenwaysTimeoutError):
        await bike.read_status()
    assert not bike._lock.locked()


async def test_failing_raw_callback_does_not_break_requests():
    def broken(_data):
        raise RuntimeError("listener bug")

    bike = TenwaysBike(FakeClient())
    await bike.start_raw_notifications(broken)
    assert (await bike.read_status()).battery_percent == 68


async def test_awaitable_raw_callback_is_scheduled():
    seen = []

    def callback(data):
        future = asyncio.get_running_loop().create_future()
        seen.append(bytes(data))
        future.set_result(None)
        return future

    bike = TenwaysBike(FakeClient())
    await bike.start_raw_notifications(callback)
    await bike.read_status()
    assert seen


async def test_leaving_context_stops_notifications_on_external_client():
    fake = FakeClient()
    async with TenwaysBike(fake) as bike:
        await bike.read_status()
        assert fake.notify is not None
    assert fake.notify is None
    assert fake.connected  # the caller owns the connection


async def test_stop_raw_notifications_waits_for_pending_request():
    fake = FakeClient()
    bike = TenwaysBike(fake)
    await bike.start_raw_notifications(lambda _data: None)
    status_task = asyncio.create_task(bike.read_status())
    await asyncio.sleep(0)
    await bike.stop_raw_notifications()
    assert (await status_task).battery_percent == 68
