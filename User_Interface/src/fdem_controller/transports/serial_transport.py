from __future__ import annotations

import threading
import time
from typing import Any

from ..constants import BAUD_RATE
from ..events import Connected, Disconnected, LineReceived, SerialPortInfo, TransportFailure, TransportKind
from ..protocol import LineFramer, ProtocolValueError
from .base import EventSink, Transport


class SerialTransport(Transport):
    kind = TransportKind.USB

    def __init__(self, event_sink: EventSink) -> None:
        super().__init__(event_sink)
        self._serial: Any | None = None
        self._port = ""
        self._reader: threading.Thread | None = None
        self._bootstrap_timer: threading.Timer | None = None
        self._bootstrap_sent = False
        self._expected_disconnect = False
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()

    @staticmethod
    def list_ports() -> list[SerialPortInfo]:
        from serial.tools import list_ports

        ports = [
            SerialPortInfo(
                device=port.device,
                description=(port.description or "").strip(),
                hardware_id=(port.hwid or "").strip(),
            )
            for port in list_ports.comports()
        ]
        return sorted(ports, key=lambda item: item.device.lower())

    @property
    def connected(self) -> bool:
        serial_port = self._serial
        return bool(serial_port is not None and getattr(serial_port, "is_open", False) and not self._stop.is_set())

    def connect(self, port: str) -> None:
        import serial

        if self.connected:
            raise RuntimeError("Serial transport is already connected")
        serial_port = serial.Serial(
            port=None,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
            write_timeout=2.0,
        )
        serial_port.dtr = False
        serial_port.rts = False
        serial_port.port = port
        serial_port.open()

        with self._state_lock:
            self._serial = serial_port
            self._port = port
            self._expected_disconnect = False
            self._bootstrap_sent = False
            self._stop.clear()

        self.event_sink(Connected(self.kind, port))
        self._reader = threading.Thread(target=self._read_loop, name="FDEM-USB-reader", daemon=True)
        self._reader.start()
        self._bootstrap_timer = threading.Timer(0.8, self._send_bootstrap)
        self._bootstrap_timer.daemon = True
        self._bootstrap_timer.start()

    def _send_bootstrap(self) -> None:
        with self._state_lock:
            if self._bootstrap_sent or not self.connected:
                return
            self._bootstrap_sent = True
        try:
            self.send_line("STATUS")
            self.send_line("TELEM:1")
        except Exception as error:  # transport error is reported through the shared event stream
            self.event_sink(TransportFailure(self.kind, str(error)))

    def send_line(self, line: str) -> None:
        data = (line.rstrip("\r\n") + "\n").encode("utf-8")
        with self._write_lock:
            serial_port = self._serial
            if serial_port is None or not serial_port.is_open:
                raise RuntimeError("USB serial is not connected")
            serial_port.write(data)
            serial_port.flush()

    def _read_loop(self) -> None:
        framer = LineFramer()
        unexpected_reason = ""
        try:
            while not self._stop.is_set():
                serial_port = self._serial
                if serial_port is None or not serial_port.is_open:
                    break
                chunk = serial_port.read(max(1, getattr(serial_port, "in_waiting", 0)))
                if not chunk:
                    continue
                try:
                    lines = framer.feed(chunk)
                except ProtocolValueError as error:
                    self.event_sink(TransportFailure(self.kind, str(error)))
                    continue
                for line in lines:
                    self.event_sink(LineReceived(self.kind, line))
                    if line.startswith("FDEM-TX READY"):
                        self._send_bootstrap()
        except Exception as error:
            unexpected_reason = str(error)
            if not self._expected_disconnect:
                self.event_sink(TransportFailure(self.kind, unexpected_reason))
        finally:
            if not self._expected_disconnect:
                self._close_port()
                self.event_sink(Disconnected(self.kind, unexpected_reason, expected=False))

    def _close_port(self) -> None:
        serial_port = self._serial
        self._serial = None
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                pass

    def disconnect(self) -> None:
        if self._serial is None:
            return
        self._expected_disconnect = True
        if self._bootstrap_timer is not None:
            self._bootstrap_timer.cancel()
            self._bootstrap_timer = None
        try:
            if self.connected:
                self.send_line("TELEM:0")
                time.sleep(0.05)
        except Exception:
            pass
        self._stop.set()
        self._close_port()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=0.5)
        self._reader = None
        self.event_sink(Disconnected(self.kind, expected=True))
