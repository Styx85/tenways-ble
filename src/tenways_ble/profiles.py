"""Which TENWAYS models speak which variant of the King Meter protocol.

The TENWAYS app (2.18.0, 2.19.0, analysed statically) picks a driver from the
name a bike advertises. A profile mirrors one driver: the keys the app asks
for, the CRC byte order of its requests and how some values decode. The
request key lists agree with tenways-bridge's notes of the same app
(https://github.com/stein155/tenways-bridge, MIT).

Only the Longtail Duo is tested. The other King Meter profiles follow the app
and are marked untested. Models whose protocol is not implemented (encrypted
displays, Nordic UART, other frame formats) get an unsupported profile, so
that callers can say so instead of sending requests the bike will not answer.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Profile:
    """One driver of the TENWAYS app."""

    name: str
    status_keys: tuple[int, ...] = ()
    info_keys: tuple[int, ...] = ()
    # The app fills in the CRC low byte first for this driver (CGO800).
    crc_low_first: bool = False
    # The app writes to the King Meter characteristic with response.
    write_with_response: bool = False
    # CGO800: odometer in whole km and firmware as ASCII (others: 0.1 km, dotted bytes).
    cgo800_values: bool = False
    tested: bool = False
    supported: bool = True
    # Why an unsupported model is not supported.
    reason: str | None = None


LONGTAIL_STATUS = (0x06, 0x07, 0x08, 0x09, 0x11, 0x0A, 0x0B, 0x0C, 0x0F, 0x23, 0x4F)
LONGTAIL_INFO = (0x04, 0x05, 0x4F, 0x70)

LONGTAIL_DUO = Profile("Longtail Duo", LONGTAIL_STATUS, LONGTAIL_INFO, tested=True)
# Names the app writes to with response (2.19.0); all others use write without response,
# as captured on the Longtail Duo. Of these, only CGO009_D has a supported profile.
WRITE_WITH_RESPONSE_NAMES = (
    "AGO AIR", "CGO600_D", "Wayfarer_B", "CGO009_D", "AGOX_D", "AGOT_D", "CGO COMPACT_D", "AGO AIR-BELT_D",
)
# Names the app sends the clock (key 0x3C) to after connecting.
CLOCK_NAMES = ("AGOX", "AGOT", "CARGO", "Longtail Duo")

# Same driver as the Longtail Duo; the app writes to it with response.
CGO009_D = Profile("CGO009_D", LONGTAIL_STATUS, LONGTAIL_INFO, write_with_response=True)
CGO009 = Profile(
    "CGO009",
    (0x06, 0x07, 0x08, 0x09, 0x11, 0x12, 0x0A, 0x0B, 0x0C, 0x0F, 0x23, 0x4F, 0x50),
    (0x04, 0x05, 0x70, 0x4F, 0x50),
)
CGO800 = Profile(
    "CGO800",
    (0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0F, 0x11, 0x23),
    (0x04, 0x05),
    crc_low_first=True,
    cgo800_values=True,
)
# The app's default driver: AGO, AGOX, AGOT, CARGO and unknown names.
AGO = Profile("AGO", (0x05, 0x06, 0x07, 0x08, 0x09, 0x11, 0x0A, 0x0B, 0x0C, 0x0F, 0x23), (0x04, 0x05))

AGO_AIR = Profile("AGO AIR", supported=False, reason="encrypted King Meter session (0xD8/0xD2 handshake)")
CGO600_D = Profile("CGO600_D", supported=False, reason="0x57 frames, not King Meter")
CGO600 = Profile("CGO600", supported=False, reason="Nordic UART, not King Meter")
DM = Profile("DM", supported=False, reason="separate driver in the app, not analysed")
HELMET = Profile("smart helmet", supported=False, reason="TENWAYS helmet, not a bike")

PROFILES = (LONGTAIL_DUO, CGO009_D, CGO009, CGO800, AGO, AGO_AIR, CGO600_D, CGO600, DM, HELMET)

# Names the app hands to its AGO AIR driver besides "AGO AIR" and "Wayfarer_B".
AGO_AIR_NAMES = ("AGOX_D", "AGOT_D", "CGO COMPACT_D", "AGO AIR-BELT_D")


def profile_for(name: str | None) -> Profile:
    """The profile for an advertised name, matched in the app's order.

    A missing or unknown name gets the app's default driver (AGO).
    """
    if not name:
        return AGO
    if name.startswith("DM"):
        return DM
    if name.startswith("CGO600") and not name.startswith("CGO600_D"):
        return CGO600
    if name.startswith("CGO800"):
        return CGO800
    if name.startswith("CGO009") and not name.startswith(("CGO009L", "CGO009_D")):
        return CGO009
    if name.startswith("Longtail Duo"):
        return LONGTAIL_DUO
    if name.startswith("CGO009_D"):
        return CGO009_D
    if name.startswith(("AGO AIR", "Wayfarer_B") + AGO_AIR_NAMES):
        return AGO_AIR
    if name.startswith("CGO600_D"):
        return CGO600_D
    if "smart-helmet-" in name:
        return HELMET
    return AGO
