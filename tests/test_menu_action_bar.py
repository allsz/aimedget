"""Testes da barra superior Fluent Rail nos menus de contexto dos widgets."""

import unittest
from unittest import mock

from PySide6.QtCore import QPoint
from PySide6.QtGui import QContextMenuEvent, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core import widget_animator
from app.core.anchor_manager import anchor_manager
from app.hub.theme import THEME_DARK, THEME_LIGHT, THEME_TRUE_DARK
from app.ui_components.fluent_menu import FluentMusicMenu
from app.ui_components.menu_action_bar import ActionBarItem, FluentActionBar
from app.widgets.music.skins.vinyl_skin import VinylMusicSkin
from app.widgets.performance.performance_card import PerformanceCard
from app.widgets.timer.skins.base_skin import FluentTimerMenu
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
from app.widgets.weather.weather_card import WeatherCard

_app = QApplication.instance() or QApplication([])


def _capture_menu(widget, menu_cls=FluentMusicMenu):
    captured = {}

    def fake_exec(self, *args, **kwargs):
        captured["menu"] = self
        captured["bar"] = self.action_bar
        captured["actions"] = list(self.actions())

    with mock.patch.object(menu_cls, "exec", fake_exec):
        widget.contextMenuEvent(
            QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5))
        )
    return captured


class FluentActionBarUnitTests(unittest.TestCase):
    def test_toggle_indicator_dot_to_bar_and_off_state(self):
        toggled = []
        items = [
            ActionBarItem("pin", "pin", "Remember", toggle=True, checked=False, on_trigger=toggled.append),
            ActionBarItem("anchor", "anchor", "Anchor", toggle=True, checked=True, on_trigger=lambda v: None),
        ]
        bar = FluentActionBar(items, theme=THEME_DARK)
        bar.resize(220, 40)

        pin_btn = bar.button("pin")
        anchor_btn = bar.button("anchor")

        # Desmarcado: nada visível (sem ponto nem barrinha)
        self.assertFalse(pin_btn.isChecked())
        self.assertEqual(pin_btn._dot_alpha.x, 0.0)
        self.assertEqual(pin_btn._bar.x, 0.0)

        # Marcado inicialmente (ex.: ancorado): permanece selecionado
        self.assertTrue(anchor_btn.isChecked())
        self.assertEqual(anchor_btn._dot_alpha.x, 1.0)
        self.assertEqual(anchor_btn._bar.x, 1.0)

        # Clicar liga o toggle com alvo dot -> bar
        with mock.patch.object(widget_animator, "animations_enabled", return_value=True):
            pin_btn.click()
            self.assertTrue(pin_btn.isChecked())
            self.assertEqual(toggled, [True])
            self.assertEqual(pin_btn._dot_alpha.t, 1.0)
            self.assertEqual(pin_btn._bar.t, 1.0)

            # Clicar de novo desliga e manda a barrinha encolher de volta a 0
            pin_btn.click()
            self.assertFalse(pin_btn.isChecked())
            self.assertEqual(toggled, [True, False])
            self.assertEqual(pin_btn._bar.t, 0.0)

    def test_paints_cleanly_in_all_themes(self):
        items = [
            ActionBarItem("refresh", "refresh", "Refresh", spin_on_click=True, on_trigger=lambda: None),
            ActionBarItem("pin", "pin", "Pin", toggle=True, checked=True, on_trigger=lambda v: None),
            ActionBarItem("desktop", "desktop", "Desktop", toggle=True, checked=False, on_trigger=lambda v: None),
            ActionBarItem("anchor", "anchor", "Anchor", toggle=True, checked=True, on_trigger=lambda v: None),
            ActionBarItem("detach", "detach", "Detach", on_trigger=lambda: None),
            ActionBarItem("smart_hover", "smart_hover", "Smart", toggle=True, checked=True, on_trigger=lambda v: None),
            ActionBarItem("reset_size", "reset_size", "Reset", spin_on_click=True, on_trigger=lambda: None),
        ]
        for theme in (THEME_LIGHT, THEME_DARK, THEME_TRUE_DARK):
            bar = FluentActionBar(items, theme=theme)
            bar.resize(320, 40)
            bar._pill.hover(bar.button("pin"))
            img = QImage(320, 40, QImage.Format.Format_ARGB32)
            img.fill(0)
            bar.render(img)


class WidgetContextMenuRailTests(unittest.TestCase):
    def test_weather_menu_has_refresh_pin_desktop_in_top_rail(self):
        card = WeatherCard()
        try:
            refreshed = []
            card.refresh_requested.connect(lambda: refreshed.append(1))
            res = _capture_menu(card, FluentMusicMenu)
            bar = res["bar"]
            self.assertIsNotNone(bar)
            self.assertIn("refresh", bar.buttons)
            self.assertIn("pin", bar.buttons)
            self.assertIn("desktop", bar.buttons)
            # Refresh é exclusivo do Weather e dispara o sinal
            bar.button("refresh").click()
            self.assertEqual(refreshed, [1])
        finally:
            card.close()

    def test_performance_menu_has_pin_desktop_without_refresh(self):
        card = PerformanceCard()
        try:
            res = _capture_menu(card, FluentMusicMenu)
            bar = res["bar"]
            self.assertIsNotNone(bar)
            self.assertNotIn("refresh", bar.buttons)
            self.assertIn("pin", bar.buttons)
            self.assertIn("desktop", bar.buttons)
        finally:
            card.close()

    def test_timer_menu_has_pin_smart_hover_reset_size(self):
        skin = WindowsTimerSkin()
        try:
            res = _capture_menu(skin, FluentTimerMenu)
            bar = res["bar"]
            self.assertIsNotNone(bar)
            self.assertIn("pin", bar.buttons)
            self.assertIn("smart_hover", bar.buttons)
            self.assertIn("reset_size", bar.buttons)
        finally:
            skin.close()

    def test_anchor_button_remains_selected_while_anchored(self):
        skin = VinylMusicSkin(scale=0.5)
        mgr = anchor_manager()
        try:
            mgr._windows["music"] = skin
            mgr.set_anchored(skin, True)
            res = _capture_menu(skin, FluentMusicMenu)
            anchor_btn = res["bar"].button("anchor")
            self.assertIsNotNone(anchor_btn)
            self.assertTrue(anchor_btn.isChecked())
            # Clicar desancora e atualiza o estado do gerenciador
            anchor_btn.click()
            self.assertFalse(mgr.is_anchored(skin))
        finally:
            mgr.set_anchored(skin, False)
            skin.close()


if __name__ == "__main__":
    unittest.main()
