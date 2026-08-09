#include "StatusLeds.h"

#include "Config.h"

namespace {
constexpr uint8_t POS_GREEN_CHANNEL = 0;
constexpr uint8_t POS_RED_CHANNEL = 1;
constexpr uint8_t NEG_GREEN_CHANNEL = 2;
constexpr uint8_t NEG_RED_CHANNEL = 3;
constexpr uint8_t OUTPUT_CHANNEL = 4;
constexpr uint8_t BLUETOOTH_CHANNEL = 5;
}

bool StatusLeds::begin() {
  if (!Config::ledPinsConfigured()) return false;
  attachChannel(Config::PIN_LED_POSITIVE_GREEN, POS_GREEN_CHANNEL);
  attachChannel(Config::PIN_LED_POSITIVE_RED, POS_RED_CHANNEL);
  attachChannel(Config::PIN_LED_NEGATIVE_GREEN, NEG_GREEN_CHANNEL);
  attachChannel(Config::PIN_LED_NEGATIVE_RED, NEG_RED_CHANNEL);
  attachChannel(Config::PIN_LED_OUTPUT, OUTPUT_CHANNEL);
  attachChannel(Config::PIN_LED_BLUETOOTH, BLUETOOTH_CHANNEL);
  ready_ = true;
  setBatteryHealth(0);
  setOutputActive(false);
  setBluetoothState(false, false);
  return true;
}

void StatusLeds::setBatteryHealth(uint8_t percent) {
  if (!ready_) return;
  percent = constrain(percent, 0, 100);
  const uint8_t green = static_cast<uint8_t>((percent * Config::LED_PWM_MAX_DUTY) / 100);
  const uint8_t red = Config::LED_PWM_MAX_DUTY - green;
  writeChannel(POS_GREEN_CHANNEL, green);
  writeChannel(POS_RED_CHANNEL, red);
  writeChannel(NEG_GREEN_CHANNEL, green);
  writeChannel(NEG_RED_CHANNEL, red);
}

void StatusLeds::setOutputActive(bool active) {
  outputActive_ = active;
  if (ready_) writeChannel(OUTPUT_CHANNEL, active ? Config::LED_PWM_MAX_DUTY : 0);
}

void StatusLeds::setBluetoothState(bool enabled, bool connected) {
  bluetoothEnabled_ = enabled;
  bluetoothConnected_ = connected;
  if (!ready_ || enabled) return;
  writeChannel(BLUETOOTH_CHANNEL, 0);
}

void StatusLeds::update(uint32_t now) {
  if (!ready_) return;
  if (!bluetoothEnabled_) {
    writeChannel(BLUETOOTH_CHANNEL, 0);
  } else if (bluetoothConnected_) {
    writeChannel(BLUETOOTH_CHANNEL, Config::LED_PWM_MAX_DUTY);
  } else if (now - lastBlinkMs_ >= Config::BLE_ADVERTISING_BLINK_MS) {
    lastBlinkMs_ = now;
    blinkOn_ = !blinkOn_;
    writeChannel(BLUETOOTH_CHANNEL, blinkOn_ ? Config::LED_PWM_MAX_DUTY : 0);
  }
}

void StatusLeds::attachChannel(int pin, uint8_t channel) {
  ledcSetup(channel, Config::LED_PWM_FREQUENCY_HZ, Config::LED_PWM_RESOLUTION_BITS);
  ledcAttachPin(pin, channel);
  writeChannel(channel, 0);
}

void StatusLeds::writeChannel(uint8_t channel, uint8_t duty) {
  ledcWrite(channel, duty);
}
