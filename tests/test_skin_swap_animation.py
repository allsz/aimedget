"""Testes da troca animada de skin (crossfade sem piscar e sem ativar o Hub no fundo) e do PreviewStage."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from app.core import widget_animator
from app.core.preview_registry import SkinSpec
from app.hub.components.preview_stage import PreviewStage


def _dummy_spec(spec_id: str, color: str) -> SkinSpec:
    def _paint(p: QPainter, rect, _state, _theme):
        p.fillRect(rect, QColor(color))

    return SkinSpec(
        id=spec_id,
        widget_id="music",
        title=spec_id,
        subtitle="",
        natural_size=QSize(80, 60),
        mock_state=lambda: None,
        paint=_paint,
    )


class TestSkinSwapAnimation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_swap_skin_shows_new_before_closing_old_and_crossfades(self):
        old_w = QWidget()
        new_w = QWidget()
        try:
            old_w.show()
            with mock.patch.object(widget_animator, "animations_enabled", return_value=True):
                widget_animator.swap_skin_windows(old_w, new_w, was_visible=True, duration_ms=40)
                # Nova janela já está visível enquanto a antiga faz fade-out (sem piscar nem pular foco para o Hub)
                self.assertTrue(new_w.isVisible())
                self.assertTrue(old_w.isVisible())
                anim = getattr(new_w, "_skin_swap_anim", None)
                self.assertIsNotNone(anim)
                anim.setCurrentTime(40)
                anim.finished.emit()
                self.assertAlmostEqual(new_w.windowOpacity(), 1.0, delta=0.01)
                self.assertFalse(old_w.isVisible())
        finally:
            new_w.close()
            old_w.close()

    def test_swap_skin_instant_when_animations_disabled(self):
        old_w = QWidget()
        new_w = QWidget()
        try:
            old_w.show()
            with mock.patch.object(widget_animator, "animations_enabled", return_value=False):
                widget_animator.swap_skin_windows(old_w, new_w, was_visible=True)
                self.assertTrue(new_w.isVisible())
                self.assertFalse(old_w.isVisible())
                self.assertAlmostEqual(new_w.windowOpacity(), 1.0, delta=0.01)
        finally:
            new_w.close()
            old_w.close()

    def test_preview_stage_crossfades_on_spec_change(self):
        stage = PreviewStage(spec=_dummy_spec("a", "#ff0000"))
        try:
            stage.resize(120, 90)
            stage.show()
            # Primeiro paint preenche o cache
            img = QImage(stage.size(), QImage.Format.Format_ARGB32)
            stage.render(img)
            self.assertIsNotNone(stage._cached_pixmap)

            with mock.patch.object(widget_animator, "animations_enabled", return_value=True):
                stage.set_spec(_dummy_spec("b", "#0000ff"))
                self.assertIsNotNone(stage._prev_pixmap)
                self.assertLess(stage._swap_progress, 1.0)
                stage.render(img)
                stage._on_swap_done()
                self.assertIsNone(stage._prev_pixmap)
                self.assertEqual(stage._swap_progress, 1.0)
        finally:
            stage.close()


if __name__ == "__main__":
    unittest.main()
