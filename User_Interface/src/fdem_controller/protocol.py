from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

from .constants import (
    DAC_B_LSB_VOLTS,
    MAX_AMPLITUDE_VPP,
    MAX_FREQUENCY_HZ,
    MAX_PROTOCOL_LINE,
    MAX_TRIM_STEPS,
    MIN_AMPLITUDE_VPP,
    MIN_FREQUENCY_HZ,
    MIN_TRIM_STEPS,
    POWER_STAGE_GAIN,
)


class ProtocolValueError(ValueError):
    """Raised when a controller value cannot be represented by the firmware protocol."""


@dataclass(frozen=True)
class BatteryTelemetry:
    positive_volts: float
    negative_volts: float
    health_percent: int


@dataclass(frozen=True)
class DeviceStatus:
    frequency_hz: float | None = None
    amplitude_vpp: float | None = None
    waveform: str | None = None
    trim_codes: int | None = None
    trim_output_volts: float | None = None
    calibration: str | None = None
    calibration_gain: float | None = None
    bluetooth_enabled: bool | None = None
    telemetry_enabled: bool | None = None
    wiper: int | None = None
    dac_b_nominal_volts: float | None = None
    dac_a_volts: float | None = None
    dac_b_volts: float | None = None
    battery: BatteryTelemetry | None = None
    battery_available: bool = True
    fields: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CalibrationProgress:
    stage: str
    point: int | None = None
    total: int | None = None


@dataclass(frozen=True)
class Acknowledgement:
    kind: str = "settings"
    fields: Mapping[str, str] = field(default_factory=dict)
    value: str = ""


@dataclass(frozen=True)
class DeviceError:
    code: str


@dataclass(frozen=True)
class HelpMessage:
    text: str


@dataclass(frozen=True)
class BootMessage:
    ready: bool
    text: str


@dataclass(frozen=True)
class RawMessage:
    text: str


ProtocolMessage = (
    BatteryTelemetry
    | DeviceStatus
    | CalibrationProgress
    | Acknowledgement
    | DeviceError
    | HelpMessage
    | BootMessage
    | RawMessage
)


class LineFramer:
    """Turn arbitrarily fragmented CR/LF text into complete protocol lines."""

    def __init__(self, maximum_buffer: int = MAX_PROTOCOL_LINE) -> None:
        self._buffer = ""
        self._maximum_buffer = maximum_buffer

    @property
    def buffered_text(self) -> str:
        return self._buffer

    def clear(self) -> None:
        self._buffer = ""

    def feed(self, data: bytes | str) -> list[str]:
        text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
        self._buffer += text.replace("\r", "\n")
        if len(self._buffer) > self._maximum_buffer and "\n" not in self._buffer:
            self._buffer = ""
            raise ProtocolValueError("RECEIVE_BUFFER_TOO_LONG")

        lines: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line:
                lines.append(line)
        return lines


def _bounded_number(value: float, minimum: float, maximum: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ProtocolValueError(f"INVALID_{name}") from error
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ProtocolValueError(f"{name}_OUT_OF_RANGE")
    return number


def _format_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def build_settings_command(frequency_hz: float, amplitude_vpp: float, waveform: str) -> str:
    frequency = _bounded_number(frequency_hz, MIN_FREQUENCY_HZ, MAX_FREQUENCY_HZ, "FREQUENCY")
    amplitude = _bounded_number(amplitude_vpp, MIN_AMPLITUDE_VPP, MAX_AMPLITUDE_VPP, "AMPLITUDE")
    waveform = waveform.upper()
    if waveform not in {"S", "T"}:
        raise ProtocolValueError("INVALID_WAVEFORM")
    return f"F:{_format_number(frequency)} A:{_format_number(amplitude)} W:{waveform}"


def build_amplitude_command(amplitude_vpp: float) -> str:
    amplitude = _bounded_number(amplitude_vpp, MIN_AMPLITUDE_VPP, MAX_AMPLITUDE_VPP, "AMPLITUDE")
    return f"A:{_format_number(amplitude)}"


def build_trim_command(user_steps: int) -> str:
    try:
        steps = int(user_steps)
    except (TypeError, ValueError) as error:
        raise ProtocolValueError("INVALID_TRIM") from error
    if not MIN_TRIM_STEPS <= steps <= MAX_TRIM_STEPS:
        raise ProtocolValueError("TRIM_OUT_OF_RANGE")
    return f"TRIM:{-steps}"


def trim_output_volts(user_steps: int) -> float:
    return int(user_steps) * DAC_B_LSB_VOLTS * POWER_STAGE_GAIN


def _pairs(payload: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in payload.split(","):
        key, separator, value = entry.partition(":")
        if separator and key:
            result[key] = value
    return result


def _float(fields: Mapping[str, str], key: str) -> float | None:
    try:
        return float(fields[key])
    except (KeyError, TypeError, ValueError):
        return None


def _int(fields: Mapping[str, str], key: str) -> int | None:
    try:
        return int(fields[key])
    except (KeyError, TypeError, ValueError):
        return None


def _switch(fields: Mapping[str, str], key: str) -> bool | None:
    value = fields.get(key)
    return True if value == "1" else False if value == "0" else None


def parse_message(raw_line: str) -> ProtocolMessage:
    line = raw_line.strip()
    if not line:
        return RawMessage("")
    if line.startswith("BAT:"):
        values = line[4:].split(",")
        if len(values) == 3:
            try:
                return BatteryTelemetry(float(values[0]), float(values[1]), max(0, min(100, int(values[2]))))
            except ValueError:
                pass
        return RawMessage(line)
    if line.startswith("STATUS:"):
        fields = _pairs(line[7:])
        battery: BatteryTelemetry | None = None
        available = fields.get("BAT") != "UNAVAILABLE"
        if available and {"BATP", "BATN", "BAT"}.issubset(fields):
            try:
                battery = BatteryTelemetry(
                    float(fields["BATP"]), float(fields["BATN"]), max(0, min(100, int(fields["BAT"])))
                )
            except ValueError:
                battery = None
        return DeviceStatus(
            frequency_hz=_float(fields, "F"),
            amplitude_vpp=_float(fields, "A"),
            waveform=fields.get("W") if fields.get("W") in {"S", "T"} else None,
            trim_codes=_int(fields, "TRIM"),
            trim_output_volts=_float(fields, "TRIM_OUT"),
            calibration=fields.get("CAL"),
            calibration_gain=_float(fields, "CAL_GAIN"),
            bluetooth_enabled=_switch(fields, "BLT"),
            telemetry_enabled=_switch(fields, "TELEM"),
            wiper=_int(fields, "WIPER"),
            dac_b_nominal_volts=_float(fields, "DACB_NOM"),
            dac_a_volts=_float(fields, "DACA"),
            dac_b_volts=_float(fields, "DACB"),
            battery=battery,
            battery_available=available,
            fields=fields,
        )
    if line.startswith("CAL:STEP:"):
        stage = line[9:]
        if "/" in stage:
            point_text, total_text = stage.split("/", 1)
            try:
                return CalibrationProgress("sweep", int(point_text), int(total_text))
            except ValueError:
                pass
        return CalibrationProgress("perturb" if stage == "PERTURB" else stage.lower())
    if line == "OK":
        return Acknowledgement()
    if line.startswith("OK:CAL:STARTED:"):
        return Acknowledgement("cal_started", value=line.removeprefix("OK:CAL:STARTED:"))
    if line.startswith("OK:CAL:COMPLETE:GAIN:"):
        return Acknowledgement("cal_complete", value=line.removeprefix("OK:CAL:COMPLETE:GAIN:"))
    if line.startswith("OK:CAL:CLEAR:GAIN:"):
        return Acknowledgement("cal_clear", value=line.removeprefix("OK:CAL:CLEAR:GAIN:"))
    if line.startswith("OK:"):
        tokens = line[3:].split(":")
        fields = {tokens[index]: tokens[index + 1] for index in range(0, len(tokens) - 1, 2)}
        return Acknowledgement(fields=fields)
    if line.startswith("ERR:"):
        return DeviceError(line[4:])
    if line.startswith("HELP:"):
        return HelpMessage(line[5:])
    if line.startswith("FDEM-TX READY"):
        return BootMessage("CONFIGURE PINS" not in line, line)
    return RawMessage(line)

