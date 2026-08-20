from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from .client import TenwaysBike, scan_tenways


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tenways", description="TENWAYS BLE diagnostics")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan for nearby TENWAYS BLE devices")
    scan.add_argument("--timeout", type=float, default=5.0)

    battery = sub.add_parser("battery", help="Read standard BLE battery level")
    battery.add_argument("address")

    info = sub.add_parser("info", help="Show device name, battery and services")
    info.add_argument("address")

    listen = sub.add_parser("listen", help="Subscribe to raw TENWAYS notifications")
    listen.add_argument("address")

    return parser


async def _scan(timeout: float) -> int:
    devices = await scan_tenways(timeout)
    if not devices:
        print("No TENWAYS BLE devices found.")
        return 1
    for device in devices:
        rssi = f"{device.rssi} dBm" if device.rssi is not None else "RSSI n/a"
        print(f"{device.address:<20} {device.name or '<unnamed>':<28} {rssi}")
    return 0


async def _battery(address: str) -> int:
    async with TenwaysBike(address) as bike:
        value = await bike.battery_level()
    print(f"Battery: {value} %")
    return 0


async def _info(address: str) -> int:
    async with TenwaysBike(address) as bike:
        info = await bike.info()
    print(f"Address: {info.address}")
    print(f"Name: {info.name or '<unknown>'}")
    print(f"Battery: {info.battery_level if info.battery_level is not None else '<unavailable>'}%")
    print("Services:")
    for uuid in info.services:
        print(f"  {uuid}")
    return 0


async def _listen(address: str) -> int:
    stop = asyncio.Event()

    def on_packet(data: bytes) -> None:
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        print(f"RX {now}  {data.hex(' ')}", flush=True)

    async with TenwaysBike(address) as bike:
        try:
            battery = await bike.battery_level()
            print(f"Battery: {battery} %")
        except Exception as exc:
            print(f"Battery read failed: {exc}")

        await bike.start_raw_notifications(on_packet)
        print("Subscribed to proprietary TENWAYS notifications.")
        print("Waiting for packets; press Ctrl+C to stop.")

        try:
            await stop.wait()
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await bike.stop_raw_notifications()
            except Exception:
                pass
    return 0


async def _amain(args: argparse.Namespace) -> int:
    if args.command == "scan":
        return await _scan(args.timeout)
    if args.command == "battery":
        return await _battery(args.address)
    if args.command == "info":
        return await _info(args.address)
    if args.command == "listen":
        return await _listen(args.address)
    raise RuntimeError("Unhandled command")


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        code = asyncio.run(_amain(args))
    except KeyboardInterrupt:
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
