"""Trocar de área de trabalho virtual: widgets fixados ficam invisíveis enquanto o Windows desliza (ele não os desenha
nesse tempo) e depois entram do lado da área nova com a mola SLIDE (variação B, "Depois do slide")."""

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

    def test_waits_hidden_during_the_windows_slide_then_enters_from_the_new_side(self):
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            self.card.animator.sweep(1)   # para a direita: a área nova vem da direita
            self.assertTrue(self.card.animator.is_sweeping())
            t0 = time.perf_counter()
            samples = []
            end = t0 + 2.5
            while time.perf_counter() < end and self.card.animator.is_sweeping():
                QCoreApplication.processEvents()
                samples.append(((time.perf_counter() - t0) * 1000, (self.card.pos() - self.rest).x(),
                                self.card.windowOpacity(), self.card.rest_pos()))
                time.sleep(0.004)
        hold = [(x, o) for t, x, o, _ in samples if t < wa.SWEEP_HOLD_MS - 30]
        enter = [(x, o) for t, x, o, _ in samples if t > wa.SWEEP_HOLD_MS + 20]
        # Enquanto o Windows desliza: invisível e parado no ponto de partida (nada a ver, nada gasto à toa)
        self.assertTrue(hold)
        self.assertTrue(all(o == 0.0 and x == wa.SWEEP_PX for x, o in hold))
        # Depois: entra da direita até o lugar, ficando visível (anima, não pula)
        xs = [x for x, _ in enter]
        self.assertGreater(len(set(xs)), 6)
        self.assertTrue(all(0 <= x <= wa.SWEEP_PX for x in xs))                       # só vem da direita, sem passar
        self.assertTrue(all(b <= a for a, b in zip(xs, xs[1:])))                      # anda só num sentido
        ops = [o for _, o in enter]
        self.assertTrue(all(b >= a - 1e-6 for a, b in zip(ops, ops[1:])))             # o fade só cresce
        self.assertTrue(all(r == self.rest for *_, r in samples))   # o repouso nunca muda (nada grava o desvio)
        # termina limpo
        self.assertFalse(self.card.animator.is_sweeping())
        self.assertEqual(self.card.pos(), self.rest)
        self.assertEqual(self.card.windowOpacity(), 1.0)
        self.assertFalse(self.card.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_left_switch_enters_from_the_left(self):
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            self.card.animator.sweep(-1)
            _pump(0.05)
            self.assertEqual((self.card.pos() - self.rest).x(), -wa.SWEEP_PX)
            self.assertEqual(self.card.windowOpacity(), 0.0)
            self._record(2.5)
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

    def test_second_switch_restarts_the_wait_while_hidden(self):
        """Outra troca no meio da entrada: o Windows volta a esconder o widget, então ele recomeça invisível."""
        with mock.patch.object(wa, "animations_enabled", return_value=True):
            self.card.animator.sweep(1)
            _pump(wa.SWEEP_HOLD_MS / 1000.0 + 0.06)
            self.assertGreater(self.card.windowOpacity(), 0.0)   # já entrando
            self.card.animator.sweep(-1)
            self.assertEqual(self.card.windowOpacity(), 0.0)     # o salto de lado acontece invisível
            self.assertEqual((self.card.pos() - self.rest).x(), -wa.SWEEP_PX)
            self._record(2.5)
        self.assertEqual(self.card.pos(), self.rest)
        self.assertEqual(self.card.windowOpacity(), 1.0)

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
            _pump(wa.SWEEP_HOLD_MS / 1000.0 + 1.0)
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
