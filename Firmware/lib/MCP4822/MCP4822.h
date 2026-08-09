#pragma once

#include <Arduino.h>

class MCP4822 {
 public:
  enum class Channel : uint8_t { A, B };

  MCP4822(uint8_t chipSelectPin, float referenceVolts);

  bool begin();
  void setCode(Channel channel, uint16_t code);
  void setVoltage(Channel channel, float volts);
  uint16_t code(Channel channel) const;
  uint16_t voltageToCode(float volts) const;
  float codeToVoltage(uint16_t code) const;

 private:
  uint8_t chipSelectPin_;
  float referenceVolts_;
  uint16_t codeA_ = 0;
  uint16_t codeB_ = 0;
  bool ready_ = false;
};
