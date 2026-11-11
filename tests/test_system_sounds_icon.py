"""O ícone de Sons do Sistema segue a cor do tema do mixer (escuro no tema claro)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.core.app_theme import mixer_theme_from_hub
from app.hub.theme import THEME_DARK, THEME_LIGHT
from app.services.win_app_icon_extractor import create_system_sounds_icon, is_glyph_icon
from app.widgets.volume_mixer.app_volume_row import AppVolumeRow

_app = QApplication.instance() or QApplication([])


def _opaque_colors(img: QImage) -> set[tuple[int, int, int]]:
    out = set()
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                out.add((c.red(), c.green(), c.blue()))
    return out


class SystemSoundsIconTests(unittest.TestCase):
    def _assert_close(self, colors, expected, tol=3):
        self.assertTrue(colors)
        for c in colors:   # a imagem é pré-multiplicada: pode haver 1-2 de diferença por arredondamento
            self.assertTrue(all(abs(a - b) <= tol for a, b in zip(c, expected)), (c, expected))

    def test_glyph_is_detected_but_other_icons_are_not(self):
        self.assertTrue(is_glyph_icon(create_system_sounds_icon()))
        other = QImage(16, 16, QImage.Format.Format_ARGB32)
        other.fill(0xFF336699)
        self.assertFalse(is_glyph_icon(other))
        self.assertFalse(is_glyph_icon(QImage()))

    def test_glyph_follows_theme_icon_color(self):
        row = AppVolumeRow("__system_sounds__", "Sons do Sistema", 100, False, create_system_sounds_icon())
        row.theme = mixer_theme_from_hub(THEME_LIGHT)
        light = row._icon_for_theme()
        self._assert_close(_opaque_colors(light), (0x1F, 0x1E, 0x1D))
        row.theme = mixer_theme_from_hub(THEME_DARK)
        self._assert_close(_opaque_colors(row._icon_for_theme()), (255, 255, 255))

    def test_regular_app_icon_is_untouched(self):
        other = QImage(16, 16, QImage.Format.Format_ARGB32)
        other.fill(0xFF336699)
        row = AppVolumeRow("chrome", "Chrome", 100, False, other)
        row.theme = mixer_theme_from_hub(THEME_LIGHT)
        self.assertIs(row._icon_for_theme(), row._scaled_icon)


if __name__ == "__main__":
    unittest.main()
