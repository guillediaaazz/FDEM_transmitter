#include <unity.h>

#include "CommandProtocol.h"
#include "OffsetGainMath.h"

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
  TEST_ASSERT_TRUE(CommandProtocol::parse("CAL", command, error));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(CommandProtocol::Type::Calibrate), static_cast<int>(command.type));
  TEST_ASSERT_TRUE(CommandProtocol::parse("TRIM:-12 BLT:0", command, error));
  TEST_ASSERT_TRUE(command.hasManualOffsetTrim);
  TEST_ASSERT_EQUAL_INT(-12, command.manualOffsetTrimCodes);
  TEST_ASSERT_FALSE(command.bluetooth);
  TEST_ASSERT_TRUE(CommandProtocol::parse("TELEM:1", command, error));
  TEST_ASSERT_TRUE(command.telemetry);
}

void test_derives_offset_gain_scale_from_feedback_slopes() {
  const float nominalDac[] = {0.1f, 0.2f, 0.3f, 0.4f, 0.5f};
  const float feedback[] = {1.728f, 1.806f, 1.884f, 1.962f, 2.040f};
  const OffsetGainMath::LinearFit fit = OffsetGainMath::fitLine(nominalDac, feedback, 5);
  TEST_ASSERT_TRUE(fit.valid);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 0.78f, fit.slope);
  float calculatedScale = 0.0f;
  TEST_ASSERT_TRUE(OffsetGainMath::deriveGainScale(1.0f, fit.slope, -19.5f,
                                                    0.01f, 0.75f, 1.25f, calculatedScale));
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 1.04f, calculatedScale);
}

void test_rejects_invalid_gain_derivation() {
  float calculatedScale = 0.0f;
  TEST_ASSERT_FALSE(OffsetGainMath::deriveGainScale(1.0f, 0.1f, 0.001f,
                                                     0.01f, 0.75f, 1.25f, calculatedScale));
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
  RUN_TEST(test_derives_offset_gain_scale_from_feedback_slopes);
  RUN_TEST(test_rejects_invalid_gain_derivation);
  return UNITY_END();
}
