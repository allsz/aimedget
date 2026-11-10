"""
Testes automatizados de renderização e snapshot para widgets e skins da suíte Aimedget.
Pode ser executado com:
  python tests/test_previews.py
ou com:
  pytest tests/test_previews.py
"""

import os
import sys
import unittest
from pathlib import Path

# Garante raiz do projeto no path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.preview_card import PreviewCard
from app.core.preview_registry import (
    SKIN_REGISTRY,
    WIDGET_REGISTRY,
    get_skins_for_widget,
    get_widget_spec,
)
from app.core.typography import init_app_font
from app.hub.components.preview_stage import PreviewStage
from app.hub.theme import THEME_DARK, THEME_LIGHT
from app.widgets.keylock_osd import KEYLOCK_SPEC
from app.widgets.music.skins import init_music_skin_specs
from app.widgets.timer import init_timer_spec
from app.widgets.volume_mixer import init_volume_spec

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


class TestWidgetPreviews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        init_app_font()

    def _render_spec_to_image(self, spec, theme=THEME_DARK, dpr=1.0) -> QImage:
        state = spec.mock_state()
        nat = spec.natural_size(state) if callable(spec.natural_size) else spec.natural_size
        w = max(1, int(round(nat.width() * dpr)))
        h = max(1, int(round(nat.height() * dpr)))

        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        spec.paint(p, QRectF(0.0, 0.0, float(nat.width()), float(nat.height())), state, theme)
        p.end()

        return img

    def test_keylock_spec(self):
        spec = get_widget_spec("keylock_osd")
        self.assertIsNotNone(spec)
        img = self._render_spec_to_image(spec)
        self.assertFalse(img.isNull())
        self.assertGreater(img.width(), 50)
        self.assertGreater(img.height(), 30)

        out_path = SNAPSHOT_DIR / "keylock.png"
        saved = img.save(str(out_path))
        self.assertTrue(saved, f"Falha ao salvar {out_path}")

    def test_timer_spec(self):
        spec = init_timer_spec()
        self.assertIsNotNone(spec)
        img = self._render_spec_to_image(spec)
        self.assertFalse(img.isNull())
        self.assertEqual(img.width(), 164)
        self.assertEqual(img.height(), 164)

        out_path = SNAPSHOT_DIR / "timer.png"
        saved = img.save(str(out_path))
        self.assertTrue(saved, f"Falha ao salvar {out_path}")

    def test_volume_spec(self):
        spec = init_volume_spec()
        self.assertIsNotNone(spec)
        img = self._render_spec_to_image(spec)
        self.assertFalse(img.isNull())
        self.assertGreater(img.width(), 150)
        self.assertGreater(img.height(), 60)

        out_path = SNAPSHOT_DIR / "volume.png"
        saved = img.save(str(out_path))
        self.assertTrue(saved, f"Falha ao salvar {out_path}")

    def test_music_skin_specs(self):
        specs = init_music_skin_specs()
        self.assertEqual(len(specs), 4)

        skin_ids = [s.id for s in specs]
        self.assertIn("vinyl", skin_ids)
        self.assertIn("fullcover", skin_ids)
        self.assertIn("ripple", skin_ids)
        self.assertIn("capa_empilhada", skin_ids)

        for s in specs:
            img = self._render_spec_to_image(s)
            self.assertFalse(img.isNull(), f"Render falhou para {s.id}")
            out_path = SNAPSHOT_DIR / f"music_{s.id}.png"
            saved = img.save(str(out_path))
            self.assertTrue(saved, f"Falha ao salvar {out_path}")

    def test_preview_stage_caching(self):
        timer_spec = init_timer_spec()
        stage = PreviewStage(spec=timer_spec, theme=THEME_DARK)
        stage.resize(200, 128)

        # Força pintura
        img1 = stage._render_preview_pixmap(200, 128, 1.0)
        self.assertFalse(img1.isNull())

        # Troca tema e invalida cache
        stage.set_theme(THEME_LIGHT)
        self.assertIsNone(stage._cached_pixmap)

        img2 = stage._render_preview_pixmap(200, 128, 1.0)
        self.assertFalse(img2.isNull())

    def test_preview_card_selection(self):
        specs = init_music_skin_specs()
        card = PreviewCard(spec=specs[0], is_selected=False)
        self.assertFalse(card.is_selected())

        card.set_selected(True)
        self.assertTrue(card.is_selected())


if __name__ == "__main__":
    unittest.main()
