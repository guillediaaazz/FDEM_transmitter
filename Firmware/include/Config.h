#pragma once

#include <Arduino.h>

// This is the only file that should need board-specific adjustment.  Pin
// assignments deliberately default to -1 so a new build cannot accidentally
// drive an unknown connection.
namespace Config {

constexpr int PIN_UNASSIGNED = -1;

// ---- Pin assignments: fill these before connecting the hardware. ----
constexpr int PIN_SPI_SCK = 33;
//constexpr int PIN_SPI_SCK = 27;
constexpr int PIN_SPI_MOSI = 32;
constexpr int PIN_SPI_MISO = PIN_UNASSIGNED;  // Not used by these write-only ICs.
constexpr int PIN_AD9837_FSYN = 27;
//constexpr int PIN_AD9837_FSYN = 33; // Just for bring-up, SCK and CS were swapped on the board.
constexpr int PIN_AD5160_CS = 26;
constexpr int PIN_MCP4822_CS = 25;

constexpr int PIN_ADC_POSITIVE_RAIL = 36;
constexpr int PIN_ADC_NEGATIVE_RAIL = 39;
// Reserved for a future offset-feedback experiment. It is not read by the
// current firmware, which uses only the manual DAC-B trim below.
constexpr int PIN_ADC_OFFSET_FEEDBACK = 34;

constexpr int PIN_LED_POSITIVE_GREEN = 18;
constexpr int PIN_LED_POSITIVE_RED = 19;
constexpr int PIN_LED_NEGATIVE_GREEN = 4;
constexpr int PIN_LED_NEGATIVE_RED = 16;
constexpr int PIN_LED_OUTPUT = 13;
constexpr int PIN_LED_BLUETOOTH = 14;

// ---- Serial and BLE ----
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr char BLE_DEVICE_NAME[] = "FDEM-TX";
constexpr bool BLE_ENABLED_AT_BOOT = true;
constexpr char NUS_SERVICE_UUID[] = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char NUS_RX_UUID[] = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";  // Client -> ESP32
constexpr char NUS_TX_UUID[] = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";  // ESP32 -> client
constexpr size_t MAX_COMMAND_LENGTH = 128;
constexpr uint32_t BATTERY_TELEMETRY_INTERVAL_MS = 1000;
// Keep a terminal usable at boot. The web UI enables USB telemetry explicitly.
constexpr bool USB_TELEMETRY_ENABLED_AT_BOOT = false;

// ---- Signal path ----
constexpr float DDS_REFERENCE_CLOCK_HZ = 16000000.0f;
constexpr float DDS_OUTPUT_VPP = 0.605f;
constexpr float DDS_OUTPUT_OFFSET = 0.046f;  // It does not reach 0 V. It goes from 0.037 V to 0.647 V.
constexpr float PRE_DIGIPOT_BUFFER_GAIN = 2.0f;

// Measure the closed-loop LM1875 gain and replace this nominal value.
constexpr float POWER_STAGE_GAIN_V_V = 16.667f;
constexpr float MIN_FREQUENCY_HZ = 1.0f;
constexpr float MAX_FREQUENCY_HZ = 8000.0f;
constexpr float MIN_OUTPUT_VPP = 0.0f;
constexpr float MAX_OUTPUT_VPP = 20.0f;

// Keep the DAC at midscale while every new FREQ0 word is loaded.
// This is not required for normal DDS operation, in fact, it could create
// some jitter in the analog part every time the frequency is updated, 
// but it can be useful during board bring-up.
constexpr bool DDS_RESET_AROUND_FREQUENCY_WRITES = false;

// AD5160 wiring: A = signal input, B = ground, W = output.
constexpr uint8_t DIGIPOT_MUTE_WIPER = 0;
constexpr uint8_t DIGIPOT_MAX_SIGNAL_WIPER = 255;

// ---- MCP4822 ----
// Effective MCP4822 reference at the DAC output. Keep 2.048 V initially;
// replace it only after measuring the actual full-scale/reference behavior.
constexpr float DAC_REFERENCE_VOLTS = 2.048f;
constexpr uint16_t DAC_MAX_CODE = 4095;
constexpr float FEEDBACK_BIAS_DAC_VOLTS = 0.2895f;  // MCP4822 channel A, nominal hardware bias.

// ---- Manual output-offset trim ----
// The AD5160 W-to-B wiper resistance leaves a small signal at code 0. Add
// this DAC-B voltage only while A:0 is selected to subtract that residual.
constexpr float DIGIPOT_MUTE_RESIDUAL_DAC_B_VOLTS = 0.006f;
// User-controlled signed adjustment added directly to the DAC-B code. It is
// deliberately volatile and always starts at zero after boot.
constexpr int MANUAL_DAC_B_TRIM_LIMIT_CODES = 255;

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
constexpr uint8_t LED_PWM_MAX_DUTY = 220;
constexpr uint32_t BLE_ADVERTISING_BLINK_MS = 500;

inline bool pinAssigned(int pin) { return pin != PIN_UNASSIGNED; }

inline bool signalPinsConfigured() {
  return pinAssigned(PIN_SPI_SCK) && pinAssigned(PIN_SPI_MOSI) &&
         pinAssigned(PIN_AD9837_FSYN) && pinAssigned(PIN_AD5160_CS) &&
         pinAssigned(PIN_MCP4822_CS);
}

inline bool powerMonitorPinsConfigured() {
  return pinAssigned(PIN_ADC_POSITIVE_RAIL) && pinAssigned(PIN_ADC_NEGATIVE_RAIL);
}

inline bool ledPinsConfigured() {
  return pinAssigned(PIN_LED_POSITIVE_GREEN) && pinAssigned(PIN_LED_POSITIVE_RED) &&
         pinAssigned(PIN_LED_NEGATIVE_GREEN) && pinAssigned(PIN_LED_NEGATIVE_RED) &&
         pinAssigned(PIN_LED_OUTPUT) && pinAssigned(PIN_LED_BLUETOOTH);
}
}  // namespace Config
