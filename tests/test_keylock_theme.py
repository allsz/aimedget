"""
Testes do tema do flyout de Caps/Num Lock.
  python tests/test_keylock_theme.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.widgets.keylock_osd import theme as theme_mod
from app.widgets.keylock_osd.skin import KeyLockState, paint_keylock, natural_size
from app.widgets.keylock_osd.theme import DEFAULT_THEME, load_user_theme, theme_from_dict

_app = QApplication.instance() or QApplication([])


def _pill_center_px(img: QImage, state: KeyLockState) -> QColor:
    """Pixel no centro da pílula (a largura do card depende da fonte, então não é fixa)."""
    cx = 20 + int(natural_size(state).width() / 2)
    return img.pixelColor(cx, 20 + 42)


def _render(state: KeyLockState) -> QImage:
    sz = natural_size(state)
    img = QImage(int(sz.width()) + 40, 90, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(90, 90, 120))
    p = QPainter(img)
    paint_keylock(p, QRectF(20, 20, sz.width(), sz.height()), state)
    p.end()
    return img


class ThemeParsingTests(unittest.TestCase):
    def test_empty_dict_is_default(self):
        self.assertEqual(theme_from_dict({}), DEFAULT_THEME)

    def test_valid_values_applied(self):
        t = theme_from_dict({"on_color": "#b46cff", "radius": 14})
        self.assertEqual(t.on_color, QColor("#b46cff"))
        self.assertEqual(t.radius, 14.0)
        self.assertEqual(t.card_bg, DEFAULT_THEME.card_bg)  # o resto fica no padrão

    def test_invalid_values_fall_back(self):
        t = theme_from_dict({"on_color": "roxo", "border": 123, "radius": "grande", "card_bg": "#12"})
        self.assertEqual(t, DEFAULT_THEME)

    def test_unknown_keys_ignored(self):
        self.assertEqual(theme_from_dict({"nao_existe": "#fff"}), DEFAULT_THEME)

    def test_radius_is_clamped(self):
        self.assertEqual(theme_from_dict({"radius": 999}).radius, 25.0)
        self.assertEqual(theme_from_dict({"radius": -5}).radius, 0.0)
        self.assertEqual(theme_from_dict({"radius": True}).radius, DEFAULT_THEME.radius)  # bool não é número aqui

    def test_alpha_format_supported(self):
        self.assertEqual(theme_from_dict({"card_bg": "#80102030"}).card_bg.alpha(), 0x80)


class ThemeFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = config_manager.config_dir
        config_manager.config_dir = self._tmp.name
        self._old_cfg_path = config_manager.config_path
        self._old_themes = config_manager._data.get("themes")
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")  # nunca lê/grava a config real
        config_manager._data.pop("themes", None)                                    # sem tema escolhido
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

    def _write(self, text: str, mtime_bump: int = 0):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        if mtime_bump:  # garante mtime diferente em sistemas de arquivos de baixa resolução
            st = os.stat(self.path)
            os.utime(self.path, (st.st_atime, st.st_mtime + mtime_bump))

    def test_missing_file_is_default(self):
        self.assertEqual(load_user_theme(), DEFAULT_THEME)

    def test_loads_file(self):
        self._write(json.dumps({"on_color": "#b46cff"}))
        self.assertEqual(load_user_theme().on_color, QColor("#b46cff"))

    def test_broken_json_is_default(self):
        self._write("{ isso não é json")
        self.assertEqual(load_user_theme(), DEFAULT_THEME)

    def test_json_not_an_object_is_default(self):
        self._write("[1, 2, 3]")
        self.assertEqual(load_user_theme(), DEFAULT_THEME)

    def test_reloads_when_file_changes(self):
        self._write(json.dumps({"on_color": "#ff0000"}))
        self.assertEqual(load_user_theme().on_color, QColor("#ff0000"))
        self._write(json.dumps({"on_color": "#00ff00"}), mtime_bump=5)
        self.assertEqual(load_user_theme().on_color, QColor("#00ff00"))

    def test_deleting_file_returns_to_default(self):
        self._write(json.dumps({"on_color": "#ff0000"}))
        load_user_theme()
        os.remove(self.path)
        self.assertEqual(load_user_theme(), DEFAULT_THEME)


class ThemePaintTests(unittest.TestCase):
    def test_default_theme_is_the_original_look(self):
        """Pixels de referência do visual original: a pílula ON é #4cc2ff e o fundo é #1e1e1e."""
        st = KeyLockState(label="Caps Lock", is_on=True, anim_val=1.0)
        pill = _pill_center_px(_render(st), st)
        self.assertEqual((pill.red(), pill.green(), pill.blue()), (76, 194, 255))

    def test_theme_changes_the_pill_color(self):
        purple = theme_from_dict({"on_color": "#b46cff"})
        st = KeyLockState(label="Caps Lock", is_on=True, anim_val=1.0, theme=purple)
        pill = _pill_center_px(_render(st), st)
        self.assertEqual((pill.red(), pill.green(), pill.blue()), (0xB4, 0x6C, 0xFF))

    def test_theme_changes_the_background(self):
        pink = theme_from_dict({"card_bg": "#ff69b4"})
        img = _render(KeyLockState(label="Caps Lock", is_on=False, anim_val=0.0, theme=pink))
        px = img.pixelColor(20 + 100, 20 + 5)
        self.assertEqual((px.red(), px.green(), px.blue()), (0xFF, 0x69, 0xB4))


if __name__ == "__main__":
    unittest.main()
