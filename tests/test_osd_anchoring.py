"""
Ancoragem da barra de volume ao Music Widget durante o arraste:
- A barra acompanha o widget continuamente (sem "teletransporte").
- Nas paredes da tela ela troca de lado uma vez, com histerese (sem oscilar), e nunca sai da tela.
- Acompanha só a posição de repouso (ignora o deslize da animação) e solta o widget ao sumir.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app.core.widget_animator as wa
from app.widgets.music.volume_osd import (
    BAR_W,
    EDGE_GAP,
    SCREEN_MARGIN,
    SHADOW_MARGIN,
    SIDE_HYSTERESIS,
    MusicVolumeOSD,
    compute_osd_placement,
)


def wait_until(condition, timeout_ms: int = 2000) -> bool:
    """Espera a condição valer (até `timeout_ms`), processando eventos. Mais robusto que esperar um tempo fixo."""
    waited = 0
    while not condition():
        if waited >= timeout_ms:
            return False
        QTest.qWait(10)
        waited += 10
    return True


SCREEN = QRect(0, 0, 1920, 1040)
WIDGET = QSize(264, 148)
OSD = QSize(BAR_W, 90)


def place(x, y, prev=None, screen=SCREEN):
    return compute_osd_placement(QRect(QPoint(x, y), WIDGET), OSD, screen, previous_side=prev)


def inside(pos: QPoint, screen=SCREEN) -> bool:
    return (
        pos.x() >= screen.left()
        and pos.y() >= screen.top()
        and pos.x() + OSD.width() <= screen.right() + 1
        and pos.y() + OSD.height() <= screen.bottom() + 1
    )


class TestPlacementWhileDragging(unittest.TestCase):
    def _sweep_x(self, xs, y=400):
        prev, out = None, []
        for x in xs:
            pos, side = place(x, y, prev)
            out.append((x, pos, side))
            prev = side
        return out

    def test_horizontal_drag_into_both_walls_flips_once_each_way(self):
        right_wall = SCREEN.width() - WIDGET.width()
        forward = list(range(0, right_wall + 1))
        run = self._sweep_x(forward + forward[::-1])
        sides = [s for _, _, s in run]
        flips = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
        self.assertEqual(flips, 2, "deve ir à esquerda perto da parede e voltar uma única vez")
        for _, pos, _ in run:
            self.assertTrue(inside(pos))

    def test_continuous_follow_same_side(self):
        # Sem trocar de lado, a barra anda exatamente o que o widget andou (nenhum salto)
        run = self._sweep_x(range(0, SCREEN.width() - WIDGET.width() + 1))
        for (x0, p0, s0), (x1, p1, s1) in zip(run, run[1:]):
            if s0 == s1:
                self.assertEqual(p1.x() - p0.x(), x1 - x0)
                self.assertEqual(p1.y(), p0.y())

    def test_jitter_around_the_wall_never_oscillates(self):
        right_wall = SCREEN.width() - WIDGET.width()
        threshold = right_wall - EDGE_GAP - OSD.width() - SCREEN_MARGIN
        prev, sides = None, []
        for step in range(200):
            x = threshold + (3 if step % 2 else -3)   # treme de um lado ao outro da fronteira
            pos, prev = place(x, 300, prev)
            sides.append(prev)
        flips = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
        self.assertLessEqual(flips, 1)

    def test_hysteresis_band_keeps_left_until_clear(self):
        right_wall = SCREEN.width() - WIDGET.width()
        # força "left" e recua o widget só um pouco: ainda deve ficar à esquerda
        _, side = place(right_wall - 5, 300, None)
        self.assertEqual(side, "left")
        _, side = place(right_wall - 5 - SIDE_HYSTERESIS // 2, 300, "left")
        self.assertEqual(side, "left")
        _, side = place(right_wall - 5 - SIDE_HYSTERESIS - 40, 300, "left")
        self.assertEqual(side, "right")

    def test_vertical_walls_clamp_smoothly(self):
        prev, last_y = None, None
        for y in list(range(-80, SCREEN.height() + 80)):
            pos, prev = place(700, y, prev)
            self.assertTrue(inside(pos), (y, pos))
            if last_y is not None:
                self.assertLessEqual(abs(pos.y() - last_y), 1)   # nunca salta
            last_y = pos.y()

    def test_all_corners_and_diagonals_stay_inside(self):
        prev = None
        for t in range(0, 101):
            x = round((SCREEN.width() - WIDGET.width()) * t / 100)
            y = round((SCREEN.height() - WIDGET.height()) * t / 100)
            for xx, yy in ((x, y), (SCREEN.width() - WIDGET.width() - x, y), (x, SCREEN.height() - WIDGET.height() - y)):
                pos, prev = place(xx, yy, prev)
                self.assertTrue(inside(pos), (xx, yy, pos))

    def test_second_monitor_with_negative_coordinates(self):
        left_screen = QRect(-1920, 0, 1920, 1080)
        prev = None
        for x in range(-1920, -WIDGET.width() + 1, 7):
            pos, prev = place(x, 500, prev, screen=left_screen)
            self.assertTrue(inside(pos, left_screen), (x, pos))


class TestLiveAnchoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._orig = wa.animations_enabled
        wa.animations_enabled = lambda: True
        from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

        self.skin = VinylMusicSkin()
        self.skin.move(100, 120)
        self.skin.show()
        self.osd = MusicVolumeOSD()
        self.osd.show_for(self.skin, 50, False)

    def tearDown(self):
        wa.animations_enabled = self._orig
        self.osd.hide()
        self.skin.close()

    def body(self) -> QPoint:
        return QPoint(self.osd.x() + SHADOW_MARGIN, self.osd.y() + SHADOW_MARGIN)

    def test_follows_widget_drag_without_new_scroll(self):
        before = self.body()
        self.skin.move(150, 160)                      # arraste, sem rolar a roda
        after = self.body()
        self.assertEqual(after.x() - before.x(), 50)
        self.assertEqual(after.y() - before.y(), 40)
        self.assertEqual(after.x(), self.skin.x() + self.skin.width() + EDGE_GAP)

    def test_drag_into_right_wall_flips_left_and_back_with_hysteresis(self):
        screen = self.skin.screen().availableGeometry()
        wall_x = screen.right() + 1 - self.skin.width() - 4
        self.skin.move(wall_x, 150)
        self.assertLess(self.body().x(), self.skin.x())                 # foi para a esquerda
        self.assertEqual(self.body().x(), self.skin.x() - EDGE_GAP - BAR_W)
        self.skin.move(wall_x - 10, 150)                                # recuo curto: não oscila
        self.assertLess(self.body().x(), self.skin.x())
        self.skin.move(100, 150)                                        # longe da parede: volta
        self.assertGreater(self.body().x(), self.skin.x())

    def test_wheel_tick_during_drag_does_not_teleport(self):
        self.skin.move(220, 140)
        followed = self.body()
        self.osd.show_for(self.skin, 55, False)                         # tick da roda no meio do arraste
        self.assertEqual(self.body(), followed)

    def test_ignores_slide_animation_offset(self):
        rest_body = self.body()
        self.skin.animator.hide(400)
        QTest.qWait(120)                                                # widget deslocado pelo deslize
        self.assertNotEqual(self.skin.pos(), self.skin.rest_pos())
        self.assertEqual(self.body(), rest_body)

    def test_hiding_the_widget_fades_the_bar_out_too(self):
        self.skin.hide()
        self.assertTrue(wait_until(lambda: not self.osd.isVisible(), 2000))

    def test_stops_following_after_it_disappears(self):
        self.osd._start_fade_out()
        QTest.qWait(300)
        self.assertFalse(self.osd.isVisible())
        parked = self.osd.pos()
        self.skin.move(300, 300)
        self.assertEqual(self.osd.pos(), parked)

    def test_resize_keeps_bar_shorter_than_widget(self):
        self.skin.set_scale(0.75, save_preference=False)
        self.assertLess(self.osd._bar_h, self.skin.height())


if __name__ == "__main__":
    unittest.main()
