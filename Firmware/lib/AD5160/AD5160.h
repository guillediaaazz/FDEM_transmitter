#pragma once

#include <Arduino.h>

class AD5160 {
 public:
  explicit AD5160(uint8_t chipSelectPin);

  bool begin();
  void setWiper(uint8_t value);
  uint8_t wiper() const { return wiper_; }

 private:
  uint8_t chipSelectPin_;
  uint8_t wiper_ = 0;
  bool ready_ = false;
};
