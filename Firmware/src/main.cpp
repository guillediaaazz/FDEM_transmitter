#include <Arduino.h>
#include <Preferences.h>

#include "CommandProtocol.h"
#include "CommsManager.h"
#include "Config.h"
#include "OffsetGainMath.h"
#include "PowerMonitor.h"
#include "StatusLeds.h"
#include "WaveEngine.h"

namespace {
enum class CalibrationPhase : uint8_t { Idle, SweepSettling, PerturbBaseSettling, PerturbSettling };

struct GainCalibrationState {
  CalibrationPhase phase = CalibrationPhase::Idle;
  uint8_t pointIndex = 0;
  float signalDacVolts[Config::OFFSET_GAIN_CALIBRATION_POINTS] = {};
  float feedbackVolts[Config::OFFSET_GAIN_CALIBRATION_POINTS] = {};
  float originalAmplitudeVpp = 0.0f;
  float perturbBaseFeedbackVolts = NAN;
  uint32_t changedAtMs = 0;
};

CommsManager comms;
PowerMonitor powerMonitor;
StatusLeds statusLeds;
WaveEngine waveEngine;
Preferences preferences;
RailReadings rails;
GainCalibrationState calibration;
bool signalHardwareReady = false;
bool preferencesReady = false;
uint32_t lastTelemetryMs = 0;

bool calibrationRunning() { return calibration.phase != CalibrationPhase::Idle; }

String waveformName(WaveEngine::Waveform waveform) {
  return waveform == WaveEngine::Waveform::Sine ? "S" : "T";
}

String hexWord(uint16_t value) {
  char text[7];
  snprintf(text, sizeof(text), "0x%04X", value);
  return String(text);
}

float calibrationMaximumVpp() {
  return min(Config::OFFSET_GAIN_CALIBRATION_MAX_OUTPUT_VPP, Config::MAX_OUTPUT_VPP);
}

float calibrationPointVpp(uint8_t pointIndex) {
  return calibrationMaximumVpp() * (pointIndex + 1) / Config::OFFSET_GAIN_CALIBRATION_POINTS;
}

String ddsDiagnosticsMessage() {
  const AD9837::Diagnostics diagnostics = waveEngine.ddsDiagnostics();
  char tuningWord[11];
  snprintf(tuningWord, sizeof(tuningWord), "0x%07lX", static_cast<unsigned long>(diagnostics.tuningWord));
  return "DDS:DIAG:F:" + String(diagnostics.frequencyHz, 3) +
         ",TW:" + String(tuningWord) + ",CTRL:" + hexWord(diagnostics.controlWord) +
         ",LSW:" + hexWord(diagnostics.frequencyLsbWord) + ",MSW:" + hexWord(diagnostics.frequencyMsbWord) +
         ",RESET:" + String(diagnostics.resetApplied ? 1 : 0) +
         ",W:" + String(diagnostics.waveform == AD9837::Waveform::Sine ? "S" : "T") +
         ",SPI:MODE2:4MHZ,WORDS:" + String(diagnostics.wordsWritten);
}

String offsetDiagnosticsMessage() {
  const WaveEngine::OffsetDiagnostics diagnostics = waveEngine.offsetDiagnostics();
  return "OFFSET:DIAG:WIPER:" + String(diagnostics.wiper) + ",ATT:" + String(diagnostics.attenuationFraction, 6) +
         ",NOM:" + String(diagnostics.nominalDacBVolts, 4) + ",GAIN:" + String(diagnostics.offsetGainScale, 5) +
         ",TRIM:" + String(diagnostics.manualTrimCodes) + ",CAL_ADJ:" + String(diagnostics.calibrationAdjustmentCodes) +
         ",DACA_CODE:" + String(diagnostics.dacACode) + ",DACA:" + String(diagnostics.dacAVolts, 4) +
         ",DACB_CODE:" + String(diagnostics.dacBCode) + ",DACB:" + String(diagnostics.dacBVolts, 4);
}

String statusMessage() {
  String message = "STATUS:F:" + String(waveEngine.frequencyHz(), 2) + ",A:" + String(waveEngine.appliedAmplitudeVpp(), 3) +
                   ",W:" + waveformName(waveEngine.waveform()) + ",TRIM:" + String(waveEngine.manualOffsetTrimCodes()) +
                   ",TRIM_OUT:" + String(waveEngine.manualOffsetTrimOutputVolts(), 3) +
                   ",CAL:" + String(calibrationRunning() ? "RUNNING" : "IDLE") +
                   ",CAL_GAIN:" + String(waveEngine.offsetGainScale(), 5) +
                   ",BLT:" + String(comms.bluetoothEnabled() ? 1 : 0) + ",TELEM:" + String(comms.usbTelemetryEnabled() ? 1 : 0);
  if (signalHardwareReady) {
    const WaveEngine::OffsetDiagnostics diagnostics = waveEngine.offsetDiagnostics();
    message += ",WIPER:" + String(diagnostics.wiper) + ",DACB_NOM:" + String(diagnostics.nominalDacBVolts, 4) +
               ",DACA:" + String(diagnostics.dacAVolts, 4) + ",DACB:" + String(diagnostics.dacBVolts, 4);
  }
  if (rails.valid) {
    message += ",BATP:" + String(rails.positiveVolts, 2) + ",BATN:" + String(rails.negativeVolts, 2) +
               ",BAT:" + String(rails.healthPercent);
  } else {
    message += ",BAT:UNAVAILABLE";
  }
  return message;
}

void restoreAfterCalibration() {
  waveEngine.clearCalibrationDacBAdjustment();
  waveEngine.setAmplitude(calibration.originalAmplitudeVpp);
  calibration.phase = CalibrationPhase::Idle;
}

void failCalibration(const char* reason) {
  restoreAfterCalibration();
  comms.broadcast("ERR:CAL:" + String(reason));
}

bool startCalibration(uint32_t now, String& error) {
  if (!signalHardwareReady || !powerMonitor.offsetFeedbackAvailable()) {
    error = "HW_UNCONFIGURED";
    return false;
  }
  if (calibrationRunning()) {
    error = "CAL_RUNNING";
    return false;
  }
  if (Config::OFFSET_GAIN_CALIBRATION_POINTS < 2 || !waveEngine.canProduceAmplitude(calibrationMaximumVpp())) {
    error = "CAL_CONFIG";
    return false;
  }

  calibration = GainCalibrationState();
  calibration.originalAmplitudeVpp = waveEngine.requestedAmplitudeVpp();
  calibration.phase = CalibrationPhase::SweepSettling;
  calibration.changedAtMs = now;
  if (!waveEngine.setAmplitude(calibrationPointVpp(0))) {
    calibration.phase = CalibrationPhase::Idle;
    error = "OUT_OF_RANGE";
    return false;
  }
  return true;
}

void updateCalibration(uint32_t now) {
  if (!calibrationRunning() || now - calibration.changedAtMs < Config::OFFSET_GAIN_CALIBRATION_SETTLE_MS) return;
  const float feedback = powerMonitor.readOffsetFeedbackVolts(Config::OFFSET_GAIN_CALIBRATION_SAMPLES);
  if (!isfinite(feedback)) {
    failCalibration("ADC_UNAVAILABLE");
    return;
  }
  if (feedback <= Config::OFFSET_GAIN_CALIBRATION_ADC_MIN_VOLTS ||
      feedback >= Config::OFFSET_GAIN_CALIBRATION_ADC_MAX_VOLTS) {
    failCalibration("FEEDBACK_SATURATED");
    return;
  }

  if (calibration.phase == CalibrationPhase::SweepSettling) {
    calibration.signalDacVolts[calibration.pointIndex] = waveEngine.unscaledSignalDacBVolts();
    calibration.feedbackVolts[calibration.pointIndex] = feedback;
    ++calibration.pointIndex;
    if (calibration.pointIndex < Config::OFFSET_GAIN_CALIBRATION_POINTS) {
      if (!waveEngine.setAmplitude(calibrationPointVpp(calibration.pointIndex))) {
        failCalibration("OUT_OF_RANGE");
        return;
      }
      calibration.changedAtMs = now;
      comms.broadcast("CAL:STEP:" + String(calibration.pointIndex + 1) + "/" +
                      String(Config::OFFSET_GAIN_CALIBRATION_POINTS));
      return;
    }

    const uint8_t midpoint = Config::OFFSET_GAIN_CALIBRATION_POINTS / 2;
    if (!waveEngine.setAmplitude(calibrationPointVpp(midpoint))) {
      failCalibration("OUT_OF_RANGE");
      return;
    }
    calibration.phase = CalibrationPhase::PerturbBaseSettling;
    calibration.changedAtMs = now;
    comms.broadcast("CAL:STEP:PERTURB");
    return;
  }

  if (calibration.phase == CalibrationPhase::PerturbBaseSettling) {
    calibration.perturbBaseFeedbackVolts = feedback;
    if (!waveEngine.setCalibrationDacBAdjustmentCodes(Config::OFFSET_GAIN_CALIBRATION_DAC_STEP_CODES)) {
      failCalibration("DAC_HEADROOM");
      return;
    }
    calibration.phase = CalibrationPhase::PerturbSettling;
    calibration.changedAtMs = now;
    return;
  }

  if (calibration.phase == CalibrationPhase::PerturbSettling) {
    waveEngine.clearCalibrationDacBAdjustment();
    const OffsetGainMath::LinearFit fit = OffsetGainMath::fitLine(
        calibration.signalDacVolts, calibration.feedbackVolts, Config::OFFSET_GAIN_CALIBRATION_POINTS);
    const float dacStepVolts = Config::OFFSET_GAIN_CALIBRATION_DAC_STEP_CODES * waveEngine.dacBVoltsPerCode();
    const float dacResponseSlope = (feedback - calibration.perturbBaseFeedbackVolts) / dacStepVolts;
    float newScale = 1.0f;
    if (!fit.valid || fit.rmse > Config::OFFSET_GAIN_CALIBRATION_MAX_FIT_RMSE_VOLTS) {
      failCalibration("NONLINEAR");
      return;
    }
    if (!OffsetGainMath::deriveGainScale(waveEngine.offsetGainScale(), fit.slope, dacResponseSlope,
                                         Config::OFFSET_GAIN_CALIBRATION_MIN_DAC_RESPONSE_V_PER_V,
                                         Config::OFFSET_GAIN_CALIBRATION_MIN_SCALE,
                                         Config::OFFSET_GAIN_CALIBRATION_MAX_SCALE, newScale)) {
      failCalibration("INVALID_GAIN");
      return;
    }
    if (!waveEngine.setOffsetGainScale(newScale)) {
      failCalibration("INVALID_GAIN");
      return;
    }
    if (preferencesReady) preferences.putFloat(Config::OFFSET_GAIN_PREFERENCE_KEY, newScale);
    restoreAfterCalibration();
    comms.broadcast("OK:CAL:COMPLETE:GAIN:" + String(newScale, 5));
  }
}

String handleCommand(const String& rawCommand) {
  String debugCommand = rawCommand;
  debugCommand.trim();
  debugCommand.toUpperCase();
  if (debugCommand.startsWith("DDS:")) {
    if (!signalHardwareReady) return "ERR:HW_UNCONFIGURED";
    if (debugCommand == "DDS:DIAG") return ddsDiagnosticsMessage();
    if (debugCommand == "DDS:TEST") {
      waveEngine.runDdsKnownGoodTest();
      return "OK:DDS:TEST:1KHZ:SINE";
    }
    if (debugCommand == "DDS:TRACE:0" || debugCommand == "DDS:TRACE:1") {
      const bool enabled = debugCommand.endsWith("1");
      waveEngine.setDdsTraceEnabled(enabled);
      return "OK:DDS:TRACE:" + String(enabled ? 1 : 0);
    }
    if (debugCommand == "DDS:RESET:0" || debugCommand == "DDS:RESET:1") {
      const bool reset = debugCommand.endsWith("1");
      waveEngine.setDdsReset(reset);
      return "OK:DDS:RESET:" + String(reset ? 1 : 0);
    }
    return "ERR:DDS_DEBUG_COMMAND";
  }
  if (debugCommand.startsWith("OFFSET:")) {
    if (!signalHardwareReady) return "ERR:HW_UNCONFIGURED";
    if (debugCommand == "OFFSET:DIAG") return offsetDiagnosticsMessage();
    return "ERR:OFFSET_DEBUG_COMMAND";
  }
  if (debugCommand == "CAL:CLEAR") {
    if (!signalHardwareReady) return "ERR:HW_UNCONFIGURED";
    if (calibrationRunning()) return "ERR:CAL_RUNNING";
    waveEngine.setOffsetGainScale(1.0f);
    if (preferencesReady) preferences.putFloat(Config::OFFSET_GAIN_PREFERENCE_KEY, 1.0f);
    return "OK:CAL:CLEAR:GAIN:1.00000";
  }

  CommandProtocol::Command command;
  std::string parseError;
  if (!CommandProtocol::parse(rawCommand.c_str(), command, parseError)) return "ERR:" + String(parseError.c_str());

  if (command.type == CommandProtocol::Type::Help) {
    return "HELP:F:<Hz> A:<Vpp> W:<S|T> TRIM:<signed DAC steps> CAL CAL:CLEAR BLT:<0|1> TELEM:<0|1> STATUS HELP DDS:DIAG DDS:TEST DDS:TRACE:<0|1> DDS:RESET:<0|1> OFFSET:DIAG";
  }
  if (command.type == CommandProtocol::Type::Status) return statusMessage();
  if (command.type == CommandProtocol::Type::Calibrate) {
    String error;
    if (!startCalibration(millis(), error)) return "ERR:" + error;
    return "OK:CAL:STARTED:STEP:1/" + String(Config::OFFSET_GAIN_CALIBRATION_POINTS);
  }
  if (calibrationRunning() && (command.hasFrequency || command.hasAmplitude || command.hasWaveform || command.hasManualOffsetTrim)) {
    return "ERR:CAL_RUNNING";
  }

  if ((command.hasFrequency && (command.frequency < Config::MIN_FREQUENCY_HZ || command.frequency > Config::MAX_FREQUENCY_HZ)) ||
      (command.hasAmplitude && !waveEngine.canProduceAmplitude(command.amplitude)) ||
      (command.hasManualOffsetTrim && !waveEngine.canSetManualOffsetTrimCodes(command.manualOffsetTrimCodes))) return "ERR:OUT_OF_RANGE";
  if ((command.hasFrequency || command.hasAmplitude || command.hasWaveform || command.hasManualOffsetTrim) && !signalHardwareReady) return "ERR:HW_UNCONFIGURED";

  const WaveEngine::Waveform waveform = command.waveform == 'S' ? WaveEngine::Waveform::Sine : WaveEngine::Waveform::Triangle;
  if (command.hasFrequency) waveEngine.setFrequency(command.frequency);
  if (command.hasAmplitude) waveEngine.setAmplitude(command.amplitude);
  if (command.hasWaveform) waveEngine.setWaveform(waveform);
  if (command.hasManualOffsetTrim) {
    waveEngine.setManualOffsetTrimCodes(command.manualOffsetTrimCodes);
    if (preferencesReady) preferences.putInt(Config::MANUAL_TRIM_PREFERENCE_KEY, command.manualOffsetTrimCodes);
  }
  if (command.hasBluetooth) comms.setBluetoothEnabled(command.bluetooth);
  if (command.hasTelemetry) comms.setUsbTelemetryEnabled(command.telemetry);

  String response = "OK";
  if (command.hasFrequency) response += ":F:" + String(command.frequency, 2);
  if (command.hasAmplitude) response += ":A:" + String(waveEngine.appliedAmplitudeVpp(), 3);
  if (command.hasWaveform) response += ":W:" + waveformName(waveform);
  if (command.hasManualOffsetTrim) response += ":TRIM:" + String(command.manualOffsetTrimCodes);
  if (command.hasBluetooth) response += ":BLT:" + String(command.bluetooth ? 1 : 0);
  if (command.hasTelemetry) response += ":TELEM:" + String(command.telemetry ? 1 : 0);
  return response;
}

void updateTelemetry(uint32_t now) {
  if (now - lastTelemetryMs < Config::BATTERY_TELEMETRY_INTERVAL_MS) return;
  lastTelemetryMs = now;
  rails = powerMonitor.readRails();
  if (!rails.valid) return;
  statusLeds.setBatteryHealth(rails.healthPercent);
  comms.broadcastTelemetry("BAT:" + String(rails.positiveVolts, 2) + "," +
                           String(rails.negativeVolts, 2) + "," + String(rails.healthPercent));
}
}  // namespace

void setup() {
  signalHardwareReady = waveEngine.begin();
  powerMonitor.begin();
  statusLeds.begin();
  preferencesReady = preferences.begin(Config::PREFERENCES_NAMESPACE, false);
  if (preferencesReady) {
    waveEngine.setManualOffsetTrimCodes(preferences.getInt(Config::MANUAL_TRIM_PREFERENCE_KEY, 0));
    waveEngine.setOffsetGainScale(preferences.getFloat(Config::OFFSET_GAIN_PREFERENCE_KEY, 1.0f));
  }
  comms.begin(handleCommand);
  Serial.println(signalHardwareReady ? "FDEM-TX READY" : "FDEM-TX READY: CONFIGURE PINS");
}

void loop() {
  const uint32_t now = millis();
  comms.poll();
  updateTelemetry(now);
  updateCalibration(now);
  if (signalHardwareReady) statusLeds.setOutputActive(waveEngine.isOutputActive());
  statusLeds.setBluetoothState(comms.bluetoothEnabled(), comms.bluetoothConnected());
  statusLeds.update(now);
}
