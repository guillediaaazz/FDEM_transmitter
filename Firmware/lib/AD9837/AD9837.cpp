#include "AD9837.h"

#include <SPI.h>

namespace {
constexpr uint16_t CONTROL_B28 = 0x2000;
constexpr uint16_t CONTROL_RESET = 0x0100;
constexpr uint16_t CONTROL_TRIANGLE = 0x0002;
constexpr uint16_t FREQ0_REGISTER = 0x4000;
constexpr uint32_t TUNING_WORD_MASK = 0x0FFFFFFF;
}

AD9837::AD9837(uint8_t fsyncPin, float referenceClockHz)
    : fsyncPin_(fsyncPin), referenceClockHz_(referenceClockHz) {}

bool AD9837::begin() {
  pinMode(fsyncPin_, OUTPUT);
  digitalWrite(fsyncPin_, HIGH);
  ready_ = true;
  writeConfiguration();
  return true;
}

uint32_t AD9837::frequencyToTuningWord(float frequencyHz, float referenceClockHz) {
  if (frequencyHz <= 0.0f || referenceClockHz <= 0.0f) return 0;
  const double scale = 268435456.0 / static_cast<double>(referenceClockHz);
  const uint64_t word = static_cast<uint64_t>(frequencyHz * scale + 0.5);
  return static_cast<uint32_t>(word) & TUNING_WORD_MASK;
}

void AD9837::setFrequency(float frequencyHz) {
  frequencyHz_ = frequencyHz;
  if (!ready_) return;

  const uint32_t word = frequencyToTuningWord(frequencyHz_, referenceClockHz_);
  writeWord(CONTROL_B28 | (reset_ ? CONTROL_RESET : 0) |
            (waveform_ == Waveform::Triangle ? CONTROL_TRIANGLE : 0));
  writeWord(FREQ0_REGISTER | static_cast<uint16_t>(word & 0x3FFF));
  writeWord(FREQ0_REGISTER | static_cast<uint16_t>((word >> 14) & 0x3FFF));
  writeConfiguration();
}

void AD9837::setWaveform(Waveform waveform) {
  waveform_ = waveform;
  if (ready_) writeConfiguration();
}

void AD9837::setReset(bool reset) {
  reset_ = reset;
  if (ready_) writeConfiguration();
}

void AD9837::writeConfiguration() {
  writeWord(CONTROL_B28 | (reset_ ? CONTROL_RESET : 0) |
            (waveform_ == Waveform::Triangle ? CONTROL_TRIANGLE : 0));
}

void AD9837::writeWord(uint16_t word) {
  if (!ready_) return;
  SPI.beginTransaction(SPISettings(4000000, MSBFIRST, SPI_MODE2));
  digitalWrite(fsyncPin_, LOW);
  SPI.transfer16(word);
  digitalWrite(fsyncPin_, HIGH);
  SPI.endTransaction();
}
