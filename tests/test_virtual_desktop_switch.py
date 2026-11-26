"""Trocar de área de trabalho virtual: widgets fixados saem com os apps e voltam do lado oposto (variação B)."""

import sys
import time
import unittest
import uuid
from unittest import mock

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QWidget

from app.core import widget_animator as wa
from app.core.config_manager import config_manager
from app.core.virtual_desktop_watcher import switch_direction, virtual_desktop_watcher

_app = QApplication.instance() or QApplication(sys.argv)

A, B, C = (uuid.uuid4().bytes for _ in range(3))


def _pump(sec: float):
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        QCoreApplication.processEvents()
        time.sleep(0.004)


class SwitchDirectionTests(unittest.TestCase):
    def test_right_and_left(self):
        ids = [A, B, C]
        self.assertEqual(switch_direction((A, ids), (B, ids)), 1)
        self.assertEqual(switch_direction((C, ids), (A, ids)), -1)

    def test_no_switch(self):
        ids = [A, B]
        self.assertEqual(switch_direction((A, ids), (A, ids)), 0)
        self.assertEqual(switch_direction((A, ids), (A, [A, B, C])), 0)   # criou uma área sem ir para ela
        self.assertEqual(switch_direction(None, (A, ids)), 0)
        self.assertEqual(switch_direction((A, ids), None), 0)

    def test_new_desktop_is_to_the_right(self):
        self.assertEqual(switch_direction((A, [A, B]), (C, [A, B, C])), 1)   # Ctrl+Win+D

    def test_deleted_desktop(self):
        # apagou a do meio: o Windows vai para a da esquerda
        self.assertEqual(switch_direction((B, [A, B, C]), (A, [A, C])), -1)
        # apagou a primeira: a da direita assume a mesma posição
        self.assertEqual(switch_direction((A, [A, B, C]), (B, [B, C])), 1)


class _Card(wa.AnimatedSkinMixin, QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setGeometry(300, 300, 120, 80)
        self._init_animator()


class SweepMotionTests(unittest.TestCase):
    def setUp(self):
        self.card = _Card()
        self.card.show()
        _pump(0.05)
        self.rest = self.card.pos()

    def tearDown(self):
        self.card.animator.settle()
        self.card.close()
        self.card.deleteLater()
        QCoreApplication.processEvents()

    def _record(self, max_sec=2.0):
        samples = []
        end = time.perf_counter() + max_sec
        while time.perf_counter() < end and self.card.animator.is_sweeping():
            QCoreApplication.processEvents()
            samples.append(((self.card.pos() - self.rest).x(), self.card.windowOpacity(),
                            self.card.rest_pos()))
            time.sleep(0.004)
        return samples

    def test_slides_out_with_the_apps_and_back_from_the_other_side(self):
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            self.card.animator.sweep(1)   # para a direita: os apps saem pela esquerda
            self.assertTrue(self.card.animator.is_sweeping())
            samples = self._record()
        xs = [x for x, _, _ in samples]
        self.assertGreater(len(set(xs)), 6)                       # anima (não pula)
        self.assertLessEqual(min(xs), -wa.SWEEP_PX + 2)           # saiu pela esquerda
        self.assertGreater(max(xs), wa.SWEEP_PX // 2)              # voltou pela direita
        self.assertLess(xs.index(min(xs)), xs.index(max(xs)))     # primeiro sai, depois volta
        self.assertLess(min(o for _, o, _ in samples), 0.2)       # some no meio
        self.assertTrue(all(r == self.rest for _, _, r in samples))   # o repouso nunca muda (nada grava o desvio)
        # termina limpo
        self.assertFalse(self.card.animator.is_sweeping())
        self.assertEqual(self.card.pos(), self.rest)
        self.assertEqual(self.card.windowOpacity(), 1.0)
        self.assertFalse(self.card.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_left_switch_mirrors(self):
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            self.card.animator.sweep(-1)
            xs = [x for x, _, _ in self._record()]
        self.assertGreaterEqual(max(xs[:5] + [0]), 0)
        self.assertGreater(max(xs[: len(xs) // 3]), wa.SWEEP_PX // 2)   # sai pela direita
        self.assertEqual(self.card.pos(), self.rest)

    def test_without_windows_animations_nothing_moves(self):
        with mock.patch.object(wa, "animations_enabled", return_value=False):
            self.card.animator.sweep(1)
        self.assertFalse(self.card.animator.is_sweeping())
        self.assertEqual(self.card.pos(), self.rest)
        self.assertEqual(self.card.windowOpacity(), 1.0)

    def test_settle_mid_way_lands_at_rest(self):
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            self.card.animator.sweep(1)
            _pump(0.08)
            self.assertNotEqual(self.card.pos(), self.rest)
            self.card.animator.settle()
        self.assertFalse(self.card.animator.is_sweeping())
        self.assertEqual(self.card.pos(), self.rest)
        self.assertEqual(self.card.windowOpacity(), 1.0)

    def test_second_switch_mid_way_continues_without_jump(self):
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            self.card.animator.sweep(1)
            _pump(0.06)
            before = self.card.pos().x()
            self.card.animator.sweep(1)
            self.assertLessEqual(abs(self.card.pos().x() - before), 3)
            self._record()
        self.assertEqual(self.card.pos(), self.rest)

    def test_hide_mid_way_hides_from_rest(self):
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            self.card.animator.sweep(1)
            _pump(0.05)
            self.card.animator.hide(0)
        self.assertFalse(self.card.animator.is_sweeping())
        self.assertFalse(self.card.isVisible())
        self.assertEqual(self.card.pos(), self.rest)


@unittest.skipUnless(sys.platform == "win32", "áreas de trabalho virtuais são do Windows")
class PinnedWidgetFollowsSwitchTests(unittest.TestCase):
    def setUp(self):
        from app.core import desktop_layer
        if not desktop_layer.desktop_host():
            self.skipTest("sem janela de desktop (sessão sem Explorer)")
        self._saved = dict(config_manager._data.get("weather_widget", {}))
        self._orig_save = config_manager._save
        config_manager._save = lambda *a, **k: None
        config_manager._data["weather_widget"] = {"desktop_mode": True}
        from app.widgets.weather.weather_card import WeatherCard
        self.card = WeatherCard(desktop_mode=True)

    def tearDown(self):
        self.card.animator.settle()
        self.card.close()
        self.card.deleteLater()
        QCoreApplication.processEvents()
        config_manager._data["weather_widget"] = self._saved
        config_manager._save = self._orig_save

    def test_pinned_card_sweeps_on_switch_and_stops_listening_when_hidden(self):
        watcher = virtual_desktop_watcher()
        users = watcher._users
        self.card.show()
        _pump(0.2)
        self.assertEqual(watcher._users, users + 1)
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            watcher.switched.emit(1)
            self.assertTrue(self.card.animator.is_sweeping())
            _pump(1.0)
        self.assertFalse(self.card.animator.is_sweeping())
        self.card.hide()
        self.assertEqual(watcher._users, users)

    def test_floating_card_does_not_follow(self):
        """Sem fixar, o widget não está em todas as áreas: não há o que acompanhar."""
        watcher = virtual_desktop_watcher()
        users = watcher._users
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=False):
            self.card.set_desktop_mode(False)
        self.card.show()
        _pump(0.2)
        self.assertEqual(watcher._users, users)
        watcher.switched.emit(1)
        self.assertFalse(self.card.animator.is_sweeping())


@unittest.skipUnless(sys.platform == "win32", "registro do Windows")
class WatcherThreadTests(unittest.TestCase):
    def test_starts_and_stops_with_its_users(self):
        from app.core.virtual_desktop_watcher import VirtualDesktopWatcher, read_state
        if read_state() is None:
            self.skipTest("sem áreas de trabalho virtuais no registro")
        w = VirtualDesktopWatcher()
        w.acquire()
        w.acquire()
        self.assertTrue(w.is_running())
        w.release()
        self.assertTrue(w.is_running())
        w.release()
        self.assertFalse(w.is_running())


if __name__ == "__main__":
    unittest.main()
