"""Regressão: ações de menu dos widgets devem restaurar o Hub (mesmo minimizado) e rolar até a seção alvo."""

import unittest
from unittest import mock

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication

from app.core.i18n import t
from app.hub.hub_window import AimedgetHubWindow
from app.ui_components.fluent_menu import FluentMusicMenu
from app.widgets.weather.weather_card import WeatherCard

_app = QApplication.instance() or QApplication([])


class HubDeepLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = AimedgetHubWindow()
        cls.hub.resize(900, 560)

    @classmethod
    def tearDownClass(cls):
        cls.hub.hide()
        cls.hub.tray_icon.hide()

    def test_show_and_activate_restores_minimized_window(self):
        self.hub.show()
        self.hub.setWindowState(self.hub.windowState() | Qt.WindowState.WindowMinimized)
        _app.processEvents()
        self.assertTrue(self.hub.isMinimized())

        self.hub.show_and_activate()
        _app.processEvents()
        self.assertTrue(self.hub.isVisible())
        self.assertFalse(self.hub.isMinimized())

    def test_show_weather_cities_opens_hub_and_scrolls_to_cities(self):
        self.hub.sidebar.select_page("ov")
        self.hub.page_weather.scroll.verticalScrollBar().setValue(0)
        self.hub.setWindowState(self.hub.windowState() | Qt.WindowState.WindowMinimized)
        _app.processEvents()

        self.hub.show_weather_cities()
        _app.processEvents()

        self.assertTrue(self.hub.isVisible())
        self.assertFalse(self.hub.isMinimized())
        self.assertEqual(self.hub.stack.currentWidget(), self.hub.page_weather)
        self.assertGreater(self.hub.page_weather.scroll.verticalScrollBar().value(), 0)

    def test_show_music_skins_opens_hub_and_scrolls_to_skins(self):
        self.hub.sidebar.select_page("ov")
        self.hub.page_music.scroll.verticalScrollBar().setValue(0)
        self.hub.hide()
        _app.processEvents()

        self.hub.show_music_skins()
        _app.processEvents()

        self.assertTrue(self.hub.isVisible())
        self.assertFalse(self.hub.isMinimized())
        self.assertEqual(self.hub.stack.currentWidget(), self.hub.page_music)
        self.assertGreater(self.hub.page_music.scroll.verticalScrollBar().value(), 0)

    def test_show_and_activate_fades_in_from_zero_opacity_to_hide_white_flash(self):
        import time

        self.hub.hide()
        _app.processEvents()

        self.hub.show_and_activate()
        self.assertEqual(self.hub.windowOpacity(), 0.0)

        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline and self.hub.windowOpacity() < 0.999:
            _app.processEvents()
            time.sleep(0.01)
        self.assertAlmostEqual(self.hub.windowOpacity(), 1.0, places=2)

    def test_weather_card_menu_manage_cities_emits_signal(self):
        card = WeatherCard()
        got = []
        card.manage_cities_requested.connect(lambda: got.append(1))

        captured = {}

        def fake_exec(menu_self, *args, **kwargs):
            for act in menu_self.actions():
                sub = act.menu()
                if sub is not None:
                    for sub_act in sub.actions():
                        if sub_act.text() == t("weather_menu_manage_cities"):
                            captured["action"] = sub_act

        with mock.patch.object(FluentMusicMenu, "exec", fake_exec):
            card.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(10, 10), QPoint(10, 10)))

        self.assertIn("action", captured)
        captured["action"].trigger()
        self.assertEqual(got, [1])
