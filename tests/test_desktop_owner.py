"""
Cartão fixado tem o desktop como janela dona: quando o Windows sobe o desktop (clique nele, "Atualizar", Win+D), leva
o cartão junto na mesma operação, sem o quadro em que o cartão ficava atrás do desktop (piscada).
"""

import ctypes
import sys
import time
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app.core import desktop_layer
from app.core.config_manager import config_manager

_FAKE_HOST = 0x1000
_SOME_WINDOW = 0x2000      # vizinha específica escolhida pelo Windows ao mover o grupo do dono
_REWRITTEN = 0x3000        # o que insert_after_for devolveria


def _pos(insert_after, flags=desktop_layer.SWP_NOMOVE | desktop_layer.SWP_NOSIZE):
    pos = desktop_layer.WINDOWPOS()
    pos.hwndInsertAfter = insert_after
    pos.flags = flags
    return pos


class WindowPosHookTests(unittest.TestCase):
    """O gancho de WM_WINDOWPOSCHANGING barra subidas, mas não briga com o Windows levando o cartão com o dono."""

    def _run(self, pos, owned: bool):
        with mock.patch.object(desktop_layer, "IS_WINDOWS", True), \
                mock.patch.object(desktop_layer, "desktop_host", return_value=_FAKE_HOST), \
                mock.patch.object(desktop_layer, "owner_of", return_value=_FAKE_HOST if owned else 0), \
                mock.patch.object(desktop_layer, "insert_after_for", return_value=_REWRITTEN):
            desktop_layer.on_window_pos_changing(ctypes.addressof(pos), 0x4000)
        return pos.hwndInsertAfter or 0

    def test_raise_to_top_is_sent_back_to_the_desktop_level(self):
        for owned in (True, False):
            self.assertEqual(self._run(_pos(desktop_layer.HWND_TOP), owned), _REWRITTEN)

    def test_topmost_and_bottom_requests_are_rewritten(self):
        for value in (desktop_layer.HWND_BOTTOM, desktop_layer.HWND_TOPMOST, desktop_layer.HWND_NOTOPMOST):
            self.assertEqual(self._run(_pos(value), owned=True), _REWRITTEN)

    def test_owned_card_follows_the_desktop_untouched(self):
        self.assertEqual(self._run(_pos(_SOME_WINDOW), owned=True), _SOME_WINDOW)

    def test_card_without_desktop_owner_keeps_the_old_rule(self):
        self.assertEqual(self._run(_pos(_SOME_WINDOW), owned=False), _REWRITTEN)

    def test_no_zorder_change_is_left_alone(self):
        pos = _pos(desktop_layer.HWND_TOP, flags=desktop_layer.SWP_NOZORDER)
        self.assertEqual(self._run(pos, owned=False), 0)


@unittest.skipUnless(sys.platform == "win32", "janela dona é do Windows")
class DesktopOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.host = desktop_layer.desktop_host()
        if not self.host:
            self.skipTest("sem janela de desktop (sessão sem Explorer)")
        self._saved = dict(config_manager._data.get("weather_widget", {}))
        self._orig_save = config_manager._save
        config_manager._save = lambda *a, **k: None
        config_manager._data["weather_widget"] = {"desktop_mode": True}
        from app.widgets.weather.weather_card import WeatherCard
        self.card = WeatherCard(desktop_mode=True)

    def tearDown(self):
        self.card.close()
        self.card.deleteLater()
        QCoreApplication.processEvents()
        config_manager._data["weather_widget"] = self._saved
        config_manager._save = self._orig_save

    def _pump(self, sec=0.3):
        end = time.time() + sec
        while time.time() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)

    def _hwnd(self):
        return int(self.card.winId())

    def test_pinned_card_is_owned_by_the_desktop(self):
        self.card.show()
        self._pump(0.2)
        self.assertEqual(desktop_layer.owner_of(self._hwnd()), self.host)
        self.assertTrue(desktop_layer.z_order_above_desktop(self._hwnd()))

    def test_unpinning_drops_the_owner_and_pinning_restores_it(self):
        self.card.show()
        self._pump(0.2)
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=False):
            self.card.set_desktop_mode(False)
            self._pump(0.1)
            self.assertEqual(desktop_layer.owner_of(self._hwnd()), 0)
            ex = desktop_layer._user32.GetWindowLongW(self._hwnd(), desktop_layer.GWL_EXSTYLE)
            self.assertTrue(ex & desktop_layer.WS_EX_TOPMOST)

            self.card.set_desktop_mode(True)
            self._pump(0.1)
            self.assertEqual(desktop_layer.owner_of(self._hwnd()), self.host)
            self.assertTrue(desktop_layer.z_order_above_desktop(self._hwnd()))

    def test_guard_takes_the_desktop_again_when_the_owner_is_lost(self):
        """Explorer reiniciado: o vínculo some, e o guarda refaz com o desktop atual."""
        self.card.show()
        self._pump(0.2)
        desktop_layer.set_owner(self._hwnd(), 0)
        self.assertEqual(desktop_layer.owner_of(self._hwnd()), 0)
        self.card.pin_guard().check()
        self.assertEqual(desktop_layer.owner_of(self._hwnd()), self.host)
        self.assertTrue(desktop_layer.z_order_above_desktop(self._hwnd()))


if __name__ == "__main__":
    unittest.main()
