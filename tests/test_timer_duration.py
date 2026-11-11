"""
Timer: a duração pode ser zerada (00:00:00), mas só inicia com 10 s ou mais.
O ajuste "pula" entre 0 e 10 s: valores de 1 a 9 s nunca existem.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.widgets.timer.duration_rules import (
    MAX_SECONDS,
    MIN_RUN_SECONDS,
    normalize_duration,
    step_duration,
)


class TestRules(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_duration(0), 0)
        self.assertEqual(normalize_duration(-5), 0)
        for s in range(1, 10):
            self.assertEqual(normalize_duration(s), 10, s)
        self.assertEqual(normalize_duration(10), 10)
        self.assertEqual(normalize_duration(300), 300)
        self.assertEqual(normalize_duration(MAX_SECONDS + 99), MAX_SECONDS)

    def test_stepping_down_jumps_from_10_to_zero(self):
        self.assertEqual(step_duration(11, -1), 10)
        self.assertEqual(step_duration(10, -1), 0)      # 10 -> 00:00:00 (sem passar por 9)
        self.assertEqual(step_duration(0, -1), 0)

    def test_stepping_up_jumps_from_zero_to_10(self):
        self.assertEqual(step_duration(0, 1), 10)
        self.assertEqual(step_duration(0, 5), 10)
        self.assertEqual(step_duration(10, 1), 11)

    def test_big_steps_stop_at_10_before_zeroing(self):
        self.assertEqual(step_duration(40, -60), 10)    # 40 s - 1 min => para em 10 s
        self.assertEqual(step_duration(15, -5), 10)
        self.assertEqual(step_duration(10, -60), 0)     # já em 10 s: o próximo passo zera

    def test_no_dead_values_in_any_walk(self):
        v, seen = 300, set()
        for _ in range(400):                            # desce até o fim
            v = step_duration(v, -1)
            seen.add(v)
        for _ in range(60):                             # e sobe de volta
            v = step_duration(v, 1)
            seen.add(v)
        self.assertFalse(seen & set(range(1, MIN_RUN_SECONDS)))
        self.assertIn(0, seen)

    def test_legacy_value_between_1_and_9(self):
        self.assertEqual(step_duration(5, -1), 0)
        self.assertEqual(step_duration(5, 1), 10)

    def test_upper_bound(self):
        self.assertEqual(step_duration(MAX_SECONDS, 3600), MAX_SECONDS)


class TestControllerAndSkin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        config_manager.set_timer_mode("timer")
        config_manager.set_timer_duration(300)

        from app.widgets.timer.timer_controller import TimerWidgetController

        self.c = TimerWidgetController()

    def tearDown(self):
        self.c._ticker.stop()
        self.c.skin.close()
        config_manager.config_path, config_manager._data = self._path, self._data

    def wheel(self, dy):
        ev = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        self.c.skin.wheelEvent(ev)

    def test_can_be_zeroed_and_does_not_start(self):
        self.c.set_duration(0)
        self.assertEqual(self.c.target_duration, 0.0)
        self.assertEqual(self.c.current_seconds, 0.0)
        self.assertFalse(self.c.can_start())
        self.c.play()
        self.assertFalse(self.c.is_running)
        self.c.toggle_play_pause()
        self.assertFalse(self.c.is_running)

    def test_zero_is_persisted(self):
        self.c.set_duration(0)
        self.assertEqual(config_manager.get_timer_duration(300), 0)

    def test_values_1_to_9_snap_to_10_and_can_start(self):
        self.c.set_duration(5)
        self.assertEqual(self.c.target_duration, 10.0)
        self.assertTrue(self.c.can_start())
        self.c.play()
        self.assertTrue(self.c.is_running)

    def test_scroll_from_10_down_goes_to_zero_and_back_up_to_10(self):
        self.c.set_duration(10)
        self.c.skin.hovered_time_segment = "seconds"
        config_manager._data.setdefault("timer_widget", {})["smart_hover"] = True
        self.wheel(-120)                                    # -1 s
        self.assertEqual(self.c.target_duration, 0.0)       # 10 -> 00:00:00
        self.assertEqual(self.c.current_seconds, 0.0)
        self.assertFalse(self.c.skin.is_play_enabled())
        self.wheel(120)                                     # +1 s
        self.assertEqual(self.c.target_duration, 10.0)      # 00:00:00 -> 10 s
        self.assertTrue(self.c.skin.is_play_enabled())

    def test_play_button_state_follows_duration(self):
        self.c.set_duration(0)
        self.assertFalse(self.c.skin.is_play_enabled())
        self.assertEqual(self.c.skin._hit_test_for_play(), "play_disabled")
        self.c.set_duration(60)
        self.assertTrue(self.c.skin.is_play_enabled())
        self.assertEqual(self.c.skin._hit_test_for_play(), "play_pause")

    def test_running_timer_keeps_pause_available(self):
        self.c.set_duration(10)
        self.c.play()
        self.assertTrue(self.c.skin.is_play_enabled())      # o botão vira "pausar"
        self.c.pause()

    def test_finished_timer_restarts_with_configured_duration(self):
        self.c.set_duration(30)
        self.c.current_seconds = 0.0                        # terminou
        self.c.play()
        self.assertTrue(self.c.is_running)
        self.assertEqual(self.c.current_seconds, 30.0)

    def test_stopwatch_is_not_affected(self):
        self.c.set_duration(0)
        self.c.set_mode("stopwatch")
        self.assertTrue(self.c.can_start())
        self.c.play()
        self.assertTrue(self.c.is_running)
        self.c.pause()


class TypedDurationTests(unittest.TestCase):
    def test_fields_are_independent(self):
        from app.widgets.timer.duration_rules import compose_duration, split_duration
        fields = split_duration(0)
        fields["minutes"] = 20
        fields["seconds"] = 55
        self.assertEqual(compose_duration(fields), 20 * 60 + 55)      # 00:20:55
        fields["hours"] = 1
        self.assertEqual(compose_duration(fields), 3600 + 20 * 60 + 55)
        self.assertEqual(split_duration(3600 + 20 * 60 + 55), {"hours": 1, "minutes": 20, "seconds": 55})

    def test_field_limits(self):
        from app.widgets.timer.duration_rules import typed_field_accepts
        self.assertTrue(typed_field_accepts("minutes", "24"))
        self.assertFalse(typed_field_accepts("minutes", "240"))       # 240 fica 24
        self.assertFalse(typed_field_accepts("seconds", "60"))
        self.assertTrue(typed_field_accepts("hours", "99"))
        self.assertFalse(typed_field_accepts("hours", "100"))

    def test_total_limits_and_minimum(self):
        from app.widgets.timer.duration_rules import MAX_SECONDS, compose_duration
        self.assertEqual(MAX_SECONDS, 99 * 3600 + 59 * 60 + 59)
        self.assertEqual(compose_duration({"hours": 0, "minutes": 0, "seconds": 5}), 10)
        self.assertEqual(compose_duration({"hours": 0, "minutes": 0, "seconds": 0}), 0)


if __name__ == "__main__":
    unittest.main()
