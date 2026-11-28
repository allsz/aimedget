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


_ACTIVATE = desktop_layer.SWP_NOMOVE | desktop_layer.SWP_NOSIZE           # clique no widget (0x3 no log)
_CARRY = _ACTIVATE | desktop_layer.SWP_NOACTIVATE                           # levado com o grupo do dono (0x13)


def _pos(insert_after, flags=_CARRY):
    pos = desktop_layer.WINDOWPOS()
    pos.hwndInsertAfter = insert_after
    pos.flags = flags
    return pos


class WindowPosHookTests(unittest.TestCase):
    """O gancho de WM_WINDOWPOSCHANGING barra subidas, mas não briga com o Windows levando o cartão com o dono."""

    def _run(self, pos, owned: bool, over_app: bool = False):
        with mock.patch.object(desktop_layer, "IS_WINDOWS", True), \
                mock.patch.object(desktop_layer, "desktop_host", return_value=_FAKE_HOST), \
                mock.patch.object(desktop_layer, "owner_of", return_value=_FAKE_HOST if owned else 0), \
                mock.patch.object(desktop_layer, "_lands_over_an_app", return_value=over_app), \
                mock.patch.object(desktop_layer, "insert_after_for", return_value=_REWRITTEN):
            desktop_layer.on_window_pos_changing(ctypes.addressof(pos), 0x4000)
        return pos.hwndInsertAfter or 0

    def test_click_raise_to_a_specific_window_over_apps_is_rewritten(self):
        """Clique num widget: "logo abaixo da última sempre-no-topo", por cima dos apps. Não pode passar."""
        self.assertEqual(self._run(_pos(_SOME_WINDOW), owned=True, over_app=True), _REWRITTEN)

    def test_activation_is_rewritten_even_when_the_neighbor_looks_harmless(self):
        """
        Medido no log: clicar num widget pede "logo abaixo da Default IME do app", que AGORA está colada no desktop,
        mas sobe junto com a janela ativada no mesmo lote. Ativação (sem SWP_NOACTIVATE) sempre é reescrita.
        """
        pos = _pos(_SOME_WINDOW, flags=_ACTIVATE)
        self.assertEqual(self._run(pos, owned=True, over_app=False), _REWRITTEN)

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


class LandsOverAnAppTests(unittest.TestCase):
    """Descer a pilha a partir da vizinha pedida até o desktop: alguma janela de verdade no caminho?"""

    def _run(self, stack, covering, insert_after, own=0x4000):
        below = dict(zip(stack, stack[1:]))   # stack: de cima para baixo

        def get_window(hwnd, cmd):
            self.assertEqual(cmd, desktop_layer.GW_HWNDNEXT)
            return below.get(hwnd, 0)

        user32 = mock.Mock()
        user32.GetWindow.side_effect = get_window
        with mock.patch.object(desktop_layer, "_user32", user32), \
                mock.patch.object(desktop_layer, "desktop_host", return_value=_FAKE_HOST), \
                mock.patch.object(desktop_layer, "_covers", side_effect=lambda w: w in covering):
            return desktop_layer._lands_over_an_app(insert_after, own)

    def test_below_the_last_topmost_window_is_over_the_apps(self):
        stack = [0x10, 0x20, 0x4000, _FAKE_HOST]   # 0x10: sempre-no-topo oculta, 0x20: o chat
        self.assertTrue(self._run(stack, {0x20}, 0x10))

    def test_next_to_the_desktop_is_not(self):
        stack = [0x20, 0x30, 0x4000, _FAKE_HOST]   # 0x30: a "Default IME" do Explorer (invisível)
        self.assertFalse(self._run(stack, {0x20}, 0x30))

    def test_below_another_pinned_widget_is_not(self):
        stack = [0x20, 0x5000, 0x4000, _FAKE_HOST]   # 0x5000: outro widget fixado (janela-ferramenta)
        self.assertFalse(self._run(stack, {0x20}, 0x5000))

    def test_desktop_mid_move_is_left_alone(self):
        """A vizinha está abaixo do desktop (ele está subindo): não dá para julgar, deixa passar como antes."""
        stack = [0x20, _FAKE_HOST, 0x30, 0x40]
        self.assertFalse(self._run(stack, {0x20, 0x40}, 0x30))


class WindowPosChangedTests(unittest.TestCase):
    """Depois de o Windows aplicar a mudança: widget que ficou por cima de um app volta ao desktop na hora."""

    def _run(self, pos, escaped: bool):
        with mock.patch.object(desktop_layer, "IS_WINDOWS", True), \
                mock.patch.object(desktop_layer, "needs_replace", return_value=escaped) as needs, \
                mock.patch.object(desktop_layer, "send_to_desktop_layer") as send:
            fixed = desktop_layer.on_window_pos_changed(ctypes.addressof(pos), 0x4000)
        return fixed, needs, send

    def test_group_raised_over_an_app_is_sent_back(self):
        fixed, _needs, send = self._run(_pos(_SOME_WINDOW), escaped=True)
        self.assertTrue(fixed)
        send.assert_called_once_with(0x4000)

    def test_carried_with_the_desktop_is_left_alone(self):
        """Win+D: desktop e widgets sobem juntos, nada de verdade no meio. Não mexe (era a piscada antiga)."""
        fixed, _needs, send = self._run(_pos(_SOME_WINDOW), escaped=False)
        self.assertFalse(fixed)
        send.assert_not_called()

    def test_moves_without_zorder_skip_the_stack_walk(self):
        """Arrastar e animar (SWP_NOZORDER) não pagam o passeio pela pilha de janelas."""
        fixed, needs, send = self._run(_pos(0, flags=desktop_layer.SWP_NOZORDER), escaped=True)
        self.assertFalse(fixed)
        needs.assert_not_called()
        send.assert_not_called()

    def test_own_correction_does_not_recurse(self):
        pos = _pos(_SOME_WINDOW)

        def send_again(hwnd):   # a correção gera outro WM_WINDOWPOSCHANGED para a mesma janela
            self.assertFalse(desktop_layer.on_window_pos_changed(ctypes.addressof(pos), hwnd))

        with mock.patch.object(desktop_layer, "IS_WINDOWS", True), \
                mock.patch.object(desktop_layer, "needs_replace", return_value=True), \
                mock.patch.object(desktop_layer, "send_to_desktop_layer", side_effect=send_again) as send:
            self.assertTrue(desktop_layer.on_window_pos_changed(ctypes.addressof(pos), 0x4000))
        send.assert_called_once()
        self.assertEqual(desktop_layer._correcting, set())


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

    def test_group_raise_over_an_app_is_undone_in_the_same_call(self):
        """
        Clicar num widget sobe o grupo do dono com vizinhas específicas ("logo abaixo da última sempre-no-topo",
        depois "logo abaixo do clicado"), e todos passavam por cima dos apps até o guarda os devolver (1 a 2
        quadros). Agora o pedido é reescrito antes de acontecer.
        """
        from PySide6.QtWidgets import QWidget

        self.card.show()
        self._pump(0.2)
        app_window = QWidget()   # um "app" comum, de primeiro nível, por cima do desktop
        app_window.setGeometry(self.card.geometry())
        app_window.show()
        app_window.raise_()
        self._pump(0.2)
        try:
            app_hwnd = int(app_window.winId())
            self.assertTrue(desktop_layer.z_order_above_desktop(self._hwnd()))
            above_app = desktop_layer._user32.GetWindow(app_hwnd, desktop_layer.GW_HWNDPREV) or 0
            if not above_app:
                self.skipTest("o app de teste ficou no topo da pilha: não há vizinha específica acima dele")
            guard_before = self.card.pin_guard().replacements
            fixed_before = desktop_layer.escapes_fixed
            # O que o Windows faz com os outros membros do grupo: "logo abaixo desta janela", acima do app.
            desktop_layer._user32.SetWindowPos(self._hwnd(), above_app, 0, 0, 0, 0,
                                               desktop_layer.SWP_NOMOVE | desktop_layer.SWP_NOSIZE
                                               | desktop_layer.SWP_NOACTIVATE)
            # Sem processEvents: a correção tem de ter acontecido dentro do SetWindowPos.
            self.assertTrue(desktop_layer.z_order_above_desktop(self._hwnd()))
            self.assertFalse(desktop_layer.needs_replace(self._hwnd()))
            self.assertEqual(self.card.pin_guard().replacements, guard_before)
            # Barrado antes de acontecer (WM_WINDOWPOSCHANGING), não desfeito depois: nenhum quadro por cima.
            self.assertEqual(desktop_layer.escapes_fixed, fixed_before)
        finally:
            app_window.close()
            app_window.deleteLater()


if __name__ == "__main__":
    unittest.main()
