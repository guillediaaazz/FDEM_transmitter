from __future__ import annotations

import unittest

from fdem_controller.protocol import (
    Acknowledgement,
    BatteryTelemetry,
    CalibrationProgress,
    DeviceError,
    DeviceStatus,
    LineFramer,
    ProtocolValueError,
    RawMessage,
    build_amplitude_command,
    build_settings_command,
    build_trim_command,
    parse_message,
    trim_output_volts,
)


class ProtocolTests(unittest.TestCase):
    def test_builds_firmware_commands_and_inverts_user_trim(self) -> None:
        self.assertEqual(build_settings_command(1000, 12.5, "s"), "F:1000 A:12.5 W:S")
        self.assertEqual(build_amplitude_command(0), "A:0")
        self.assertEqual(build_trim_command(1), "TRIM:-1")
        self.assertEqual(build_trim_command(-255), "TRIM:255")
        self.assertAlmostEqual(trim_output_volts(1), (2.048 / 4096) * 16.667)

    def test_rejects_out_of_range_values(self) -> None:
        for frequency in (0, 8000.1):
            with self.assertRaises(ProtocolValueError):
                build_settings_command(frequency, 1, "S")
        for amplitude in (-0.1, 20.1):
            with self.assertRaises(ProtocolValueError):
                build_settings_command(1000, amplitude, "S")
        with self.assertRaises(ProtocolValueError):
            build_settings_command(1000, 1, "X")
        with self.assertRaises(ProtocolValueError):
            build_trim_command(256)

    def test_line_framer_handles_fragmentation_cr_lf_and_crlf(self) -> None:
        framer = LineFramer()
        self.assertEqual(framer.feed(b"STATUS:F:1000,A:4,W:S,TR"), [])
        self.assertEqual(
            framer.feed(b"IM:-1\r\nBAT:12.5,-12.4,87\rHELP:abc\n"),
            ["STATUS:F:1000,A:4,W:S,TRIM:-1", "BAT:12.5,-12.4,87", "HELP:abc"],
        )

    def test_parses_full_status_and_user_trim_direction(self) -> None:
        message = parse_message(
            "STATUS:F:1000.00,A:4.020,W:T,TRIM:-3,TRIM_OUT:-0.025,CAL:IDLE,CAL_GAIN:1.04000,"
            "BLT:1,TELEM:0,WIPER:51,DACB_NOM:0.1234,DACA:0.2895,DACB:0.1219,"
            "BATP:12.50,BATN:-12.40,BAT:87"
        )
        self.assertIsInstance(message, DeviceStatus)
        assert isinstance(message, DeviceStatus)
        self.assertEqual(message.frequency_hz, 1000.0)
        self.assertEqual(message.amplitude_vpp, 4.02)
        self.assertEqual(message.waveform, "T")
        self.assertEqual(message.trim_codes, -3)
        self.assertTrue(message.bluetooth_enabled)
        self.assertFalse(message.telemetry_enabled)
        self.assertEqual(message.battery, BatteryTelemetry(12.5, -12.4, 87))

    def test_parses_battery_unavailable_and_malformed_battery(self) -> None:
        status = parse_message("STATUS:F:1000,A:0,W:S,TRIM:0,CAL:IDLE,BLT:1,BAT:UNAVAILABLE")
        self.assertIsInstance(status, DeviceStatus)
        assert isinstance(status, DeviceStatus)
        self.assertFalse(status.battery_available)
        self.assertIsNone(status.battery)
        self.assertIsInstance(parse_message("BAT:broken"), RawMessage)

    def test_parses_calibration_ack_progress_error_and_unknown(self) -> None:
        self.assertEqual(parse_message("CAL:STEP:3/5"), CalibrationProgress("sweep", 3, 5))
        self.assertEqual(parse_message("CAL:STEP:PERTURB"), CalibrationProgress("perturb"))
        self.assertEqual(
            parse_message("OK:CAL:COMPLETE:GAIN:1.04000"),
            Acknowledgement("cal_complete", value="1.04000"),
        )
        self.assertEqual(parse_message("ERR:CAL:NONLINEAR"), DeviceError("CAL:NONLINEAR"))
        self.assertEqual(parse_message("DDS:DIAG:F:1000"), RawMessage("DDS:DIAG:F:1000"))


if __name__ == "__main__":
    unittest.main()

