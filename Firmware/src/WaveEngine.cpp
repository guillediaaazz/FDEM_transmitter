#include "WaveEngine.h"

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
  const float maximumAttenuation = attenuatorFractionForWiper(Config::DIGIPOT_MAX_SIGNAL_WIPER);
  return prePowerVpp <= Config::DDS_OUTPUT_VPP * Config::PRE_DIGIPOT_BUFFER_GAIN * maximumAttenuation + 0.0001f;
}

bool WaveEngine::setAmplitude(float requestedVpp) {
  if (!canProduceAmplitude(requestedVpp)) return false;
  requestedAmplitudeVpp_ = requestedVpp;
  if (ready_) applyAmplitude();
  return true;
}

bool WaveEngine::canSetManualOffsetTrimCodes(int codes) const {
  return codes >= -Config::MANUAL_DAC_B_TRIM_LIMIT_CODES &&
         codes <= Config::MANUAL_DAC_B_TRIM_LIMIT_CODES;
}

bool WaveEngine::setManualOffsetTrimCodes(int codes) {
  if (!canSetManualOffsetTrimCodes(codes)) return false;
  manualOffsetTrimCodes_ = codes;
  if (ready_) applyOffsetDac();
  return true;
}

bool WaveEngine::canSetOffsetGainScale(float scale) const {
  return isfinite(scale) && scale >= Config::OFFSET_GAIN_CALIBRATION_MIN_SCALE &&
         scale <= Config::OFFSET_GAIN_CALIBRATION_MAX_SCALE;
}

bool WaveEngine::setOffsetGainScale(float scale) {
  if (!canSetOffsetGainScale(scale)) return false;
  offsetGainScale_ = scale;
  if (ready_) applyOffsetDac();
  return true;
}

bool WaveEngine::setCalibrationDacBAdjustmentCodes(int codes) {
  const int nominalCode = dac_.voltageToCode(nominalDacBVolts());
  const int outputCode = nominalCode + manualOffsetTrimCodes_ + codes;
  if (outputCode < 0 || outputCode > Config::DAC_MAX_CODE) return false;
  calibrationDacBAdjustmentCodes_ = codes;
  if (ready_) applyOffsetDac();
  return true;
}

void WaveEngine::clearCalibrationDacBAdjustment() {
  calibrationDacBAdjustmentCodes_ = 0;
  if (ready_) applyOffsetDac();
}

void WaveEngine::setWaveform(Waveform waveform) {
  waveform_ = waveform;
  if (ready_) {
    dds_.setWaveform(waveform_ == Waveform::Sine ? AD9837::Waveform::Sine : AD9837::Waveform::Triangle);
  }
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

WaveEngine::OffsetDiagnostics WaveEngine::offsetDiagnostics() const {
  const uint16_t dacBCode = dac_.code(MCP4822::Channel::B);
  return {
      attenuator_.wiper(),
      attenuatorFraction(),
      nominalDacBVolts(),
      offsetGainScale_,
      manualOffsetTrimCodes_,
      calibrationDacBAdjustmentCodes_,
      dac_.code(MCP4822::Channel::A),
      dac_.codeToVoltage(dac_.code(MCP4822::Channel::A)),
      dacBCode,
      dac_.codeToVoltage(dacBCode),
  };
}

bool WaveEngine::isOutputActive() const { return requestedAmplitudeVpp_ > 0.0f; }

float WaveEngine::appliedAmplitudeVpp() const {
  // A:0 remains the user-visible safe mute state even though code 0 has a
  // small physical residual that is handled by the dedicated DAC-B term.
  if (requestedAmplitudeVpp_ <= 0.0f) return 0.0f;
  const float sourceVpp = Config::DDS_OUTPUT_VPP * Config::PRE_DIGIPOT_BUFFER_GAIN;
  return max(0.0f, sourceVpp * attenuatorFraction() * Config::POWER_STAGE_GAIN_V_V);
}

float WaveEngine::manualOffsetTrimOutputVolts() const {
  return manualOffsetTrimCodes_ * dac_.codeToVoltage(1) * Config::POWER_STAGE_GAIN_V_V;
}

float WaveEngine::unscaledSignalDacBVolts() const { return signalDacBVoltsBeforeGain(); }

float WaveEngine::dacBVoltsPerCode() const { return dac_.codeToVoltage(1); }

void WaveEngine::applyAmplitude() {
  const float sourceVpp = Config::DDS_OUTPUT_VPP * Config::PRE_DIGIPOT_BUFFER_GAIN;
  const float prePowerVpp = requestedAmplitudeVpp_ / Config::POWER_STAGE_GAIN_V_V;
  const float requestedFraction = constrain(prePowerVpp / sourceVpp, 0.0f, 1.0f);
  // With A as the input, B grounded, and W as the output, the divider ratio
  // is RWB / (RWB + RWA). Inverting that ratio selects the nearest AD5160
  // code for the requested amplitude while retaining the 60 Ohm wiper term.
  const float resistanceToB = requestedFraction *
      (Config::DIGIPOT_END_TO_END_RESISTANCE_OHMS + Config::DIGIPOT_WIPER_RESISTANCE_OHMS);
  const float code = (resistanceToB - Config::DIGIPOT_WIPER_RESISTANCE_OHMS) *
      Config::DIGIPOT_RESISTOR_POSITIONS / Config::DIGIPOT_END_TO_END_RESISTANCE_OHMS;
  const uint8_t wiper = static_cast<uint8_t>(constrain(
      static_cast<int>(lroundf(code)), static_cast<int>(Config::DIGIPOT_MUTE_WIPER),
      static_cast<int>(Config::DIGIPOT_MAX_SIGNAL_WIPER)));
  attenuator_.setWiper(wiper);
  applyOffsetDac();
}

void WaveEngine::applyOffsetDac() {
  const int nominalCode = dac_.voltageToCode(nominalDacBVolts());
  const int outputCode = constrain(nominalCode + manualOffsetTrimCodes_ + calibrationDacBAdjustmentCodes_,
                                   0, static_cast<int>(Config::DAC_MAX_CODE));
  dac_.setCode(MCP4822::Channel::B, static_cast<uint16_t>(outputCode));
}

float WaveEngine::attenuatorFraction() const {
  return attenuatorFractionForWiper(attenuator_.wiper());
}

float WaveEngine::attenuatorFractionForWiper(uint8_t wiper) const {
  if (Config::DIGIPOT_END_TO_END_RESISTANCE_OHMS <= 0.0f ||
      Config::DIGIPOT_RESISTOR_POSITIONS <= 0.0f) {
    return 0.0f;
  }
  const float code = constrain(static_cast<float>(wiper),
                               static_cast<float>(Config::DIGIPOT_MUTE_WIPER),
                               static_cast<float>(Config::DIGIPOT_MAX_SIGNAL_WIPER));
  const float resistanceWb = code * Config::DIGIPOT_END_TO_END_RESISTANCE_OHMS /
      Config::DIGIPOT_RESISTOR_POSITIONS + Config::DIGIPOT_WIPER_RESISTANCE_OHMS;
  const float resistanceWa = (Config::DIGIPOT_RESISTOR_POSITIONS - code) *
      Config::DIGIPOT_END_TO_END_RESISTANCE_OHMS / Config::DIGIPOT_RESISTOR_POSITIONS;
  return constrain(resistanceWb / (resistanceWb + resistanceWa), 0.0f, 1.0f);
}

float WaveEngine::signalDacBVoltsBeforeGain() const {
  // The subtractor must remove the actual DC level at its signal input, not
  // merely half of the requested Vpp. AD9837 VOUT does not begin at 0 V: its
  // specified low-level offset is amplified by the pre-digipot buffer and
  // attenuated by the same AD5160 wiper setting as the waveform. Using the
  // discrete wiper fraction keeps DAC-B aligned with the Vpp truly applied.
  const float ddsCentreVolts = Config::DDS_OUTPUT_OFFSET + Config::DDS_OUTPUT_VPP * 0.5f;
  return ddsCentreVolts * Config::PRE_DIGIPOT_BUFFER_GAIN * attenuatorFraction();
}

float WaveEngine::nominalDacBVolts() const {
  float offsetVolts = signalDacBVoltsBeforeGain() * offsetGainScale_;
  if (requestedAmplitudeVpp_ <= 0.0f) {
    offsetVolts += Config::DIGIPOT_MUTE_RESIDUAL_DAC_B_VOLTS;
  }
  return offsetVolts;
}
