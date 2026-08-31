#pragma once

#include <cmath>
#include <cctype>
#include <climits>
#include <cstdlib>
#include <string>

// Platform-independent parser so the serial/BLE grammar can be unit-tested on
// a desktop. Hardware validation and command execution remain in main.cpp.
namespace CommandProtocol {
enum class Type { Help, Status, Calibrate, Settings };

struct Command {
  Type type = Type::Settings;
  bool hasFrequency = false;
  bool hasAmplitude = false;
  bool hasWaveform = false;
  bool hasManualOffsetTrim = false;
  bool hasBluetooth = false;
  bool hasTelemetry = false;
  float frequency = 0.0f;
  float amplitude = 0.0f;
  char waveform = 'S';
  int manualOffsetTrimCodes = 0;
  bool bluetooth = false;
  bool telemetry = false;
};

inline std::string normalize(const std::string& raw) {
  const std::size_t first = raw.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) return "";
  const std::size_t last = raw.find_last_not_of(" \t\r\n");
  std::string result = raw.substr(first, last - first + 1);
  for (std::size_t index = 0; index < result.size(); ++index) {
    result[index] = static_cast<char>(std::toupper(static_cast<unsigned char>(result[index])));
  }
  return result;
}

inline bool parseFloat(const std::string& text, float& value) {
  if (text.empty()) return false;
  char* end = nullptr;
  value = std::strtof(text.c_str(), &end);
  return end != text.c_str() && *end == '\0' && std::isfinite(value);
}

inline bool parseSwitch(const std::string& text, bool& value) {
  if (text == "0") {
    value = false;
    return true;
  }
  if (text == "1") {
    value = true;
    return true;
  }
  return false;
}

inline bool parseInt(const std::string& text, int& value) {
  if (text.empty()) return false;
  char* end = nullptr;
  const long parsed = std::strtol(text.c_str(), &end, 10);
  if (end == text.c_str() || *end != '\0' || parsed < INT_MIN || parsed > INT_MAX) return false;
  value = static_cast<int>(parsed);
  return true;
}

inline bool parse(const std::string& raw, Command& command, std::string& error) {
  command = Command();
  const std::string line = normalize(raw);
  if (line == "HELP") {
    command.type = Type::Help;
    return true;
  }
  if (line == "STATUS") {
    command.type = Type::Status;
    return true;
  }
  if (line == "CAL") {
    command.type = Type::Calibrate;
    return true;
  }
  if (line.empty()) {
    error = "INVALID_SYNTAX";
    return false;
  }

  std::size_t start = 0;
  while (start < line.size()) {
    const std::size_t end = line.find_first_of(" \t", start);
    const std::string token = line.substr(start, end == std::string::npos ? std::string::npos : end - start);
    start = end == std::string::npos ? line.size() : line.find_first_not_of(" \t", end);
    if (start == std::string::npos) start = line.size();

    const std::size_t colon = token.find(':');
    if (colon == 0 || colon == std::string::npos || colon == token.size() - 1 || token.find(':', colon + 1) != std::string::npos) {
      error = "INVALID_SYNTAX";
      return false;
    }
    const std::string key = token.substr(0, colon);
    const std::string value = token.substr(colon + 1);
    if (key == "F") {
      if (command.hasFrequency || !parseFloat(value, command.frequency)) { error = "INVALID_FREQUENCY"; return false; }
      command.hasFrequency = true;
    } else if (key == "A") {
      if (command.hasAmplitude || !parseFloat(value, command.amplitude)) { error = "INVALID_AMPLITUDE"; return false; }
      command.hasAmplitude = true;
    } else if (key == "W") {
      if (command.hasWaveform || (value != "S" && value != "T")) { error = "INVALID_WAVEFORM"; return false; }
      command.waveform = value[0];
      command.hasWaveform = true;
    } else if (key == "TRIM") {
      if (command.hasManualOffsetTrim || !parseInt(value, command.manualOffsetTrimCodes)) { error = "INVALID_TRIM"; return false; }
      command.hasManualOffsetTrim = true;
    } else if (key == "BLT") {
      if (command.hasBluetooth || !parseSwitch(value, command.bluetooth)) { error = "INVALID_BLT"; return false; }
      command.hasBluetooth = true;
    } else if (key == "TELEM") {
      if (command.hasTelemetry || !parseSwitch(value, command.telemetry)) { error = "INVALID_TELEM"; return false; }
      command.hasTelemetry = true;
    } else {
      error = "UNKNOWN_COMMAND";
      return false;
    }
  }
  if (!command.hasFrequency && !command.hasAmplitude && !command.hasWaveform &&
      !command.hasManualOffsetTrim && !command.hasBluetooth && !command.hasTelemetry) {
    error = "INVALID_SYNTAX";
    return false;
  }
  return true;
}
}  // namespace CommandProtocol
