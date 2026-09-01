from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TransportKind(str, Enum):
    USB = "usb"
    BLE = "ble"


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str
    hardware_id: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.device} — {self.description}" if self.description else self.device


@dataclass(frozen=True)
class BleDeviceInfo:
    identifier: str
    name: str
    rssi: int | None = None
    native: object | None = None

    @property
    def display_name(self) -> str:
        signal = f" ({self.rssi} dBm)" if self.rssi is not None else ""
        return f"{self.name or 'FDEM-TX'} — {self.identifier}{signal}"


@dataclass(frozen=True)
class Connected:
    transport: TransportKind
    target: str


@dataclass(frozen=True)
class Disconnected:
    transport: TransportKind
    reason: str = ""
    expected: bool = False


@dataclass(frozen=True)
class LineReceived:
    transport: TransportKind
    line: str


@dataclass(frozen=True)
class TransportFailure:
    transport: TransportKind
    message: str


@dataclass(frozen=True)
class BleScanCompleted:
    devices: tuple[BleDeviceInfo, ...]
    error: str = ""


TransportEvent = Connected | Disconnected | LineReceived | TransportFailure | BleScanCompleted

