"""Controle de Tamanho do Hub na Bateria e no Timer: anima até o tamanho novo, termina limpo e grava; sem animações do
Windows, vale na hora. Os dois cartões do Hub acompanham o widget."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.screen_metrics import BASELINE_TIMER_SIZE


def _pump(sec: float):
    end = time.time() + sec
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.004)


class _TempConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        path, data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = {}
        self.addCleanup(lambda: (setattr(config_manager, "config_path", path), setattr(config_manager, "_data", data)))


class TimerSizeTests(_TempConfig):
    def _controller(self, animated: bool):
        from app.widgets.timer import timer_controller as tc
        patcher = mock.patch.object(tc, "animations_enabled", return_value=animated)
        patcher.start()
        self.addCleanup(patcher.stop)
        c = tc.TimerWidgetController()
        self.addCleanup(c.skin.close)
        return c

    def test_slider_animates_to_the_new_side_and_saves_it(self):
        c = self._controller(animated=True)
        c.skin.show()
        _pump(0.05)
        start = c.skin.square_side()
        sides = []
        c.scale_applied.connect(lambda s: sides.append(round(s * BASELINE_TIMER_SIZE[0])))
        c.set_scale(1.40)
        target = round(1.40 * BASELINE_TIMER_SIZE[0])
        self.assertNotEqual(c.skin.square_side(), target)            # não pulou
        _pump(1.2)
        self.assertEqual(c.skin.square_side(), target)               # assentou no alvo
        self.assertGreater(len(set(sides)), 3)                       # passou por tamanhos no meio
        self.assertTrue(all(b >= a for a, b in zip(sides, sides[1:])), "o lado voltou durante a animação")
        self.assertGreater(target, start)
        self.assertEqual(config_manager.get_timer_saved_size(), (target, target))
        self.assertFalse(c.is_scale_auto())

    def test_without_animations_the_side_changes_at_once(self):
        c = self._controller(animated=False)
        c.skin.show()
        c.set_scale(0.80)
        self.assertEqual(c.skin.square_side(), round(0.80 * BASELINE_TIMER_SIZE[0]))

    def test_auto_follows_the_screen_and_the_corner_handle_turns_it_off(self):
        from app.core.screen_metrics import get_auto_timer_size
        c = self._controller(animated=False)
        c.set_scale(None)
        self.assertTrue(c.is_scale_auto())
        self.assertEqual(c.skin.square_side(), c._clamp_side(get_auto_timer_size(widget=c.skin)[0]))
        c.skin.size_committed.emit(200)                                # soltou a alça do canto
        self.assertFalse(c.is_scale_auto())

    def test_menu_default_size_goes_through_the_controller(self):
        c = self._controller(animated=False)
        c.set_scale(1.3)
        c.skin._reset_default_size()
        self.assertTrue(c.is_scale_auto())

    def test_a_new_skin_keeps_the_size_and_still_reports_it(self):
        c = self._controller(animated=False)
        c.set_scale(1.2)
        side = c.skin.square_side()
        c.set_skin("windows")
        self.addCleanup(c.skin.close)
        self.assertEqual(c.skin.square_side(), side)
        seen = []
        c.scale_applied.connect(seen.append)
        c.apply_scale_live(1.0)
        self.assertTrue(seen)


class _FakeBatteryService(QObject):
    devices_updated = Signal(list)

    def refresh(self):
        pass

    def notify_change(self, *a, **k):
        pass


class BatterySizeTests(_TempConfig):
    def _controller(self, animated: bool):
        from app.ui_components import floating_card as fc
        from app.widgets.battery.battery_controller import BatteryWidgetController
        patcher = mock.patch.object(fc, "animations_enabled", return_value=animated)
        patcher.start()
        self.addCleanup(patcher.stop)
        c = BatteryWidgetController(service=_FakeBatteryService())
        self.addCleanup(c.skin.close)
        return c

    def test_slider_animates_the_scale_and_saves_it(self):
        c = self._controller(animated=True)
        c.skin.show()
        _pump(0.05)
        widths = []
        c.skin.scale_applied.connect(lambda _s: widths.append(c.skin.width()))
        c.set_scale(1.4)
        self.assertNotAlmostEqual(c.skin.scale(), 1.4, places=2)    # não pulou
        self.assertTrue(c.skin.is_scale_animating())                # o alinhador do anchor espera
        _pump(1.2)
        self.assertAlmostEqual(c.skin.scale(), 1.4, places=2)
        self.assertGreater(len(set(widths)), 3)
        self.assertTrue(all(b >= a for a, b in zip(widths, widths[1:])), "a largura voltou durante a animação")
        self.assertEqual(config_manager.get_battery("scale", None), 1.4)
        self.assertFalse(c.is_scale_auto())

    def test_without_animations_the_scale_changes_at_once_and_keeps_the_shape(self):
        c = self._controller(animated=False)
        shape = c.skin.base_size()
        c.set_scale(0.8)
        self.assertAlmostEqual(c.skin.scale(), 0.8, places=3)
        self.assertEqual(c.skin.base_size(), shape)                 # o formato (canto) é outra coisa

    def test_auto_and_saved_scale_survive_a_restart(self):
        c = self._controller(animated=False)
        c.set_scale(1.25)
        c.skin.close()
        again = self._controller(animated=False)
        self.assertAlmostEqual(again.skin.scale(), 1.25, places=3)
        again.set_scale(None)
        self.assertTrue(config_manager.get_battery("scale_auto", False))

    def test_match_size_hits_the_neighbor_in_screen_pixels_at_any_scale(self):
        """"Igualar" com a bateria fora de 100%: o alvo é em px de tela, o cartão tem de chegar nele exatamente."""
        from app.core.anchor_manager import anchor_manager, card_rect
        c = self._controller(animated=False)
        c.set_scale(0.8)
        anchor_manager().match_widget_size(c.skin, target_w=300.0)
        self.assertAlmostEqual(card_rect(c.skin).w, 300.0, delta=1.0)
        anchor_manager().match_widget_size(c.skin, target_h=210.0)
        self.assertAlmostEqual(card_rect(c.skin).h, 210.0, delta=1.0)
        self.assertAlmostEqual(c.skin.scale(), 0.8, places=3)          # igualar mexe no formato, não na escala


class HubCardsTests(_TempConfig):
    def test_battery_and_timer_pages_have_the_size_card_in_sync(self):
        from app.hub.battery_page import BatteryPage
        from app.hub.timer_page import TimerPage
        for cls, ctrl_attr in ((BatteryPage, "battery_controller"), (TimerPage, "timer_controller")):
            page = cls()
            page.resize(800, 1400)
            page.show()
            _pump(0.1)
            self.assertTrue(page.scale_card.isVisible(), cls.__name__)
            controller = getattr(page.bridge, ctrl_attr)
            with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=False), \
                    mock.patch("app.widgets.timer.timer_controller.animations_enabled", return_value=False):
                controller.set_scale(1.3)
            _pump(0.05)
            self.assertEqual(page.scale_card.slider.value(), 130, cls.__name__)
            page.close()


if __name__ == "__main__":
    unittest.main()
