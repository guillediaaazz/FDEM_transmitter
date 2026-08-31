#pragma once

#include <Arduino.h>

struct RailReadings {
  float positiveVolts = NAN;
  float negativeVolts = NAN;
  uint8_t healthPercent = 0;
  bool valid = false;
};

class PowerMonitor {
 public:
  bool begin();
  RailReadings readRails() const;
  bool offsetFeedbackAvailable() const;
  float readOffsetFeedbackVolts(uint8_t samples) const;

 private:
  float readAdcVolts(int pin, uint8_t samples) const;
  uint8_t batteryPercent(float railMagnitudeVolts) const;
  bool ready_ = false;
};
