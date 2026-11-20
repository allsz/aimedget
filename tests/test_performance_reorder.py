"""Testes do modo de reordenação direta das métricas no PerformanceCard."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from app.ui_components.menu_action_bar import draw_menu_icon
from app.widgets.performance.card_painter import DONE_RECT, pill_bounds, pill_rect
from app.widgets.performance.card_state import ALL_METRICS, PerformanceState, normalize_metric_order
from app.widgets.performance.performance_card import PerformanceCard


class TestPerformanceReorder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_normalize_and_preserve_hidden_fps_slot(self):
        self.assertEqual(normalize_metric_order(None), ALL_METRICS)
        self.assertEqual(normalize_metric_order(["ram", "cpu", "cpu", "bogus"]), ("ram", "cpu", "fps", "gpu", "vram"))

        st = PerformanceState(fps_enabled=False, metric_order=("cpu", "fps", "gpu", "vram", "ram"))
        self.assertEqual(st.visible_metrics(), ("cpu", "gpu", "vram", "ram"))
        # Move RAM (index 3) para o topo (index 0): FPS oculto mantém sua posição relativa (índice 1)
        self.assertTrue(st.move_visible_metric(3, 0))
        self.assertEqual(st.visible_metrics(), ("ram", "cpu", "gpu", "vram"))
        st.set_fps_enabled(True)
        self.assertEqual(st.visible_metrics(), ("ram", "fps", "cpu", "gpu", "vram"))

    def test_drag_pill_reorders_clamped_and_emits_signal(self):
        card = PerformanceCard(fps_enabled=True)
        emitted = []
        card.metric_order_changed.connect(emitted.append)
        try:
            card.show()
            card.set_reorder_mode(True)
            self.assertTrue(card.is_reordering())

            # Pressiona a primeira pílula (FPS) e arrasta muito abaixo do cartão (deve ficar preso no limite)
            r0 = pill_rect(0, 5)
            self.assertTrue(card._on_card_press(r0.center()))
            self.assertEqual(card.state.drag_metric, "fps")

            y0, _h, _gap, y_max = pill_bounds(5)
            self.assertTrue(card._on_card_move(QPointF(r0.center().x(), 999.0)))
            self.assertAlmostEqual(card.state.drag_y, y_max, delta=0.01)
            self.assertEqual(card.state.visible_metrics()[-1], "fps")

            # Solta: salva a ordem e continua no modo de reordenação para poder mover outra pílula
            self.assertTrue(card._on_card_release(QPointF(r0.center().x(), y_max)))
            self.assertIsNone(card.state.drag_metric)
            self.assertTrue(card.is_reordering())
            self.assertEqual(len(emitted), 1)
            self.assertEqual(emitted[0][-1], "fps")

            # Clicar no botão ✓ (Concluir) sai do modo de reordenação
            self.assertTrue(card._on_card_press(DONE_RECT.center()))
            self.assertTrue(card._on_card_release(DONE_RECT.center()))
            self.assertFalse(card.is_reordering())
        finally:
            card.close()

    def test_escape_and_outside_click_exit_reorder_mode(self):
        card = PerformanceCard(fps_enabled=False)
        other = QWidget()
        try:
            card.show()
            card.set_reorder_mode(True)
            card.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            self.assertFalse(card.is_reordering())

            card.set_reorder_mode(True)
            card.eventFilter(QApplication.instance(), QEvent(QEvent.Type.ApplicationDeactivate))
            self.assertFalse(card.is_reordering())
        finally:
            card.close()
            other.close()

    def test_reorder_menu_icon_paints_pixels(self):
        img = QImage(32, 32, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        draw_menu_icon(p, "reorder", QRectF(4, 4, 24, 24), QColor("#FFFFFF"))
        p.end()
        non_empty = sum(1 for x in range(32) for y in range(32) if img.pixelColor(x, y).alpha() > 0)
        self.assertGreater(non_empty, 40)


if __name__ == "__main__":
    unittest.main()
