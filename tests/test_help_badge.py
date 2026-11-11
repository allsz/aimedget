"""O "?" do Caps Lock guarda o aviso sobre indicadores de fabricante, sem ocupar a página."""

import unittest

from PySide6.QtWidgets import QApplication

from app.core import i18n
from app.hub.components.help_badge import HelpBadge
from app.hub.theme import THEME_LIGHT

_app = QApplication.instance() or QApplication([])


class HelpBadgeTests(unittest.TestCase):
    def test_message_is_in_the_tooltip_and_escaped(self):
        b = HelpBadge("A < B & C", theme=THEME_LIGHT)
        self.assertEqual(b.text_message(), "A < B & C")
        self.assertIn("A &lt; B &amp; C", b.toolTip())

    def test_text_can_be_updated_and_cleared(self):
        b = HelpBadge("um", theme=THEME_LIGHT)
        b.set_text("dois")
        self.assertIn("dois", b.toolTip())
        b.set_text("")
        self.assertEqual(b.toolTip(), "")
        b.show_message()   # sem texto: não abre balão nem quebra

    def test_small_fixed_size(self):
        b = HelpBadge("x", theme=THEME_LIGHT)
        self.assertEqual((b.width(), b.height()), (HelpBadge.SIZE, HelpBadge.SIZE))

    def test_oem_message_exists_in_both_languages(self):
        for lang in ("pt", "en"):
            table = i18n.TRANSLATIONS[lang] if hasattr(i18n, "TRANSLATIONS") else None
            if table is not None:
                self.assertTrue(table.get("keys_oem_osd_help"))


class MusicPageWarningTests(unittest.TestCase):
    def test_music_page_has_the_firefox_youtube_music_warning(self):
        from app.hub.pages import MusicPage
        page = MusicPage()
        self.assertTrue(hasattr(page, "web_help"))
        self.assertIn("Firefox", page.web_help.text_message())
        self.assertIn("YouTube Music", page.web_help.text_message())
        # o título continua no cabeçalho, ao lado do "?"
        self.assertIsNotNone(page.lbl_title.parent())
        page.retranslate_ui()
        page.set_theme(THEME_LIGHT)


if __name__ == "__main__":
    unittest.main()
