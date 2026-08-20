from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .const import BATTERY_LEVEL_UUID, TENWAYS_NAME_PREFIX, TENWAYS_NOTIFY_UUID
from .models import TenwaysAdvertisement, TenwaysInfo

NotificationCallback = Callable[[bytes], None | Awaitable[None]]


class TenwaysError(RuntimeError):
    """Base exception for tenways-ble."""


class TenwaysBatteryError(TenwaysError):
    """Raised when the standard battery value cannot be decoded."""


def _looks_like_tenways(device: BLEDevice, adv: AdvertisementData | None) -> bool:
    names = [device.name]
    if adv is not None:
        names.append(adv.local_name)
    return any(name and name.lower().startswith(TENWAYS_NAME_PREFIX) for name in names)


async def scan_tenways(timeout: float = 5.0) -> list[TenwaysAdvertisement]:
    """Scan for nearby devices whose advertised name looks like TENWAYS."""

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
    """Minimal BLE client for a TENWAYS bicycle.

    The class intentionally exposes only operations known to be safe/read-only.
    Proprietary write commands are not implemented yet.
    """

    def __init__(self, address_or_device: str | BLEDevice, *, timeout: float = 15.0) -> None:
        self.address_or_device = address_or_device
        self.timeout = timeout
        self._client: BleakClient | None = None

    @property
    def client(self) -> BleakClient:
        if self._client is None or not self._client.is_connected:
            raise TenwaysError("Bike is not connected")
        return self._client

    async def connect(self) -> None:
        if self._client is not None and self._client.is_connected:
            return
        self._client = BleakClient(self.address_or_device, timeout=self.timeout)
        await self._client.connect()

    async def disconnect(self) -> None:
        if self._client is None:
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

    async def battery_level(self) -> int:
        """Read the Bluetooth standard Battery Level characteristic."""

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

    async def start_raw_notifications(self, callback: NotificationCallback) -> None:
        """Subscribe to the proprietary TENWAYS notification characteristic."""

        async def run_callback(data: bytes) -> None:
            result = callback(data)
            if asyncio.iscoroutine(result):
                await result

        def bleak_callback(_sender: Any, data: bytearray) -> None:
            payload = bytes(data)
            result = callback(payload)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)

        await self.client.start_notify(TENWAYS_NOTIFY_UUID, bleak_callback)

    async def stop_raw_notifications(self) -> None:
        await self.client.stop_notify(TENWAYS_NOTIFY_UUID)
