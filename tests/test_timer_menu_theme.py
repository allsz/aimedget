"""Abrir o menu de contexto do Timer não pode descartar as cores do tema escolhido (destaque, borda, botões)."""

import unittest
from unittest import mock

from PySide6.QtCore import QPoint
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication

import app.widgets.timer.skins.base_skin as base_skin
from app.hub.theme import THEME_DARK, THEME_LIGHT
from app.widgets.timer import theme as timer_theme
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin

_app = QApplication.instance() or QApplication([])

LAVENDER = {
    "card_bg": "#b78af0", "border": "#aaffffff", "text": "#ffffff", "muted_text": "#f1e6ff",
    "accent": "#6a35c9", "accent_hover": "#5a2bb3", "on_accent": "#ffffff", "button_bg": "#33ffffff", "icon": "#ffffff",
}


def _open_menu(skin):
    with mock.patch.object(base_skin.FluentTimerMenu, "exec", lambda self, *a: None):
        skin.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5)))


def _colors(skin):
    t = skin.theme
    return (t.accent, t.line, t.panel2, t.panel, t.text)


class MenuKeepsTheTimerThemeTests(unittest.TestCase):
    def _skin(self, data):
        theme = timer_theme.theme_from_dict(data)
        with mock.patch.object(timer_theme, "load_user_theme", lambda: theme):
            return WindowsTimerSkin(), theme

    def test_theme_colors_survive_opening_the_menu_any_number_of_times(self):
        skin, _ = self._skin(LAVENDER)
        before = _colors(skin)
        self.assertEqual(skin.theme.accent.lower(), "#ff6a35c9")
        for _ in range(3):
            _open_menu(skin)
            self.assertEqual(_colors(skin), before)

    def test_menu_still_follows_the_hub_theme_underneath(self):
        # tema só com figurinhas (sem cores): o Timer segue o claro/escuro do Hub, e o menu o atualiza
        skin, _ = self._skin({"stickers": []})
        for hub in (THEME_DARK, THEME_LIGHT):
            with mock.patch.object(skin, "_resolve_active_theme", lambda h=hub: h):
                _open_menu(skin)
            self.assertEqual(skin.theme.line, hub.line)

    def test_partial_theme_keeps_its_own_colors_and_takes_the_rest_from_the_hub(self):
        skin, _ = self._skin({"accent": "#6a35c9"})
        with mock.patch.object(skin, "_resolve_active_theme", lambda: THEME_DARK):
            _open_menu(skin)
        self.assertEqual(skin.theme.accent.lower(), "#ff6a35c9")   # do tema
        self.assertEqual(skin.theme.line, THEME_DARK.line)          # do Hub

    def test_menu_uses_the_hub_colors_not_the_timer_theme(self):
        """
        O texto do tema (ex.: branco) sobre o fundo do menu claro o deixava ilegível, e a borda translúcida do tema
        aparecia mais clara nas curvas. O menu segue o Hub; só o widget usa as cores do tema.
        """
        skin, _ = self._skin(LAVENDER)
        for hub in (THEME_DARK, THEME_LIGHT):
            with mock.patch.object(skin, "_resolve_active_theme", lambda h=hub: h):
                qss = skin._build_menu_qss() if skin.update_theme() is None else ""
            self.assertIn(hub.menu_bg, qss)
            self.assertIn(hub.line, qss)
            self.assertNotIn("aaffffff", qss.lower())      # a borda translúcida do tema fica fora do menu
            self.assertNotIn("#ffffffff", qss.lower())     # e o texto do tema também
            self.assertEqual(skin.theme.accent.lower(), "#ff6a35c9")   # o widget segue com o tema


if __name__ == "__main__":
    unittest.main()
