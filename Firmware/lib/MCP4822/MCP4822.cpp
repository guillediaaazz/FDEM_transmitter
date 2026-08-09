#include "MCP4822.h"

#include <SPI.h>

namespace {
constexpr uint16_t DAC_CHANNEL_B = 0x8000;
constexpr uint16_t DAC_GAIN_1X = 0x2000;
constexpr uint16_t DAC_ACTIVE = 0x1000;
constexpr uint16_t DAC_CODE_MASK = 0x0FFF;
}

MCP4822::MCP4822(uint8_t chipSelectPin, float referenceVolts)
    : chipSelectPin_(chipSelectPin), referenceVolts_(referenceVolts) {}

bool MCP4822::begin() {
  pinMode(chipSelectPin_, OUTPUT);
  digitalWrite(chipSelectPin_, HIGH);
  ready_ = true;
  setCode(Channel::A, codeA_);
  setCode(Channel::B, codeB_);
  return true;
}

void MCP4822::setCode(Channel channel, uint16_t code) {
  code = min<uint16_t>(code, DAC_CODE_MASK);
  if (channel == Channel::A) {
    codeA_ = code;
  } else {
    codeB_ = code;
  }
  if (!ready_) return;

  uint16_t frame = DAC_GAIN_1X | DAC_ACTIVE | code;
  if (channel == Channel::B) frame |= DAC_CHANNEL_B;
  SPI.beginTransaction(SPISettings(8000000, MSBFIRST, SPI_MODE0));
  digitalWrite(chipSelectPin_, LOW);
  SPI.transfer16(frame);
  digitalWrite(chipSelectPin_, HIGH);
  SPI.endTransaction();
}

void MCP4822::setVoltage(Channel channel, float volts) {
  setCode(channel, voltageToCode(volts));
}

uint16_t MCP4822::code(Channel channel) const {
  return channel == Channel::A ? codeA_ : codeB_;
}

uint16_t MCP4822::voltageToCode(float volts) const {
  if (volts <= 0.0f) return 0;
  if (volts >= referenceVolts_) return DAC_CODE_MASK;
  return static_cast<uint16_t>((volts / referenceVolts_) * DAC_CODE_MASK + 0.5f);
}

float MCP4822::codeToVoltage(uint16_t code) const {
  return (min<uint16_t>(code, DAC_CODE_MASK) * referenceVolts_) / DAC_CODE_MASK;
}
