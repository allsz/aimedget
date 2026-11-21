"""Testes das skins Nothing Dot para os widgets de Clima e Desempenho."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication

from app.services.performance_service import PerformanceSnapshot
from app.ui_components.dot_matrix import NOTHING_BG, draw_dot_text, draw_dot_weather_icon, measure_dot_text
from app.widgets.performance.card_painter import ND_TRIGGER_RECT, nd_dropdown_rect, paint_performance_card
from app.widgets.performance.card_state import SKIN_FLUENT, SKIN_NOTHING_DOT
from app.widgets.performance.performance_card import PerformanceCard
from app.widgets.performance.specs import init_performance_skin_specs
from app.widgets.weather import font_skins
from app.widgets.weather.card_painter import paint_card
from app.widgets.weather.specs import init_weather_skin_specs, mock_state as mock_weather_state


class TestNothingDotSkins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_dot_matrix_text_and_icons_render(self):
        w, h = measure_dot_text("24°", dot_r=3.0, gap=7.2)
        self.assertGreater(w, 40.0)
        self.assertGreater(h, 30.0)

        img = QImage(160, 80, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        draw_dot_text(p, "24°", QRectF(8, 8, 120, 60), dot_r=3.0, gap=7.2, red_degree=True)
        draw_dot_weather_icon(p, "rain", QRectF(110, 16, 40, 40))
        p.end()
        non_empty = sum(1 for x in range(160) for y in range(80) if img.pixelColor(x, y).alpha() > 0)
        self.assertGreater(non_empty, 100)

    def test_weather_nothing_dot_skin_discovered_and_renders_without_city_red_dot(self):
        ids = [s.id for s in init_weather_skin_specs()]
        self.assertIn(font_skins.DEFAULT_SKIN, ids)
        self.assertIn(font_skins.NOTHING_DOT_SKIN, ids)

        state = mock_weather_state(skin_id=font_skins.NOTHING_DOT_SKIN)
        img = QImage(300, 262, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        paint_card(p, QRectF(0, 0, 300, 262), state, 3.2)
        p.end()

        # Fundo fosco Nothing (#161616) e nenhum ponto vermelho à esquerda da cidade
        self.assertEqual(img.pixelColor(150, 70), NOTHING_BG)
        for x in range(12, 22):
            for y in range(20, 34):
                c = img.pixelColor(x, y)
                self.assertFalse(c.red() > 180 and c.green() < 60, f"ponto vermelho inesperado em ({x},{y})")

    def test_performance_nothing_dot_scroll_and_dropdown(self):
        ids = [s.id for s in init_performance_skin_specs()]
        self.assertEqual(ids, [SKIN_FLUENT, SKIN_NOTHING_DOT])

        card = PerformanceCard(fps_enabled=True, skin_id=SKIN_NOTHING_DOT)
        picked = []
        card.metric_selected.connect(lambda m: (picked.append(m), card.state.select(m, now=card.now())))
        try:
            snap = PerformanceSnapshot(cpu_pct=41.0, cpu_ghz=4.2, gpu_pct=64.0, gpu_name="RTX 4070", ram_pct=52.0)
            for _ in range(20):
                card.state.push(snap)
            card.show()

            # Scroll do mouse alterna entre categorias
            before = card.state.selected
            we = QWheelEvent(
                QPointF(150, 150),
                QPointF(150, 150),
                QPoint(0, 0),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            card.wheelEvent(we)
            self.assertNotEqual(card.state.selected, before)

            # Clicar no gatilho abre o dropdown interno; clicar em um item seleciona e fecha
            self.assertTrue(card._on_card_press(ND_TRIGGER_RECT.center()))
            self.assertTrue(card.state.dropdown_open)

            dd_r = nd_dropdown_rect(len(card.state.visible_metrics()))
            # Primeiro item do dropdown
            first_item = QPointF(dd_r.center().x(), dd_r.y() + 14.0)
            self.assertTrue(card._on_card_press(first_item))
            self.assertFalse(card.state.dropdown_open)
            self.assertEqual(card.state.selected, card.state.visible_metrics()[0])

            # Esc fecha o dropdown aberto
            card.set_dropdown_open(True)
            card.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            self.assertFalse(card.state.dropdown_open)

            # Pintura direta sem erro
            img = QImage(300, 262, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            card.state.dropdown_progress = 1.0
            paint_performance_card(p, QRectF(0, 0, 300, 262), card.state, now=card.now())
            p.end()
            self.assertEqual(img.pixelColor(280, 20), NOTHING_BG)
        finally:
            card.close()

    def test_weather_and_performance_theme_json_validation_and_crossfade(self):
        import json
        import tempfile
        from unittest import mock
        from app.core import widget_animator
        from app.core.theme_validation import CONTAINERS, validate_theme_folder

        self.assertIn("weather", CONTAINERS)
        self.assertIn("performance", CONTAINERS)

        with tempfile.TemporaryDirectory() as tmp:
            for container in ("weather", "performance"):
                folder = Path(tmp) / container / "cyber"
                folder.mkdir(parents=True)
                (folder / "theme.json").write_text(
                    json.dumps({
                        "name": "Cyber",
                        "card_bg": "#101820",
                        "accent": "#00e5ff",
                        "dot_on": "#e0f7fa",
                        "dot_off": "#223344",
                    }),
                    encoding="utf-8",
                )
                rep = validate_theme_folder(str(folder), container)
                self.assertTrue(rep.ok, f"{container} report errors/issues: {rep.errors} {rep.issues}")
                self.assertIn("card_bg", rep.applied)
                self.assertIn("accent", rep.applied)

        # Crossfade de troca de skin em FloatingCard (PerformanceCard)
        card = PerformanceCard(skin_id=SKIN_FLUENT)
        try:
            card.show()
            with mock.patch.object(widget_animator, "animations_enabled", return_value=True):
                card.begin_skin_crossfade(duration_ms=160)
                self.assertIsNotNone(card._skin_swap_prev)
                card.set_skin(SKIN_NOTHING_DOT)
                img = QImage(card.size(), QImage.Format.Format_ARGB32)
                card.render(img)
                # Avança além da duração: libera pixmap anterior
                self.assertIsNone(card._skin_swap_progress(card._skin_swap_t0 + 1.0))
                self.assertIsNone(card._skin_swap_prev)
        finally:
            card.close()

    def test_fps_detail_without_redundant_prefix_and_animates_to_zero_on_game_close(self):
        from app.services.fps_service import FpsReading
        from app.widgets.performance.card_state import FPS_CLEAR_DUR, PerformanceState

        st = PerformanceState(fps_enabled=True, selected="fps", animated=True)
        for v in (120.0, 130.0, 140.0):
            st.push_fps(FpsReading(fps=v, app_name="Volleyball"), now=10.0)
        self.assertEqual(st.detail_text("fps"), "Volleyball")

        # Jogo fechou: inicia recolhimento suave até zero
        st.push_fps(FpsReading(fps=None), now=20.0)
        self.assertTrue(st.transitions_busy(20.1))
        mid = st.samples("fps", now=20.0 + FPS_CLEAR_DUR * 0.5)
        self.assertEqual(len(mid), 3)
        self.assertTrue(all(0.0 < m < orig for m, orig in zip(mid, (120.0, 130.0, 140.0))))

        # Ao concluir a duração, o gráfico zera e para o relógio
        self.assertEqual(st.samples("fps", now=20.0 + FPS_CLEAR_DUR + 0.05), [])
        self.assertFalse(st.transitions_busy(20.0 + FPS_CLEAR_DUR + 0.05))


if __name__ == "__main__":
    unittest.main()
