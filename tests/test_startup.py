"""
Testes automatizados para inicialização com Windows e modo minimizado.
Pode ser executado com:
  python tests/test_startup.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.typography import init_app_font
from app.hub.pages import GeneralPage
from app.hub.theme import THEME_DARK


class TestStartupConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        init_app_font()

    def test_start_minimized_config(self):
        orig_min = config_manager.is_start_minimized_enabled()
        try:
            config_manager.set_start_minimized_enabled(True)
            self.assertTrue(config_manager.is_start_minimized_enabled())

            config_manager.set_start_minimized_enabled(False)
            self.assertFalse(config_manager.is_start_minimized_enabled())
        finally:
            config_manager.set_start_minimized_enabled(orig_min)

    def test_sync_windows_startup_safety(self):
        """Garante que a rotina de sincronização do registro do Windows executa com segurança."""
        orig_win = config_manager.is_start_with_windows_enabled()
        orig_min = config_manager.is_start_minimized_enabled()
        try:
            # Não altera o registro real para True nos testes, mas valida que sync funciona sem crash
            config_manager.set_start_with_windows_enabled(False)
            config_manager.sync_windows_startup()
        finally:
            config_manager.set_start_with_windows_enabled(orig_win)
            config_manager.set_start_minimized_enabled(orig_min)

    def test_general_page_ui(self):
        """Valida que a interface da página Geral renderiza o controle com estados corretos."""
        page = GeneralPage(theme=THEME_DARK)
        self.assertTrue(hasattr(page, "s_min"))
        self.assertTrue(hasattr(page, "t_min"))
        self.assertTrue(hasattr(page, "d_min"))

        # Testa alternância via switch da UI
        initial_val = page.s_min.is_checked()
        page.s_min.toggle()
        new_val = page.s_min.is_checked()
        self.assertEqual(new_val, not initial_val)
        self.assertEqual(config_manager.is_start_minimized_enabled(), new_val)

        # Restaura
        page.s_min.toggle()
        self.assertEqual(page.s_min.is_checked(), initial_val)
        page.close()
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
