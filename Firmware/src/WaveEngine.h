#pragma once

#include <Arduino.h>

#include <AD5160.h>
#include <AD9837.h>
#include <MCP4822.h>

class WaveEngine {
 public:
  enum class Waveform : uint8_t { Sine, Triangle };

  struct OffsetDiagnostics {
    uint8_t wiper;
    float attenuationFraction;
    float nominalDacBVolts;
    int correctionCodes;
    uint16_t dacBCode;
    float dacBVolts;
  };

  WaveEngine();
  bool begin();
  bool setFrequency(float frequencyHz);
  bool setAmplitude(float requestedVpp);
  void setWaveform(Waveform waveform);
  void setAutoCalibration(bool enabled);
  void setStoredCorrection(int correctionCodes);
  void startCalibration();
  void updateOffset(float feedbackVolts, uint32_t now);
  void runDdsKnownGoodTest();
  void setDdsTraceEnabled(bool enabled);
  void setDdsReset(bool reset);
  AD9837::Diagnostics ddsDiagnostics() const;
  OffsetDiagnostics offsetDiagnostics() const;

  bool canProduceAmplitude(float requestedVpp) const;
  bool isOutputActive() const;
  bool autoCalibrationEnabled() const { return autoCalibrationEnabled_; }
  bool calibrationRunning() const { return calibrationRunning_; }
  bool takeCalibrationFinished();
  int correctionCodes() const { return correctionCodes_; }
  float frequencyHz() const { return frequencyHz_; }
  float requestedAmplitudeVpp() const { return requestedAmplitudeVpp_; }
  float appliedAmplitudeVpp() const;
  Waveform waveform() const { return waveform_; }

 private:
  void applyAmplitude();
  void applyOffsetDac();
  void adjustCorrection(float feedbackVolts, float gain);
  int clampCorrection(int value) const;
  float attenuatorFraction() const;
  float nominalDacBVolts() const;

  AD9837 dds_;
  AD5160 attenuator_;
  MCP4822 dac_;
  float frequencyHz_ = 1000.0f;
  float requestedAmplitudeVpp_ = 0.0f;
  Waveform waveform_ = Waveform::Sine;
  int correctionCodes_ = 0;
  bool ready_ = false;
  bool autoCalibrationEnabled_ = false;
  bool calibrationRunning_ = false;
  bool restoreAutoAfterCalibration_ = false;
  bool calibrationFinished_ = false;
  uint8_t calibrationSteps_ = 0;
  uint8_t settledSteps_ = 0;
  uint32_t lastOffsetUpdateMs_ = 0;
};
