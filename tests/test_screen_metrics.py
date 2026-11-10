"""
Testes automatizados para detecção de resolução, densidade de tela e escala dos widgets.
Pode ser executado com:
  python tests/test_screen_metrics.py
ou:
  pytest tests/test_screen_metrics.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Garante raiz do projeto no path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.screen_metrics import (
    BASELINE_MUSIC_SCALE,
    BASELINE_TIMER_SIZE,
    format_scale_percent,
    get_auto_music_scale,
    get_auto_timer_size,
    get_screen_scale_ratio,
)
from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
from app.widgets.music.skins.fullcover_skin import FullCoverSkin
from app.widgets.music.skins.ripple_skin import RippleSkin
from app.widgets.music.skins.vinyl_skin import VinylMusicSkin


def make_mock_screen(width: int, height: int):
    screen = MagicMock()
    screen.geometry.return_value = QRect(0, 0, width, height)
    return screen


class TestScreenMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_resolution_scale_ratios(self):
        """Valida se as resoluções comuns do Windows mapeiam para os fatores de escala esperados."""
        cases = [
            (1280, 720, 0.50),    # 720p HD
            (1366, 768, 0.55),    # Notebooks populares
            (1920, 1080, 0.75),   # 1080p Full HD
            (2560, 1440, 1.00),   # 1440p QHD (Baseline canônico do usuário)
            (3440, 1440, 1.00),   # Ultrawide 1440p
            (1080, 1920, 0.75),   # Monitor secundário em modo retrato (portrait)
            (3840, 2160, 1.50),   # 4K UHD
        ]
        for w, h, expected_ratio in cases:
            mock_s = make_mock_screen(w, h)
            ratio = get_screen_scale_ratio(mock_s)
            self.assertAlmostEqual(ratio, expected_ratio, places=2, msg=f"Falha na resolução {w}x{h}")

    def test_music_widget_proportional_scales(self):
        """Valida dimensões resultantes do Music Widget para evitar jumpscares."""
        cases = [
            (1280, 720, 0.25, 240, 135),    # 720p: não invade a tela
            (1920, 1080, 0.375, 360, 202),  # 1080p: proporção idêntica à 1440p
            (2560, 1440, 0.50, 480, 270),   # 1440p: 100% idêntico ao atual
            (3840, 2160, 0.75, 720, 405),   # 4K: nítido e legível
        ]
        for w, h, exp_scale, exp_w, exp_h in cases:
            mock_s = make_mock_screen(w, h)
            scale = get_auto_music_scale(mock_s)
            self.assertAlmostEqual(scale, exp_scale, places=3)
            calc_w = int(round(960 * scale))
            calc_h = int(round(540 * scale))
            self.assertEqual(calc_w, exp_w)
            self.assertEqual(calc_h, exp_h)

    def test_timer_widget_proportional_sizes(self):
        """Valida que o Timer Widget mantém proporção e respeita o tamanho mínimo de legibilidade."""
        cases = [
            (1280, 720, 120, 120),   # 720p: clamp mínimo de 120px
            (1920, 1080, 123, 123),  # 1080p: ~123px
            (2560, 1440, 164, 164),  # 1440p: 164px canônico atual
            (3840, 2160, 246, 246),  # 4K: 246px
        ]
        for w, h, exp_w, exp_h in cases:
            mock_s = make_mock_screen(w, h)
            tw, th = get_auto_timer_size(mock_s)
            self.assertEqual((tw, th), (exp_w, exp_h))

    def test_format_scale_percent(self):
        self.assertEqual(format_scale_percent(0.50), "100%")
        self.assertEqual(format_scale_percent(0.375), "75%")
        self.assertEqual(format_scale_percent(0.625), "125%")
        self.assertEqual(format_scale_percent(0.75), "150%")

    def test_config_manager_scale_persistence(self):
        orig = config_manager.get_music_scale()
        try:
            # Modo automático
            config_manager.set_music_scale(None)
            self.assertTrue(config_manager.is_music_scale_auto())
            self.assertIsNone(config_manager.get_music_scale())

            # Modo manual customizado
            config_manager.set_music_scale(0.625)
            self.assertFalse(config_manager.is_music_scale_auto())
            self.assertEqual(config_manager.get_music_scale(), 0.625)
            self.assertEqual(config_manager.get_effective_music_scale(), 0.625)

            # Restaura automático
            config_manager.set_music_scale(None)
            self.assertTrue(config_manager.is_music_scale_auto())
        finally:
            config_manager.set_music_scale(orig)

    def test_all_skins_live_rescaling(self):
        """Testa se todas as 4 skins de música aceitam redimensionamento dinâmico sem erros."""
        skin_classes = [VinylMusicSkin, FullCoverSkin, RippleSkin, CapaEmpilhadaSkin]
        for cls in skin_classes:
            skin = cls(scale=0.50)
            if hasattr(skin, "timer"):
                skin.timer.stop()

            # Escala inicial 0.50
            init_w, init_h = skin.width(), skin.height()
            self.assertGreater(init_w, 200)
            self.assertGreater(init_h, 100)

            # Reduz para 0.375 (75%)
            skin.set_scale(0.375, save_preference=False)
            self.assertAlmostEqual(skin.scale, 0.375, places=3)
            self.assertEqual(skin.width(), int(round(skin.canvas_w * 0.375)))
            self.assertEqual(skin.height(), int(round(skin.canvas_h * 0.375)))

            # Amplia para 0.75 (150%)
            skin.set_scale(0.75, save_preference=False)
            self.assertAlmostEqual(skin.scale, 0.75, places=3)
            self.assertEqual(skin.width(), int(round(skin.canvas_w * 0.75)))
            self.assertEqual(skin.height(), int(round(skin.canvas_h * 0.75)))

            # Clamping do range seguro (0.35 a 0.80)
            skin.set_scale(0.10, save_preference=False)
            self.assertAlmostEqual(skin.scale, 0.35, places=3)
            skin.set_scale(2.50, save_preference=False)
            self.assertAlmostEqual(skin.scale, 0.80, places=3)

            # Verificação da alça de redimensionamento no canto inferior direito
            self.assertTrue(skin.is_in_resize_grip(QPointF(skin.width() - 5, skin.height() - 5)))
            self.assertFalse(skin.is_in_resize_grip(QPointF(10, 10)))

            skin.close()
            skin.deleteLater()

    def test_resize_grip_contrast_and_corner_containment(self):
        """
        Valida que:
        1. Em fundos claros (Capa Empilhada), a alça usa tom escuro para alto contraste.
        2. Em fundos escuros (Vinil), a alça usa tom claro.
        3. A posição da alça fica estritamente contida dentro da curvatura do card (sem vazar).
        """
        import math

        # Capa Empilhada (fundo pastel claro)
        stacked = CapaEmpilhadaSkin(scale=0.50)
        col_stacked = stacked.get_resize_grip_color()
        # Deve ser escuro (R, G, B baixos) para contraste com o card claro
        self.assertLess(col_stacked.red(), 60)
        self.assertLess(col_stacked.green(), 60)
        self.assertLess(col_stacked.blue(), 60)

        # O ponto do grip precisa estar estritamente dentro da curva circular do card
        margin = stacked.get_resize_grip_margin()
        r_screen = stacked.CARD_RADIUS * stacked.scale
        dx = r_screen - margin
        dy = r_screen - margin
        dist_from_arc_center = math.hypot(dx, dy)
        self.assertLess(dist_from_arc_center, r_screen, "Ponto da alça está fora do arco da borda do card!")

        stacked.close()
        stacked.deleteLater()

        # Vinil (fundo escuro)
        vinyl = VinylMusicSkin(scale=0.50)
        col_vinyl = vinyl.get_resize_grip_color()
        self.assertEqual(col_vinyl, QColor(255, 255, 255))

        margin_v = vinyl.get_resize_grip_margin()
        r_v = vinyl.CARD_RADIUS * vinyl.scale
        dx_v = r_v - margin_v
        dy_v = r_v - margin_v
        dist_v = math.hypot(dx_v, dy_v)
        self.assertLess(dist_v, r_v, "Ponto da alça de vinil está fora do arco da borda!")

        vinyl.close()
        vinyl.deleteLater()

    def test_music_page_scale_chips_selection_states(self):
        """Valida que nenhum chip fica selecionado quando o usuário escolhe um tamanho customizado."""
        from app.hub.pages import MusicPage
        from app.hub.theme import THEME_LIGHT

        page = MusicPage(theme=THEME_LIGHT)

        # 1. Modo Automático -> chip 'auto' selecionado
        page.update_scale_selection(None)
        self.assertEqual(page._scale_chips["auto"].property("selected"), "true")
        self.assertEqual(page._scale_chips["0.50"].property("selected"), "false")

        # 2. Preset 100% (0.50) -> chip '0.50' selecionado
        page.update_scale_selection(0.50)
        self.assertEqual(page._scale_chips["auto"].property("selected"), "false")
        self.assertEqual(page._scale_chips["0.50"].property("selected"), "true")
        self.assertEqual(page._scale_chips["0.75"].property("selected"), "false")

        # 3. Tamanho custom do usuário (ex: 0.44 ou 0.58) -> NENHUM chip selecionado!
        page.update_scale_selection(0.44)
        for k, btn in page._scale_chips.items():
            self.assertEqual(btn.property("selected"), "false", f"Chip {k} não deveria estar selecionado para escala custom 0.44")

        page.update_scale_selection(0.582)
        for k, btn in page._scale_chips.items():
            self.assertEqual(btn.property("selected"), "false", f"Chip {k} não deveria estar selecionado para escala custom 0.582")

        page.deleteLater()

    def test_timer_widget_safe_bounds(self):
        """Valida que o Timer Widget respeita o range seguro de aumento proporcional."""
        from app.widgets.timer.skins.base_skin import BaseTimerSkin
        self.assertEqual(BaseTimerSkin.DEFAULT_SIZE, 164)
        self.assertLessEqual(BaseTimerSkin.MIN_WIDTH, 130)
        self.assertLessEqual(BaseTimerSkin.MAX_WIDTH, 260)
        self.assertGreaterEqual(BaseTimerSkin.MAX_WIDTH, 240)


if __name__ == "__main__":
    unittest.main()
