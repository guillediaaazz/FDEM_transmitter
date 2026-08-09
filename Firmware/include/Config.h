#pragma once

#include <Arduino.h>

// This is the only file that should need board-specific adjustment.  Pin
// assignments deliberately default to -1 so a new build cannot accidentally
// drive an unknown connection.
namespace Config {

constexpr int PIN_UNASSIGNED = -1;

// ---- Pin assignments: fill these before connecting the hardware. ----
constexpr int PIN_SPI_SCK = PIN_UNASSIGNED;
constexpr int PIN_SPI_MOSI = PIN_UNASSIGNED;
constexpr int PIN_SPI_MISO = PIN_UNASSIGNED;  // Not used by these write-only ICs.
constexpr int PIN_AD9837_FSYN = PIN_UNASSIGNED;
constexpr int PIN_AD5160_CS = PIN_UNASSIGNED;
constexpr int PIN_MCP4822_CS = PIN_UNASSIGNED;

constexpr int PIN_ADC_POSITIVE_RAIL = PIN_UNASSIGNED;
constexpr int PIN_ADC_NEGATIVE_RAIL = PIN_UNASSIGNED;
constexpr int PIN_ADC_OFFSET_FEEDBACK = PIN_UNASSIGNED;

constexpr int PIN_LED_POSITIVE_GREEN = PIN_UNASSIGNED;
constexpr int PIN_LED_POSITIVE_RED = PIN_UNASSIGNED;
constexpr int PIN_LED_NEGATIVE_GREEN = PIN_UNASSIGNED;
constexpr int PIN_LED_NEGATIVE_RED = PIN_UNASSIGNED;
constexpr int PIN_LED_OUTPUT = PIN_UNASSIGNED;
constexpr int PIN_LED_BLUETOOTH = PIN_UNASSIGNED;

// ---- Serial and BLE ----
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr char BLE_DEVICE_NAME[] = "FDEM-TX";
constexpr bool BLE_ENABLED_AT_BOOT = true;
constexpr char NUS_SERVICE_UUID[] = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char NUS_RX_UUID[] = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";  // Client -> ESP32
constexpr char NUS_TX_UUID[] = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";  // ESP32 -> client
constexpr size_t MAX_COMMAND_LENGTH = 128;
constexpr uint32_t BATTERY_TELEMETRY_INTERVAL_MS = 1000;

// ---- Signal path ----
constexpr float DDS_REFERENCE_CLOCK_HZ = 16000000.0f;
constexpr float DDS_OUTPUT_VPP = 0.600f;
constexpr float PRE_DIGIPOT_BUFFER_GAIN = 2.0f;
// Measure the closed-loop LM1875 gain and replace this nominal value.
constexpr float POWER_STAGE_GAIN_V_V = 16.667f;
constexpr float MIN_FREQUENCY_HZ = 1.0f;
constexpr float MAX_FREQUENCY_HZ = 8000.0f;
constexpr float MIN_OUTPUT_VPP = 0.0f;
constexpr float MAX_OUTPUT_VPP = 20.0f;

// AD5160 wiring: A = signal input, B = ground, W = output.
constexpr uint8_t DIGIPOT_MUTE_WIPER = 0;
constexpr uint8_t DIGIPOT_MAX_SIGNAL_WIPER = 255;

// ---- MCP4822 ----
constexpr float DAC_REFERENCE_VOLTS = 2.048f;
constexpr uint16_t DAC_MAX_CODE = 4095;
constexpr float FEEDBACK_BIAS_DAC_VOLTS = 0.2895f;  // MCP4822 channel A

// ---- Output offset feedback loop ----
constexpr float OFFSET_FEEDBACK_GAIN = 4.7f;
constexpr float OFFSET_FEEDBACK_TARGET_VOLTS = 1.650f;
// +1 means increasing DAC-B code raises the measured ADC voltage; -1 means it lowers it.
constexpr int OFFSET_CORRECTION_POLARITY = -1;
constexpr int OFFSET_CORRECTION_LIMIT_CODES = 600;
constexpr float OFFSET_CALIBRATION_GAIN = 0.70f;
constexpr float OFFSET_AUTO_GAIN = 0.12f;
constexpr float OFFSET_SETTLED_ERROR_VOLTS = 0.010f;
constexpr uint8_t OFFSET_CALIBRATION_MAX_STEPS = 24;
constexpr uint8_t OFFSET_CALIBRATION_SETTLED_STEPS = 3;
constexpr uint32_t OFFSET_CALIBRATION_INTERVAL_MS = 250;
constexpr uint32_t OFFSET_AUTO_INTERVAL_MS = 500;

// ---- ESP32 ADC and battery monitoring ----
constexpr float ADC_VOLTAGE_SCALE = 1.0f;
constexpr float ADC_VOLTAGE_OFFSET_VOLTS = 0.0f;
constexpr uint8_t ADC_AVERAGE_SAMPLES = 8;
constexpr float POSITIVE_RAIL_ADC_ATTENUATION = 0.1754f;
constexpr float NEGATIVE_RAIL_ADC_ATTENUATION = 0.2128f;
constexpr float BATTERY_EMPTY_VOLTS = 10.5f;
constexpr float BATTERY_FULL_VOLTS = 12.6f;

// ---- LED PWM ----
constexpr uint32_t LED_PWM_FREQUENCY_HZ = 5000;
constexpr uint8_t LED_PWM_RESOLUTION_BITS = 8;
constexpr uint8_t LED_PWM_MAX_DUTY = 255;
constexpr uint32_t BLE_ADVERTISING_BLINK_MS = 500;

inline bool pinAssigned(int pin) { return pin != PIN_UNASSIGNED; }

inline bool signalPinsConfigured() {
  return pinAssigned(PIN_SPI_SCK) && pinAssigned(PIN_SPI_MOSI) &&
         pinAssigned(PIN_AD9837_FSYN) && pinAssigned(PIN_AD5160_CS) &&
         pinAssigned(PIN_MCP4822_CS);
}

inline bool powerMonitorPinsConfigured() {
  return pinAssigned(PIN_ADC_POSITIVE_RAIL) && pinAssigned(PIN_ADC_NEGATIVE_RAIL) &&
         pinAssigned(PIN_ADC_OFFSET_FEEDBACK);
}

inline bool ledPinsConfigured() {
  return pinAssigned(PIN_LED_POSITIVE_GREEN) && pinAssigned(PIN_LED_POSITIVE_RED) &&
         pinAssigned(PIN_LED_NEGATIVE_GREEN) && pinAssigned(PIN_LED_NEGATIVE_RED) &&
         pinAssigned(PIN_LED_OUTPUT) && pinAssigned(PIN_LED_BLUETOOTH);
}
}  // namespace Config
