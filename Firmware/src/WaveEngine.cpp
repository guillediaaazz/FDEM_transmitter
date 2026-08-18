#include "WaveEngine.h"

#include <math.h>

#include <SPI.h>

#include "Config.h"

WaveEngine::WaveEngine()
    : dds_(Config::PIN_AD9837_FSYN, Config::DDS_REFERENCE_CLOCK_HZ),
      attenuator_(Config::PIN_AD5160_CS),
      dac_(Config::PIN_MCP4822_CS, Config::DAC_REFERENCE_VOLTS) {}

bool WaveEngine::begin() {
  if (!Config::signalPinsConfigured()) return false;
  SPI.begin(Config::PIN_SPI_SCK, Config::PIN_SPI_MISO, Config::PIN_SPI_MOSI);
  dds_.begin();
  attenuator_.begin();
  dac_.begin();
  dac_.setVoltage(MCP4822::Channel::A, Config::FEEDBACK_BIAS_DAC_VOLTS);
  dds_.setFrequency(frequencyHz_, Config::DDS_RESET_AROUND_FREQUENCY_WRITES);
  dds_.setWaveform(AD9837::Waveform::Sine);
  dds_.setReset(false);
  ready_ = true;
  applyAmplitude();  // Starts with wiper 0, leaving the output muted.
  return true;
}

bool WaveEngine::setFrequency(float frequencyHz) {
  if (frequencyHz < Config::MIN_FREQUENCY_HZ || frequencyHz > Config::MAX_FREQUENCY_HZ) return false;
  frequencyHz_ = frequencyHz;
  if (ready_) dds_.setFrequency(frequencyHz_, Config::DDS_RESET_AROUND_FREQUENCY_WRITES);
  return true;
}

bool WaveEngine::canProduceAmplitude(float requestedVpp) const {
  if (requestedVpp < Config::MIN_OUTPUT_VPP || requestedVpp > Config::MAX_OUTPUT_VPP ||
      Config::POWER_STAGE_GAIN_V_V <= 0.0f) {
    return false;
  }
  const float prePowerVpp = requestedVpp / Config::POWER_STAGE_GAIN_V_V;
  return prePowerVpp <= Config::DDS_OUTPUT_VPP * Config::PRE_DIGIPOT_BUFFER_GAIN + 0.0001f;
}

bool WaveEngine::setAmplitude(float requestedVpp) {
  if (!canProduceAmplitude(requestedVpp)) return false;
  requestedAmplitudeVpp_ = requestedVpp;
  if (ready_) applyAmplitude();
  return true;
}

void WaveEngine::setWaveform(Waveform waveform) {
  waveform_ = waveform;
  if (ready_) {
    dds_.setWaveform(waveform_ == Waveform::Sine ? AD9837::Waveform::Sine : AD9837::Waveform::Triangle);
  }
}

void WaveEngine::setAutoCalibration(bool enabled) {
  if (calibrationRunning_) {
    restoreAutoAfterCalibration_ = enabled;
    return;
  }
  autoCalibrationEnabled_ = enabled;
}

void WaveEngine::setStoredCorrection(int correctionCodes) {
  correctionCodes_ = clampCorrection(correctionCodes);
  if (ready_) applyOffsetDac();
}

void WaveEngine::startCalibration() {
  if (!ready_ || calibrationRunning_) return;
  restoreAutoAfterCalibration_ = autoCalibrationEnabled_;
  autoCalibrationEnabled_ = false;
  calibrationRunning_ = true;
  calibrationFinished_ = false;
  calibrationSteps_ = 0;
  settledSteps_ = 0;
  lastOffsetUpdateMs_ = 0;
}

void WaveEngine::runDdsKnownGoodTest() {
  if (!ready_) return;
  frequencyHz_ = 1000.0f;
  waveform_ = Waveform::Sine;
  dds_.runKnownGoodTest();
}

void WaveEngine::setDdsTraceEnabled(bool enabled) {
  dds_.setTraceEnabled(enabled);
}

void WaveEngine::setDdsReset(bool reset) {
  dds_.setReset(reset);
}

AD9837::Diagnostics WaveEngine::ddsDiagnostics() const {
  return dds_.diagnostics();
}

void WaveEngine::updateOffset(float feedbackVolts, uint32_t now) {
  if (!ready_ || isnan(feedbackVolts)) return;

  if (calibrationRunning_) {
    if (now - lastOffsetUpdateMs_ < Config::OFFSET_CALIBRATION_INTERVAL_MS) return;
    lastOffsetUpdateMs_ = now;
    adjustCorrection(feedbackVolts, Config::OFFSET_CALIBRATION_GAIN);
    ++calibrationSteps_;
    if (fabsf(Config::OFFSET_FEEDBACK_TARGET_VOLTS - feedbackVolts) <= Config::OFFSET_SETTLED_ERROR_VOLTS) {
      ++settledSteps_;
    } else {
      settledSteps_ = 0;
    }
    if (settledSteps_ >= Config::OFFSET_CALIBRATION_SETTLED_STEPS ||
        calibrationSteps_ >= Config::OFFSET_CALIBRATION_MAX_STEPS) {
      calibrationRunning_ = false;
      autoCalibrationEnabled_ = restoreAutoAfterCalibration_;
      calibrationFinished_ = true;
    }
    return;
  }

  if (!autoCalibrationEnabled_ || now - lastOffsetUpdateMs_ < Config::OFFSET_AUTO_INTERVAL_MS) return;
  lastOffsetUpdateMs_ = now;
  adjustCorrection(feedbackVolts, Config::OFFSET_AUTO_GAIN);
}

bool WaveEngine::takeCalibrationFinished() {
  const bool finished = calibrationFinished_;
  calibrationFinished_ = false;
  return finished;
}

bool WaveEngine::isOutputActive() const { return requestedAmplitudeVpp_ > 0.0f; }

float WaveEngine::appliedAmplitudeVpp() const {
  const float sourceVpp = Config::DDS_OUTPUT_VPP * Config::PRE_DIGIPOT_BUFFER_GAIN;
  return max(0.0f, sourceVpp * attenuatorFraction() * Config::POWER_STAGE_GAIN_V_V);
}

void WaveEngine::applyAmplitude() {
  const float sourceVpp = Config::DDS_OUTPUT_VPP * Config::PRE_DIGIPOT_BUFFER_GAIN;
  const float prePowerVpp = requestedAmplitudeVpp_ / Config::POWER_STAGE_GAIN_V_V;
  const float fraction = constrain(prePowerVpp / sourceVpp, 0.0f, 1.0f);
  const uint8_t wiper = static_cast<uint8_t>(Config::DIGIPOT_MUTE_WIPER +
      fraction * (Config::DIGIPOT_MAX_SIGNAL_WIPER - Config::DIGIPOT_MUTE_WIPER) + 0.5f);
  attenuator_.setWiper(wiper);
  applyOffsetDac();
}

void WaveEngine::applyOffsetDac() {
  const float dividerFraction = attenuatorFraction();

  // The subtractor must remove the actual DC level at its signal input, not
  // merely half of the requested Vpp.  AD9837 VOUT does not begin at 0 V:
  // its specified low-level offset is amplified by the pre-digipot buffer and
  // attenuated by the same AD5160 wiper setting as the waveform.  Using the
  // discrete wiper fraction also keeps the DAC-B value aligned with the Vpp
  // that is truly applied, rather than the ideal requested Vpp.
  const float ddsCentreVolts = Config::DDS_OUTPUT_OFFSET + Config::DDS_OUTPUT_VPP * 0.5f;
  const float nominalOffsetVolts = ddsCentreVolts * Config::PRE_DIGIPOT_BUFFER_GAIN * dividerFraction;
  const int nominalCode = dac_.voltageToCode(nominalOffsetVolts);
  const int outputCode = constrain(nominalCode + correctionCodes_, 0, static_cast<int>(Config::DAC_MAX_CODE));
  dac_.setCode(MCP4822::Channel::B, static_cast<uint16_t>(outputCode));
}

float WaveEngine::attenuatorFraction() const {
  const int span = Config::DIGIPOT_MAX_SIGNAL_WIPER - Config::DIGIPOT_MUTE_WIPER;
  if (span <= 0) return 0.0f;
  return constrain((static_cast<int>(attenuator_.wiper()) - Config::DIGIPOT_MUTE_WIPER) /
                       static_cast<float>(span),
                   0.0f, 1.0f);
}

void WaveEngine::adjustCorrection(float feedbackVolts, float gain) {
  const float errorVolts = Config::OFFSET_FEEDBACK_TARGET_VOLTS - feedbackVolts;
  const float dacCodesPerVolt = Config::DAC_MAX_CODE / Config::DAC_REFERENCE_VOLTS;
  int deltaCodes = static_cast<int>(errorVolts * dacCodesPerVolt * gain * Config::OFFSET_CORRECTION_POLARITY);
  if (deltaCodes == 0 && fabsf(errorVolts) > Config::OFFSET_SETTLED_ERROR_VOLTS) {
    deltaCodes = errorVolts > 0.0f ? Config::OFFSET_CORRECTION_POLARITY : -Config::OFFSET_CORRECTION_POLARITY;
  }
  correctionCodes_ = clampCorrection(correctionCodes_ + deltaCodes);
  applyOffsetDac();
}

int WaveEngine::clampCorrection(int value) const {
  return constrain(value, -Config::OFFSET_CORRECTION_LIMIT_CODES, Config::OFFSET_CORRECTION_LIMIT_CODES);
}
