"""
Testes do mini OSD de volume do Music Widget:
- Regra de ancoragem e limitação à tela (direita -> esquerda -> acima/abaixo), incluindo
  monitores múltiplos com coordenadas negativas.
- Fluxo da roda do mouse: acúmulo fracionário, limites 0..100 e exibição do OSD.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from PySide6.QtGui import QColor, QImage, QPixmap

from app.widgets.music.volume_osd import (
    BAR_W,
    EDGE_GAP,
    SCREEN_MARGIN,
    bar_height_for,
    compute_osd_position,
    is_light_backdrop,
    sample_backdrop_luminance,
)

BODY_W, BODY_H = BAR_W, 120
OSD = QSize(BODY_W, BODY_H)


def inside(pos: QPoint, screen: QRect) -> bool:
    return (
        pos.x() >= screen.left()
        and pos.y() >= screen.top()
        and pos.x() + BODY_W <= screen.right() + 1
        and pos.y() + BODY_H <= screen.bottom() + 1
    )


class TestOsdPosition(unittest.TestCase):
    SCREEN = QRect(0, 0, 1920, 1040)

    def test_prefers_right_side_centered(self):
        widget = QRect(400, 300, 480, 270)
        pos = compute_osd_position(widget, OSD, self.SCREEN)
        self.assertEqual(pos.x(), widget.right() + 1 + EDGE_GAP)
        self.assertEqual(pos.y() + BODY_H // 2, widget.center().y())

    def test_flips_left_near_right_edge(self):
        widget = QRect(1920 - 480 - 4, 300, 480, 270)
        pos = compute_osd_position(widget, OSD, self.SCREEN)
        self.assertEqual(pos.x(), widget.left() - EDGE_GAP - BODY_W)
        self.assertTrue(inside(pos, self.SCREEN))

    def test_clamps_at_top_and_bottom(self):
        top = compute_osd_position(QRect(400, 0, 480, 100), OSD, self.SCREEN)
        self.assertEqual(top.y(), self.SCREEN.top() + SCREEN_MARGIN)
        bottom = compute_osd_position(QRect(400, 960, 480, 80), OSD, self.SCREEN)
        self.assertEqual(bottom.y() + BODY_H, self.SCREEN.bottom() + 1 - SCREEN_MARGIN)

    def test_corners_stay_inside(self):
        for x in (0, 1920 - 480):
            for y in (0, 1040 - 270):
                widget = QRect(x, y, 480, 270)
                self.assertTrue(inside(compute_osd_position(widget, OSD, self.SCREEN), self.SCREEN), (x, y))

    def test_secondary_monitor_left_of_primary(self):
        # Monitor à esquerda (coordenadas negativas): a "direita" do widget seria o outro monitor
        screen = QRect(-1920, 0, 1920, 1080)
        widget = QRect(-500, 200, 480, 270)
        pos = compute_osd_position(widget, OSD, screen)
        self.assertTrue(inside(pos, screen))
        self.assertLess(pos.x(), widget.left())

    def test_widget_spanning_screen_uses_above_or_below(self):
        widget = QRect(10, 400, 1900, 200)
        pos = compute_osd_position(widget, OSD, self.SCREEN)
        self.assertTrue(inside(pos, self.SCREEN))
        self.assertFalse(QRect(pos, OSD).intersects(widget))

    def test_tiny_screen_never_negative_overflow(self):
        screen = QRect(0, 0, 300, 120)
        pos = compute_osd_position(QRect(10, 10, 200, 100), OSD, screen)
        self.assertGreaterEqual(pos.x(), screen.left())
        self.assertGreaterEqual(pos.y(), screen.top())


class TestBarAndBackdrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_bar_is_shorter_than_widget(self):
        for widget_h in (100, 148, 270, 540, 900):
            h = bar_height_for(widget_h)
            self.assertLess(h, widget_h, widget_h)
            self.assertGreaterEqual(h, 32)
        self.assertEqual(bar_height_for(270), 162)  # 60%

    def test_light_backdrop_picks_dark_ink(self):
        self.assertTrue(is_light_backdrop(0.9))      # papel de parede branco
        self.assertTrue(is_light_backdrop(0.35))
        self.assertFalse(is_light_backdrop(0.05))    # fundo escuro
        self.assertFalse(is_light_backdrop(None))    # sem captura: padrão branco

    def _screen_with(self, color: str):
        class Geo:
            def topLeft(self):
                return QPoint(0, 0)

        class Scr:
            def geometry(self):
                return Geo()

            def grabWindow(self, wid, x, y, w, h):
                img = QImage(max(1, w), max(1, h), QImage.Format.Format_RGB32)
                img.fill(QColor(color))
                return QPixmap.fromImage(img)

        return Scr()

    def test_sampling_white_and_black_wallpaper(self):
        rect = QRect(100, 100, BAR_W, 120)
        white = sample_backdrop_luminance(self._screen_with("#FFFFFF"), rect)
        black = sample_backdrop_luminance(self._screen_with("#000000"), rect)
        self.assertAlmostEqual(white, 1.0, places=2)
        self.assertAlmostEqual(black, 0.0, places=2)
        self.assertTrue(is_light_backdrop(white))
        self.assertFalse(is_light_backdrop(black))

    def test_sampling_failure_returns_none(self):
        class Broken:
            def geometry(self):
                raise RuntimeError("sem captura")

        self.assertIsNone(sample_backdrop_luminance(Broken(), QRect(0, 0, 8, 8)))


class _FakeMixer:
    def __init__(self, volume=50, muted=False):
        self.volume, self.muted = volume, muted
        self.sets = []

    def get_master_volume(self):
        return self.volume

    def get_master_mute(self):
        return self.muted

    def set_master_volume(self, v, from_ui=True):
        self.volume = v
        self.sets.append((v, from_ui))
        if v > 0:
            self.muted = False


class _FakeOsd:
    def __init__(self):
        self.calls = []

    def show_for(self, anchor, volume, muted):
        self.calls.append((volume, muted))


class TestWheelFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _bridge(self, mixer, osd):
        from app.hub.service_bridge import HubServiceBridge

        b = QObject()
        b._wheel_remainder = 0.0
        b.audio_service = mixer
        b.music_volume_osd = osd
        b.music_controller = type("C", (), {"skin": object()})()
        b._resolve_music_volume_target = lambda: None  # player não identificado => volume do sistema
        b.handler = lambda n: HubServiceBridge._on_music_volume_wheel(b, n)
        return b

    def test_step_clamp_and_osd(self):
        mixer, osd = _FakeMixer(98), _FakeOsd()
        b = self._bridge(mixer, osd)
        b.handler(1.0)   # +2 -> 100
        b.handler(1.0)   # já no máximo: não reescreve, mas mostra o OSD
        self.assertEqual(mixer.volume, 100)
        self.assertEqual(mixer.sets, [(100, True)])
        self.assertEqual(osd.calls, [(100, False), (100, False)])
        mixer.volume = 1
        b.handler(-1.0)  # -2 -> 0
        self.assertEqual(mixer.volume, 0)

    def test_fractional_touchpad_accumulates(self):
        mixer, osd = _FakeMixer(50), _FakeOsd()
        b = self._bridge(mixer, osd)
        for _ in range(3):
            b.handler(0.125)  # 3 x 0,25% = 0,75%: ainda sem passo inteiro
        self.assertEqual(mixer.volume, 50)
        self.assertEqual(osd.calls, [])
        b.handler(0.125)      # completa 1%
        self.assertEqual(mixer.volume, 51)
        for _ in range(4):
            b.handler(0.125)
        self.assertEqual(mixer.volume, 52)

    def test_scroll_up_unmutes(self):
        mixer, osd = _FakeMixer(30, muted=True), _FakeOsd()
        b = self._bridge(mixer, osd)
        b.handler(1.0)
        self.assertFalse(mixer.muted)
        self.assertEqual(osd.calls[-1], (32, False))

    def test_skin_wheel_signal(self):
        from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

        skin = VinylMusicSkin()
        got = []
        skin.volume_wheel_requested.connect(got.append)
        ev = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        skin.wheelEvent(ev)
        self.assertEqual(got, [1.0])
        self.assertTrue(ev.isAccepted())

    def test_wheel_ignored_when_option_disabled(self):
        from app.core.config_manager import config_manager
        from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

        previous = config_manager.is_music_wheel_volume_enabled()
        config_manager._data.setdefault("music_widget", {})["wheel_volume"] = False
        try:
            skin = VinylMusicSkin()
            got = []
            skin.volume_wheel_requested.connect(got.append)
            ev = QWheelEvent(
                QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            skin.wheelEvent(ev)
            self.assertEqual(got, [])
        finally:
            config_manager._data["music_widget"]["wheel_volume"] = previous


if __name__ == "__main__":
    unittest.main()
