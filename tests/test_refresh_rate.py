"""Intervalo dos timers de animação na taxa do monitor: uma regra só, usada por todos os que animam."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QWidget

from app.core import refresh_rate as rr

app = QApplication.instance() or QApplication(sys.argv)


def _screen(hz):
    screen = mock.Mock()
    screen.refreshRate.return_value = hz
    return screen


class RefreshIntervalTests(unittest.TestCase):
    def test_follows_the_monitor_of_the_widget(self):
        w = QWidget()
        for hz, expected in ((144.0, 7), (120.0, 8), (75.0, 13), (60.0, 17)):
            with mock.patch.object(w, "screen", return_value=_screen(hz)):
                self.assertEqual(rr.refresh_interval_ms(w), expected, hz)

    def test_falls_back_to_60_hz_when_qt_reports_nothing_plausible(self):
        w = QWidget()
        for hz in (0.0, 1.0, 10.0, -5.0):
            with mock.patch.object(w, "screen", return_value=_screen(hz)):
                self.assertEqual(rr.refresh_interval_ms(w), 17, hz)

    def test_caps_absurd_rates(self):
        w = QWidget()
        with mock.patch.object(w, "screen", return_value=_screen(1000.0)):
            self.assertEqual(rr.refresh_interval_ms(w), 4)               # 240 Hz é o teto
        self.assertGreaterEqual(rr.MIN_MS, 1)

    def test_without_a_widget_it_uses_the_primary_screen(self):
        with mock.patch.object(app, "primaryScreen", return_value=_screen(144.0)):
            self.assertEqual(rr.refresh_interval_ms(), 7)
            self.assertEqual(rr.refresh_interval_ms(None), 7)

    def test_without_any_screen_it_still_answers(self):
        w = QWidget()
        with mock.patch.object(w, "screen", return_value=None), \
                mock.patch.object(app, "primaryScreen", return_value=None):
            self.assertEqual(rr.refresh_interval_ms(w), 17)

    def test_every_animation_timer_uses_the_shared_rule(self):
        """Sem cópias: ninguém mais calcula a taxa por conta própria."""
        root = Path(__file__).resolve().parent.parent / "app"
        offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                     if "refreshRate()" in p.read_text(encoding="utf-8") and p.name != "refresh_rate.py"]
        self.assertEqual(offenders, [], "use app.core.refresh_rate.refresh_interval_ms")


if __name__ == "__main__":
    unittest.main()
