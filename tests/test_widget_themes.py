"""Temas de widget: Capa Empilhada (themes/music) e Timer Aimedget (themes/timer)."""

import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.hub.theme import THEME_DARK, THEME_LIGHT
from app.widgets.music.skins import stack_theme
from app.widgets.music.skins.stack_palette import get_default_pastel_theme
from app.widgets.timer import theme as timer_theme
from app.widgets.timer.skins.skin import TimerState, paint_windows_timer

_app = QApplication.instance() or QApplication(sys.argv)


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = (config_manager.config_dir, config_manager.config_path, config_manager._data.get("themes"))
        config_manager.config_dir = self._tmp.name
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")
        config_manager._data.pop("themes", None)
        for loader in (stack_theme.loader, timer_theme.loader):
            loader.reset()

    def tearDown(self):
        config_manager.config_dir, config_manager.config_path = self._old[0], self._old[1]
        config_manager._data.pop("themes", None)
        if self._old[2] is not None:
            config_manager._data["themes"] = self._old[2]
        for loader in (stack_theme.loader, timer_theme.loader):
            loader.reset()
        self._tmp.cleanup()

    def install(self, loader, theme_id, data, image_color=None):
        folder = os.path.join(loader.themes_dir(), theme_id)
        os.makedirs(folder, exist_ok=True)
        if image_color is not None:
            img = QImage(32, 32, QImage.Format.Format_ARGB32)
            img.fill(QColor(image_color))
            img.save(os.path.join(folder, "fundo.png"))
        with open(os.path.join(folder, "theme.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        loader.set_active(theme_id)


class StackThemeParsingTests(unittest.TestCase):
    def test_empty_theme_is_the_original_adaptive_look(self):
        th = stack_theme.theme_from_dict({})
        self.assertTrue(th.adaptive)
        self.assertIsNone(th.progress_fill)
        self.assertIsNone(th.progress_track)

    def test_any_palette_color_makes_it_fixed_and_fills_the_rest_from_the_original(self):
        th = stack_theme.theme_from_dict({"accent": "#9b5de5", "card_bg": "#f3ecff"})
        self.assertFalse(th.adaptive)
        self.assertEqual(th.palette.accent_main, QColor("#9b5de5"))
        self.assertEqual(th.palette.card_bg, QColor("#f3ecff"))
        self.assertEqual(th.palette.title_color, get_default_pastel_theme().title_color)

    def test_adaptive_true_keeps_the_cover_palette(self):
        th = stack_theme.theme_from_dict({"accent": "#9b5de5", "adaptive": True, "progress_fill": "#ff0000"})
        self.assertTrue(th.adaptive)
        self.assertEqual(th.progress_fill, QColor("#ff0000"))

    def test_invalid_values_fall_back(self):
        th = stack_theme.theme_from_dict({"accent": "roxo", "adaptive": "sim"})
        self.assertTrue(th.adaptive)


class TimerThemeParsingTests(unittest.TestCase):
    def test_empty_theme_keeps_the_app_colors(self):
        self.assertIs(timer_theme.theme_from_dict({}).apply_to(THEME_DARK), THEME_DARK)

    def test_only_given_colors_are_replaced(self):
        th = timer_theme.theme_from_dict({"card_bg": "#f3ecff", "accent": "#9b5de5"})
        out = th.apply_to(THEME_DARK)
        self.assertEqual(QColor(out.panel), QColor("#f3ecff"))
        self.assertEqual(QColor(out.accent), QColor("#9b5de5"))
        self.assertEqual(QColor(out.accent_hover).name(), QColor("#9b5de5").darker(110).name())   # hover derivado
        self.assertEqual(out.text, THEME_DARK.text)                                  # o resto segue o app
        self.assertEqual(out.is_dark, THEME_DARK.is_dark)

    def test_partial_theme_follows_light_and_dark(self):
        th = timer_theme.theme_from_dict({"accent": "#9b5de5"})
        self.assertEqual(th.apply_to(THEME_LIGHT).panel, THEME_LIGHT.panel)
        self.assertEqual(th.apply_to(THEME_DARK).panel, THEME_DARK.panel)


class TimerPaintTests(_Isolated):
    def render(self, theme, art):
        img = QImage(164, 164, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        paint_windows_timer(p, QRectF(0, 0, 164, 164), TimerState(), theme, art=art)
        p.end()
        return img

    def test_background_image_is_painted_inside_the_card(self):
        self.install(timer_theme.loader, "lav", {"background": {"image": "fundo.png"}}, image_color="#00ff00")
        art = timer_theme.load_user_theme()
        img = self.render(THEME_DARK, art)
        self.assertEqual(img.pixelColor(30, 140).name(), "#00ff00")          # canto de baixo do cartão
        self.assertEqual(img.pixelColor(2, 2).alpha(), 0)                     # fora do cartão: transparente

    def test_without_art_the_card_is_the_app_panel(self):
        img = self.render(THEME_DARK, None)
        self.assertEqual(img.pixelColor(30, 140).name(), QColor(THEME_DARK.panel).name())

    def test_live_skin_uses_theme_colors_on_top_of_the_app(self):
        self.install(timer_theme.loader, "lav", {"card_bg": "#f3ecff"})
        from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
        skin = WindowsTimerSkin()
        try:
            self.assertEqual(QColor(skin.theme.panel), QColor("#f3ecff"))
            skin.update_theme(THEME_LIGHT)                       # o app mudou de modo: o tema continua por cima
            self.assertEqual(QColor(skin.theme.panel), QColor("#f3ecff"))
            self.assertEqual(skin.theme.text, THEME_LIGHT.text)
            timer_theme.loader.set_active("default")
            skin.reload_skin_theme()
            self.assertEqual(skin.theme.panel, THEME_LIGHT.panel)
        finally:
            skin.close()


class StackSkinTests(_Isolated):
    def make_skin(self):
        from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
        skin = CapaEmpilhadaSkin(scale=0.5)
        skin.timer.stop()
        self.addCleanup(skin.close)
        return skin

    def test_fixed_palette_ignores_the_album_cover(self):
        self.install(stack_theme.loader, "lav", {"card_bg": "#f3ecff", "accent": "#9b5de5"})
        skin = self.make_skin()
        cover = QImage(64, 64, QImage.Format.Format_ARGB32)
        cover.fill(QColor("#00aa00"))   # capa verde: a paleta adaptativa ficaria verde
        self.assertEqual(skin._palette_for(cover).accent_main, QColor("#9b5de5"))
        self.assertEqual(skin.target_pastel_theme.card_bg, QColor("#f3ecff"))

    def test_without_theme_the_palette_still_comes_from_the_cover(self):
        skin = self.make_skin()
        cover = QImage(64, 64, QImage.Format.Format_ARGB32)
        cover.fill(QColor("#00aa00"))
        self.assertNotEqual(skin._palette_for(cover).accent_main, get_default_pastel_theme().accent_main)

    def test_background_is_painted_on_the_card(self):
        self.install(stack_theme.loader, "lav", {"background": {"image": "fundo.png"}, "adaptive": True},
                     image_color="#0000ff")
        skin = self.make_skin()
        img = QImage(skin.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        skin.render(img, QPoint(0, 0))
        self.assertEqual(img.pixelColor(skin.width() - 60, 30).name(), "#0000ff")   # área livre do cartão

    def test_reload_switches_theme_without_recreating_the_skin(self):
        skin = self.make_skin()
        self.assertTrue(skin.skin_theme.adaptive)
        self.install(stack_theme.loader, "lav", {"accent": "#9b5de5"})
        skin.reload_skin_theme()
        self.assertEqual(skin.target_pastel_theme.accent_main, QColor("#9b5de5"))

    def test_behind_stickers_become_below(self):
        folder = os.path.join(self._tmp.name, "art")
        os.makedirs(folder)
        img = QImage(8, 8, QImage.Format.Format_ARGB32)
        img.fill(QColor("#ff00ff"))
        img.save(os.path.join(folder, "s.png"))
        th = stack_theme.theme_from_dict({"stickers": [{"image": "s.png", "layer": "behind", "width": 10}]}, folder)
        self.assertEqual([s.layer for s in th.stickers], ["below"])


if __name__ == "__main__":
    unittest.main()
