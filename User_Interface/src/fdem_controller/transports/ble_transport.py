from __future__ import annotations

import asyncio
from concurrent.futures import Future
import threading
from typing import Any

from ..constants import BLE_DEVICE_NAME, BLE_SCAN_SECONDS, NUS_RX_UUID, NUS_SERVICE_UUID, NUS_TX_UUID
from ..events import (
    BleDeviceInfo,
    BleScanCompleted,
    Connected,
    Disconnected,
    LineReceived,
    TransportFailure,
    TransportKind,
)
from ..protocol import LineFramer, ProtocolValueError
from .base import EventSink, Transport


class BleTransport(Transport):
    kind = TransportKind.BLE

    def __init__(self, event_sink: EventSink) -> None:
        super().__init__(event_sink)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="FDEM-BLE-loop", daemon=True)
        self._thread.start()
        self._client: Any | None = None
        self._connected = False
        self._expected_disconnect = False
        self._disconnect_reported = False
        self._framer = LineFramer()
        self._write_lock = asyncio.Lock()
        self._target = ""

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()

    def _submit(self, coroutine: Any) -> Future[Any]:
        if not self._loop.is_running():
            raise RuntimeError("Bluetooth worker is not running")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    @property
    def connected(self) -> bool:
        return self._connected

    def scan(self, timeout: float = BLE_SCAN_SECONDS) -> None:
        self._submit(self._scan(timeout))

    async def _scan(self, timeout: float) -> None:
        from bleak import BleakScanner

        found: dict[str, BleDeviceInfo] = {}

        def detected(device: Any, advertisement: Any) -> None:
            name = (getattr(advertisement, "local_name", None) or getattr(device, "name", None) or "").strip()
            service_uuids = {value.lower() for value in (getattr(advertisement, "service_uuids", None) or [])}
            if name != BLE_DEVICE_NAME and NUS_SERVICE_UUID.lower() not in service_uuids:
                return
            identifier = str(getattr(device, "address", "") or getattr(device, "name", "") or id(device))
            found[identifier] = BleDeviceInfo(
                identifier=identifier,
                name=name or BLE_DEVICE_NAME,
                rssi=getattr(advertisement, "rssi", None),
                native=device,
            )

        try:
            async with BleakScanner(detection_callback=detected, service_uuids=[NUS_SERVICE_UUID]):
                await asyncio.sleep(timeout)
            devices = tuple(sorted(found.values(), key=lambda item: (item.name.lower(), item.identifier.lower())))
            self.event_sink(BleScanCompleted(devices))
        except Exception as error:
            self.event_sink(BleScanCompleted((), str(error)))

    def connect(self, device: BleDeviceInfo) -> None:
        self._submit(self._connect(device))

    async def _connect(self, device: BleDeviceInfo) -> None:
        from bleak import BleakClient

        if self._connected:
            self.event_sink(TransportFailure(self.kind, "Bluetooth is already connected"))
            return
        self._expected_disconnect = False
        self._disconnect_reported = False
        self._framer.clear()
        self._target = device.name or device.identifier
        client: Any | None = None
        stage = "initialization"
        try:
            # Supplying a service UUID filter makes WinRT use its
            # GetGattServicesForUuid path.  On affected Windows 11 versions
            # that path fails with 0x80070016 (ERROR_BAD_COMMAND) during
            # discovery even though the radio connection is healthy.  Let
            # Windows enumerate the small database instead.  Try its cache
            # first, then force a fresh enumeration for stale-cache cases.
            discovery_modes = (
                ("cached GATT service discovery", True),
                ("uncached GATT service discovery", False),
            )
            for attempt, (stage, use_cache) in enumerate(discovery_modes):
                client = BleakClient(
                    device.native or device.identifier,
                    disconnected_callback=self._on_disconnected,
                    timeout=20.0,
                    winrt={"use_cached_services": use_cache},
                )
                self._client = client
                try:
                    await client.connect()
                    stage = "notification subscription"
                    await client.start_notify(NUS_TX_UUID, self._notification)
                    break
                except Exception as error:
                    can_retry = attempt == 0 and self._is_windows_discovery_error(error)
                    old_client = client
                    self._client = None
                    if getattr(old_client, "is_connected", False):
                        try:
                            await old_client.disconnect()
                        except Exception:
                            pass
                    if not can_retry:
                        raise
                    await asyncio.sleep(0.5)
            else:  # pragma: no cover - the loop either succeeds or raises
                raise RuntimeError("Bluetooth discovery attempts were exhausted")

            self._connected = True
            self.event_sink(Connected(self.kind, self._target))
            # Give WinRT a brief opportunity to finish enabling notifications
            # before the first command is queued to the NUS RX characteristic.
            await asyncio.sleep(0.1)
            await self._send("STATUS")
        except Exception as error:
            if not str(error).startswith("Bluetooth write failed:"):
                self.event_sink(TransportFailure(self.kind, f"Bluetooth {stage} failed: {error}"))
            self._report_disconnected(str(error), expected=False)
            # A failed first write does not necessarily make WinRT release the
            # radio link.  Close the local connection before forgetting it so
            # the next scan/connect attempt is not blocked by a stale session.
            if client is not None and getattr(client, "is_connected", False):
                try:
                    await client.disconnect()
                except Exception:
                    pass

    @staticmethod
    def _is_windows_discovery_error(error: Exception) -> bool:
        """Return whether retrying WinRT discovery without its cache is useful."""
        winerror = getattr(error, "winerror", None)
        message = str(error).lower()
        return (
            winerror in {-2147024874, 0x80070016}
            or "does not recognize the command" in message
            or "no reconoce el comando" in message
            or "characteristic" in message and "not found" in message
        )

    def _notification(self, _characteristic: Any, data: bytearray) -> None:
        try:
            lines = self._framer.feed(bytes(data))
        except ProtocolValueError as error:
            self.event_sink(TransportFailure(self.kind, str(error)))
            return
        for line in lines:
            self.event_sink(LineReceived(self.kind, line))

    def send_line(self, line: str) -> None:
        future = self._submit(self._send(line))
        future.add_done_callback(self._consume_future)

    @staticmethod
    def _consume_future(future: Future[Any]) -> None:
        try:
            future.exception()
        except Exception:
            pass

    async def _send(self, line: str) -> None:
        client = self._client
        if client is None or not self._connected:
            raise RuntimeError("Bluetooth is not connected")
        data = (line.rstrip("\r\n") + "\n").encode("utf-8")
        try:
            async with self._write_lock:
                # The firmware's NUS RX characteristic explicitly supports
                # WRITE_NR.  WinRT can reject a write-with-response request
                # with ERROR_BAD_COMMAND even when service discovery and
                # notification subscription succeeded.
                await client.write_gatt_char(NUS_RX_UUID, data, response=False)
        except Exception as error:
            message = f"Bluetooth write failed: {error}"
            self.event_sink(TransportFailure(self.kind, message))
            raise RuntimeError(message) from error

    def _on_disconnected(self, client: Any) -> None:
        # Ignore callbacks from a failed discovery attempt after its client
        # has already been superseded or explicitly cleared.
        if client is not self._client:
            return
        self._loop.call_soon_threadsafe(
            self._report_disconnected, "Bluetooth link disconnected", self._expected_disconnect
        )

    def _report_disconnected(self, reason: str, expected: bool) -> None:
        if self._disconnect_reported:
            return
        self._disconnect_reported = True
        self._connected = False
        self._client = None
        self.event_sink(Disconnected(self.kind, reason, expected=expected))

    def disconnect(self) -> None:
        if self._client is None and not self._connected:
            return
        self._expected_disconnect = True
        self._submit(self._disconnect())

    async def _disconnect(self) -> None:
        client = self._client
        try:
            if client is not None and getattr(client, "is_connected", False):
                try:
                    await client.stop_notify(NUS_TX_UUID)
                except Exception:
                    pass
                await client.disconnect()
        except Exception as error:
            self.event_sink(TransportFailure(self.kind, str(error)))
        finally:
            self._report_disconnected("", expected=True)

    def shutdown(self) -> None:
        if not self._loop.is_running():
            return
        try:
            if self._client is not None or self._connected:
                self._expected_disconnect = True
                self._submit(self._disconnect()).result(timeout=2.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
