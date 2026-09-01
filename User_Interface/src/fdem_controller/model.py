from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time

from .constants import TELEMETRY_STALE_SECONDS
from .events import TransportKind
from .protocol import Acknowledgement, BatteryTelemetry, CalibrationProgress, DeviceError, DeviceStatus, ProtocolMessage


class DisconnectRequirement(str, Enum):
    BLOCKED_CALIBRATION = "blocked_calibration"
    DIRECT = "direct"
    CONFIRM_ACTIVE = "confirm_active"
    CONFIRM_UNKNOWN = "confirm_unknown"


@dataclass
class ControllerState:
    connected: bool = False
    connecting: bool = False
    transport: TransportKind | None = None
    target: str = ""
    synchronized: bool = False
    output_known: bool = False
    frequency_hz: float = 1000.0
    amplitude_vpp: float = 0.0
    waveform: str = "S"
    user_trim_steps: int = 0
    calibration_running: bool = False
    calibration_detail: str = "idle"
    calibration_gain: float | None = None
    bluetooth_enabled: bool | None = None
    positive_rail: float | None = None
    negative_rail: float | None = None
    battery_percent: int | None = None
    battery_available: bool = True
    last_telemetry_at: float = 0.0
    last_error: str = ""

    @property
    def controls_enabled(self) -> bool:
        return self.connected and self.synchronized and not self.calibration_running

    @property
    def output_active(self) -> bool | None:
        return self.amplitude_vpp > 0.0 if self.output_known else None

    @property
    def disconnect_requirement(self) -> DisconnectRequirement:
        if self.calibration_running:
            return DisconnectRequirement.BLOCKED_CALIBRATION
        if self.output_active is True:
            return DisconnectRequirement.CONFIRM_ACTIVE
        if self.output_active is None:
            return DisconnectRequirement.CONFIRM_UNKNOWN
        return DisconnectRequirement.DIRECT

    def telemetry_stale(self, now: float | None = None) -> bool:
        if not self.last_telemetry_at:
            return True
        return (time.monotonic() if now is None else now) - self.last_telemetry_at >= TELEMETRY_STALE_SECONDS

    def begin_connect(self, transport: TransportKind, target: str) -> None:
        self.connecting = True
        self.connected = False
        self.transport = transport
        self.target = target
        self.synchronized = False
        self.output_known = False
        self.last_error = ""

    def mark_connected(self) -> None:
        self.connecting = False
        self.connected = True

    def mark_disconnected(self, error: str = "") -> None:
        self.connected = False
        self.connecting = False
        self.synchronized = False
        self.output_known = False
        self.transport = None
        self.target = ""
        self.last_error = error

    def apply(self, message: ProtocolMessage, now: float | None = None) -> None:
        if isinstance(message, BatteryTelemetry):
            self._apply_battery(message, now)
        elif isinstance(message, DeviceStatus):
            self._apply_status(message, now)
        elif isinstance(message, CalibrationProgress):
            self.calibration_running = True
            self.calibration_detail = (
                f"sweep:{message.point}/{message.total}" if message.stage == "sweep" else message.stage
            )
        elif isinstance(message, Acknowledgement):
            self._apply_ack(message)
        elif isinstance(message, DeviceError):
            self.last_error = message.code
            if message.code.startswith("CAL:"):
                self.calibration_running = False
                self.calibration_detail = f"failed:{message.code}"

    def _apply_battery(self, battery: BatteryTelemetry, now: float | None) -> None:
        self.positive_rail = battery.positive_volts
        self.negative_rail = battery.negative_volts
        self.battery_percent = battery.health_percent
        self.battery_available = True
        self.last_telemetry_at = time.monotonic() if now is None else now

    def _apply_status(self, status: DeviceStatus, now: float | None) -> None:
        if status.frequency_hz is not None:
            self.frequency_hz = status.frequency_hz
        if status.amplitude_vpp is not None:
            self.amplitude_vpp = status.amplitude_vpp
            self.output_known = True
        if status.waveform is not None:
            self.waveform = status.waveform
        if status.trim_codes is not None:
            self.user_trim_steps = -status.trim_codes
        if status.calibration is not None:
            self.calibration_running = status.calibration == "RUNNING"
            self.calibration_detail = "running" if self.calibration_running else "idle"
        if status.calibration_gain is not None:
            self.calibration_gain = status.calibration_gain
        if status.bluetooth_enabled is not None:
            self.bluetooth_enabled = status.bluetooth_enabled
        if status.battery is not None:
            self._apply_battery(status.battery, now)
        elif not status.battery_available:
            self.positive_rail = None
            self.negative_rail = None
            self.battery_percent = None
            self.battery_available = False
        self.synchronized = True

    def _apply_ack(self, ack: Acknowledgement) -> None:
        if ack.kind == "cal_started":
            self.calibration_running = True
            self.calibration_detail = "sweep:1/5"
            return
        if ack.kind in {"cal_complete", "cal_clear"}:
            self.calibration_running = False
            self.calibration_detail = "complete" if ack.kind == "cal_complete" else "idle"
            try:
                self.calibration_gain = float(ack.value)
            except ValueError:
                pass
            return
        fields = ack.fields
        try:
            if "F" in fields:
                self.frequency_hz = float(fields["F"])
            if "A" in fields:
                self.amplitude_vpp = float(fields["A"])
                self.output_known = True
            if fields.get("W") in {"S", "T"}:
                self.waveform = fields["W"]
            if "TRIM" in fields:
                self.user_trim_steps = -int(fields["TRIM"])
            if fields.get("BLT") in {"0", "1"}:
                self.bluetooth_enabled = fields["BLT"] == "1"
        except ValueError:
            self.last_error = "INVALID_ACKNOWLEDGEMENT"
