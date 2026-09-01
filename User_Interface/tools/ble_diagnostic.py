"""Exercise the FDEM Nordic-UART link without starting the desktop GUI."""

from __future__ import annotations

import asyncio

from bleak import BleakClient, BleakScanner

from fdem_controller.constants import BLE_DEVICE_NAME, NUS_RX_UUID, NUS_TX_UUID


async def main() -> int:
    print("Scanning for FDEM-TX...")
    device = await BleakScanner.find_device_by_filter(
        lambda candidate, advertisement: (
            (advertisement.local_name or candidate.name or "").strip() == BLE_DEVICE_NAME
        ),
        timeout=10.0,
    )
    if device is None:
        print("RESULT: FDEM-TX was not found")
        return 2

    print(f"Found {device.name} at {device.address}")
    received = asyncio.Event()

    def notification(_characteristic, data: bytearray) -> None:
        print(f"RX: {bytes(data)!r}")
        received.set()

    client = BleakClient(device, timeout=20.0)
    try:
        print("Stage: connect and unfiltered service discovery")
        await client.connect()
        print(f"Connected: {client.is_connected}")
        for service in client.services:
            print(f"Service: {service.uuid}")
            for characteristic in service.characteristics:
                print(f"  Characteristic: {characteristic.uuid} {characteristic.properties}")

        print("Stage: enable TX notifications")
        await client.start_notify(NUS_TX_UUID, notification)
        print("Stage: write STATUS without response")
        await client.write_gatt_char(NUS_RX_UUID, b"STATUS\n", response=False)
        try:
            await asyncio.wait_for(received.wait(), timeout=5.0)
        except TimeoutError:
            print("RESULT: STATUS was written, but no notification arrived")
            return 3
        print("RESULT: complete BLE round trip succeeded")
        return 0
    except Exception as error:
        print(f"RESULT: {type(error).__name__}: {error}")
        return 1
    finally:
        if client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
