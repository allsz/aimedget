"""Testes de sincronização ao vivo entre menus de contexto dos widgets e páginas do Hub."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.hub.pages import TimerPage
from app.hub.weather_page import WeatherPage


class TestWidgetHubSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_timer_context_menu_toggles_sync_to_hub_page(self):
        orig_smart = config_manager.is_timer_smart_hover_enabled()
        orig_rem = config_manager.is_timer_position_remembered()
        page = TimerPage()
        try:
            skin = page.bridge.timer_controller.skin
            self.assertIsNotNone(skin)

            skin._toggle_smart_hover(False)
            self.assertFalse(page.sw_smart_hover.isChecked())
            skin._toggle_smart_hover(True)
            self.assertTrue(page.sw_smart_hover.isChecked())

            skin._toggle_remember_position(False)
            self.assertFalse(page.sw_remember.isChecked())
            skin._toggle_remember_position(True)
            self.assertTrue(page.sw_remember.isChecked())
        finally:
            page.close()
            config_manager.set_timer_smart_hover_enabled(orig_smart)
            config_manager.set_timer_position_remembered(orig_rem)

    def test_weather_context_menu_units_sync_to_hub_page(self):
        orig_unit = config_manager.get_weather("units", "c")
        orig_mode = config_manager.get_weather("forecast_mode", "daily")
        page = WeatherPage()
        try:
            page.controller.skin.units_changed.emit("f")
            self.assertEqual(page._unit_group.button("f").property("selected"), "true")
            self.assertEqual(page._unit_group.button("c").property("selected"), "false")

            page.controller.skin.units_changed.emit("c")
            self.assertEqual(page._unit_group.button("c").property("selected"), "true")
            self.assertEqual(page._unit_group.button("f").property("selected"), "false")

            page.controller.skin.forecast_mode_changed.emit("hourly")
            self.assertEqual(page.controller.forecast_mode(), "hourly")
            self.assertEqual(page._forecast_group.button("hourly").property("selected"), "true")

            page.controller.skin.forecast_mode_changed.emit("daily")
            self.assertEqual(page.controller.forecast_mode(), "daily")
            self.assertEqual(page._forecast_group.button("daily").property("selected"), "true")
        finally:
            page.close()
            config_manager.set_weather("units", orig_unit)
            config_manager.set_weather("forecast_mode", orig_mode)

    def test_battery_context_menu_follow_accent_syncs_to_hub_page(self):
        from app.hub.battery_page import BatteryPage

        orig = bool(config_manager.get_battery("follow_accent", False))
        page = BatteryPage()
        try:
            page.controller.skin.option_requested.emit("follow_accent", "on")
            self.assertTrue(bool(config_manager.get_battery("follow_accent", False)))
            self.assertTrue(page.sw_accent.isChecked())

            page.controller.skin.option_requested.emit("follow_accent", "off")
            self.assertFalse(bool(config_manager.get_battery("follow_accent", False)))
            self.assertFalse(page.sw_accent.isChecked())
        finally:
            page.close()
            config_manager.set_battery("follow_accent", orig)


if __name__ == "__main__":
    unittest.main()
