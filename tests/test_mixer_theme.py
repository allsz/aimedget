"""
Testes do tema do flyout de Volume / Mixer.
  python tests/test_mixer_theme.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.typography import init_app_font
from app.widgets.volume_mixer import theme as theme_mod
from app.widgets.volume_mixer.theme import DEFAULT_THEME, load_user_theme, theme_from_dict

_app = QApplication.instance() or QApplication([])
init_app_font()


def _rgb(c: QColor):
    return (c.red(), c.green(), c.blue())


class ThemeParsingTests(unittest.TestCase):
    def test_empty_dict_is_default(self):
        self.assertEqual(theme_from_dict({}), DEFAULT_THEME)

    def test_accent_also_colors_the_thumb(self):
        t = theme_from_dict({"accent": "#b46cff"})
        self.assertEqual(t.accent, QColor("#b46cff"))
        self.assertEqual(t.thumb, QColor("#b46cff"))

    def test_explicit_thumb_wins_over_accent(self):
        t = theme_from_dict({"accent": "#b46cff", "thumb": "#ffffff"})
        self.assertEqual(t.thumb, QColor("#ffffff"))

    def test_invalid_accent_keeps_default_thumb(self):
        t = theme_from_dict({"accent": "roxo"})
        self.assertEqual(t, DEFAULT_THEME)

    def test_values_and_clamping(self):
        t = theme_from_dict({"card_bg": "#3b1d4a", "muted_text": "#aaaaaa", "radius": 999})
        self.assertEqual(t.card_bg, QColor("#3b1d4a"))
        self.assertEqual(t.muted_text, QColor("#aaaaaa"))
        self.assertEqual(t.radius, 25.0)

    def test_unknown_keys_and_bad_art_do_not_break(self):
        t = theme_from_dict({"nao_existe": 1, "stickers": "oi", "background": 3, "accent": "#123456"}, "/pasta/qualquer")
        self.assertEqual(t.accent, QColor("#123456"))
        self.assertIsNone(t.background)
        self.assertEqual(t.stickers, ())


class ThemeFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = config_manager.config_dir
        config_manager.config_dir = self._tmp.name
        self._old_cfg_path = config_manager.config_path
        self._old_themes = config_manager._data.get("themes")
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")  # nunca lê/grava a config real
        config_manager._data["themes"] = {"mixer": "custom"}                          # foco: o arquivo solto
        theme_mod.reset_cache()
        self.path = theme_mod.theme_path()

    def tearDown(self):
        config_manager.config_dir = self._old_dir
        config_manager.config_path = self._old_cfg_path
        config_manager._data.pop("themes", None)
        if self._old_themes is not None:
            config_manager._data["themes"] = self._old_themes
        theme_mod.reset_cache()
        self._tmp.cleanup()

    def test_path_is_separate_from_keylock(self):
        self.assertTrue(self.path.endswith(os.path.join("themes", "mixer", "theme.json")))

    def test_missing_and_broken_files_give_default(self):
        self.assertIs(load_user_theme(), DEFAULT_THEME)
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ quebrado")
        theme_mod.reset_cache()
        self.assertIs(load_user_theme(), DEFAULT_THEME)

    def test_loads_and_caches(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"accent": "#b46cff"}, f)
        first = load_user_theme()
        self.assertEqual(first.accent, QColor("#b46cff"))
        self.assertIs(load_user_theme(), first)  # mesmo objeto enquanto nada muda


class MixerRenderTests(unittest.TestCase):
    """Usa o mixer 'headless' do Hub (já com um app Spotify na lista e a gaveta expandida)."""

    @classmethod
    def setUpClass(cls):
        from app.widgets.volume_mixer.specs import _get_headless_volume_mixer
        cls.flyout = _get_headless_volume_mixer()

    def tearDown(self):
        self.flyout._apply_theme(DEFAULT_THEME)  # não deixa o tema vazar para outros testes

    def _render(self) -> QImage:
        f = self.flyout
        img = QImage(f.width(), f.height(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(90, 90, 120))
        p = QPainter(img)
        f.render(p, QPoint(0, 0))
        p.end()
        return img

    def _master_track_px(self, img: QImage) -> QColor:
        card = self.flyout._card_rect()
        return img.pixelColor(int(card.left() + 60), int(card.top() + 24))  # parte preenchida (valor 50)

    def test_default_is_the_original_blue(self):
        self.assertEqual(_rgb(self._master_track_px(self._render())), (84, 175, 244))

    def test_accent_recolors_header_and_row_sliders(self):
        self.flyout._apply_theme(theme_from_dict({"accent": "#b46cff"}))
        img = self._render()
        self.assertEqual(_rgb(self._master_track_px(img)), (0xB4, 0x6C, 0xFF))
        self.assertEqual(self.flyout.master_slider.thumb_inner, QColor("#b46cff"))
        self.assertTrue(all(r.theme is self.flyout.theme for r in self.flyout._rows))
        self.assertEqual(self.flyout._rows[0].slider.track_active, QColor("#b46cff"))

    def test_card_background_and_radius(self):
        self.flyout._apply_theme(theme_from_dict({"card_bg": "#ff69b4", "radius": 0}))
        img = self._render()
        card = self.flyout._card_rect()
        inside = img.pixelColor(int(card.left() + 120), int(card.top() + 3))
        self.assertEqual(_rgb(inside), (0xFF, 0x69, 0xB4))
        corner = img.pixelColor(int(card.left() + 1), int(card.top() + 1))  # radius 0: o canto também é card
        self.assertNotEqual(_rgb(corner), (90, 90, 120))

    def test_theme_applies_to_rows_created_after(self):
        from app.services.audio_mixer_service import AppAudioSession
        self.flyout._apply_theme(theme_from_dict({"accent": "#00ff00"}))
        img = QImage(24, 24, QImage.Format.Format_ARGB32)
        img.fill(0)
        original = list(self.flyout._rows)
        try:
            self.flyout.on_sessions_updated(
                original and [AppAudioSession(app_id=r.app_id, name=r.name, volume=r.volume, is_muted=False, icon=img) for r in original]
                + [AppAudioSession(app_id="novo", name="Novo", volume=10, is_muted=False, icon=img)]
            )
            new_row = [r for r in self.flyout._rows if r.app_id == "novo"][0]
            self.assertEqual(new_row.slider.track_active, QColor("#00ff00"))
        finally:
            self.flyout.on_sessions_updated(
                [AppAudioSession(app_id=r.app_id, name=r.name, volume=r.volume, is_muted=False, icon=img) for r in original]
            )

    def test_same_theme_object_is_a_noop(self):
        t = theme_from_dict({"accent": "#00ff00"})
        self.flyout._apply_theme(t)
        row = self.flyout._rows[0]
        row.slider.track_active = QColor("#123456")  # marca: se reaplicasse, voltaria a #00ff00
        self.flyout._apply_theme(t)
        self.assertEqual(row.slider.track_active, QColor("#123456"))

    def test_background_and_stickers_are_painted(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            red = QImage(40, 40, QImage.Format.Format_ARGB32)
            red.fill(QColor("#ff0000"))
            red.save(os.path.join(tmp.name, "bg.png"))
            green = QImage(10, 10, QImage.Format.Format_ARGB32)
            green.fill(QColor("#00ff00"))
            green.save(os.path.join(tmp.name, "s.png"))
            t = theme_from_dict(
                {"background": {"image": "bg.png"},
                 "stickers": [{"image": "s.png", "anchor": "top-right", "x": 4, "y": -4}]},
                tmp.name,
            )
            self.flyout._apply_theme(t)
            img = self._render()
            card = self.flyout._card_rect()
            self.assertEqual(_rgb(img.pixelColor(int(card.left() + 120), int(card.top() + 3))), (255, 0, 0))
            cx, cy = int(card.right() + 4), int(card.top() - 4)
            self.assertEqual(_rgb(img.pixelColor(cx, cy)), (0, 255, 0))
        finally:
            self.flyout._apply_theme(DEFAULT_THEME)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
