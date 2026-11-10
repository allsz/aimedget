"""
Diálogo de importar tema: resumo em linguagem do usuário, aviso de substituição na própria linha do flyout,
detalhes técnicos fechados, altura que acompanha o conteúdo e título sem o sufixo " -".
  python tests/test_import_dialog_layout.py
"""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel

_app = QApplication.instance() or QApplication([])

from app.core.config_manager import config_manager
from app.core.i18n import i18n
from app.core.theme_package import analyze_package
from app.core.typography import init_app_font
from app.hub.components.theme_import_dialog import (
    CONTENT_WIDTH, ThemeImportDialog, friendly_summary, warning_color,
)
from app.hub.theme import THEME_DARK, THEME_LIGHT

init_app_font()


class _Lang(unittest.TestCase):
    """Troca o idioma sem deixar rastro na config do usuário."""

    def setUp(self):
        self._orig = config_manager.get_language("pt")
        i18n.set_language("pt")

    def tearDown(self):
        i18n.set_language(self._orig)


class SummaryTests(_Lang):
    def test_technical_names_become_plain_words(self):
        text = friendly_summary(["card_bg", "border", "radius", "scale", "auto_scale", "shadow", "background"], 0)
        self.assertEqual(text, "Cores, cantos, tamanho, sombra e fundo")

    def test_stickers_are_counted_with_the_right_plural(self):
        self.assertTrue(friendly_summary(["card_bg"], 1).endswith("1 figurinha"))
        self.assertTrue(friendly_summary(["card_bg"], 7).endswith("7 figurinhas"))
        self.assertNotIn("(s)", friendly_summary(["card_bg"], 7))

    def test_layout_tokens_and_single_item(self):
        self.assertEqual(friendly_summary(["indicator", "show_icon", "size"], 0), "Tamanho e texto e indicador")
        self.assertEqual(friendly_summary(["accent"], 0), "Cores")

    def test_empty_theme(self):
        self.assertIn("padrão", friendly_summary([], 0))

    def test_english(self):
        i18n.set_language("en")
        self.assertEqual(friendly_summary(["card_bg", "radius"], 2), "Colors, corners and 2 stickers")


class DialogTests(_Lang):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def report(self, files):
        path = os.path.join(self._tmp.name, "p.aimskin")
        with zipfile.ZipFile(path, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
        report = analyze_package(path)
        self.addCleanup(report.close)
        return report

    def dialog(self, files, theme=THEME_DARK):
        dlg = ThemeImportDialog(self.report(files), theme)
        self.addCleanup(dlg.deleteLater)
        return dlg

    def texts(self, dlg):
        return [lb.text() for lb in dlg.findChildren(QLabel)]

    def good(self, **extra):
        return json.dumps({"name": "Tema Bom", "card_bg": "#112233", "radius": 6, **extra})

    def test_title_is_just_the_name_and_width_is_fixed(self):
        dlg = self.dialog({"keylock/theme.json": self.good()})
        self.assertEqual(dlg.windowTitle(), "Importar tema")
        self.assertEqual(dlg.heading.text(), "Tema Bom")
        self.assertEqual(dlg.width(), CONTENT_WIDTH)

    def test_summary_is_plain_and_technical_names_are_only_in_the_details(self):
        dlg = self.dialog({"keylock/theme.json": self.good()})
        visible = [lb.text() for lb in dlg.findChildren(QLabel) if not dlg.details.isAncestorOf(lb)]
        self.assertIn("Cores e cantos", visible)
        self.assertFalse(any("card_bg" in text for text in visible))
        self.assertTrue(any("card_bg" in text for text in self.texts(dlg)))   # mas existem nos detalhes

    def test_details_are_closed_by_default_and_toggle_the_height(self):
        dlg = self.dialog({"keylock/theme.json": self.good(), "keylock/lixo.exe": b"MZ"})
        dlg.show()
        self.assertTrue(dlg.details.isHidden())
        closed = dlg.height()
        dlg.btn_details.click()
        self.assertFalse(dlg.details.isHidden())
        self.assertGreater(dlg.height(), closed)
        self.assertEqual(dlg.btn_details.text(), "Ocultar detalhes")
        dlg.btn_details.click()
        self.assertEqual(dlg.height(), closed)           # volta ao tamanho do conteúdo, sem espaço morto

    def test_one_flyout_makes_a_shorter_dialog_than_two(self):
        one = self.dialog({"keylock/theme.json": self.good()})
        two = self.dialog({"keylock/theme.json": self.good(), "mixer/theme.json": self.good()})
        self.assertLess(one.height(), two.height())

    def test_replace_warning_sits_in_the_row_of_the_flyout_that_has_the_theme(self):
        from app.widgets.keylock_osd import theme as kl_theme
        os.makedirs(os.path.join(kl_theme.loader.themes_dir(), "tema-bom"), exist_ok=True)
        try:
            dlg = self.dialog({"keylock/theme.json": self.good(), "mixer/theme.json": self.good()})
        finally:
            os.rmdir(os.path.join(kl_theme.loader.themes_dir(), "tema-bom"))
        warnings = [lb for lb in dlg.findChildren(QLabel) if "já existe" in lb.text().lower()]
        self.assertEqual(len(warnings), 1)                # só no Caps/Num, que já tem o tema
        self.assertIn(warning_color(THEME_DARK), warnings[0].styleSheet())
        self.assertNotIn(THEME_DARK.accent, warnings[0].styleSheet())   # destaque do app é só para ação
        self.assertEqual(dlg.btn_ok.text(), "Substituir e aplicar")

    def test_ampersand_in_a_flyout_name_is_not_a_keyboard_shortcut(self):
        i18n.set_language("en")                           # "Volume & mixer"
        dlg = self.dialog({"mixer/theme.json": self.good()})
        label = dlg.findChildren(QCheckBox)[-1]
        self.assertEqual(label.text().replace("&&", "&"), "Volume & mixer")
        self.assertIn("&&", label.text())

    def test_ignored_items_are_counted_in_the_row(self):
        dlg = self.dialog({"keylock/theme.json": self.good(card_bgg="#fff", raio=3)})
        self.assertTrue(any("2 ajustes com problema serão ignorados" in text for text in self.texts(dlg)))

    def test_light_and_dark_warning_colors_are_readable(self):
        def lum(hex_color):
            r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
            f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

        for theme in (THEME_DARK, THEME_LIGHT):
            a, b = lum(warning_color(theme)), lum(theme.panel)
            self.assertGreaterEqual((max(a, b) + 0.05) / (min(a, b) + 0.05), 4.5, theme.mode)


class WindowTitleTests(unittest.TestCase):
    def test_hub_title_stays_blank_without_the_old_display_name_hack(self):
        src = (Path(__file__).resolve().parent.parent / "app" / "hub" / "hub_window.py").read_text(encoding="utf-8")
        self.assertNotIn('setApplicationDisplayName(" ")', src)
        main = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
        self.assertNotIn('setApplicationDisplayName(" ")', main)   # o " -" dos diálogos vinha daqui


if __name__ == "__main__":
    unittest.main()
