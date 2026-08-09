#pragma once

#include <Arduino.h>

class StatusLeds {
 public:
  bool begin();
  void setBatteryHealth(uint8_t percent);
  void setOutputActive(bool active);
  void setBluetoothState(bool enabled, bool connected);
  void update(uint32_t now);

 private:
  void attachChannel(int pin, uint8_t channel);
  void writeChannel(uint8_t channel, uint8_t duty);

  bool ready_ = false;
  bool outputActive_ = false;
  bool bluetoothEnabled_ = false;
  bool bluetoothConnected_ = false;
  bool blinkOn_ = false;
  uint32_t lastBlinkMs_ = 0;
};
