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
        page = WeatherPage()
        try:
            page.controller.skin.units_changed.emit("f")
            self.assertEqual(page._unit_group.button("f").property("selected"), "true")
            self.assertEqual(page._unit_group.button("c").property("selected"), "false")

            page.controller.skin.units_changed.emit("c")
            self.assertEqual(page._unit_group.button("c").property("selected"), "true")
            self.assertEqual(page._unit_group.button("f").property("selected"), "false")
        finally:
            page.close()
            config_manager.set_weather("units", orig_unit)


if __name__ == "__main__":
    unittest.main()
