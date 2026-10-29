from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import inspect
import logging
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .const import (
    BATTERY_LEVEL_UUID,
    TENWAYS_NAME_PREFIXES,
    TENWAYS_NOTIFY_UUID,
    TENWAYS_SERVICE_UUID,
    TENWAYS_WRITE_UUID,
)
from .models import TenwaysAdvertisement, TenwaysInfo
from .protocol import (
    CMD_INFO,
    CMD_STATUS,
    INFO_REQUEST,
    STATUS_REQUEST,
    TYPE_READ,
    FrameAssembler,
    TenwaysDeviceInfo,
    TenwaysProtocolError,
    TenwaysStatus,
    decode_device_info,
    decode_status,
    parse_frame,
)

_LOGGER = logging.getLogger(__name__)

NotificationCallback = Callable[[bytes], None | Awaitable[None]]


class TenwaysError(RuntimeError):
    """Base exception for tenways-ble."""


class TenwaysBatteryError(TenwaysError):
    """Raised when the standard battery value cannot be decoded."""


class TenwaysTimeoutError(TenwaysError, TimeoutError):
    """Raised when the bike does not answer a request in time."""


class TenwaysUnsupportedError(TenwaysError):
    """Raised when the device lacks the King Meter service."""


def _looks_like_tenways(device: BLEDevice, adv: AdvertisementData | None) -> bool:
    names = [device.name]
    if adv is not None:
        names.append(adv.local_name)
        if TENWAYS_SERVICE_UUID in (adv.service_uuids or []):
            return True
    return any(
        name and name.lower().startswith(TENWAYS_NAME_PREFIXES) for name in names
    )


async def scan_tenways(timeout: float = 5.0) -> list[TenwaysAdvertisement]:
    """Scan for nearby devices whose advertisement looks like TENWAYS."""

    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    result: list[TenwaysAdvertisement] = []

    for _key, value in found.items():
        device, adv = value
        if not _looks_like_tenways(device, adv):
            continue
        result.append(
            TenwaysAdvertisement(
                address=device.address,
                name=adv.local_name or device.name,
                rssi=adv.rssi,
            )
        )

    return sorted(result, key=lambda item: item.rssi if item.rssi is not None else -999, reverse=True)


class TenwaysBike:
    """BLE client for a TENWAYS bicycle.

    Pass an address or ``BLEDevice`` to let this class manage the connection,
    or an already connected ``BleakClient`` (e.g. from bleak-retry-connector)
    to only speak the protocol over it; the caller then owns the connection.

    Only read requests are sent. Write commands are not implemented.
    """

    def __init__(
        self,
        address_or_device: str | BLEDevice | BleakClient,
        *,
        timeout: float = 15.0,
        response_timeout: float = 5.0,
    ) -> None:
        self.timeout = timeout
        self.response_timeout = response_timeout
        self._owns_client = not isinstance(address_or_device, BleakClient)
        self.address_or_device = address_or_device
        self._client: BleakClient | None = None if self._owns_client else address_or_device
        self._lock = asyncio.Lock()
        self._assembler = FrameAssembler()
        self._pending: tuple[int, asyncio.Future[bytes]] | None = None
        self._protocol_notify = False
        self._raw_callback: NotificationCallback | None = None
        self._callback_tasks: set[asyncio.Future[Any]] = set()

    @property
    def client(self) -> BleakClient:
        if self._client is None or not self._client.is_connected:
            raise TenwaysError("Bike is not connected")
        return self._client

    async def connect(self) -> None:
        if not self._owns_client:
            return
        if self._client is not None and self._client.is_connected:
            return
        self._client = BleakClient(
            self.address_or_device,
            timeout=self.timeout,
            disconnected_callback=self._on_disconnect,
        )
        await self._client.connect()

    async def disconnect(self) -> None:
        self._raw_callback = None
        await self._stop_notify()
        if not self._owns_client or self._client is None:
            return
        try:
            if self._client.is_connected:
                await self._client.disconnect()
        finally:
            self._client = None

    async def __aenter__(self) -> "TenwaysBike":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.disconnect()

    async def _stop_notify(self) -> None:
        """Drop our notification subscription, also on a connection we do not own."""

        client = self._client
        subscribed = self._protocol_notify
        self._protocol_notify = False
        if subscribed and client is not None and client.is_connected:
            try:
                await client.stop_notify(TENWAYS_NOTIFY_UUID)
            except Exception as exc:
                _LOGGER.debug("Could not stop notifications: %s", exc)

    def _on_disconnect(self, _client: BleakClient) -> None:
        self._protocol_notify = False
        if self._pending is not None and not self._pending[1].done():
            self._pending[1].set_exception(TenwaysError("Bike disconnected"))

    async def battery_level(self) -> int:
        """Read the Bluetooth standard Battery Level characteristic.

        This is not the traction battery; see :meth:`read_status`.
        """

        raw = bytes(await self.client.read_gatt_char(BATTERY_LEVEL_UUID))
        if len(raw) != 1:
            raise TenwaysBatteryError(f"Unexpected battery payload: {raw.hex(' ')}")
        value = raw[0]
        if not 0 <= value <= 100:
            raise TenwaysBatteryError(f"Invalid battery value: {value}")
        return value

    async def info(self) -> TenwaysInfo:
        name: str | None = None
        try:
            name = self.client.name
        except Exception:
            pass

        try:
            battery = await self.battery_level()
        except Exception:
            battery = None

        services = tuple(str(service.uuid).lower() for service in self.client.services)
        address = getattr(self.client, "address", str(self.address_or_device))
        return TenwaysInfo(
            address=address,
            name=name,
            battery_level=battery,
            services=services,
        )

    def supports_protocol(self) -> bool:
        services = self.client.services
        return (
            services.get_characteristic(TENWAYS_WRITE_UUID) is not None
            and services.get_characteristic(TENWAYS_NOTIFY_UUID) is not None
        )

    async def read_status(self) -> TenwaysStatus:
        """Request and decode live telemetry (command 0x0B)."""

        return decode_status(await self._request(STATUS_REQUEST, CMD_STATUS))

    async def read_device_info(self) -> TenwaysDeviceInfo:
        """Request firmware and serial number (command 0x04)."""

        return decode_device_info(await self._request(INFO_REQUEST, CMD_INFO))

    async def _request(self, request: bytes, cmd: int) -> bytes:
        async with self._lock:
            client = self.client
            if not self.supports_protocol():
                raise TenwaysUnsupportedError("King Meter service not found")
            if not self._protocol_notify:
                self._assembler.reset()
                await client.start_notify(TENWAYS_NOTIFY_UUID, self._on_notify)
                self._protocol_notify = True
            future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
            self._pending = (cmd, future)
            try:
                # The timeout covers the write too: a stalled write must not hold the lock.
                async with asyncio.timeout(self.response_timeout):
                    await client.write_gatt_char(TENWAYS_WRITE_UUID, request, response=False)
                    return await future
            except TimeoutError as exc:
                raise TenwaysTimeoutError(f"No reply to command {cmd:#04x}") from exc
            finally:
                self._pending = None

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        payload = bytes(data)
        if self._raw_callback is not None:
            try:
                result = self._raw_callback(payload)
                if inspect.isawaitable(result):
                    task = asyncio.ensure_future(result)
                    self._callback_tasks.add(task)
                    task.add_done_callback(self._callback_done)
            except Exception:
                # A faulty listener must not stop the reply reaching a pending request.
                _LOGGER.exception("Raw notification callback failed")
        for raw in self._assembler.feed(payload):
            try:
                frame = parse_frame(raw)
            except TenwaysProtocolError as exc:
                _LOGGER.debug("Dropping invalid frame %s: %s", raw.hex(" "), exc)
                continue
            pending = self._pending
            if (pending is not None and not pending[1].done()
                    and frame.type == TYPE_READ and frame.cmd == pending[0]):
                pending[1].set_result(raw)
            else:
                _LOGGER.debug("Unsolicited frame %s", raw.hex(" "))

    def _callback_done(self, task: asyncio.Future[Any]) -> None:
        self._callback_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            _LOGGER.error("Raw notification callback failed", exc_info=task.exception())

    async def start_raw_notifications(self, callback: NotificationCallback) -> None:
        """Subscribe to the proprietary TENWAYS notification characteristic."""

        self._raw_callback = callback
        if not self._protocol_notify:
            self._assembler.reset()
            await self.client.start_notify(TENWAYS_NOTIFY_UUID, self._on_notify)
            self._protocol_notify = True

    async def stop_raw_notifications(self) -> None:
        # Under the lock, so a request in flight keeps its subscription until it is answered.
        async with self._lock:
            self._raw_callback = None
            await self._stop_notify()
