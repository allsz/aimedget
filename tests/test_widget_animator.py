"""
Testes da animação de surgir/sumir do Music Widget:
- Animador isolado: fade + deslize, reversão no meio, "reduzir animações" do Windows.
- Interações com o controller: posição de repouso (Lembrar posição / troca de skin), estado
  "mostrando" durante a saída, atalho duplo e música retomando no meio da saída.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import app.core.widget_animator as wa
from app.core.config_manager import config_manager
from app.core.widget_animator import SLIDE_PX, SlideFadeAnimator


def wait_until(condition, timeout_ms: int = 2000) -> bool:
    """Espera a condição valer (até `timeout_ms`), processando eventos. Mais robusto que esperar um tempo fixo."""
    waited = 0
    while not condition():
        if waited >= timeout_ms:
            return False
        QTest.qWait(10)
        waited += 10
    return True


def make_widget():
    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.resize(120, 60)
    w.move(200, 150)
    return w


class TestAnimator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._orig = wa.animations_enabled
        wa.animations_enabled = lambda: True

    def tearDown(self):
        wa.animations_enabled = self._orig

    def test_show_starts_invisible_and_displaced_then_settles(self):
        w = make_widget()
        a = SlideFadeAnimator(w)
        a.show(120)
        self.assertTrue(w.isVisible())
        self.assertLess(w.windowOpacity(), 0.2)
        self.assertEqual(w.pos(), QPoint(200, 150 + SLIDE_PX))   # começa abaixo
        self.assertEqual(a.rest_pos(), QPoint(200, 150))          # repouso nunca deslocado
        self.assertTrue(wait_until(lambda: not a.is_animating(), 2000))
        self.assertEqual(w.pos(), QPoint(200, 150))
        self.assertAlmostEqual(w.windowOpacity(), 1.0, places=2)
        w.close()

    def test_hide_ends_hidden_at_rest_position_and_full_opacity(self):
        w = make_widget()
        w.show()
        a = SlideFadeAnimator(w)
        a.hide(100)
        self.assertTrue(w.isVisible())
        self.assertTrue(a.is_hiding())
        self.assertTrue(wait_until(lambda: not w.isVisible(), 2000))
        self.assertEqual(w.pos(), QPoint(200, 150))
        self.assertAlmostEqual(w.windowOpacity(), 1.0, places=2)  # pronto para a próxima exibição
        w.close()

    def test_reverse_mid_hide_returns_to_rest_without_drift(self):
        w = make_widget()
        w.show()
        a = SlideFadeAnimator(w)
        a.hide(200)
        QTest.qWait(70)
        self.assertTrue(a.is_hiding())
        a.show(200)                     # atalho de novo no meio da saída
        self.assertFalse(a.is_hiding())
        QTest.qWait(320)
        self.assertTrue(w.isVisible())
        self.assertEqual(w.pos(), QPoint(200, 150))
        self.assertAlmostEqual(w.windowOpacity(), 1.0, places=2)
        w.close()

    def test_settle_snaps_to_final_state(self):
        w = make_widget()
        w.show()
        a = SlideFadeAnimator(w)
        a.hide(300)
        QTest.qWait(40)
        a.settle()
        self.assertFalse(w.isVisible())
        self.assertEqual(w.pos(), QPoint(200, 150))
        self.assertFalse(a.is_animating())
        w.close()

    def test_reduced_motion_is_instant(self):
        wa.animations_enabled = lambda: False
        w = make_widget()
        a = SlideFadeAnimator(w)
        a.show(200)
        self.assertTrue(w.isVisible())
        self.assertAlmostEqual(w.windowOpacity(), 1.0, places=2)
        self.assertEqual(w.pos(), QPoint(200, 150))
        a.hide(200)
        self.assertFalse(w.isVisible())
        self.assertEqual(w.pos(), QPoint(200, 150))
        w.close()

    def test_blocks_mouse_only_while_animating(self):
        w = make_widget()
        a = SlideFadeAnimator(w)
        a.show(100)
        self.assertTrue(w.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertTrue(wait_until(
            lambda: not w.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), 2000))
        w.close()


class _FakeWorker(QObject):
    media_updated = Signal(str, str, bool, float, float, object, str)
    _last_is_playing = False
    _last_title = ""

    def send_command(self, *a):
        pass


class TestControllerInteractions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._orig = wa.animations_enabled
        wa.animations_enabled = lambda: True
        self._cfg_path = config_manager.config_path
        self._cfg_data = config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()

        from app.widgets.music.music_controller import MusicWidgetController

        self.ctrl = MusicWidgetController(media_worker=_FakeWorker())
        self.ctrl.skin.move(300, 200)

    def tearDown(self):
        self.ctrl.skin.close()
        wa.animations_enabled = self._orig
        config_manager.config_path = self._cfg_path
        config_manager._data = self._cfg_data

    def test_is_shown_false_during_fade_out_even_though_visible(self):
        c = self.ctrl
        c.show()
        QTest.qWait(260)
        self.assertTrue(c.is_shown())
        c.hide()
        self.assertTrue(c.skin.isVisible())     # ainda na tela...
        self.assertFalse(c.is_shown())          # ...mas o controller já a considera saindo
        self.assertTrue(c.is_hiding())
        QTest.qWait(260)
        self.assertFalse(c.skin.isVisible())

    def test_soft_hide_is_slower_than_hotkey_hide(self):
        c = self.ctrl
        c.show()
        QTest.qWait(260)
        c.hide()                                 # atalho: 160 ms
        QTest.qWait(220)
        self.assertFalse(c.skin.isVisible())

        c.show()
        QTest.qWait(260)
        c.hide(soft=True)                        # timeout: 320 ms
        QTest.qWait(200)
        self.assertTrue(c.skin.isVisible())      # ainda saindo aos 200 ms
        QTest.qWait(260)
        self.assertFalse(c.skin.isVisible())

    def test_remember_position_never_records_displaced_point(self):
        c = self.ctrl
        c.show()
        QTest.qWait(260)
        c.skin.move(310, 210)
        c.hide(soft=True)
        QTest.qWait(80)                          # no meio do deslize
        self.assertNotEqual(c.skin.pos(), QPoint(310, 210))
        c.skin._toggle_remember_position(True)   # ex.: clicar no menu aberto durante a saída
        self.assertEqual(config_manager.get_music_saved_position(), (310, 210))

    def test_music_resuming_mid_fade_out_reverses_instead_of_hiding(self):
        c = self.ctrl
        config_manager.set_auto_launch_enabled(True)
        c.show()
        QTest.qWait(260)
        c.hide(soft=True)
        QTest.qWait(80)
        self.assertTrue(c.is_hiding())
        c._handle_auto_launch_lifecycle("Faixa", "Artista", True, 1.0, 100.0, b"", "generic")
        QTest.qWait(400)
        self.assertTrue(c.skin.isVisible())
        self.assertTrue(c.is_shown())
        self.assertEqual(c.skin.pos(), QPoint(300, 200))   # de volta ao repouso, sem deslocamento
        self.assertFalse(c.skin.animator.is_animating())

    def test_double_hotkey_press_reverses(self):
        from app.hub.service_bridge import HubServiceBridge

        c = self.ctrl
        b = QObject()
        b.music_controller = c
        toggle = lambda: HubServiceBridge.toggle_music_widget(b)
        c.show()
        QTest.qWait(260)
        toggle()                                  # começa a sair
        self.assertTrue(c.is_hiding())
        QTest.qWait(50)
        toggle()                                  # aperta de novo: volta
        QTest.qWait(320)
        self.assertTrue(c.is_shown())
        self.assertEqual(c.skin.pos(), QPoint(300, 200))

    def test_skin_swap_during_fade_out_does_not_resurrect_widget(self):
        c = self.ctrl
        c.show()
        QTest.qWait(260)
        c.hide(soft=True)
        QTest.qWait(60)
        c.set_skin("fullcover")                   # troca de skin no meio da saída
        QTest.qWait(400)
        self.assertFalse(c.skin.isVisible())
        self.assertEqual(c.skin.rest_pos(), QPoint(300, 200))


if __name__ == "__main__":
    unittest.main()
