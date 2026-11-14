<p align="center"><img src="https://raw.githubusercontent.com/Styx85/tenways-ble/main/docs/icon.png" alt="" width="160"></p>

# tenways-ble

Small experimental Python library and CLI for local BLE access to TENWAYS e-bikes. It powers the Home Assistant integration [ha-tenways](https://github.com/Styx85/ha-tenways).

- discovers nearby TENWAYS BLE devices;
- decodes the proprietary **King Meter** frame protocol (CRC-16/MODBUS, TLV fields) used by the TENWAYS Longtail Duo and, untested, other King Meter models (see [Supported bikes](#supported-bikes));
- reads live telemetry: traction battery, odometer, trip, max/average speed, ride time, light, remaining range;
- reads firmware and serial number;
- reads the standard Bluetooth Battery Level characteristic (`0x2A19`), which is **not** the traction battery;
- writes only what the TENWAYS app also writes, and only when called: the clock sync `set_clock()` and clearing the trip `reset_trip()`. No lock, light or configuration commands.

The protocol was reconstructed from an Android HCI capture of the official TENWAYS app; all test vectors are the original captured frames. **Tested on a Longtail Duo**, including both writes; current speed and power are not yet confirmed while riding.

## Installation

```bash
pip install tenways-ble
```

Python 3.11 or newer and [bleak](https://github.com/hbldh/bleak). On Linux, BlueZ and a working Bluetooth adapter are required.

## Library usage

```python
import asyncio
from tenways_ble import TenwaysBike

async def main():
    async with TenwaysBike("E8:88:6C:31:B3:0D") as bike:
        status = await bike.read_status()
        print(status.battery_percent, status.odometer_km)

asyncio.run(main())
```

`TenwaysBike` also accepts an already connected `BleakClient` (for example from `bleak-retry-connector` in Home Assistant). It then only speaks the protocol and leaves the connection to the caller.

The sans-I/O protocol module `tenways_ble.protocol` builds and parses frames without any Bluetooth dependency.

Both writes wait for an acknowledgement that carries the written key; pass `wait_for_reply=False` to only send.

## CLI

```bash
tenways scan                            # likely TENWAYS devices nearby
tenways status E8:88:6C:31:B3:0D        # live telemetry (traction battery, odometer, …)
tenways device-info E8:88:6C:31:B3:0D   # firmware and serial number
tenways battery E8:88:6C:31:B3:0D       # standard BLE battery (not the traction battery)
tenways info E8:88:6C:31:B3:0D          # basic GATT information and battery level
tenways listen E8:88:6C:31:B3:0D        # proprietary notifications, stop with Ctrl+C
```

## Supported bikes

The library picks a profile from the advertised name, matched like the TENWAYS app picks its driver (`TenwaysBike(client, name=...)`, CLI `--model`). Without a name it assumes a Longtail Duo.

| Advertised name | App driver | Status | Notes |
|---|---|---|---|
| `Longtail Duo` | long tail duo/CGO009_D | **tested** | all reads, `set_clock()`, `reset_trip()` |
| `CGO009_D` | long tail duo/CGO009_D | untested | same requests as the Duo; written with response like the app |
| `CGO009` (not `CGO009L`) | 009 | untested | asks for assist level `0x12` too (`raw_12`) |
| `CGO800`, `CGO800 Plus`, `CGO800S` | 800s | untested | CRC low byte first, odometer in whole km, firmware as text; some CGO800 Plus displays need the encrypted session (not supported) |
| `AGO`, `AGOX`, `AGOT`, `CARGO`, `CGO009L`, other names | ago (the app's default) | untested | same status fields as the Duo, serial number from key `0x05` |
| `AGO AIR`, `Wayfarer_B`, `AGOX_D`, `AGOT_D`, `CGO COMPACT_D`, `AGO AIR-BELT_D` | AGO AIR | not supported | encrypted King Meter session (`0xD8`/`0xD2` handshake) |
| `CGO600_D` | CGO600_D | not supported | `0x57` frames, not King Meter |
| `CGO600`, `CGO600 Pro`, `CGO600 PLUS` | Nordic UART | not supported | not King Meter |
| `DM…` | DM | not supported | separate driver, not analysed |

"Untested" means the requests follow the app, but no such bike has answered this library yet. Not supported models raise `TenwaysUnsupportedError` and nothing is sent. With a debug log of your bike (or, for the unsupported ones, an HCI capture of the TENWAYS app; never publish it raw) they can be added: please open an issue. Details: [driver per model](https://github.com/Styx85/tenways-ble/blob/main/docs/RESEARCH.md#driver-per-model).

## Safety

`tenways-ble` never writes arbitrary data to the proprietary TENWAYS write characteristic; the only writes are the explicit clock sync and clear trip, both taken from the TENWAYS app. Reverse engineering should start from observed traffic rather than guessed commands.

Never publish a raw phone HCI log; it contains traffic and identifiers of other devices.

## Documentation

- [Devices and King Meter protocol](https://github.com/Styx85/tenways-ble/blob/main/docs/PROTOCOL.md): GATT layout, frame format, every key and both writes, with what is confirmed on the bike.
- [Research notes](https://github.com/Styx85/tenways-ble/blob/main/docs/RESEARCH.md): findings from the app's code, read and write keys per model, tests on the Duo, open fields, capture procedure.
- [Development](https://github.com/Styx85/tenways-ble/blob/main/docs/DEVELOPMENT.md): development install, HCI trace on Linux, releasing.

## License

MIT

## Acknowledgements / Credits

Based on and inspired by [stein155/cgo600-bridge](https://github.com/stein155/cgo600-bridge), which provided valuable groundwork for understanding the proprietary TENWAYS telemetry protocol and its integration with Home Assistant.

Many thanks to the original author and contributors.

The Longtail Duo implementation was developed using independently captured Bluetooth HCI traffic from the official TENWAYS app. It uses the King Meter BLE transport rather than the Nordic UART Service used by the CGO600 bridge.
