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
    float offsetGainScale;
    int manualTrimCodes;
    int calibrationAdjustmentCodes;
    uint16_t dacACode;
    float dacAVolts;
    uint16_t dacBCode;
    float dacBVolts;
  };

  WaveEngine();
  bool begin();
  bool setFrequency(float frequencyHz);
  bool setAmplitude(float requestedVpp);
  bool setManualOffsetTrimCodes(int codes);
  bool setOffsetGainScale(float scale);
  bool setCalibrationDacBAdjustmentCodes(int codes);
  void clearCalibrationDacBAdjustment();
  void setWaveform(Waveform waveform);
  void runDdsKnownGoodTest();
  void setDdsTraceEnabled(bool enabled);
  void setDdsReset(bool reset);
  AD9837::Diagnostics ddsDiagnostics() const;
  OffsetDiagnostics offsetDiagnostics() const;

  bool canProduceAmplitude(float requestedVpp) const;
  bool canSetManualOffsetTrimCodes(int codes) const;
  bool canSetOffsetGainScale(float scale) const;
  bool isOutputActive() const;
  int manualOffsetTrimCodes() const { return manualOffsetTrimCodes_; }
  float offsetGainScale() const { return offsetGainScale_; }
  float manualOffsetTrimOutputVolts() const;
  float unscaledSignalDacBVolts() const;
  float dacBVoltsPerCode() const;
  float frequencyHz() const { return frequencyHz_; }
  float requestedAmplitudeVpp() const { return requestedAmplitudeVpp_; }
  float appliedAmplitudeVpp() const;
  Waveform waveform() const { return waveform_; }

 private:
  void applyAmplitude();
  void applyOffsetDac();
  float attenuatorFraction() const;
  float attenuatorFractionForWiper(uint8_t wiper) const;
  float signalDacBVoltsBeforeGain() const;
  float nominalDacBVolts() const;

  AD9837 dds_;
  AD5160 attenuator_;
  MCP4822 dac_;
  float frequencyHz_ = 1000.0f;
  float requestedAmplitudeVpp_ = 0.0f;
  Waveform waveform_ = Waveform::Sine;
  int manualOffsetTrimCodes_ = 0;
  int calibrationDacBAdjustmentCodes_ = 0;
  float offsetGainScale_ = 1.0f;
  bool ready_ = false;
};
