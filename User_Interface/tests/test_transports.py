from __future__ import annotations

import asyncio
from queue import Empty, Queue
import sys
import time
import types
import unittest
from unittest.mock import patch

from fdem_controller.events import BleDeviceInfo, BleScanCompleted, Connected, Disconnected, LineReceived
from fdem_controller.transports.ble_transport import BleTransport
from fdem_controller.transports.serial_transport import SerialTransport


def wait_for(events: Queue, event_type: type, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    held = []
    while time.monotonic() < deadline:
        try:
            event = events.get(timeout=0.05)
        except Empty:
            continue
        held.append(event)
        if isinstance(event, event_type):
            return event, held
    raise AssertionError(f"Timed out waiting for {event_type.__name__}; received {held!r}")


class FakeSerial:
    def __init__(self, **_kwargs) -> None:
        self.dtr = True
        self.rts = True
        self.port = None
        self.is_open = False
        self.in_waiting = 1
        self.reads = [b"FDEM-TX READY\r\n", b"STATUS:F:1000,A:0,W:S,TRIM:0,CAL:IDLE,BLT:1,BAT:UNAVAILABLE\r\n"]
        self.writes: list[bytes] = []

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def read(self, _size: int) -> bytes:
        if self.reads:
            return self.reads.pop(0)
        time.sleep(0.01)
        return b""

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def flush(self) -> None:
        pass


class TransportTests(unittest.TestCase):
    def test_serial_discovers_bootstraps_reads_and_orderly_disconnects(self) -> None:
        fake = FakeSerial()
        serial_module = types.ModuleType("serial")
        serial_module.EIGHTBITS = 8
        serial_module.PARITY_NONE = "N"
        serial_module.STOPBITS_ONE = 1
        serial_module.Serial = lambda **kwargs: fake
        port = types.SimpleNamespace(device="COM7", description="ESP32", hwid="USB VID:PID")
        list_ports_module = types.ModuleType("serial.tools.list_ports")
        list_ports_module.comports = lambda: [port]
        tools_module = types.ModuleType("serial.tools")
        tools_module.list_ports = list_ports_module
        serial_module.tools = tools_module
        modules = {
            "serial": serial_module,
            "serial.tools": tools_module,
            "serial.tools.list_ports": list_ports_module,
        }
        events: Queue = Queue()
        with patch.dict(sys.modules, modules):
            transport = SerialTransport(events.put)
            self.assertEqual(transport.list_ports()[0].display_name, "COM7 — ESP32")
            transport.connect("COM7")
            wait_for(events, Connected)
            _, received = wait_for(events, LineReceived)
            deadline = time.monotonic() + 1
            while b"TELEM:1\n" not in fake.writes and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(fake.dtr)
            self.assertFalse(fake.rts)
            self.assertIn(b"STATUS\n", fake.writes)
            self.assertIn(b"TELEM:1\n", fake.writes)
            transport.send_line("HELP")
            self.assertEqual(fake.writes[-1], b"HELP\n")
            transport.disconnect()
            disconnected, _ = wait_for(events, Disconnected)
            self.assertTrue(disconnected.expected)
            self.assertIn(b"TELEM:0\n", fake.writes)
            self.assertTrue(any(isinstance(event, LineReceived) for event in received))

    def test_ble_scans_connects_notifies_writes_and_disconnects(self) -> None:
        native = types.SimpleNamespace(address="AA:BB", name="FDEM-TX")
        advertisement = types.SimpleNamespace(
            local_name="FDEM-TX", service_uuids=["6e400001-b5a3-f393-e0a9-e50e24dcca9e"], rssi=-42
        )

        class FakeScanner:
            def __init__(self, detection_callback, service_uuids):
                self.callback = detection_callback
                self.service_uuids = service_uuids

            async def __aenter__(self):
                self.callback(native, advertisement)
                return self

            async def __aexit__(self, *_args):
                return False

        clients = []

        class FakeClient:
            def __init__(self, device, disconnected_callback, timeout, winrt):
                self.device = device
                self.disconnected_callback = disconnected_callback
                self.timeout = timeout
                self.winrt = winrt
                self.is_connected = False
                self.notification = None
                self.writes = []
                clients.append(self)

            async def connect(self):
                self.is_connected = True

            async def start_notify(self, _uuid, callback):
                self.notification = callback

            async def stop_notify(self, _uuid):
                pass

            async def write_gatt_char(self, uuid, data, response):
                self.writes.append((uuid, bytes(data), response))

            async def disconnect(self):
                self.is_connected = False
                self.disconnected_callback(self)

        bleak_module = types.ModuleType("bleak")
        bleak_module.BleakScanner = FakeScanner
        bleak_module.BleakClient = FakeClient
        events: Queue = Queue()
        with patch.dict(sys.modules, {"bleak": bleak_module}):
            transport = BleTransport(events.put)
            try:
                transport.scan(timeout=0.01)
                scan, _ = wait_for(events, BleScanCompleted)
                self.assertEqual(len(scan.devices), 1)
                self.assertEqual(scan.devices[0].rssi, -42)
                transport.connect(scan.devices[0])
                wait_for(events, Connected)
                deadline = time.monotonic() + 1
                while not clients[0].writes and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(clients[0].winrt, {"use_cached_services": True})
                self.assertEqual(clients[0].timeout, 20.0)
                self.assertEqual(clients[0].writes[0][1], b"STATUS\n")
                self.assertFalse(clients[0].writes[0][2])
                clients[0].notification(None, bytearray(b"BAT:12.4,"))
                clients[0].notification(None, bytearray(b"-12.3,80\n"))
                line, _ = wait_for(events, LineReceived)
                self.assertEqual(line.line, "BAT:12.4,-12.3,80")
                transport.send_line("HELP")
                deadline = time.monotonic() + 1
                while len(clients[0].writes) < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(clients[0].writes[-1][1], b"HELP\n")
                transport.disconnect()
                disconnected, _ = wait_for(events, Disconnected)
                self.assertTrue(disconnected.expected)
            finally:
                transport.shutdown()

    def test_ble_retries_windows_bad_command_with_uncached_discovery(self) -> None:
        native = types.SimpleNamespace(address="AA:BB", name="FDEM-TX")
        device = BleDeviceInfo(identifier="AA:BB", name="FDEM-TX", rssi=-39, native=native)
        clients = []

        class FakeClient:
            def __init__(self, target, disconnected_callback, timeout, winrt):
                self.target = target
                self.disconnected_callback = disconnected_callback
                self.timeout = timeout
                self.winrt = winrt
                self.is_connected = False
                self.writes = []
                clients.append(self)

            async def connect(self):
                if self.winrt["use_cached_services"]:
                    raise PermissionError(13, "The device does not recognize the command", None, -2147024874)
                self.is_connected = True

            async def start_notify(self, _uuid, _callback):
                pass

            async def write_gatt_char(self, uuid, data, response):
                self.writes.append((uuid, bytes(data), response))

            async def stop_notify(self, _uuid):
                pass

            async def disconnect(self):
                self.is_connected = False
                self.disconnected_callback(self)

        bleak_module = types.ModuleType("bleak")
        bleak_module.BleakClient = FakeClient
        events: Queue = Queue()
        with patch.dict(sys.modules, {"bleak": bleak_module}):
            transport = BleTransport(events.put)
            try:
                transport.connect(device)
                connected, received = wait_for(events, Connected)
                self.assertEqual(connected.target, "FDEM-TX")
                self.assertEqual(len(clients), 2)
                self.assertEqual(clients[0].winrt, {"use_cached_services": True})
                self.assertEqual(clients[1].winrt, {"use_cached_services": False})
                self.assertFalse(any(isinstance(event, Disconnected) for event in received))
            finally:
                transport.shutdown()


if __name__ == "__main__":
    unittest.main()
