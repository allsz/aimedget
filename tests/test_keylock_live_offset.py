"""
Distância da borda ao vivo: ao arrastar o slider do Hub o flyout do Caps Lock aparece, segue o valor quadro a quadro
(sem gravar em disco) e sai quando o slider assenta. Protótipo: mockups/keylock-live-offset.html.
  python tests/test_keylock_live_offset.py
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from app.core.config_manager import config_manager
from app.core.typography import init_app_font
from app.hub.theme import THEME_DARK
from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout

init_app_font()


def pump_until(cond, timeout_s=2.0):
    end = time.perf_counter() + timeout_s
    while time.perf_counter() < end and not cond():
        _app.processEvents()
        time.sleep(0.004)
    return cond()


class FlyoutLiveAdjustTests(unittest.TestCase):
    def setUp(self):
        self.fly = KeyLockFlyout()
        self.fly.set_anchor("bc", force=True)
        self.addCleanup(self._close)

    def _close(self):
        self.fly._hide_timer.stop()
        self.fly._anim_timer.stop()
        self.fly.hide()
        self.fly.deleteLater()

    def test_begin_shows_and_stays_past_the_hold_time(self):
        self.assertFalse(self.fly.isVisible())
        self.fly.begin_live_adjust()
        self.assertTrue(self.fly.isVisible())
        self.assertTrue(self.fly.is_presenting())
        self.assertFalse(self.fly._hide_timer.isActive())        # sem prazo para sumir enquanto arrasta
        # uma tecla de verdade no meio do arraste não religa o prazo
        self.fly.show_osd("Num Lock", True)
        self.assertFalse(self.fly._hide_timer.isActive())

    def test_preview_moves_at_once_by_the_offset_without_saving(self):
        self.fly.begin_live_adjust()
        self.fly.preview_edge_offset(0)
        y0 = self.fly.y()
        with mock.patch.object(config_manager, "set_keylock_edge_offset") as save:
            for v in (10.4, 25.0, 40.0):
                self.fly.preview_edge_offset(v)
                # na hora, sem a suavização do _on_tick (±1 px: o Y base pode cair em meio pixel)
                self.assertLessEqual(abs((y0 - self.fly.y()) - v), 1.0)
            save.assert_not_called()
        self.assertEqual(self.fly.edge_offset(), 40.0)

    def test_preview_clamps_and_skips_moves_within_the_same_pixel(self):
        self.fly.begin_live_adjust()
        self.fly.preview_edge_offset(999)
        self.assertEqual(self.fly.edge_offset(), 120.0)
        self.fly.preview_edge_offset(30.0)
        with mock.patch.object(self.fly, "move") as move:
            self.fly.preview_edge_offset(30.2)                   # mesmo pixel: nenhum move()
            move.assert_not_called()
            self.fly.preview_edge_offset(33.0)
            move.assert_called_once()

    def test_preview_while_hidden_only_stores_the_value(self):
        with mock.patch.object(self.fly, "move") as move:
            self.fly.preview_edge_offset(50)
            move.assert_not_called()
        self.assertEqual(self.fly.edge_offset(), 50.0)
        self.assertFalse(self.fly.isVisible())

    def test_end_fades_out_with_motion_and_finishes_hidden(self):
        self.fly.begin_live_adjust()
        self.assertTrue(pump_until(lambda: self.fly._popup_progress >= 1.0))
        self.fly.end_live_adjust()
        self.assertFalse(self.fly.is_live_adjusting())
        self.assertTrue(self.fly.isVisible())                    # não some no corte
        seen = []
        self.assertTrue(pump_until(lambda: seen.append(self.fly._popup_progress) or not self.fly.isVisible()))
        self.assertTrue(any(0.0 < p < 1.0 for p in seen))        # passou por quadros intermediários
        self.assertFalse(self.fly._anim_timer.isActive())        # terminou limpo

    def test_end_without_begin_does_nothing(self):
        self.fly.end_live_adjust()
        self.assertFalse(self.fly.isVisible())


class PageWiringTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = config_manager.config_path
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")
        from app.hub.pages import LockKeysPage
        self.page = LockKeysPage(theme=THEME_DARK)
        self.bridge = self.page.bridge = mock.Mock()
        self.slider = self.page.offset_slider

    def tearDown(self):
        self.page.deleteLater()
        config_manager.config_path = self._old_path
        self._tmp.cleanup()

    def test_drag_begins_once_previews_every_frame_and_ends_on_commit(self):
        for v in (3.2, 7.9, 12.5):
            self.slider.live_value_changed.emit(v)
        self.bridge.begin_keylock_live_offset.assert_called_once()
        self.assertEqual([c.args[0] for c in self.bridge.preview_keylock_edge_offset.call_args_list], [3.2, 7.9, 12.5])
        self.slider.value_changed.emit(13)                       # inteiro emitido no meio do arraste: ignorado
        self.bridge.set_keylock_edge_offset.assert_not_called()
        self.bridge.trigger_test_keylock.assert_not_called()

        self.slider.interaction_finished.emit()
        self.bridge.set_keylock_edge_offset.assert_called_once()   # grava uma só vez
        self.bridge.end_keylock_live_offset.assert_called_once()
        self.bridge.trigger_test_keylock.assert_not_called()       # sai, não reaparece

        self.slider.live_value_changed.emit(20.0)                # um novo arraste recomeça a sessão
        self.assertEqual(self.bridge.begin_keylock_live_offset.call_count, 2)

    def test_keyboard_step_saves_and_shows_like_before(self):
        self.slider.value_changed.emit(30)
        self.bridge.set_keylock_edge_offset.assert_called_once_with(30)
        self.bridge.trigger_test_keylock.assert_called_once()
        self.bridge.begin_keylock_live_offset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
