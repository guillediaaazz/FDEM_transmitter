#pragma once

#include <Arduino.h>

class AD9837 {
 public:
  enum class Waveform : uint8_t { Sine, Triangle };

  struct Diagnostics {
    float frequencyHz;
    uint32_t tuningWord;
    uint16_t controlWord;
    uint16_t frequencyLsbWord;
    uint16_t frequencyMsbWord;
    uint32_t wordsWritten;
    bool resetApplied;
    bool traceEnabled;
    Waveform waveform;
  };

  AD9837(uint8_t fsyncPin, float referenceClockHz);

  bool begin();
  void setFrequency(float frequencyHz, bool resetDuringWrite = false);
  void setWaveform(Waveform waveform);
  void setReset(bool reset);
  void runKnownGoodTest();
  void setTraceEnabled(bool enabled) { traceEnabled_ = enabled; }
  Diagnostics diagnostics() const;

  static uint32_t frequencyToTuningWord(float frequencyHz, float referenceClockHz);

 private:
  void writeWord(uint16_t word);
  void writeConfiguration();
  uint16_t controlWord(bool forceReset = false) const;

  uint8_t fsyncPin_;
  float referenceClockHz_;
  float frequencyHz_ = 1000.0f;
  Waveform waveform_ = Waveform::Sine;
  bool reset_ = true;
  bool ready_ = false;
  bool traceEnabled_ = false;
  uint32_t wordsWritten_ = 0;
  uint16_t lastFrequencyLsbWord_ = 0;
  uint16_t lastFrequencyMsbWord_ = 0;
};
