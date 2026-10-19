# Research leads

Leads for decoding more of the Longtail Duo. **Nothing here is confirmed for
the King Meter BLE interface (`43480001-…`)**; only frames captured from the
official TENWAYS app count as evidence. Never derive write commands from these
sources.

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
| `0x4F` | 1 | Correlate with display/power states |
| `0x06` | 0 | Capture while riding (safely, supervised) to confirm current speed |

These are hypotheses. A key number matching a Bafang CAN code does not imply
the same meaning in the BLE protocol.

## Standard battery characteristic (`0x2A19`)

Reads 0 % after power-on on the Longtail Duo, then rises by 1 roughly with
every read while the bike is on and drops back to 0 when it is switched off.
It looks like a counter (connections or time since power-on), not a battery.

## Capture procedure

Android HCI snoop log (`mSnoopLogSettingAtEnable = full`), retrieved via bug
report from `FS/data/misc/bluetooth/logs/btsnoop_hci.log`. Trigger exactly one
action in the app per capture and note the time. Never publish a raw capture.
