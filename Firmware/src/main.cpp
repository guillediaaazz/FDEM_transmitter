#include <Arduino.h>
#include <Preferences.h>

#include "CommandProtocol.h"
#include "CommsManager.h"
#include "Config.h"
#include "PowerMonitor.h"
#include "StatusLeds.h"
#include "WaveEngine.h"

namespace {
CommsManager comms;
PowerMonitor powerMonitor;
StatusLeds statusLeds;
WaveEngine waveEngine;
Preferences preferences;
RailReadings rails;
bool signalHardwareReady = false;
bool preferencesReady = false;
uint32_t lastTelemetryMs = 0;

String waveformName(WaveEngine::Waveform waveform) {
  return waveform == WaveEngine::Waveform::Sine ? "S" : "T";
}

String hexWord(uint16_t value) {
  char text[7];
  snprintf(text, sizeof(text), "0x%04X", value);
  return String(text);
}

String ddsDiagnosticsMessage() {
  const AD9837::Diagnostics diagnostics = waveEngine.ddsDiagnostics();
  char tuningWord[11];
  snprintf(tuningWord, sizeof(tuningWord), "0x%07lX", static_cast<unsigned long>(diagnostics.tuningWord));
  return "DDS:DIAG:F:" + String(diagnostics.frequencyHz, 3) +
         ",TW:" + String(tuningWord) +
         ",CTRL:" + hexWord(diagnostics.controlWord) +
         ",LSW:" + hexWord(diagnostics.frequencyLsbWord) +
         ",MSW:" + hexWord(diagnostics.frequencyMsbWord) +
         ",RESET:" + String(diagnostics.resetApplied ? 1 : 0) +
         ",W:" + String(diagnostics.waveform == AD9837::Waveform::Sine ? "S" : "T") +
         ",SPI:MODE2:4MHZ,WORDS:" + String(diagnostics.wordsWritten) +
         ",PINS:SCLK:" + String(Config::PIN_SPI_SCK) +
         ",SDATA:" + String(Config::PIN_SPI_MOSI) +
         ",FSYNC:" + String(Config::PIN_AD9837_FSYN);
}

String statusMessage() {
  String message = "STATUS:F:" + String(waveEngine.frequencyHz(), 2) +
                   ",A:" + String(waveEngine.appliedAmplitudeVpp(), 3) +
                   ",W:" + waveformName(waveEngine.waveform()) +
                   ",AUTOCAL:" + String(waveEngine.autoCalibrationEnabled() ? 1 : 0) +
                   ",CAL:" + String(waveEngine.calibrationRunning() ? "RUNNING" : "IDLE") +
                   ",BLT:" + String(comms.bluetoothEnabled() ? 1 : 0) +
                   ",TELEM:" + String(comms.usbTelemetryEnabled() ? 1 : 0);
  if (rails.valid) {
    message += ",BATP:" + String(rails.positiveVolts, 2) +
               ",BATN:" + String(rails.negativeVolts, 2) +
               ",BAT:" + String(rails.healthPercent);
  } else {
    message += ",BAT:UNAVAILABLE";
  }
  return message;
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

  CommandProtocol::Command command;
  std::string parseError;
  if (!CommandProtocol::parse(rawCommand.c_str(), command, parseError)) return "ERR:" + String(parseError.c_str());

  if (command.type == CommandProtocol::Type::Help) {
    return "HELP:F:<Hz> A:<Vpp> W:<S|T> CAL AUTOCAL:<0|1> BLT:<0|1> TELEM:<0|1> STATUS HELP DDS:DIAG DDS:TEST DDS:TRACE:<0|1> DDS:RESET:<0|1>";
  }
  if (command.type == CommandProtocol::Type::Status) return statusMessage();
  if (command.type == CommandProtocol::Type::Calibrate) {
    if (!signalHardwareReady) return "ERR:HW_UNCONFIGURED";
    if (waveEngine.calibrationRunning()) return "ERR:CAL_ALREADY_RUNNING";
    waveEngine.startCalibration();
    return "OK:CAL:STARTED";
  }

  if ((command.hasFrequency && (command.frequency < Config::MIN_FREQUENCY_HZ || command.frequency > Config::MAX_FREQUENCY_HZ)) ||
      (command.hasAmplitude && !waveEngine.canProduceAmplitude(command.amplitude))) return "ERR:OUT_OF_RANGE";
  if ((command.hasFrequency || command.hasAmplitude || command.hasWaveform || command.hasAutoCalibration) && !signalHardwareReady) return "ERR:HW_UNCONFIGURED";

  const WaveEngine::Waveform waveform = command.waveform == 'S' ? WaveEngine::Waveform::Sine : WaveEngine::Waveform::Triangle;
  if (command.hasFrequency) waveEngine.setFrequency(command.frequency);
  if (command.hasAmplitude) waveEngine.setAmplitude(command.amplitude);
  if (command.hasWaveform) waveEngine.setWaveform(waveform);
  if (command.hasAutoCalibration) waveEngine.setAutoCalibration(command.autoCalibration);
  if (command.hasBluetooth) comms.setBluetoothEnabled(command.bluetooth);
  if (command.hasTelemetry) comms.setUsbTelemetryEnabled(command.telemetry);

  String response = "OK";
  if (command.hasFrequency) response += ":F:" + String(command.frequency, 2);
  if (command.hasAmplitude) response += ":A:" + String(waveEngine.appliedAmplitudeVpp(), 3);
  if (command.hasWaveform) response += ":W:" + waveformName(waveform);
  if (command.hasAutoCalibration) response += ":AUTOCAL:" + String(command.autoCalibration ? 1 : 0);
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
  preferencesReady = preferences.begin("fdem-tx", false);
  if (preferencesReady) waveEngine.setStoredCorrection(preferences.getInt("offset-corr", 0));
  comms.begin(handleCommand);
  Serial.println(signalHardwareReady ? "FDEM-TX READY" : "FDEM-TX READY: CONFIGURE PINS");
}

void loop() {
  const uint32_t now = millis();
  comms.poll();
  updateTelemetry(now);

  if (signalHardwareReady) {
    waveEngine.updateOffset(powerMonitor.readOffsetFeedbackVolts(), now);
    if (waveEngine.takeCalibrationFinished()) {
      if (preferencesReady) preferences.putInt("offset-corr", waveEngine.correctionCodes());
      comms.broadcast("OK:CAL:COMPLETE");
    }
    statusLeds.setOutputActive(waveEngine.isOutputActive());
  }
  statusLeds.setBluetoothState(comms.bluetoothEnabled(), comms.bluetoothConnected());
  statusLeds.update(now);
}
