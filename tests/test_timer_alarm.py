"""
Modo Alarme do Timer: o usuário escolhe um horário e o widget conta até ele (hoje, ou amanhã se já passou), pelo
relógio do sistema. Pausar desarma, reiniciar zera o horário (00:00:00), e ao chegar toca o mesmo aviso do Temporizador.
"""

import datetime
import os
import sys
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.i18n import TRANSLATIONS, i18n
from app.widgets.timer import alarm_rules as ar
from app.widgets.timer.skins.skin import TimerState, mode_label

H, M = 3600, 60


def _force_language(test: unittest.TestCase, lang: str):
    """Fixa o idioma do app no teste sem gravar na config do usuário."""
    patcher = mock.patch.object(i18n, "_current_lang", lang)
    patcher.start()
    test.addCleanup(patcher.stop)


class AlarmRulesTests(unittest.TestCase):
    def setUp(self):
        _force_language(self, "pt")

    def test_next_alarm_is_today_or_tomorrow(self):
        now = datetime.datetime(2026, 11, 11, 14, 20, 0)
        self.assertEqual(ar.next_alarm(now, 15 * H), datetime.datetime(2026, 11, 11, 15, 0, 0))
        self.assertEqual(ar.next_alarm(now, 7 * H + 30 * M), datetime.datetime(2026, 11, 12, 7, 30, 0))
        self.assertEqual(ar.next_alarm(now, 14 * H + 20 * M), datetime.datetime(2026, 11, 12, 14, 20, 0))  # agora = amanhã

    def test_wraps_around_midnight(self):
        self.assertEqual(ar.step_alarm_time(23 * H + 59 * M, M), 0)
        self.assertEqual(ar.step_alarm_time(0, -M), 23 * H + 59 * M)
        self.assertEqual(ar.normalize_alarm_time(25 * H), H)

    def test_typed_fields(self):
        self.assertTrue(ar.alarm_field_accepts("hours", "23"))
        self.assertFalse(ar.alarm_field_accepts("hours", "24"))
        self.assertFalse(ar.alarm_field_accepts("minutes", "60"))
        self.assertEqual(ar.compose_alarm_time({"hours": 7, "minutes": 30, "seconds": 0}), 7 * H + 30 * M)

    def test_default_is_the_next_full_hour_and_format(self):
        self.assertEqual(ar.default_alarm_time(datetime.datetime(2026, 1, 1, 14, 20)), 15 * H)
        self.assertEqual(ar.default_alarm_time(datetime.datetime(2026, 1, 1, 23, 5)), 0)
        self.assertEqual(ar.format_clock(7 * H + 30 * M), "07:30")
        self.assertEqual(ar.format_clock(7 * H + 30 * M + 15), "07:30:15")

    def test_labels(self):
        self.assertEqual(mode_label(TimerState(mode="alarm", alarm_time=7 * H + 30 * M)), "ALARME")
        self.assertEqual(mode_label(TimerState(mode="alarm", alarm_time=7 * H + 30 * M, is_running=True)),
                         "ALARME · 07:30")
        self.assertEqual(mode_label(TimerState(mode="alarm", alarm_finished=True)), "CONCLUÍDO")
        self.assertEqual(mode_label(TimerState(mode="timer", current_seconds=0, target_duration=60)), "CONCLUÍDO")
        self.assertEqual(mode_label(TimerState(mode="stopwatch")), "CRONÔMETRO")

    def test_labels_follow_the_app_language(self):
        i18n._current_lang = "en"
        self.assertEqual(mode_label(TimerState(mode="timer")), "TIMER")
        self.assertEqual(mode_label(TimerState(mode="stopwatch")), "STOPWATCH")
        self.assertEqual(mode_label(TimerState(mode="alarm", alarm_time=7 * H + 30 * M, is_running=True)),
                         "ALARM · 07:30")
        self.assertEqual(mode_label(TimerState(mode="alarm", alarm_finished=True)), "DONE")

    def test_timer_keys_exist_in_both_languages(self):
        keys = [k for k in TRANSLATIONS["pt"] if k.startswith(("timer_menu_", "timer_mode_", "timer_label_"))]
        self.assertGreaterEqual(len(keys), 12)
        for k in keys:
            self.assertIn(k, TRANSLATIONS["en"], k)


class _Clock:
    """Relógio controlado: substitui datetime.now() e time.time() do controller."""

    def __init__(self, start: datetime.datetime):
        self.now = start

    def advance(self, seconds: float):
        self.now += datetime.timedelta(seconds=seconds)


class AlarmControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        _force_language(self, "pt")
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        config_manager._data.setdefault("timer_widget", {})["smart_hover"] = True
        config_manager.set_timer_mode("timer")

        self.clock = _Clock(datetime.datetime(2026, 11, 11, 14, 20, 0))
        from app.widgets.timer import timer_controller as tc
        fake_dt = mock.MagicMock(wraps=datetime)
        fake_dt.datetime = mock.MagicMock(wraps=datetime.datetime)
        fake_dt.datetime.now = lambda: self.clock.now
        patches = [
            mock.patch.object(tc, "datetime", fake_dt),
            mock.patch.object(tc.time, "time", lambda: self.clock.now.timestamp()),
            mock.patch.object(tc, "play_alarm"),
            mock.patch.object(tc, "stop_alarm"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.tc = tc
        self.c = tc.TimerWidgetController()
        self.c._ticker.stop()

    def tearDown(self):
        self.c._ticker.stop()
        self.c._pulse_timer.stop()
        self.c.skin.close()
        config_manager.config_path, config_manager._data = self._path, self._data

    def tick(self, seconds):
        self.clock.advance(seconds)
        self.c._on_tick()

    def test_first_time_suggests_the_next_full_hour_and_shows_it(self):
        self.c.set_mode("alarm")
        self.assertEqual(self.c.alarm_time, 15 * H)
        self.assertEqual(self.c.current_seconds, 15 * H)        # parado, os dígitos mostram o horário
        self.assertTrue(self.c.skin.is_play_enabled())

    def test_counts_down_to_the_time_and_rings(self):
        self.c.set_mode("alarm")
        self.c.set_alarm_time(14 * H + 30 * M)
        self.c.play()
        self.assertAlmostEqual(self.c.current_seconds, 10 * M, delta=1)   # faltam 10 min
        self.tick(5 * M)
        self.assertAlmostEqual(self.c.current_seconds, 5 * M, delta=1)
        self.assertEqual(mode_label(self._state()), "ALARME · 14:30")
        self.tick(5 * M + 1)
        self.assertFalse(self.c.is_running)
        self.assertTrue(self.c.alarm_finished)
        self.assertEqual(self.c.current_seconds, 0.0)
        self.tc.play_alarm.assert_called_once()
        self.assertEqual(mode_label(self._state()), "CONCLUÍDO")

    def test_time_already_passed_today_rings_tomorrow(self):
        self.c.set_mode("alarm")
        self.c.set_alarm_time(14 * H)            # já passou (agora 14:20)
        self.c.play()
        self.assertAlmostEqual(self.c.current_seconds, 23 * H + 40 * M, delta=1)

    def test_sleeping_pc_still_rings_on_wake(self):
        self.c.set_mode("alarm")
        self.c.set_alarm_time(14 * H + 30 * M)
        self.c.play()
        self.tick(3 * H)                          # o PC dormiu além do horário: toca ao acordar
        self.assertTrue(self.c.alarm_finished)

    def test_pause_disarms_and_reset_zeroes_the_time(self):
        self.c.set_mode("alarm")
        self.c.set_alarm_time(14 * H + 30 * M)
        self.c.play()
        self.tick(60)
        self.c.pause()
        self.assertEqual(self.c.current_seconds, 14 * H + 30 * M)   # volta a mostrar o horário
        self.c.play()
        self.c.reset()
        self.assertFalse(self.c.is_running)
        self.assertEqual((self.c.alarm_time, self.c.current_seconds), (0, 0))   # como o Temporizador: 00:00:00
        self.assertEqual(config_manager.get_timer_alarm_time(), 0)

    def test_changing_the_time_while_armed_retargets(self):
        self.c.set_mode("alarm")
        self.c.set_alarm_time(14 * H + 30 * M)
        self.c.play()
        self.c.set_alarm_time(15 * H)
        self.assertTrue(self.c.is_running)
        self.assertAlmostEqual(self.c.current_seconds, 40 * M, delta=1)

    def test_time_is_saved_and_mode_survives_restart(self):
        self.c.set_mode("alarm")
        self.c.set_alarm_time(6 * H + 45 * M)
        self.c.skin.close()
        self.c = self.tc.TimerWidgetController()
        self.assertEqual((self.c.mode, self.c.alarm_time, self.c.current_seconds), ("alarm", 6 * H + 45 * M, 6 * H + 45 * M))

    def test_other_modes_are_unchanged(self):
        self.c.set_mode("timer")
        self.c.set_duration(120)
        self.assertEqual(self.c.current_seconds, 120)
        self.c.set_mode("stopwatch")
        self.assertEqual(self.c.current_seconds, 0)

    # --- edição no widget ---

    def _wheel(self, dy):
        ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.c.skin.wheelEvent(ev)

    def test_scroll_on_hours_wraps_at_midnight(self):
        self.c.set_mode("alarm")
        self.c.set_alarm_time(23 * H)
        self.c.skin.hovered_time_segment = "hours"
        self._wheel(120)
        self.assertEqual(self.c.alarm_time, 0)                    # 23h + 1 h = 00h
        self.assertEqual(config_manager.get_timer_alarm_time(), 0)
        self._wheel(-120)
        self.assertEqual(self.c.alarm_time, 23 * H)

    def test_typing_hours_caps_at_23(self):
        self.c.set_mode("alarm")
        self.c.set_alarm_time(0)
        self.c.skin.hovered_time_segment = "hours"
        for key in (Qt.Key.Key_2, Qt.Key.Key_5):                  # "25" não cabe: fica 2
            self.c.skin.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.c.alarm_time, 2 * H)
        self.c.skin.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_3, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.c.alarm_time, 23 * H)

    def test_menu_offers_the_alarm_mode(self):
        import app.widgets.timer.skins.base_skin as bs
        from PySide6.QtGui import QContextMenuEvent
        seen = []

        def fake_exec(menu, *a):
            for act in menu.actions():
                if act.menu() is not None:
                    seen.extend(a.text() for a in act.menu().actions())

        with mock.patch.object(bs.FluentTimerMenu, "exec", fake_exec):
            self.c.skin.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5)))
        self.assertIn("Alarme (Horário)", seen)

    def test_menu_is_translated(self):
        import app.widgets.timer.skins.base_skin as bs
        from PySide6.QtGui import QContextMenuEvent
        i18n._current_lang = "en"
        seen = []

        def fake_exec(menu, *a):
            for act in menu.actions():
                seen.append(act.text())
                if act.menu() is not None:
                    seen.extend(a.text() for a in act.menu().actions())

        with mock.patch.object(bs.FluentTimerMenu, "exec", fake_exec):
            self.c.skin.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5)))
        for text in ("Remember position", "Mode", "Timer (Countdown)", "Stopwatch", "Alarm (Time of day)",
                     "Reset to default size", "Close widget"):
            self.assertIn(text, seen)

    def _state(self):
        return TimerState(mode=self.c.mode, is_running=self.c.is_running, current_seconds=self.c.current_seconds,
                          alarm_time=self.c.alarm_time, alarm_finished=self.c.alarm_finished)


if __name__ == "__main__":
    unittest.main()
