from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fdem_controller.i18n import EN, ES, ERRORS, Translator, validate_translations
from fdem_controller.settings import AppSettings, SettingsStore


class TranslationAndSettingsTests(unittest.TestCase):
    def test_translation_catalogs_have_identical_keys(self) -> None:
        validate_translations()
        self.assertEqual(set(EN), set(ES))
        self.assertEqual(set(ERRORS["en"]), set(ERRORS["es"]))

    def test_translator_formats_and_translates_device_errors(self) -> None:
        translator = Translator("es")
        self.assertEqual(translator("cal_sweep", point=2, total=5), "En curso · barrido 2/5")
        self.assertIn("no lineales", translator.device_error("CAL:NONLINEAR"))
        translator.set_language("unsupported")
        self.assertEqual(translator.language, "en")

    def test_settings_roundtrip_only_contains_ui_preferences(self) -> None:
        path = MagicMock()
        temporary = MagicMock()
        path.with_suffix.return_value = temporary
        store = SettingsStore(path)
        expected = AppSettings("es", "1000x700", "usb", "COM7")
        store.save(expected)
        written = temporary.write_text.call_args.args[0]
        self.assertIn('"language": "es"', written)
        self.assertNotIn("frequency", written)
        self.assertNotIn("amplitude", written)
        temporary.replace.assert_called_once_with(path)

        path.read_text.return_value = written
        self.assertEqual(store.load(), expected)

    def test_corrupt_settings_fall_back_safely(self) -> None:
        path = MagicMock()
        path.read_text.return_value = "not json"
        settings = SettingsStore(path).load()
        self.assertIn(settings.language, {"en", "es"})
        self.assertEqual(settings.last_transport, "usb")


if __name__ == "__main__":
    unittest.main()
