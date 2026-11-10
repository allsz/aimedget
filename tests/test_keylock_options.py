"""
Opções do Lock keys no Hub: só Caps Lock e Num Lock (o Scroll Lock foi removido, pois nunca teve serviço nem flyout)
e os interruptores realmente controlam se o indicador aparece.
  python tests/test_keylock_options.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from app.core.config_manager import config_manager
from app.core.i18n import TRANSLATIONS
from app.core.typography import init_app_font
from app.hub.service_bridge import HubServiceBridge
from app.hub.theme import THEME_DARK

init_app_font()


class _IsolatedConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = config_manager.config_path
        self._old_cfg = config_manager._data.get("keylock_osd")
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")  # nunca grava a config real
        config_manager._data.pop("keylock_osd", None)

    def tearDown(self):
        config_manager.config_path = self._old_path
        config_manager._data.pop("keylock_osd", None)
        if self._old_cfg is not None:
            config_manager._data["keylock_osd"] = self._old_cfg
        self._tmp.cleanup()


class ConfigTests(_IsolatedConfig):
    def test_default_is_on_for_every_key(self):
        self.assertTrue(config_manager.is_keylock_key_enabled("Caps Lock"))
        self.assertTrue(config_manager.is_keylock_key_enabled("Num Lock"))
        self.assertTrue(config_manager.is_keylock_key_enabled("Qualquer Outra"))

    def test_toggle_is_per_key_and_persisted(self):
        config_manager.set_keylock_key_enabled("Num Lock", False)
        self.assertFalse(config_manager.is_keylock_key_enabled("Num Lock"))
        self.assertTrue(config_manager.is_keylock_key_enabled("Caps Lock"))
        config_manager.set_keylock_key_enabled("Num Lock", True)
        self.assertTrue(config_manager.is_keylock_key_enabled("Num Lock"))
        config_manager.set_keylock_key_enabled("Caps Lock", False)
        self.assertTrue(Path(config_manager.config_path).is_file())

    def test_does_not_disturb_the_hotkey_setting(self):
        config_manager.set_keylock_hotkey("Ctrl+Alt+K")
        config_manager.set_keylock_key_enabled("Caps Lock", False)
        self.assertEqual(config_manager.get_keylock_hotkey("x"), "Ctrl+Alt+K")

    def test_corrupt_values_fall_back_to_on(self):
        config_manager._data["keylock_osd"] = {"keys": "lixo"}
        self.assertTrue(config_manager.is_keylock_key_enabled("Caps Lock"))
        config_manager._data["keylock_osd"] = {"keys": {"Caps Lock": "nao"}}
        self.assertTrue(config_manager.is_keylock_key_enabled("Caps Lock"))
        config_manager.set_keylock_key_enabled("Num Lock", False)     # e a escrita se recupera
        self.assertFalse(config_manager.is_keylock_key_enabled("Num Lock"))


class BridgeFilterTests(_IsolatedConfig):
    def _call(self, name, is_on):
        fake = mock.Mock()                                        # só o que o método usa: o flyout
        HubServiceBridge._on_keylock_changed(fake, name, is_on)
        return fake.keylock_flyout.show_osd

    def test_enabled_key_shows_the_indicator(self):
        show = self._call("Caps Lock", True)
        show.assert_called_once_with("Caps Lock", True)

    def test_disabled_key_stays_silent_but_the_other_still_shows(self):
        config_manager.set_keylock_key_enabled("Caps Lock", False)
        self._call("Caps Lock", True).assert_not_called()
        self._call("Caps Lock", False).assert_not_called()
        self._call("Num Lock", True).assert_called_once_with("Num Lock", True)


class HubPageTests(_IsolatedConfig):
    def _page(self):
        from app.hub.pages import LockKeysPage
        page = LockKeysPage(theme=THEME_DARK)
        self.addCleanup(page.deleteLater)
        return page

    def test_only_caps_and_num_are_offered(self):
        page = self._page()
        self.assertEqual(list(page._key_switches), ["Caps Lock", "Num Lock"])
        self.assertEqual(len(page._opt_labels), 2)

    def test_switches_reflect_the_saved_state_and_write_back(self):
        config_manager.set_keylock_key_enabled("Num Lock", False)
        page = self._page()
        self.assertTrue(page._key_switches["Caps Lock"].isChecked())
        self.assertFalse(page._key_switches["Num Lock"].isChecked())
        page._key_switches["Caps Lock"].setChecked(False)
        self.assertFalse(config_manager.is_keylock_key_enabled("Caps Lock"))
        page._key_switches["Num Lock"].setChecked(True)
        self.assertTrue(config_manager.is_keylock_key_enabled("Num Lock"))

    def test_retranslation_still_works(self):
        page = self._page()
        page.retranslate_ui()


class TextsTests(unittest.TestCase):
    def test_no_scroll_lock_left_in_the_texts(self):
        for lang, table in TRANSLATIONS.items():
            self.assertNotIn("keys_opt_scroll_title", table, lang)
            self.assertNotIn("keys_opt_scroll_sub", table, lang)
            self.assertNotIn("Scroll", table["keys_subtitle"], lang)
        from app.widgets.keylock_osd import KEYLOCK_SPEC
        self.assertNotIn("Scroll", KEYLOCK_SPEC.subtitle)


if __name__ == "__main__":
    unittest.main()
