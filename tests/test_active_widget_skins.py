"""
Testes automatizados para a feature de skins ativas e badges numéricos:
1. Modelo de dados e persistência no JSON (settings.json).
2. Padrão de fábrica: todas as skins disponíveis vêm ativas na primeira execução.
3. Validação: mínimo de 1 skin sempre ativa (impede desmarcar todas).
4. Badges numéricos:
   - Aba Widget (Música): dinâmico conforme total de skins ativas.
   - Demais abas: ocultar badges estáticos/redundantes.
5. Atualização imediata do badge ao marcar/desmarcar no Hub.
"""

import sys
import unittest
import tempfile
import os
import json
from pathlib import Path

# Garante raiz do projeto no path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.core.config_manager import ConfigManager
from app.hub.hub_window import AimedgetHubWindow
from app.hub.service_bridge import get_service_bridge
from app.core.preview_card import PreviewCard
from app.widgets.music.skins.specs import init_music_skin_specs
from app.widgets.music.skins.base_skin import BaseMusicSkin
from app.hub.theme import THEME_DARK


class TestActiveWidgetSkins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "test_settings.json")
        self.cfg = ConfigManager(filename="test_settings.json")
        self.cfg.config_dir = self.temp_dir
        self.cfg.config_path = self.config_file
        self.cfg._data = self.cfg._default_config()

    def tearDown(self):
        try:
            if os.path.exists(self.config_file):
                os.remove(self.config_file)
            if os.path.exists(self.temp_dir):
                os.rmdir(self.temp_dir)
        except Exception:
            pass

    def test_default_factory_skins_active(self):
        """Padrão de fábrica (primeira execução): todas as skins disponíveis vêm marcadas como ativas."""
        active = self.cfg.get_active_widget_skins()
        expected = ["vinyl", "fullcover", "ripple", "capa_empilhada"]
        for skin in expected:
            self.assertIn(skin, active)
        self.assertEqual(len(active), 4)

    def test_persistence_in_json(self):
        """A lista de skins ativas persiste no arquivo de configurações."""
        self.cfg.set_skin_active("ripple", False)
        self.assertFalse(self.cfg.is_skin_active("ripple"))

        # Recarrega de um novo ConfigManager apontando para o mesmo arquivo salvo
        reloaded = ConfigManager(filename="test_settings.json")
        reloaded.config_dir = self.temp_dir
        reloaded.config_path = self.config_file
        reloaded._data = reloaded._load()

        self.assertFalse(reloaded.is_skin_active("ripple"))
        self.assertTrue(reloaded.is_skin_active("vinyl"))
        self.assertEqual(len(reloaded.get_active_widget_skins()), 3)

    def test_prevent_unchecking_all_skins(self):
        """Validar para impedir desmarcar todas (deve haver no mínimo 1 skin ativa sempre)."""
        self.cfg.set_active_widget_skins(["vinyl"])
        self.assertEqual(self.cfg.get_active_widget_skins(), ["vinyl"])

        # Tentar desmarcar a última skin ativa deve falhar e retornar False
        success = self.cfg.set_skin_active("vinyl", False)
        self.assertFalse(success)
        self.assertEqual(self.cfg.get_active_widget_skins(), ["vinyl"])

        # Tentar passar lista vazia também é rejeitado
        self.assertFalse(self.cfg.set_active_widget_skins([]))
        self.assertEqual(self.cfg.get_active_widget_skins(), ["vinyl"])

    def test_switch_current_skin_when_deactivated(self):
        """Se a skin atualmente em uso for desativada, alterna para a primeira ativa restante."""
        self.cfg.set_active_skin("fullcover")
        self.cfg.set_skin_active("fullcover", False)
        self.assertNotEqual(self.cfg.get_active_skin(), "fullcover")
        self.assertIn(self.cfg.get_active_skin(), self.cfg.get_active_widget_skins())

    def test_preview_card_toggle_control(self):
        """Testa o controle de seleção nos cards de skin e a validação do mínimo de 1 skin."""
        specs = init_music_skin_specs()
        spec = specs[0]

        # Card de escolha única (modo Flyout/Timer) -> sem toggle switch
        flyout_card = PreviewCard(spec=spec, show_active_toggle=False)
        self.assertIsNone(flyout_card.toggle_switch)

        # Card de widget com controle de menu rápido
        widget_card = PreviewCard(
            spec=spec,
            show_active_toggle=True,
            is_active_in_menu=True,
            before_toggle_callback=lambda s_id, target: target is True or False,
        )
        self.assertIsNotNone(widget_card.toggle_switch)
        self.assertTrue(widget_card.is_active_in_menu())

        widget_card.set_active_in_menu(False)
        self.assertFalse(widget_card.is_active_in_menu())

    def test_hub_sidebar_badges(self):
        """
        Valida que:
        - A aba Widget (music) exibe o total dinâmico de skins ativas.
        - As demais abas (ov, keys, vol, timer, gen) têm seus badges redundantes ocultados (count=0).
        - Ao marcar/desmarcar uma skin, o badge da aba atualiza imediatamente.
        """
        bridge = get_service_bridge()
        hub = AimedgetHubWindow()

        try:
            # Badges redundantes devem estar zerados/ocultos (count=0 e isHidden=True)
            self.assertEqual(hub.sidebar._buttons["ov"].count, 0)
            self.assertTrue(hub.sidebar._buttons["ov"].badge.isHidden())

            self.assertEqual(hub.sidebar._buttons["keys"].count, 0)
            self.assertTrue(hub.sidebar._buttons["keys"].badge.isHidden())

            self.assertEqual(hub.sidebar._buttons["vol"].count, 0)
            self.assertTrue(hub.sidebar._buttons["vol"].badge.isHidden())

            self.assertEqual(hub.sidebar._buttons["timer"].count, 0)
            self.assertTrue(hub.sidebar._buttons["timer"].badge.isHidden())

            # Aba Widget (music) exibe dinamicamente o número de skins ativas
            from app.core.config_manager import config_manager
            initial_count = len(config_manager.get_active_widget_skins())
            self.assertEqual(hub.sidebar._buttons["music"].count, initial_count)
            self.assertFalse(hub.sidebar._buttons["music"].badge.isHidden())

            # Simula desmarcar uma skin via bridge
            bridge.set_music_skin_active("ripple", False)
            expected_new_count = len(config_manager.get_active_widget_skins())
            self.assertEqual(hub.sidebar._buttons["music"].count, expected_new_count)

            # Reativa
            bridge.set_music_skin_active("ripple", True)
            self.assertEqual(hub.sidebar._buttons["music"].count, initial_count)
        finally:
            hub.close()
            hub.deleteLater()


if __name__ == "__main__":
    unittest.main()
