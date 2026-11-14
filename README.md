<p align="center"><img src="https://raw.githubusercontent.com/Styx85/tenways-ble/main/docs/icon.png" alt="" width="160"></p>

# tenways-ble

Small experimental Python library and CLI for local BLE access to TENWAYS e-bikes. It powers the Home Assistant integration [ha-tenways](https://github.com/Styx85/ha-tenways).

- discovers nearby TENWAYS BLE devices;
- decodes the proprietary **King Meter** frame protocol (CRC-16/MODBUS, TLV fields) used by the TENWAYS Longtail Duo;
- reads live telemetry: traction battery, odometer, trip, max/average speed, ride time, light, remaining range;
- reads firmware and serial number;
- reads the standard Bluetooth Battery Level characteristic (`0x2A19`), which is **not** the traction battery;
- writes only what the TENWAYS app also writes, and only when called: the clock sync `set_clock()` and clearing the trip `reset_trip()`. No lock, light or configuration commands.

The protocol was reconstructed from an Android HCI capture of the official TENWAYS app; all test vectors are the original captured frames. **Tested on a Longtail Duo**, including both writes.

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

Tested on the **Longtail Duo**. In the TENWAYS app, CGO009_D shares its driver and the AGO family (CGO009, AGO, AGO X, AGO T, CARGO) the same King Meter protocol, so they may work. CGO800 uses the other CRC byte order, AGO AIR an encrypted session, CGO600 a different protocol; these are not supported. Details: [driver per model](https://github.com/Styx85/tenways-ble/blob/main/docs/RESEARCH.md#driver-per-model).

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
