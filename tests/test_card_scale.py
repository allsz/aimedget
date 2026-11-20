"""Clima e Desempenho: tamanho automático/manual com movimento, e o cartão de tamanho do Hub."""

import time
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from app.hub.components.scale_card import ScaleCard
from app.hub.theme import THEME_DARK
from app.widgets.weather.weather_card import WeatherCard

_app = QApplication.instance() or QApplication([])


def _pump(card, limit_s=3.0):
    sizes = []
    end = time.perf_counter() + limit_s
    while card.is_scale_animating() and time.perf_counter() < end:
        _app.processEvents()
        sizes.append(card.scale())
        time.sleep(0.004)
    return sizes


class CardScaleAnimationTests(unittest.TestCase):
    def test_animates_and_ends_on_target(self):
        card = WeatherCard(scale=0.8)
        card.show()
        _app.processEvents()
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=True):
            card.animate_scale_to(1.3)
            self.assertTrue(card.is_scale_animating())
            self.assertAlmostEqual(card.scale(), 0.8, places=3)   # não pulou
            sizes = _pump(card)
        self.assertGreater(len(set(round(s, 3) for s in sizes)), 5)
        self.assertAlmostEqual(card.scale(), 1.3, places=2)
        self.assertLessEqual(max(sizes), 1.3 + 0.01)
        card.close()

    def test_without_animations_changes_at_once(self):
        card = WeatherCard(scale=0.8)
        card.show()
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=False):
            card.animate_scale_to(1.3)
        self.assertFalse(card.is_scale_animating())
        self.assertAlmostEqual(card.scale(), 1.3, places=3)
        card.close()

    def test_hiding_mid_animation_settles(self):
        card = WeatherCard(scale=0.8)
        card.show()
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=True):
            card.animate_scale_to(1.2)
            card.hide()
        self.assertFalse(card.is_scale_animating())
        self.assertAlmostEqual(card.scale(), 1.2, places=2)
        card.close()

    def test_auto_target_is_within_card_limits(self):
        from app.ui_components.floating_card import MAX_SCALE, MIN_SCALE
        card = WeatherCard(scale=1.0)
        self.assertTrue(MIN_SCALE <= card.auto_scale_target() <= MAX_SCALE)
        card.close()


class ScaleCardTests(unittest.TestCase):
    def test_auto_chip_slider_and_signals(self):
        card = ScaleCard("weather_size_title", "weather_size_sub", THEME_DARK, 75, 150)
        card.set_state(True, 110)
        self.assertEqual(card.chips["auto"].property("selected"), "true")
        self.assertEqual(card.slider.value(), 110)
        live, done, auto = [], [], []
        card.live_changed.connect(live.append)
        card.committed.connect(done.append)
        card.auto_clicked.connect(lambda: auto.append(1))
        card._on_slider_changed(120)   # mexer no controle sai do automático
        self.assertEqual(card.chips["auto"].property("selected"), "false")
        self.assertEqual(live, [120])
        card.slider.set_value(120)
        card._commit()
        self.assertEqual(done, [120])
        card.chips["auto"].click()
        self.assertEqual(auto, [1])

    def test_state_does_not_fight_the_user(self):
        card = ScaleCard("weather_size_title", "weather_size_sub", THEME_DARK, 75, 150)
        card.set_state(False, 100)
        card._on_slider_changed(130)   # o usuário está no controle (aguardando gravar)
        card.set_state(True, 90)       # chega quadro do widget: ignorado
        self.assertEqual(card.chips["auto"].property("selected"), "false")


if __name__ == "__main__":
    unittest.main()
