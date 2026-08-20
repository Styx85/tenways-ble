from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TenwaysAdvertisement:
    address: str
    name: str | None
    rssi: int | None


@dataclass(frozen=True, slots=True)
class TenwaysInfo:
    address: str
    name: str | None
    battery_level: int | None
    services: tuple[str, ...]
