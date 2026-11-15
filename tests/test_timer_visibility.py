"""O timer surge e some animado, com a mesma lógica (mixins) do widget de música."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from app.core import widget_animator as wa
from app.core.config_manager import config_manager
from app.widgets.timer.timer_controller import TimerWidgetController
from app.widgets.music.music_controller import MusicWidgetController


class SharedLogicTests(unittest.TestCase):
    def test_both_controllers_use_the_same_visibility_mixin_and_timings(self):
        for cls in (MusicWidgetController, TimerWidgetController):
            self.assertTrue(issubclass(cls, wa.AnimatedVisibilityMixin), cls)
        self.assertIs(TimerWidgetController.APPEAR_MS, wa.AnimatedVisibilityMixin.APPEAR_MS)
        self.assertEqual(MusicWidgetController.APPEAR_MS, TimerWidgetController.APPEAR_MS)
        self.assertEqual(MusicWidgetController.HIDE_MS, TimerWidgetController.HIDE_MS)
        # o código próprio da música foi removido: as consultas vêm do mixin
        for name in ("_is_shown", "is_shown", "is_hiding", "settle"):
            self.assertNotIn(name, vars(MusicWidgetController), name)
            self.assertNotIn(name, vars(TimerWidgetController), name)

    def test_both_skins_share_the_rest_position_logic(self):
        from app.widgets.music.skins.base_skin import BaseMusicSkin
        from app.widgets.timer.skins.base_skin import BaseTimerSkin
        for cls in (BaseMusicSkin, BaseTimerSkin):
            self.assertTrue(issubclass(cls, wa.AnimatedSkinMixin), cls)
            self.assertNotIn("rest_pos", vars(cls))


class TimerVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        patcher = mock.patch.object(wa, "animations_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._cfg_path, self._cfg_data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = {}
        self.addCleanup(lambda: (setattr(config_manager, "config_path", self._cfg_path),
                                 setattr(config_manager, "_data", self._cfg_data)))
        self.c = TimerWidgetController()
        self.statuses = []
        self.c.status_changed.connect(self.statuses.append)
        self.skin = self.c.skin
        self.addCleanup(self.skin.close)

    def test_enabling_the_timer_fades_and_slides_it_in(self):
        self.assertFalse(self.skin.isVisible())
        self.c.show()
        self.assertTrue(self.skin.isVisible())
        self.assertTrue(self.skin.animator.is_animating())
        self.assertLess(self.skin.windowOpacity(), 0.5)               # começa transparente...
        rest = self.skin.rest_pos()
        self.assertNotEqual(self.skin.pos(), rest)                    # ...e deslocado
        self.c.settle()
        self.assertEqual(self.skin.windowOpacity(), 1.0)
        self.assertEqual(self.skin.pos(), rest)                       # termina exatamente na posição de repouso
        self.assertEqual(self.statuses, [True])

    def test_disabling_the_timer_fades_it_out_before_hiding(self):
        self.c.show()
        self.c.settle()
        self.c.hide()
        self.assertTrue(self.skin.isVisible(), "ainda na tela durante o fade-out")
        self.assertTrue(self.c.is_hiding())
        self.assertFalse(self.c.is_shown(), "saindo conta como escondido (o atalho o traz de volta)")
        self.assertEqual(self.statuses, [True, False])                # o estado muda na hora, como antes
        self.c.settle()
        self.assertFalse(self.skin.isVisible())
        self.assertEqual(self.skin.windowOpacity(), 1.0)              # pronto para a próxima exibição

    def test_showing_again_mid_fade_out_reverses_without_repositioning(self):
        self.c.show()
        self.c.settle()
        self.c.hide()
        anim = self.skin.animator._anim
        anim.setCurrentTime(anim.duration() // 2)                     # meio do fade-out
        with mock.patch.object(self.c, "restore_or_place_at_top") as place:
            self.c.show()
            place.assert_not_called()                                 # no meio da animação a janela já está no lugar
        self.assertTrue(self.skin.animator.is_animating())
        self.assertFalse(self.c.is_hiding())
        self.c.settle()
        self.assertTrue(self.skin.isVisible())

    def test_enabling_from_hidden_still_repositions_first(self):
        with mock.patch.object(self.c, "restore_or_place_at_top") as place:
            self.c.show()
            place.assert_called_once()

    def test_saved_position_ignores_the_slide_offset(self):
        """Regressão (música): nada grava o ponto deslocado da animação."""
        self.c.show()
        self.c.settle()
        self.skin.move(300, 200)
        self.skin.animator.hide(0)                                    # sem duração: conclui
        self.c.show()                                                 # reaparece
        mid = self.skin.animator
        self.assertTrue(mid.is_animating())
        origin = self.skin.square_origin()
        self.assertEqual(origin, self.skin.rest_pos() + QPoint(self.skin.art_margin, self.skin.art_margin))
        self.assertNotEqual(origin, self.skin.pos() + QPoint(self.skin.art_margin, self.skin.art_margin))
        self.c.settle()

    def test_without_windows_animations_it_is_instant(self):
        with mock.patch.object(wa, "animations_enabled", return_value=False):
            self.c.show()
            self.assertTrue(self.skin.isVisible())
            self.assertFalse(self.skin.animator.is_animating())
            self.assertEqual(self.skin.windowOpacity(), 1.0)
            self.c.hide()
            self.assertFalse(self.skin.isVisible())

    def test_skin_switch_while_fading_out_does_not_bring_it_back(self):
        self.c.show()
        self.c.settle()
        self.c.hide()                                                 # fade-out em curso
        self.c.set_skin("windows")
        self.assertFalse(self.c.skin.isVisible())
        self.skin = self.c.skin
        self.addCleanup(self.skin.close)

    def test_hub_toggle_uses_is_shown(self):
        from app.hub import service_bridge
        src = Path(service_bridge.__file__).read_text(encoding="utf-8")
        self.assertIn("self.timer_controller.is_shown()", src)


if __name__ == "__main__":
    unittest.main()
