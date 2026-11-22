"""
Formato do Cronômetro: MM:SS:cc abaixo de 1 h e HH:MM:SS a partir dela, com a troca animada (sem corte) e o caso
sem animações (na hora).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.widgets.timer import time_layout as tl
from app.widgets.timer.skins.skin import TimerState, digits_geometry, paint_windows_timer


class TimeLayoutTests(unittest.TestCase):
    def test_stopwatch_under_an_hour_is_minutes_seconds_hundredths(self):
        texts = tl.slot_texts("stopwatch", 75.1239)
        self.assertEqual((texts["minutes"], texts["seconds"], texts["centis"]), ("01", "15", "12"))
        self.assertEqual(tl.morph_target("stopwatch", 3599.999), 0.0)

    def test_hundredths_are_cut_not_rounded(self):
        texts = tl.slot_texts("stopwatch", 59.996)
        self.assertEqual((texts["minutes"], texts["seconds"], texts["centis"]), ("00", "59", "99"))

    def test_both_formats_have_six_digits(self):
        for morph, secs in ((0.0, 75.0), (1.0, 4000.0)):
            texts, vis = tl.slot_texts("stopwatch", secs), tl.slot_visibility(morph)
            digits = sum(len(texts[k]) for k in tl.SLOT_KEYS if k not in tl.COLON_KEYS and vis[k] == 1.0)
            self.assertEqual(digits, 6)

    def test_from_one_hour_it_is_hours_minutes_seconds(self):
        texts = tl.slot_texts("stopwatch", 3600 + 61.5)
        self.assertEqual((texts["hours"], texts["minutes"], texts["seconds"]), ("01", "01", "01"))
        self.assertEqual(tl.morph_target("stopwatch", 3600.0), 1.0)

    def test_timer_and_alarm_keep_hh_mm_ss(self):
        for mode in ("timer", "alarm"):
            self.assertEqual(tl.morph_target(mode, 12.0), 1.0)
        texts = tl.slot_texts("timer", 3725.4)
        self.assertEqual((texts["hours"], texts["minutes"], texts["seconds"]), ("01", "02", "05"))

    def test_visibility_collapses_the_field_that_leaves(self):
        full = tl.slot_visibility(0.0)
        self.assertEqual((full["hours"], full["colon1"], full["centis"], full["colon3"]), (0.0, 0.0, 1.0, 1.0))
        hms = tl.slot_visibility(1.0)
        self.assertEqual((hms["hours"], hms["colon1"], hms["centis"], hms["colon3"]), (1.0, 1.0, 0.0, 0.0))

    def test_layout_is_centered_and_collapsed_fields_have_no_width(self):
        texts = tl.slot_texts("stopwatch", 5.0)
        rects = tl.layout_slots(100.0, 0.0, 40.0, tl.cell_advance(14.0), 6.0, texts, tl.slot_visibility(0.0))
        self.assertEqual(rects["hours"].width(), 0.0)
        left, right = rects["minutes"].left(), rects["centis"].right()
        self.assertAlmostEqual((left + right) / 2.0, 100.0, places=6)


class TimerMorphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        config_manager.set_timer_mode("stopwatch")
        from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
        self.skin = WindowsTimerSkin()
        self.skin.set_time_state(0.0, False, "stopwatch")
        for patcher in (mock.patch.object(self.skin, "isVisible", return_value=True),):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.skin._morph._timer.stop()
        self.skin.close()
        config_manager.config_path, config_manager._data = self._path, self._data

    def _run_to_rest(self) -> list[float]:
        """Roda a mola quadro a quadro (60 Hz simulados) até assentar; devolve o valor de cada quadro."""
        values = [self.skin.time_morph]
        now = [self.skin._morph._last]

        def fake_monotonic():
            now[0] += 1 / 60
            return now[0]

        with mock.patch("app.hub.components.tab_pill.time.monotonic", fake_monotonic):
            for _ in range(600):
                if not self.skin._morph.is_animating():
                    break
                self.skin._morph._tick()
                values.append(self.skin.time_morph)
        return values

    def test_starts_in_the_stopwatch_format(self):
        self.assertEqual(self.skin.time_morph, 0.0)

    def test_crossing_one_hour_animates_without_jumping(self):
        self.skin.set_time_state(3600.2, True, "stopwatch")
        self.assertEqual(self.skin.time_morph, 0.0)           # não pulou: a mola ainda vai sair do lugar
        self.assertTrue(self.skin._morph.is_animating())
        values = self._run_to_rest()
        self.assertGreater(len(values), 3)
        self.assertEqual(values[-1], 1.0)
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(values, values[1:])), "o formato só avança, sem voltar")
        self.assertFalse(self.skin._morph.is_animating())     # terminou limpo

    def test_reset_goes_back_to_the_stopwatch_format_animated(self):
        self.skin.set_time_state(3700.0, True, "stopwatch")
        self._run_to_rest()
        self.skin.set_time_state(0.0, False, "stopwatch")
        values = self._run_to_rest()
        self.assertEqual(values[-1], 0.0)
        self.assertTrue(all(b <= a + 1e-9 for a, b in zip(values, values[1:])))

    def test_without_windows_animations_it_switches_at_once(self):
        with mock.patch("app.hub.components.tab_pill.animations_enabled", return_value=False):
            self.skin.set_time_state(3600.2, True, "stopwatch")
        self.assertEqual(self.skin.time_morph, 1.0)
        self.assertFalse(self.skin._morph.is_animating())

    def test_hidden_skin_snaps_to_the_right_format(self):
        with mock.patch.object(self.skin, "isVisible", return_value=False):
            self.skin.set_time_state(3600.2, True, "stopwatch")
        self.assertEqual(self.skin.time_morph, 1.0)

    def test_stopwatch_digits_are_not_editable(self):
        rects, _, _ = self.skin.get_digits_geometry()
        self.assertIsNone(self.skin.get_time_segment_at(rects["seconds"].center()))

    def test_mouse_wheel_does_not_change_a_paused_stopwatch(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        self.skin.set_time_state(12.34, False, "stopwatch")
        ev = QWheelEvent(QPointF(80, 50), QPointF(80, 50), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.skin.wheelEvent(ev)
        self.assertEqual(self.skin.current_seconds, 12.34)

    def test_only_the_stopwatch_uses_fixed_digit_cells(self):
        card = QRectF(8, 8, 148, 148)
        self.assertIsNotNone(digits_geometry(card, 1.0, 5.0, "stopwatch", 0.0)[4])
        self.assertIsNone(digits_geometry(card, 1.0, 300.0, "timer", 1.0)[4])
        self.assertIsNone(digits_geometry(card, 1.0, 300.0, "alarm", 1.0)[4])

    def test_every_morph_step_paints(self):
        for morph in (0.0, 0.3, 0.7, 1.0):
            img = QImage(164, 164, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            paint_windows_timer(p, QRectF(0, 0, 164, 164),
                                TimerState(mode="stopwatch", current_seconds=3599.9, time_morph=morph))
            p.end()

    def test_width_fits_the_card_in_both_formats(self):
        card = QRectF(8, 8, 148, 148)
        for mode, secs in (("stopwatch", 5.0), ("stopwatch", 4000.0), ("timer", 3725.0)):
            rects, _, _, vis, _ = digits_geometry(card, 1.0, secs, mode, tl.morph_target(mode, secs))
            shown = [r for k, r in rects.items() if vis[k] > 0]
            self.assertGreaterEqual(min(r.left() for r in shown), card.left())
            self.assertLessEqual(max(r.right() for r in shown), card.right())


class StopwatchTickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        config_manager.set_timer_mode("timer")
        from app.widgets.timer import timer_controller as tc
        self.c = tc.TimerWidgetController()

    def tearDown(self):
        self.c._ticker.stop()
        self.c.skin.close()
        config_manager.config_path, config_manager._data = self._path, self._data

    def test_stopwatch_ticks_every_frame_and_timer_does_not(self):
        from app.core.refresh_rate import refresh_interval_ms
        self.c.set_mode("stopwatch")
        self.c.play()
        self.assertEqual(self.c._ticker.interval(), refresh_interval_ms())
        self.c.current_seconds = 3600.5   # passou de 1 h: só segundos inteiros na tela
        self.c._on_tick()
        self.assertEqual(self.c._ticker.interval(), self.c.TICK_MS)
        self.c.pause()
        self.c.set_mode("timer")
        self.c.set_duration(60)
        self.c.play()
        self.assertEqual(self.c._ticker.interval(), self.c.TICK_MS)


if __name__ == "__main__":
    unittest.main()
