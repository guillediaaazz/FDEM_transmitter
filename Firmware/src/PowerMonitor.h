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

 private:
  float readAdcVolts(int pin) const;
  uint8_t batteryPercent(float railMagnitudeVolts) const;
  bool ready_ = false;
};
