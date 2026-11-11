"""Som de fim do Timer: arquivo próprio no lugar do aviso padrão do Windows, com interruptor no Hub."""

import os
import sys
import tempfile
import unittest
import wave
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core import alarm_sound
from app.core.config_manager import config_manager


class AlarmFileTests(unittest.TestCase):
    def test_bundled_file_exists_and_is_playable_by_winsound(self):
        self.assertTrue(os.path.isfile(alarm_sound.ALARM_FILE))
        self.assertIn("mitchellsloan", os.path.basename(alarm_sound.ALARM_FILE))   # nome do autor preservado
        with wave.open(alarm_sound.ALARM_FILE, "rb") as w:
            self.assertEqual(w.getsampwidth(), 2, "winsound não toca 24 bits: o arquivo precisa ser 16 bits")
            self.assertLess(w.getnframes() / w.getframerate(), 6.0)   # curto: não vira um alarme longo

    def test_missing_file_falls_back_to_system_beep(self):
        with mock.patch("winsound.PlaySound") as play, mock.patch("winsound.MessageBeep") as beep:
            self.assertFalse(alarm_sound.play_alarm(os.path.join(tempfile.gettempdir(), "nao-existe.wav")))
        play.assert_not_called()
        beep.assert_called_once()

    def test_plays_the_file_asynchronously(self):
        import winsound
        with mock.patch("winsound.PlaySound") as play:
            self.assertTrue(alarm_sound.play_alarm())
        args = play.call_args.args
        self.assertEqual(args[0], alarm_sound.ALARM_FILE)
        self.assertTrue(args[1] & winsound.SND_ASYNC and args[1] & winsound.SND_FILENAME)


class ControllerAlarmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        from app.widgets.timer.timer_controller import TimerWidgetController
        self.c = TimerWidgetController()

    def tearDown(self):
        self.c._ticker.stop()
        self.c._pulse_timer.stop()
        self.c.skin.close()
        config_manager.config_path, config_manager._data = self._path, self._data

    def test_sound_is_on_by_default_and_persists(self):
        self.assertTrue(config_manager.is_timer_alarm_sound_enabled())
        config_manager.set_timer_alarm_sound_enabled(False)
        self.assertFalse(config_manager.is_timer_alarm_sound_enabled())

    def test_finishing_plays_the_custom_sound_not_the_windows_beep(self):
        with mock.patch("app.widgets.timer.timer_controller.play_alarm") as play, \
             mock.patch("winsound.MessageBeep") as beep:
            self.c._trigger_alarm_finish()
        play.assert_called_once()
        beep.assert_not_called()

    def test_switch_off_keeps_it_silent_but_still_pulses(self):
        config_manager.set_timer_alarm_sound_enabled(False)
        with mock.patch("app.widgets.timer.timer_controller.play_alarm") as play:
            self.c._trigger_alarm_finish()
        play.assert_not_called()
        self.assertTrue(self.c._pulse_timer.isActive())

    def test_reset_silences_a_sound_still_playing(self):
        with mock.patch("app.widgets.timer.timer_controller.stop_alarm") as stop:
            self.c.reset()
        stop.assert_called()


if __name__ == "__main__":
    unittest.main()
