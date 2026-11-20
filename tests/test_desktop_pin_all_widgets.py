"""Música e Timer também podem ficar na área de trabalho, e um grupo ancorado fica sempre numa camada só."""

import unittest
from unittest import mock

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core import anchor_manager as am
from app.core.config_manager import config_manager
from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin

_app = QApplication.instance() or QApplication([])


def _music():
    skin = CapaEmpilhadaSkin(scale=0.5)
    skin.timer.stop()
    return skin


class DesktopPinTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(config_manager, "get_widget_desktop_mode", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _check_widget(self, make, place):
        w = make()
        self.addCleanup(w.close)
        place(w)
        w.show()
        _app.processEvents()
        self.assertFalse(w.is_desktop_mode())

        # sem animações: troca na hora
        with mock.patch("app.core.desktop_pin.animations_enabled", return_value=False):
            w.set_desktop_mode(True)
        self.assertTrue(w.is_desktop_mode())
        self.assertIsNone(w.wave_progress())

        # com animações: a onda atravessa o cartão e a troca acontece no meio dela, não no clique
        with mock.patch("app.core.desktop_pin.animations_enabled", return_value=True):
            w.set_desktop_mode(False)
            self.assertTrue(w.is_desktop_mode())                # ainda não trocou
            self.assertFalse(w.desktop_mode_target())           # mas já vai para "por cima"
            seen = []
            for _ in range(60):
                QTest.qWait(20)
                p = w.wave_progress()
                if p is None:
                    break
                seen.append(p)
            self.assertGreater(len(seen), 5)                    # anima (não pula)
            self.assertIsNone(w.wave_progress())                # termina limpo
            self.assertFalse(w.is_desktop_mode())
            self.assertFalse(w._pin_wave.isVisible())

            # escondido no meio da onda: a troca vale na hora
            w.set_desktop_mode(True)
            w.hide()
            self.assertTrue(w.is_desktop_mode())
            self.assertIsNone(w.wave_progress())

    def test_music_can_pin_to_the_desktop(self):
        self._check_widget(_music, lambda w: w.move_card_to(300, 300))

    def test_timer_can_pin_to_the_desktop(self):
        self._check_widget(WindowsTimerSkin, lambda w: w.move_square_to(300, 300))


class GroupLayerTests(unittest.TestCase):
    def setUp(self):
        store = {}
        for target, attr, value in (
            (config_manager, "get_anchor", lambda k, d=None: store.get(k, d)),
            (config_manager, "set_anchor", lambda k, v: store.__setitem__(k, v)),
            (config_manager, "get_widget_desktop_mode", lambda section: False),
            (am, "animations_enabled", lambda: False),
            (am, "_manager", None),
        ):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)

    def test_music_joins_a_pinned_weather_on_the_desktop(self):
        from app.widgets.weather.weather_card import WeatherCard
        weather = WeatherCard(scale=1.0)
        music = _music()
        for w in (weather, music):
            self.addCleanup(w.close)
            w.desktop_mode_changed.connect(w.set_desktop_mode)   # o controller aplica o pedido (como no app)
        weather.move_card_to(200, 200)
        music.move_card_to(700, 260)
        weather.show()
        music.show()
        _app.processEvents()
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=False), \
                mock.patch("app.core.desktop_pin.animations_enabled", return_value=False):
            weather.set_desktop_mode(True)
            am.anchor_manager().align_widgets(weather, axis="y", align=0)
        self.assertTrue(weather.is_desktop_mode())
        self.assertTrue(music.is_desktop_mode())                # uma camada só: a música foi junto
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=False), \
                mock.patch("app.core.desktop_pin.animations_enabled", return_value=False):
            music.set_desktop_mode(False)                       # soltar pela música solta o grupo inteiro
        self.assertFalse(weather.is_desktop_mode())


if __name__ == "__main__":
    unittest.main()
