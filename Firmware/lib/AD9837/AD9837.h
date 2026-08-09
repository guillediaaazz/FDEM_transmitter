#pragma once

#include <Arduino.h>

class AD9837 {
 public:
  enum class Waveform : uint8_t { Sine, Triangle };

  AD9837(uint8_t fsyncPin, float referenceClockHz);

  bool begin();
  void setFrequency(float frequencyHz);
  void setWaveform(Waveform waveform);
  void setReset(bool reset);

  static uint32_t frequencyToTuningWord(float frequencyHz, float referenceClockHz);

 private:
  void writeWord(uint16_t word);
  void writeConfiguration();

  uint8_t fsyncPin_;
  float referenceClockHz_;
  float frequencyHz_ = 1000.0f;
  Waveform waveform_ = Waveform::Sine;
  bool reset_ = true;
  bool ready_ = false;
};
