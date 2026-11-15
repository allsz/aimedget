"""Deslize de posição (núcleo reutilizável) e a troca de posição do mixer com o flyout na tela."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtWidgets import QApplication, QWidget

from app.core import position_glide as pg

app = QApplication.instance() or QApplication(sys.argv)


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, ms):
        self.t += ms / 1000.0


class GlideEngineTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(pg, "animations_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = FakeClock()
        self.moves = []
        self.glide = pg.PositionGlide(lambda x, y: self.moves.append((x, y)), clock=self.clock)
        self.addCleanup(self.glide.stop)

    def test_duration_grows_with_distance_and_stays_in_range(self):
        self.assertEqual(pg.glide_duration_ms(0), pg.MIN_MS)
        self.assertLess(pg.glide_duration_ms(100), pg.MIN_MS + 10)   # salto curto: quase o mínimo
        self.assertGreater(pg.glide_duration_ms(1500), pg.glide_duration_ms(300))
        self.assertEqual(pg.glide_duration_ms(10 ** 6), pg.MAX_MS)
        self.assertLessEqual(pg.glide_duration_ms(1700), pg.MAX_MS)

    def test_easing_starts_fast_and_lands_without_overshoot(self):
        self.assertEqual(pg.ease_out_quart(0.0), 0.0)
        self.assertEqual(pg.ease_out_quart(1.0), 1.0)
        values = [pg.ease_out_quart(i / 20) for i in range(21)]
        self.assertEqual(values, sorted(values), "nunca volta atrás")
        self.assertTrue(all(0.0 <= v <= 1.0 for v in values), "nunca passa do alvo (o card encostado na borda não vaza)")
        self.assertGreater(pg.ease_out_quart(0.25), 0.6)   # arranca rápido
        self.assertEqual(pg.ease_out_quart(2.0), 1.0)

    def test_glides_in_the_direction_of_the_target_and_lands_exactly(self):
        self.assertTrue(self.glide.start(QPoint(100, 900), QPoint(1700, 40), duration_ms=300))
        self.assertTrue(self.glide.is_running())
        self.assertEqual(self.moves[-1], (100, 900))                 # começa onde estava

        xs, ys = [], []
        for _ in range(12):
            self.clock.advance(25)
            self.glide._on_tick()
            xs.append(self.moves[-1][0])
            ys.append(self.moves[-1][1])
        self.assertEqual(xs, sorted(xs))                              # vai para a direita...
        self.assertEqual(ys, sorted(ys, reverse=True))                # ...e para cima: a direção do alvo
        self.assertEqual(self.moves[-1], (1700, 40))                  # e termina EXATAMENTE no destino
        self.assertFalse(self.glide.is_running())

    def test_path_is_a_straight_line(self):
        self.glide.start((0, 0), (1000, 500), duration_ms=400)
        for _ in range(8):
            self.clock.advance(40)
            self.glide._on_tick()
            x, y = self.moves[-1]
            self.assertAlmostEqual(y, x / 2, delta=1.0)

    def test_finished_is_emitted_once(self):
        done = []
        self.glide.finished.connect(lambda: done.append(1))
        self.glide.start((0, 0), (300, 0), duration_ms=100)
        self.clock.advance(150)
        self.glide._on_tick()
        self.glide._on_tick()
        self.assertEqual(done, [1])

    def test_a_new_start_interrupts_from_where_the_caller_says(self):
        self.glide.start((0, 0), (1000, 0), duration_ms=400)
        self.clock.advance(100)
        self.glide._on_tick()
        here = self.glide.position()
        self.assertGreater(here.x(), 0)
        self.assertLess(here.x(), 1000)
        self.glide.start(here, (0, 800), duration_ms=300)             # o usuário escolheu outro lugar no meio do caminho
        self.assertEqual(self.moves[-1], (round(here.x()), round(here.y())))   # sem salto
        self.assertEqual(self.glide.target(), QPointF(0, 800))
        self.clock.advance(400)
        self.glide._on_tick()
        self.assertEqual(self.moves[-1], (0, 800))

    def test_stop_with_settle_jumps_to_the_destination(self):
        self.glide.start((0, 0), (500, 500), duration_ms=400)
        self.clock.advance(50)
        self.glide._on_tick()
        self.glide.stop(settle=True)
        self.assertEqual(self.moves[-1], (500, 500))
        self.assertFalse(self.glide.is_running())
        self.glide.stop(settle=True)                                  # parado: nada acontece
        self.assertEqual(self.moves[-1], (500, 500))

    def test_stop_without_settle_leaves_it_where_it_is(self):
        self.glide.start((0, 0), (500, 500), duration_ms=400)
        self.clock.advance(50)
        self.glide._on_tick()
        mid = self.moves[-1]
        self.glide.stop()
        self.assertEqual(self.moves[-1], mid)

    def test_zero_distance_and_disabled_system_animations_go_straight_there(self):
        self.assertFalse(self.glide.start((10, 10), (10, 10)))
        self.assertFalse(self.glide.is_running())
        with mock.patch.object(pg, "animations_enabled", return_value=False):
            self.assertFalse(self.glide.start((0, 0), (800, 600)))
        self.assertEqual(self.moves[-1], (800, 600))
        self.assertFalse(self.glide.is_running())
        self.assertTrue(self.glide.start((0, 0), (800, 600), respect_system_setting=False) is True)

    def test_timer_follows_the_monitor_refresh_rate(self):
        fake_screen = mock.Mock()
        fake_screen.refreshRate.return_value = 120.0
        with mock.patch.object(app, "primaryScreen", return_value=fake_screen):
            self.glide.start((0, 0), (500, 0), duration_ms=100)
            self.assertEqual(self.glide._timer.interval(), 8)          # a regra em si está em test_refresh_rate.py

    def test_moves_a_real_widget(self):
        w = QWidget()
        w.resize(50, 50)
        w.show()
        self.addCleanup(w.close)
        g = pg.PositionGlide(w.move, clock=self.clock)
        g.start((50, 60), (400, 300), duration_ms=200)
        self.assertEqual((w.x(), w.y()), (50, 60))
        self.clock.advance(250)
        g._on_tick()
        self.assertEqual((w.x(), w.y()), (400, 300))


class MixerAnchorGlideTests(unittest.TestCase):
    def setUp(self):
        for module in (pg, sys.modules["app.widgets.volume_mixer.mixer_flyout"] if "app.widgets.volume_mixer.mixer_flyout" in sys.modules else None):
            pass
        from app.widgets.volume_mixer import mixer_flyout as mf
        self.mf = mf
        patcher = mock.patch.object(pg, "animations_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fly = mf.VolumeMixerFlyout()
        self.fly._click_timer.stop()
        self.fly.show_osd(50, False)
        self.fly._slide_t = 1.0
        self.fly._anim_card_h = float(self.fly.COLLAPSED_H)
        self.fly.set_anchor("bc")
        self.fly._glide.stop(settle=True)
        self.addCleanup(self.fly.hide)

    def _card_tl(self):
        return QPointF(self.fly.pos()) + self.fly._card_rect().topLeft()

    def test_changing_position_while_visible_glides_from_where_the_card_was(self):
        before = self._card_tl()
        self.fly.set_anchor("tr")
        self.assertTrue(self.fly._glide.is_running())
        start_tl = self._card_tl()                                    # logo depois da troca...
        self.assertAlmostEqual(start_tl.x(), before.x(), delta=1.0)   # ...o card continua exatamente onde estava
        self.assertAlmostEqual(start_tl.y(), before.y(), delta=1.0)
        self.assertEqual(self.fly.anchor(), "tr")
        self.assertEqual(self.fly.windowOpacity(), 1.0)

    def test_it_lands_exactly_on_the_new_anchor(self):
        self.fly.set_anchor("tr")
        final = self.fly._glide.target()
        self.fly._glide.stop(settle=True)
        self.assertEqual((self.fly.x(), self.fly.y()), (round(final.x()), round(final.y())))
        expected = self.fly._target_pos(self.fly.height())
        self.assertEqual((self.fly.x(), self.fly.y()), expected)

    def test_stack_offset_updates_do_not_fight_the_glide(self):
        self.fly.set_anchor("ml")
        self.assertTrue(self.fly._glide.is_running())
        before = (self.fly.x(), self.fly.y())
        self.fly._place_window()                                      # o que o empilhamento do Caps Lock chama a cada quadro
        self.assertEqual((self.fly.x(), self.fly.y()), before)

    def test_finishing_the_glide_puts_the_window_at_the_exact_spot(self):
        self.fly.set_anchor("br")
        self.fly._glide._t0 -= 5.0                                    # o tempo passou
        self.fly._glide._on_tick()
        self.assertFalse(self.fly._glide.is_running())
        self.assertEqual((self.fly.x(), self.fly.y()), self.fly._target_pos(self.fly.height()))

    def test_changing_again_mid_glide_starts_from_the_current_spot(self):
        self.fly.set_anchor("tr")
        self.fly._glide._t0 -= 0.08                                   # meio do caminho
        self.fly._glide._on_tick()
        mid_tl = self._card_tl()
        self.fly.set_anchor("bl")
        again_tl = self._card_tl()
        self.assertAlmostEqual(again_tl.x(), mid_tl.x(), delta=1.0)
        self.assertAlmostEqual(again_tl.y(), mid_tl.y(), delta=1.0)
        self.assertEqual(self.fly.anchor(), "bl")

    def test_hiding_mid_glide_leaves_it_at_the_final_spot(self):
        self.fly.set_anchor("tl")
        self.fly.hide()
        self.assertFalse(self.fly._glide.is_running())
        self.assertEqual((self.fly.x(), self.fly.y()), self.fly._target_pos(self.fly.height()))

    def test_without_windows_animations_it_just_goes_there(self):
        with mock.patch.object(pg, "animations_enabled", return_value=False):
            self.fly.set_anchor("tc")
        self.assertFalse(self.fly._glide.is_running())
        self.assertEqual((self.fly.x(), self.fly.y()), self.fly._target_pos(self.fly.height()))
        self.assertEqual(self.fly.windowOpacity(), 1.0)

    def test_hidden_flyout_changes_position_instantly(self):
        self.fly.hide()
        self.fly.set_anchor("mr")
        self.assertFalse(self.fly._glide.is_running())
        self.assertEqual((self.fly.x(), self.fly.y()), self.fly._target_pos(self.fly.height()))


# ---------------------------------------------------------------------------------------------------------------
# Widgets (janelas de posição livre) e Caps/Num Lock
# ---------------------------------------------------------------------------------------------------------------

class WidgetGlideTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(pg, "animations_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        from app.core.widget_animator import SlideFadeAnimator
        self.w = QWidget()
        self.w.resize(60, 60)
        self.w.animator = SlideFadeAnimator(self.w)
        self.w.move(100, 100)
        self.w.show()
        self.addCleanup(self.w.close)

    def test_a_visible_widget_glides_from_where_it_is(self):
        self.assertTrue(pg.glide_widget_to(self.w, 900, 600))
        glide = pg.glide_of(self.w)
        self.assertTrue(glide.is_running())
        self.assertEqual((self.w.x(), self.w.y()), (100, 100))        # começa onde estava, sem salto
        glide._t0 -= 10.0
        glide._on_tick()
        self.assertEqual((self.w.x(), self.w.y()), (900, 600))
        self.assertFalse(glide.is_running())

    def test_a_hidden_widget_just_moves(self):
        self.w.hide()
        self.assertFalse(pg.glide_widget_to(self.w, 500, 400))
        self.assertEqual((self.w.x(), self.w.y()), (500, 400))

    def test_without_windows_animations_it_just_goes_there(self):
        with mock.patch.object(pg, "animations_enabled", return_value=False):
            self.assertFalse(pg.glide_widget_to(self.w, 700, 300))
        self.assertEqual((self.w.x(), self.w.y()), (700, 300))

    def test_picking_another_spot_mid_glide_starts_from_the_current_spot(self):
        pg.glide_widget_to(self.w, 900, 600)
        glide = pg.glide_of(self.w)
        glide._t0 -= 0.1
        glide._on_tick()
        here = (self.w.x(), self.w.y())
        self.assertNotEqual(here, (100, 100))
        pg.glide_widget_to(self.w, 50, 50)
        self.assertEqual((self.w.x(), self.w.y()), here)              # sem salto
        self.assertEqual(glide.target(), QPointF(50, 50))

    def test_grabbing_the_widget_with_the_mouse_stops_the_glide(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QMouseEvent
        pg.glide_widget_to(self.w, 900, 600)
        glide = pg.glide_of(self.w)
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(110, 110),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.w, press)
        self.assertFalse(glide.is_running())                          # o usuário assumiu (arrastar)

    def test_hiding_mid_glide_does_not_leave_the_rest_position_in_the_middle_of_the_path(self):
        """A animação de sumir guarda a posição de repouso: tem de ser o destino, não um ponto do caminho."""
        pg.glide_widget_to(self.w, 900, 600)
        glide = pg.glide_of(self.w)
        glide._t0 -= 0.05
        glide._on_tick()
        self.w.animator.hide(0)                                       # duração 0: conclui na hora
        self.assertFalse(self.w.isVisible())
        self.assertEqual((self.w.x(), self.w.y()), (900, 600))

    def test_the_hub_position_picker_uses_the_glide_for_music_and_timer(self):
        from app.hub import service_bridge
        src = Path(service_bridge.__file__).read_text(encoding="utf-8")
        self.assertIn("skin.glide_card_to(x, y)", src)
        self.assertIn("skin.glide_square_to(x, y)", src)

    def test_real_skins_translate_the_card_position_into_the_window_position(self):
        from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
        skin = WindowsTimerSkin()
        skin.move(10, 10)
        skin.show()
        self.addCleanup(skin.close)
        skin.glide_square_to(800, 500)
        glide = pg.glide_of(skin)
        glide._t0 -= 10.0
        glide._on_tick()
        self.assertEqual((skin.x(), skin.y()), (800 - skin.art_margin, 500 - skin.art_margin))


class KeyLockGlideTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(pg, "animations_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
        self.fly = KeyLockFlyout()
        self.fly.show_osd("Caps Lock", True)
        self.fly._hide_timer.stop()
        self.fly._popup_progress = 1.0
        self.fly.set_anchor("bc")
        self.fly._glide.stop(settle=True)
        self.addCleanup(self.fly.hide)

    def _card_tl(self):
        return QPointF(self.fly.pos()) + QPointF(self.fly._margins[0], self.fly._margins[1])

    def _final_pos(self):
        return (self.fly._get_centered_x(), int(round(self.fly._compute_target_win_y())))

    def test_changing_position_glides_from_where_the_card_was(self):
        before = self._card_tl()
        self.fly.set_anchor("tr")
        self.assertTrue(self.fly._glide.is_running())
        start = self._card_tl()
        self.assertAlmostEqual(start.x(), before.x(), delta=1.0)      # o card continua exatamente onde estava
        self.assertAlmostEqual(start.y(), before.y(), delta=1.0)
        self.assertEqual(self.fly.windowOpacity(), 1.0)

    def test_it_lands_exactly_on_the_new_anchor(self):
        self.fly.set_anchor("tr")
        self.fly._glide._t0 -= 5.0
        self.fly._glide._on_tick()
        self.assertFalse(self.fly._glide.is_running())
        self.assertEqual((self.fly.x(), self.fly.y()), self._final_pos())

    def test_forcing_the_same_anchor_does_not_animate(self):
        """O Hub chama set_anchor(force=True) a cada mudança de posição de QUALQUER flyout: sem mudança, nada anima."""
        self.fly.set_anchor("bc", force=True)
        self.assertFalse(self.fly._glide.is_running())

    def test_other_movers_do_not_fight_the_glide(self):
        self.fly.set_anchor("ml")
        self.assertTrue(self.fly._glide.is_running())
        before = (self.fly.x(), self.fly.y())
        self.fly.position_on_screen()                                 # chamado ao mostrar uma tecla
        self.fly.on_mixer_bounds_changed(100.0, 150.0, True)          # empilhamento com o mixer
        self.assertEqual((self.fly.x(), self.fly.y()), before)

    def test_hidden_flyout_goes_straight_to_the_new_anchor(self):
        self.fly.hide()
        self.fly.set_anchor("tl")
        self.assertFalse(self.fly._glide.is_running())
        self.assertEqual((self.fly.x(), self.fly.y()), self._final_pos())

    def test_hiding_mid_glide_leaves_it_at_the_final_spot(self):
        self.fly.set_anchor("br")
        self.fly.hide()
        self.assertFalse(self.fly._glide.is_running())
        self.assertEqual((self.fly.x(), self.fly.y()), self._final_pos())


if __name__ == "__main__":
    unittest.main()
