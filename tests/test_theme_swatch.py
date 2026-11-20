"""Testes do seletor circular de aparência (ThemeSwatchGroup) e da limpeza da GeneralPage."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.core.i18n import i18n
from app.hub.components.theme_swatch import ThemeSwatchButton, ThemeSwatchGroup
from app.hub.pages import GeneralPage
from app.hub.theme import THEME_DARK, THEME_LIGHT, THEME_TRUE_DARK


def _render(widget) -> QImage:
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    widget.render(img)
    return img


class TestThemeSwatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_solid_and_diagonal_system_colors(self):
        """Cada círculo usa a cor real do modo; Sistema divide 50/50 na diagonal (Claro topo-esq / Escuro base-dir)."""
        light_btn = ThemeSwatchButton("light", "Light", THEME_LIGHT)
        dark_btn = ThemeSwatchButton("dark", "Dark", THEME_DARK)
        oled_btn = ThemeSwatchButton("true_dark", "OLED", THEME_TRUE_DARK)
        sys_btn = ThemeSwatchButton("system", "System", THEME_DARK)

        cx = ThemeSwatchButton.HIT_SIZE // 2
        cy = ThemeSwatchButton.HIT_SIZE // 2

        self.assertEqual(_render(light_btn).pixelColor(cx, cy), QColor(THEME_LIGHT.bg))
        self.assertEqual(_render(dark_btn).pixelColor(cx, cy), QColor(THEME_DARK.bg))
        self.assertEqual(_render(oled_btn).pixelColor(cx, cy), QColor(THEME_TRUE_DARK.bg))

        sys_img = _render(sys_btn)
        # Quadrante superior-esquerdo dentro do círculo -> Light; inferior-direito -> Dark
        self.assertEqual(sys_img.pixelColor(cx - 4, cy - 4), QColor(THEME_LIGHT.bg))
        self.assertEqual(sys_img.pixelColor(cx + 4, cy + 4), QColor(THEME_DARK.bg))

    def test_group_selection_and_callback(self):
        picked = []
        group = ThemeSwatchGroup(
            [("light", "Light"), ("dark", "Dark"), ("true_dark", "OLED"), ("system", "System")],
            on_pick=picked.append,
            theme=THEME_DARK,
            selected="dark",
        )
        self.assertEqual(group.button("dark").property("selected"), "true")
        self.assertEqual(group.button("system").property("selected"), "false")

        group.button("true_dark").click()
        self.assertEqual(picked, ["true_dark"])

        group.set_selected("true_dark", animated=False)
        self.assertEqual(group.button("true_dark").property("selected"), "true")
        self.assertEqual(group.button("dark").property("selected"), "false")

    def test_general_page_swatches_and_compact_copy(self):
        orig = i18n.current_language
        try:
            i18n.set_language("en")
            page = GeneralPage(current_pref="system", current_lang="en", theme=THEME_DARK)
            self.assertIsInstance(page._theme_group, ThemeSwatchGroup)
            self.assertFalse(page.lbl_sub.isVisible())
            self.assertFalse(hasattr(page, "d3"))
            self.assertFalse(hasattr(page, "d4"))
            self.assertEqual(page._theme_chips["light"].toolTip(), "Light")
            self.assertEqual(page._theme_chips["true_dark"].toolTip(), "OLED")
            self.assertEqual(page._theme_chips["system"].accessibleName(), "System")

            i18n.set_language("pt")
            page.retranslate_ui()
            self.assertEqual(page._theme_chips["light"].toolTip(), "Claro")
            self.assertEqual(page._theme_chips["system"].toolTip(), "Sistema")
            self.assertEqual(page._theme_chips["dark"].accessibleName(), "Escuro")
        finally:
            i18n.set_language(orig)


if __name__ == "__main__":
    unittest.main()
