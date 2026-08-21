#include <unity.h>

#include "CommandProtocol.h"

void setUp() {}
void tearDown() {}

void test_parses_ui_settings_line() {
  CommandProtocol::Command command;
  std::string error;
  TEST_ASSERT_TRUE(CommandProtocol::parse("f:1000 A:10 w:t", command, error));
  TEST_ASSERT_TRUE(command.hasFrequency);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 1000.0f, command.frequency);
  TEST_ASSERT_TRUE(command.hasAmplitude);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 10.0f, command.amplitude);
  TEST_ASSERT_EQUAL_CHAR('T', command.waveform);
}

void test_parses_standalone_commands() {
  CommandProtocol::Command command;
  std::string error;
  TEST_ASSERT_TRUE(CommandProtocol::parse("TRIM:-12 BLT:0", command, error));
  TEST_ASSERT_TRUE(command.hasManualOffsetTrim);
  TEST_ASSERT_EQUAL_INT(-12, command.manualOffsetTrimCodes);
  TEST_ASSERT_FALSE(command.bluetooth);
  TEST_ASSERT_TRUE(CommandProtocol::parse("TELEM:1", command, error));
  TEST_ASSERT_TRUE(command.telemetry);
}

void test_rejects_duplicate_and_malformed_commands() {
  CommandProtocol::Command command;
  std::string error;
  TEST_ASSERT_FALSE(CommandProtocol::parse("F:1 F:2", command, error));
  TEST_ASSERT_EQUAL_STRING("INVALID_FREQUENCY", error.c_str());
  TEST_ASSERT_FALSE(CommandProtocol::parse("W:X", command, error));
  TEST_ASSERT_EQUAL_STRING("INVALID_WAVEFORM", error.c_str());
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_parses_ui_settings_line);
  RUN_TEST(test_parses_standalone_commands);
  RUN_TEST(test_rejects_duplicate_and_malformed_commands);
  return UNITY_END();
}
