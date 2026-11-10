"""
Testes automatizados de internacionalização (i18n) para a suíte Aimedget.
Verifica traduções completas, integridade de termos técnicos preservados (Widgets, Caps Lock, etc.),
persistência de idioma no ConfigManager e atualização dinâmica do Hub e páginas.
"""

import sys
import unittest
from pathlib import Path

# Garante raiz do projeto no path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.i18n import i18n, t, TRANSLATIONS
from app.hub.hub_window import AimedgetHubWindow
from app.hub.pages import GeneralPage, OverviewPage, MusicPage, LockKeysPage, VolumePage, TimerPage


class TestI18n(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        # Salva o idioma original para restaurar ao final
        self._orig_lang = config_manager.get_language("pt")

    def tearDown(self):
        # Restaura idioma original
        i18n.set_language(self._orig_lang)

    def test_translations_keys_consistency(self):
        """Verifica se todas as chaves de tradução existem em ambos os idiomas (pt e en)."""
        pt_keys = set(TRANSLATIONS["pt"].keys())
        en_keys = set(TRANSLATIONS["en"].keys())

        missing_in_en = pt_keys - en_keys
        missing_in_pt = en_keys - pt_keys

        self.assertEqual(missing_in_en, set(), f"Chaves faltando em 'en': {missing_in_en}")
        self.assertEqual(missing_in_pt, set(), f"Chaves faltando em 'pt': {missing_in_pt}")

    def test_technical_terms_preserved(self):
        """Verifica que termos técnicos e de marca (Widgets, Caps Lock, etc.) são preservados."""
        for lang in ("pt", "en"):
            i18n.set_language(lang)
            # Termos que não devem ser traduzidos
            self.assertEqual(t("keys_opt_caps_title"), "Caps Lock")
            self.assertEqual(t("keys_opt_num_title"), "Num Lock")
            self.assertEqual(t("overview_card_keys"), "Caps / Num Lock")
            self.assertEqual(t("overview_filter_widget"), "Widget")
            self.assertEqual(t("overview_filter_flyout"), "Flyout")
            self.assertEqual(t("tray_music_widget"), "Music Widget")
            self.assertEqual(t("tray_keys_flyout"), "Caps Lock Flyout")
            self.assertEqual(t("tray_vol_mixer"), "Volume Mixer")

    def test_switching_language_and_persistence(self):
        """Verifica se alternar idioma altera a tradução e persiste no ConfigManager."""
        i18n.set_language("en")
        self.assertEqual(i18n.current_language, "en")
        self.assertEqual(config_manager.get_language(), "en")
        self.assertEqual(t("sidebar_general"), "General")
        self.assertEqual(t("gen_theme_light"), "Light")
        self.assertEqual(t("card_configure"), "Configure")

        i18n.set_language("pt")
        self.assertEqual(i18n.current_language, "pt")
        self.assertEqual(config_manager.get_language(), "pt")
        self.assertEqual(t("sidebar_general"), "Geral")
        self.assertEqual(t("gen_theme_light"), "Claro")
        self.assertEqual(t("card_configure"), "Configurar")

    def test_general_page_language_selector(self):
        """Testa o seletor de idioma na página GeneralPage."""
        changed_calls = []
        page = GeneralPage(
            on_language_change=lambda lang: changed_calls.append(lang),
            current_lang="pt",
        )

        self.assertIn("pt", page._lang_chips)
        self.assertIn("en", page._lang_chips)
        self.assertEqual(page._lang_chips["pt"].property("selected"), "true")
        self.assertEqual(page._lang_chips["en"].property("selected"), "false")

        # Simula clique no chip 'en'
        page._set_language("en")
        self.assertEqual(page._current_lang, "en")
        self.assertEqual(page._lang_chips["en"].property("selected"), "true")
        self.assertEqual(page._lang_chips["pt"].property("selected"), "false")
        self.assertEqual(i18n.current_language, "en")
        self.assertEqual(changed_calls, ["en"])

        # Retranslate da página GeneralPage
        page.retranslate_ui()
        self.assertEqual(page.t4.text(), "Language")
        self.assertEqual(page.t1.text(), "Start with Windows")

    def test_hub_window_retranslation(self):
        """Testa a re-tradução completa de todas as páginas da HubWindow."""
        hub = AimedgetHubWindow()
        try:
            # Alterna para Português
            hub._change_language("pt")
            self.assertEqual(hub.sidebar._buttons["gen"].lbl_title.text(), "Geral")
            self.assertEqual(hub.page_overview.lbl_title.text(), "Personalização")
            self.assertEqual(hub.page_music.lbl_title.text(), "Music Player")
            self.assertEqual(hub.page_keys.lbl_title.text(), "Lock keys")
            self.assertEqual(hub.page_vol.lbl_title.text(), "Volume & mixer")
            self.assertEqual(hub.page_timer.lbl_title.text(), "Timer & Foco")
            self.assertEqual(hub.page_gen.lbl_title.text(), "Geral")

            # Alterna para Inglês
            hub._change_language("en")
            self.assertEqual(hub.sidebar._buttons["gen"].lbl_title.text(), "General")
            self.assertEqual(hub.page_overview.lbl_title.text(), "Customization")
            self.assertEqual(hub.page_music.lbl_title.text(), "Music Player")
            self.assertEqual(hub.page_keys.lbl_title.text(), "Lock keys")
            self.assertEqual(hub.page_vol.lbl_title.text(), "Volume & mixer")
            self.assertEqual(hub.page_timer.lbl_title.text(), "Timer & Focus")
            self.assertEqual(hub.page_gen.lbl_title.text(), "General")
        finally:
            hub.close()


if __name__ == "__main__":
    unittest.main()
