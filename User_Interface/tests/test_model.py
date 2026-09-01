from __future__ import annotations

import unittest

from fdem_controller.events import TransportKind
from fdem_controller.model import ControllerState, DisconnectRequirement
from fdem_controller.protocol import Acknowledgement, BatteryTelemetry, CalibrationProgress, DeviceError, DeviceStatus


class ModelTests(unittest.TestCase):
    def test_controls_require_connection_status_and_idle_calibration(self) -> None:
        state = ControllerState()
        state.begin_connect(TransportKind.USB, "COM3")
        state.mark_connected()
        self.assertFalse(state.controls_enabled)
        state.apply(DeviceStatus(amplitude_vpp=0, calibration="IDLE"))
        self.assertTrue(state.controls_enabled)
        state.apply(Acknowledgement("cal_started", value="STEP:1/5"))
        self.assertFalse(state.controls_enabled)
        self.assertEqual(state.disconnect_requirement, DisconnectRequirement.BLOCKED_CALIBRATION)

    def test_status_maps_firmware_trim_to_user_direction(self) -> None:
        state = ControllerState(connected=True)
        state.apply(
            DeviceStatus(
                frequency_hz=123.4,
                amplitude_vpp=5.02,
                waveform="T",
                trim_codes=-7,
                bluetooth_enabled=True,
                calibration="IDLE",
                calibration_gain=1.04,
            )
        )
        self.assertTrue(state.synchronized)
        self.assertEqual(state.user_trim_steps, 7)
        self.assertEqual(state.disconnect_requirement, DisconnectRequirement.CONFIRM_ACTIVE)

    def test_acknowledgement_uses_applied_amplitude(self) -> None:
        state = ControllerState(connected=True, synchronized=True, output_known=True)
        state.apply(Acknowledgement(fields={"F": "1000.00", "A": "4.020", "W": "S", "TRIM": "2"}))
        self.assertEqual(state.amplitude_vpp, 4.02)
        self.assertEqual(state.user_trim_steps, -2)

    def test_disconnect_policy_covers_muted_and_unknown_outputs(self) -> None:
        state = ControllerState(connected=True, output_known=False)
        self.assertEqual(state.disconnect_requirement, DisconnectRequirement.CONFIRM_UNKNOWN)
        state.output_known = True
        state.amplitude_vpp = 0
        self.assertEqual(state.disconnect_requirement, DisconnectRequirement.DIRECT)

    def test_telemetry_stale_after_three_seconds(self) -> None:
        state = ControllerState()
        state.apply(BatteryTelemetry(12.2, -12.1, 75), now=10.0)
        self.assertFalse(state.telemetry_stale(now=12.99))
        self.assertTrue(state.telemetry_stale(now=13.0))

    def test_calibration_failure_unlocks_controls(self) -> None:
        state = ControllerState(connected=True, synchronized=True)
        state.apply(CalibrationProgress("perturb"))
        self.assertTrue(state.calibration_running)
        state.apply(DeviceError("CAL:NONLINEAR"))
        self.assertFalse(state.calibration_running)
        self.assertTrue(state.controls_enabled)


if __name__ == "__main__":
    unittest.main()

