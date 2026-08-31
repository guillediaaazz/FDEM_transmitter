#include "PowerMonitor.h"

#include "Config.h"

bool PowerMonitor::begin() {
  if (!Config::powerMonitorPinsConfigured()) return false;

  analogReadResolution(12);
  analogSetPinAttenuation(Config::PIN_ADC_POSITIVE_RAIL, ADC_11db);
  analogSetPinAttenuation(Config::PIN_ADC_NEGATIVE_RAIL, ADC_11db);
  if (Config::pinAssigned(Config::PIN_ADC_OFFSET_FEEDBACK)) {
    analogSetPinAttenuation(Config::PIN_ADC_OFFSET_FEEDBACK, ADC_11db);
  }
  ready_ = true;
  return true;
}

RailReadings PowerMonitor::readRails() const {
  RailReadings readings;
  if (!ready_) return readings;

  const float positiveInput = readAdcVolts(Config::PIN_ADC_POSITIVE_RAIL, Config::ADC_AVERAGE_SAMPLES);
  const float negativeInput = readAdcVolts(Config::PIN_ADC_NEGATIVE_RAIL, Config::ADC_AVERAGE_SAMPLES);
  readings.positiveVolts = positiveInput / Config::POSITIVE_RAIL_ADC_ATTENUATION;
  readings.negativeVolts = -(negativeInput / Config::NEGATIVE_RAIL_ADC_ATTENUATION);
  const uint8_t positivePercent = batteryPercent(readings.positiveVolts);
  const uint8_t negativePercent = batteryPercent(-readings.negativeVolts);
  readings.healthPercent = static_cast<uint8_t>((positivePercent + negativePercent) / 2);
  readings.valid = true;
  return readings;
}

bool PowerMonitor::offsetFeedbackAvailable() const {
  return ready_ && Config::pinAssigned(Config::PIN_ADC_OFFSET_FEEDBACK);
}

float PowerMonitor::readOffsetFeedbackVolts(uint8_t samples) const {
  if (!offsetFeedbackAvailable()) return NAN;
  return readAdcVolts(Config::PIN_ADC_OFFSET_FEEDBACK, samples);
}

float PowerMonitor::readAdcVolts(int pin, uint8_t samples) const {
  if (samples == 0) return NAN;
  uint32_t millivolts = 0;
  for (uint8_t sample = 0; sample < samples; ++sample) {
    millivolts += analogReadMilliVolts(pin);
  }
  const float volts = (millivolts / static_cast<float>(samples)) / 1000.0f;
  return volts * Config::ADC_VOLTAGE_SCALE + Config::ADC_VOLTAGE_OFFSET_VOLTS;
}

uint8_t PowerMonitor::batteryPercent(float railMagnitudeVolts) const {
  const float span = Config::BATTERY_FULL_VOLTS - Config::BATTERY_EMPTY_VOLTS;
  if (span <= 0.0f || railMagnitudeVolts <= Config::BATTERY_EMPTY_VOLTS) return 0;
  if (railMagnitudeVolts >= Config::BATTERY_FULL_VOLTS) return 100;
  return static_cast<uint8_t>(((railMagnitudeVolts - Config::BATTERY_EMPTY_VOLTS) / span) * 100.0f + 0.5f);
}
