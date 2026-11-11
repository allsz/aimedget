"""O título da skin do Timer (e o rótulo do cartão na Visão geral) acompanham o idioma depois de trocá-lo no Hub."""

import sys
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from app.core.i18n import i18n
from app.hub.pages import OverviewPage, TimerPage


class TimerSkinTitleLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_title_follows_a_language_switch_in_both_directions(self):
        with mock.patch.object(i18n, "_current_lang", "en"):
            page = TimerPage()
            card = page._skin_cards["windows"]
            card._spec.title = "Default"             # a spec é criada uma vez, no idioma em que o app abriu
            i18n._current_lang = "pt"
            page.retranslate_ui()
            self.assertEqual(card._spec.title, "Padrão")      # antes ficava "Default"
            self.assertEqual(card._spec.subtitle, "PIP clássico")
            i18n._current_lang = "en"
            page.retranslate_ui()
            self.assertEqual(card._spec.title, "Default")

    def test_overview_card_label_follows_the_language(self):
        with mock.patch.object(i18n, "_current_lang", "en"):
            page = OverviewPage()
            i18n._current_lang = "pt"
            page.retranslate_ui()
            self.assertIn("Padrão", page.timer_card.lbl_subtitle.text())


if __name__ == "__main__":
    unittest.main()
