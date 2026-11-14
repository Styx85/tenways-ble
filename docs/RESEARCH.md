# Research leads

Leads for decoding more of the Longtail Duo. **Nothing here is confirmed for
the King Meter BLE interface (`43480001-…`) unless it says so.** Evidence for a
write is a frame captured from the official TENWAYS app, or a frame the app's
code would send unchanged to this model (see the app findings below); such a
frame is tried once, supervised, before it goes into the library. Never derive
write commands from the other sources here or from guessing keys.

## Hardware chain (hypothesis)

```
TENWAYS app / Home Assistant
        │  King Meter BLE (43480001-…) — confirmed by HCI capture
Display / BLE module  — possibly DigiTech BC351
        │  internal bus, probably CAN
Bafang M410 drive (250 W, 80 Nm, integrated controller) — confirmed by TENWAYS
```

The display may forward only a subset of motor data over BLE, or may answer
further, not yet captured BLE field keys. CAN frames cannot be assumed to pass
through the BLE channel.

## King Meter display protocols (serial, not BLE)

- [stancecoke/BMSBattery_S_controllers_firmware `display_kingmeter.c`](https://github.com/stancecoke/BMSBattery_S_controllers_firmware/blob/Master/display_kingmeter.c)
  — C implementation of the 901U/KM5S display protocol, including a handshake
  and OEM-specific handshake tables.
- [EBiCS/EBiCS_Firmware](https://github.com/EBiCS/EBiCS_Firmware) — separate
  implementations for KINGMETER_618U, KINGMETER_901U, Bafang LCD and TFT.
- [King Meter J-LCD5S protocol (PDF)](https://www.emubikes.com/wp-content/uploads/2020/12/J-LCD5S-protocol-From-KING-METER_1589857045208.pdf)
  — speed, battery, assist levels, error codes, lights. Useful for guessing
  which data exists, not for BLE field keys.

No public source found that documents the King Meter BLE UUID or the
`62 00 … CRC 45` framing.

## Bafang CAN (different transport)

- [speedysheep/ebike-protocols `BAFANG_CAN_PROTOCOL.md`](https://github.com/speedysheep/ebike-protocols/blob/main/bafang/BAFANG_CAN_PROTOCOL.md)
  — reverse-engineered Bafang CAN codes, e.g. `0x32/0x00` (state of charge,
  cadence, torque, remaining range), `0x32/0x01` (speed, motor current, battery
  voltage, controller and motor temperature; 16-bit little endian, temperatures
  offset −40 °C), `0x63/0x00` (assist level, mode, light bits), `0x64/0x02–05`
  (cell voltages, mV).
- [andrey-pr/OpenBafangTool](https://github.com/andrey-pr/OpenBafangTool) —
  diagnosis and configuration for Bafang UART and CAN.
- [Kaspars Dambis: Bafang CAN bus programming](https://kaspars.net/blog/bafang-canbus)
  — CAN adapter, HIGO connectors, 250 kbit/s, SocketCAN; comments mention a
  TENWAYS AGO-X with M410.

A direct CAN capture would be a later, separate option and needs opening the
bike's wiring. Not planned for now.

## Display: DigiTech BC351 (unconfirmed)

A dealer lists the Longtail Duo display as DigiTech BC351 with Bluetooth. Not
an official TENWAYS statement for every hardware revision.

- 3.5" colour display, UART or CAN, optional Bluetooth 4.2 and GPS, vendor app
  "Bikewise Pro".
- [DigiTech B-COCKPiT BC351 manual](https://www.manualslib.com/manual/3148608/Digitech-B-Cockpit-Bc351.html)
  (documents Bluetooth pairing via QR code)
- [HEPHA BC351 manual](https://www.manualslib.de/manual/1351570/Hepha-Bc351.html)
  — OEM display on the same base.

Do not treat DigiTech and King Meter as the same manufacturer without evidence.
If Bikewise Pro talks to the bike, an HCI capture of that app could reveal more
BLE commands.

## Open status fields and tests

| Field | Captured | Next test |
|---|---|---|
| `0x0B` | 655 | Remaining range: the app names it `remainingRange` and treats a low byte ≥ 0x80 (655 = 0x028F) as 0. On the parked bike at 68 %: 60, 54, 50, 45, 43 km for levels 1–5, none at level 0. Check the unit and that it falls with the battery |
| `0x11` | 0 | Light (`lightControl` in the app), 0 = off. Confirm 1 = on |
| `0x23` | 0 | `power` in the app (≤ 3000 accepted), probably motor power in W. Capture while riding, supervised |
| `0x4F` | 1 | `whetherUnlock` in the app; correlate with display/power states |
| `0x06` | 0 | Capture while riding (safely, supervised) to confirm current speed |

These are hypotheses. A key number matching a Bafang CAN code does not imply
the same meaning in the BLE protocol.

## Findings from the app's code (static analysis)

Facts only; no app code is reproduced here. Versions 2.18.0 and 2.19.0
(package `com.ycy.bluetoothbike`), looked at statically, never run.

### Frame layout

Every King Meter frame is `[type] 00 [len] [count] [payload] [crc] [crc] 45`.
Byte 3 is the **number of keys** (keys asked for in a read, TLV entries in a
reply, `1` in a write), not a command code. A write sets one key:
`63 00 [len] 01 [key] [size] [value] [crc] [crc] 45`. The app fills in the CRC
high byte first for every driver except the CGO800 ("800s").

### Driver per model

The app picks a driver from the advertised name:

| Name starts with | Driver | Protocol |
|---|---|---|
| `Longtail Duo`, `CGO009_D` | own driver ("long tail duo/CGO009_D") on the AGO base | King Meter |
| `CGO009` (not `L`/`_D`) | "009", AGO base | King Meter |
| `CGO800` | "800s" | King Meter, CRC low byte first |
| `AGO AIR`, `Wayfarer_B`, … | "AGO AIR" | King Meter, partly encrypted (`0xD8`/`0xD2` handshake) |
| `CGO600_D` | own driver | `0x57` frames |
| `CGO600` | Nordic UART | not King Meter |
| `smart-helmet-` | helmet | `55 B1 …` frames |
| anything else (AGO, AGOX, AGOT, CARGO) | "ago", the AGO base | King Meter |

(The earlier note that the Duo uses the "800s" driver was wrong: "800s" is the
CGO800 driver.)

### Read keys

| Key | App name | Decoding in the app | Asked for on the Duo |
|---|---|---|---|
| `0x04` | `meterFWVer` | dotted bytes | info request |
| `0x05` | `sn` | ASCII | info request |
| `0x06` | `spd` | ÷ 10 km/h; values above 75 are replaced by the previous value | status |
| `0x07` | `maxSpd` | ÷ 10 km/h | status |
| `0x08` | `aveSpd` | ÷ 10 km/h | status |
| `0x09` | `tripDistance` | ÷ 10; jumps of 2 km or more (5 km for some models) and falls of more than 10 km between updates are discarded | status |
| `0x0A` | `tripDuration` | seconds | status |
| `0x0B` | `remainingRange` | integer; a byte ≥ 0x80 counts as 0 | status |
| `0x0C` | `totalRange` | stored as the device's total distance, shown as odometer | status |
| `0x0F` | `battery` | % | status |
| `0x11` | `lightControl` | light | status |
| `0x12` | `boosterMode` | assist level | no (CGO009 only); the Duo answers it empty |
| `0x17` | `powerOnPassword` | power-on PIN | separate request |
| `0x23` | `power` | values above 3000 are ignored | status |
| `0x40`, `0x41`, `0x42` | `supplierCode`, `productCode`, `subModel` | ASCII | no (info variant of other models) |
| `0x4F` | `whetherUnlock` | state flag | status and info |
| `0x50` | `bTLockUnlock` | Bluetooth lock state | no (CGO009) |
| `0x51` | `meterPasswordPageState` | PIN page state | separate request |
| `0x55` | `ambientLighting` | integer | no |
| `0x70` | `iOTSn` | ASCII; the serial number this library exposes | info request |
| `0x73`, `0x76` | `airPhoneMac`, `airUnlockWhitelist` | hex | no (AGO AIR) |
| `0x80` | `protocolVersion` | dotted bytes | no (info variant of other models) |

The Duo's status request in the app is byte for byte the one this library
sends. `0x17` (PIN) is deliberately not read by this library.

### Write keys

| Key | Action | Sent to |
|---|---|---|
| `0x2D` = `01` | **clear trip**: `63 00 04 01 2d 01 01 63 e8 45` on the Duo | built into the AGO base and the "800s" driver, so the Duo's driver would send it; the app's screen hides the button for the Duo (a `clearTrip` feature flag that is not in the app, probably from the TENWAYS server) |
| `0x3C`, 7 bytes | **set clock** (flags `02`, year−2000, month, day, hour, minute, second) | names starting with `AGOX`, `AGOT`, `CARGO` or `Longtail Duo`, about a second after connecting; captured and confirmed on a Duo |
| `0x24`, 1 byte | navigation arrow | CGO800S and navigation models |
| `0x25`, 4 bytes | navigation distance | CGO800S and navigation models |
| `0x4D`, 16 bytes | unlock key | models with a Bluetooth lock |
| `0x75` | unlock whitelist | AGO AIR |
| `0x71`, `0x72` | IoT key checksum | IoT models |
| `0x52` | "full cmd" | AGO AIR |
| `0xD8` / `0xD2` | encryption handshake | encrypted displays |
| `57 03 25 01 19 …` | reset speed limit and wheel size | CGO600_D (not King Meter) |

**There is no light command for the bike** in any King Meter driver: the app
only reads `0x11`. Its "auto light on" belongs to the helmet. A light write on
`0x11` (as some projects send) is not backed by the app for these displays.

### Other findings

- **Odometer and trip were swapped** in this library before: `0x0C` is the odometer and `0x09` the trip. The capture cannot tell them apart because both hold 1201; they differ once the trip is reset.
- The app's data model also has fields this bike may or may not deliver over BLE: `cadence`, `torque`, `voltage`, `current`, `charging`, `standStill`, `lightReserveReached`, `serviceDueDate`, `serviceDueDistance`. The King Meter drivers do not parse them; they probably serve other drivers (Bosch and others).
- Statistics (week, month, year) and routes are computed on the TENWAYS server; the route is recorded with the phone's location while the app holds the BLE connection. The app's trip log is therefore only complete when the app stayed connected for the whole ride.

### Tests on the Duo (2026-11-14, through Home Assistant)

- **Clear trip works.** The bike echoed `63 00 04 01 2d 01 01 63 e8 45`. Before: trip 164.0 km, trip time 42970 s, maximum 44.7, average 13.7 km/h. After: all four 0; odometer 164.0 km and battery unchanged. This also confirms on the bike that `0x09` is the trip and `0x0C` the odometer. `TenwaysBike.reset_trip()` sends this frame.
- **`0x12` (assist level) is not available** on the Duo: the reply is `62 00 01 01 cc df 45`, a count of 1 with no entry.
- **Unknown keys get an empty reply**, not silence and not an error.

## Standard battery characteristic (`0x2A19`)

Reads 0 % after power-on on the Longtail Duo, then rises by 1 roughly with
every read while the bike is on and drops back to 0 when it is switched off.
It looks like a counter (connections or time since power-on), not a battery.

## Capture procedure

Android HCI snoop log (`mSnoopLogSettingAtEnable = full`), retrieved via bug
report from `FS/data/misc/bluetooth/logs/btsnoop_hci.log`. Trigger exactly one
action in the app per capture and note the time. Never publish a raw capture.
