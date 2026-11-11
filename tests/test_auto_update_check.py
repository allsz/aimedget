"""
Verificação automática de atualizações: padrão ligado, no máximo uma consulta por dia, pergunta antes de atualizar e
sem insistir numa versão que o usuário recusou.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.services.updater_service import AUTO_CHECK_INTERVAL_S, UpdateInfo, is_check_due

DAY = AUTO_CHECK_INTERVAL_S


class CheckDueTests(unittest.TestCase):
    def test_never_checked_is_due(self):
        self.assertTrue(is_check_due(0.0, 1_000_000.0))

    def test_checked_less_than_a_day_ago_is_not_due(self):
        now = 1_000_000.0
        self.assertFalse(is_check_due(now - 60, now))
        self.assertFalse(is_check_due(now - (DAY - 1), now))

    def test_a_day_later_is_due_again(self):
        now = 1_000_000.0
        self.assertTrue(is_check_due(now - DAY, now))
        self.assertTrue(is_check_due(now - 3 * DAY, now))

    def test_clock_set_back_does_not_block_checks_forever(self):
        now = 1_000_000.0
        self.assertTrue(is_check_due(now + 5 * DAY, now))


class _Config(unittest.TestCase):
    """Isola as chaves de atualização do config real do usuário (restaura no fim)."""

    def setUp(self):
        self._saved = dict(config_manager._data.get("updates", {})) if "updates" in config_manager._data else None
        config_manager._data.pop("updates", None)
        self._save = mock.patch.object(config_manager, "_save")
        self._save.start()

    def tearDown(self):
        self._save.stop()
        config_manager._data.pop("updates", None)
        if self._saved is not None:
            config_manager._data["updates"] = self._saved


class ConfigTests(_Config):
    def test_defaults_on_and_never_checked(self):
        self.assertTrue(config_manager.is_auto_update_check_enabled())
        self.assertEqual(config_manager.get_last_update_check(), 0.0)
        self.assertEqual(config_manager.get_declined_update_version(), "")

    def test_toggle_and_values_round_trip(self):
        config_manager.set_auto_update_check_enabled(False)
        self.assertFalse(config_manager.is_auto_update_check_enabled())
        config_manager.set_last_update_check(123.5)
        config_manager.set_declined_update_version("1.0.1")
        self.assertEqual(config_manager.get_last_update_check(), 123.5)
        self.assertEqual(config_manager.get_declined_update_version(), "1.0.1")

    def test_garbage_in_the_config_falls_back_to_defaults(self):
        config_manager._data["updates"] = {"auto_check": "sim", "last_check": "ontem", "declined_version": 7}
        self.assertTrue(config_manager.is_auto_update_check_enabled())
        self.assertEqual(config_manager.get_last_update_check(), 0.0)
        self.assertEqual(config_manager.get_declined_update_version(), "")


def _info(version="1.0.1") -> UpdateInfo:
    return UpdateInfo(latest_version=version, release_name="x", body="", download_url="https://x/setup.exe",
                      asset_name="Aimedget-Setup.exe", published_at="")


class HubWindowFlowTests(_Config):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        super().setUp()
        from app.hub import hub_window as hw

        self.hw = hw
        with mock.patch.object(hw.QTimer, "singleShot"):   # sem a consulta real ao GitHub de 5 s depois de abrir
            self.win = hw.AimedgetHubWindow()
        self.win.tray_icon.showMessage = mock.Mock()

    def tearDown(self):
        self.win.tray_icon.hide()
        super().tearDown()

    def test_disabled_or_not_due_never_calls_github(self):
        with mock.patch("app.services.updater_service.updater_service.check_for_updates") as check:
            config_manager.set_auto_update_check_enabled(False)
            self.win._check_background_update()
            config_manager.set_auto_update_check_enabled(True)
            config_manager.set_last_update_check(time.time() - 60)   # consultou há 1 minuto
            self.win._check_background_update()
            check.assert_not_called()

    def test_enabled_and_due_checks_once(self):
        with mock.patch("app.services.updater_service.updater_service.check_for_updates") as check:
            self.win._check_background_update()
            check.assert_called_once()

    def test_hub_in_tray_shows_a_balloon_and_does_not_open_a_dialog(self):
        self.win.hide()
        with mock.patch.object(self.hw, "confirm") as ask:
            self.win._on_background_update_found(_info())
            ask.assert_not_called()
        self.win.tray_icon.showMessage.assert_called_once()
        self.assertGreater(config_manager.get_last_update_check(), 0)

    def test_hub_open_asks_and_yes_starts_the_update(self):
        self.win.show()
        with mock.patch.object(self.hw, "confirm", return_value=True) as ask, \
             mock.patch.object(self.win.page_gen, "start_update") as start:
            self.win._on_background_update_found(_info())
            ask.assert_called_once()
            start.assert_called_once()
        self.assertEqual(config_manager.get_declined_update_version(), "")
        self.win.hide()

    def test_no_remembers_the_version_and_stops_asking_for_it(self):
        self.win.show()
        with mock.patch.object(self.hw, "confirm", return_value=False) as ask:
            self.win._on_background_update_found(_info("1.0.1"))
            self.assertEqual(config_manager.get_declined_update_version(), "1.0.1")
            self.win._on_background_update_found(_info("1.0.1"))   # mesma versão no dia seguinte
            self.assertEqual(ask.call_count, 1)
            self.win._on_background_update_found(_info("1.0.2"))   # uma versão MAIS nova: pergunta de novo
            self.assertEqual(ask.call_count, 2)
        self.win.hide()

    def test_clicking_the_balloon_opens_the_question(self):
        self.win.hide()
        self.win._on_background_update_found(_info())
        with mock.patch.object(self.hw, "confirm", return_value=False) as ask:
            self.win._on_tray_message_clicked()
            ask.assert_called_once()
        self.win.hide()


class GeneralPageTests(_Config):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_switch_reflects_and_writes_the_setting(self):
        from app.hub.pages import GeneralPage

        page = GeneralPage()
        self.assertTrue(page.sw_auto_update.isChecked())
        page.sw_auto_update.toggled.emit(False)
        self.assertFalse(config_manager.is_auto_update_check_enabled())

    def test_start_update_uses_the_normal_update_path(self):
        from app.hub.pages import GeneralPage

        page = GeneralPage()
        with mock.patch.object(page, "_apply_update") as apply:
            page.start_update(_info())
            self.assertEqual(page._pending_update_info.latest_version, "1.0.1")
            apply.assert_called_once()


if __name__ == "__main__":
    unittest.main()
