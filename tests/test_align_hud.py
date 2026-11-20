"""Testes do Floating Aligner HUD, Jelly Slider e engine de alinhamento + igualar tamanho."""

import unittest

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.core.anchor_manager import anchor_manager, card_rect
from app.hub.theme import THEME_DARK, THEME_LIGHT, THEME_TRUE_DARK
from app.ui_components.align_hud import AlignHudWindow
from app.ui_components.jelly_slider import JellySlider
from app.widgets.performance.performance_card import PerformanceCard
from app.widgets.weather.weather_card import WeatherCard

_app = QApplication.instance() or QApplication([])


class JellySliderTests(unittest.TestCase):
    def test_range_clamping_and_value_signal(self):
        s = JellySlider(minimum=0, maximum=32, value=10, step_minor=4, step_major=8, theme=THEME_DARK)
        s.resize(248, 94)
        self.assertEqual(s.value(), 10)

        s.set_value(99, animated=False)
        self.assertEqual(s.value(), 32)

        s.set_value(-5, animated=False)
        self.assertEqual(s.value(), 0)

    def test_paints_cleanly_in_all_themes(self):
        for theme in (THEME_LIGHT, THEME_DARK, THEME_TRUE_DARK):
            s = JellySlider(minimum=0, maximum=32, value=16, theme=theme)
            s.resize(248, 94)
            # Simula gota levantada durante o arraste para testar a ponte metaball
            s._dy.x = s._track_cy() + s.RISE * 0.65
            s._ds.x = 0.95
            img = QImage(248, 94, QImage.Format.Format_ARGB32)
            img.fill(0)
            s.render(img)


class AlignWidgetsAndHudTests(unittest.TestCase):
    def setUp(self):
        from app.core.config_manager import config_manager
        from unittest import mock
        self._prev_align_prefs = config_manager.get_anchor("align_prefs", None)
        config_manager.set_anchor("align_prefs", {})
        # Estes testes conferem o lugar final logo depois do clique: o deslize animado tem testes em test_anchor.py
        self._no_anim = mock.patch("app.core.anchor_manager.animations_enabled", return_value=False)
        self._no_anim.start()

    def tearDown(self):
        from app.core.config_manager import config_manager
        self._no_anim.stop()
        config_manager.set_anchor("align_prefs", self._prev_align_prefs if self._prev_align_prefs is not None else {})

    def test_slider_and_saved_layout_never_group_widgets_on_their_own(self):
        from app.core.config_manager import config_manager
        mgr = anchor_manager()
        config_manager.set_anchor("align_prefs", {"axis": "y", "align": 0, "match_size": True, "gap": 8})
        weather = WeatherCard(scale=1.0)
        perf = PerformanceCard(scale=0.85)
        hud = None
        try:
            weather.move(100, 100)
            perf.move(900, 500)
            weather.show()
            perf.show()
            mgr._windows["weather"] = weather
            mgr._windows["performance"] = perf
            before = card_rect(perf)
            hud = AlignHudWindow(weather, theme=THEME_DARK)
            # O layout salvo não aparece marcado: o widget não está alinhado com ninguém
            self.assertFalse(hud.action_bar.button("stack_left").isChecked())
            hud.slider.live_value_changed.emit(20.0)
            hud.slider.interaction_finished.emit()
            hud.action_bar.button("match_size").click()     # desligar: só guarda a escolha
            self.assertFalse(mgr.is_grouped(weather))
            after = card_rect(perf)
            self.assertEqual((after.l, after.t, after.w), (before.l, before.t, before.w))
        finally:
            if hud is not None:
                hud.close()
            mgr.detach(weather)
            mgr.detach(perf)
            weather.close()
            perf.close()

    def test_stack_left_and_match_size_between_weather_and_performance(self):
        mgr = anchor_manager()
        weather = WeatherCard(scale=1.0)
        perf = PerformanceCard(scale=0.85)
        try:
            weather.move(100, 100)
            perf.move(460, 240)
            weather.show()
            perf.show()
            mgr._windows["weather"] = weather
            mgr._windows["performance"] = perf

            # Antes: larguras diferentes (300 vs 255)
            self.assertGreater(card_rect(weather).w - card_rect(perf).w, 30.0)

            mgr.align_widgets(weather, axis="y", align=0, gap=12.0, match_size=True)

            rw = card_rect(weather)
            rp = card_rect(perf)
            # Bordas esquerdas e direitas alinhadas (mesma largura) + folga exata de 12 px
            self.assertAlmostEqual(rw.l, rp.l, delta=1.5)
            self.assertAlmostEqual(rw.w, rp.w, delta=2.0)
            self.assertAlmostEqual(rp.t - rw.b, 12.0, delta=1.5)

            # Mudar o gap via slider atualiza a folga em tempo real
            mgr.set_group_gap(weather, 24.0)
            rw2 = card_rect(weather)
            rp2 = card_rect(perf)
            self.assertAlmostEqual(rp2.t - rw2.b, 24.0, delta=1.5)
        finally:
            mgr.detach(weather)
            mgr.detach(perf)
            weather.close()
            perf.close()

    def test_align_hud_controls_widgets_and_renders_cleanly(self):
        mgr = anchor_manager()
        weather = WeatherCard(scale=1.0)
        perf = PerformanceCard(scale=0.85)
        hud = None
        try:
            weather.move(120, 120)
            perf.move(500, 300)
            weather.show()
            perf.show()
            mgr._windows["weather"] = weather
            mgr._windows["performance"] = perf

            hud = AlignHudWindow(weather, theme=THEME_DARK)
            hud.action_bar.button("stack_center").click()
            self.assertTrue(hud.action_bar.button("stack_center").isChecked())

            # Centro horizontal coincide
            rw, rp = card_rect(weather), card_rect(perf)
            self.assertAlmostEqual((rw.l + rw.r) / 2.0, (rp.l + rp.r) / 2.0, delta=1.5)

            # Toggle Match Size iguala as larguras
            hud.action_bar.button("match_size").click()
            self.assertTrue(hud.action_bar.button("match_size").isChecked())
            self.assertAlmostEqual(card_rect(weather).w, card_rect(perf).w, delta=2.0)

            # Jelly Slider abaixo da barra muda a folga continuamente sem gravar em disco durante o arraste
            hud.slider.live_value_changed.emit(20.0)
            self.assertAlmostEqual(card_rect(perf).t - card_rect(weather).b, 20.0, delta=1.5)
            hud.slider.interaction_finished.emit()

            # Timer do slider segue refresh_interval_ms (cap 240Hz -> >= 4ms) com PreciseTimer
            from PySide6.QtCore import Qt
            from app.core.refresh_rate import MIN_MS
            self.assertEqual(hud.slider._timer.timerType(), Qt.TimerType.PreciseTimer)
            self.assertGreaterEqual(hud.slider._timer.interval(), MIN_MS)

            img = QImage(hud.width(), hud.height(), QImage.Format.Format_ARGB32)
            img.fill(0)
            hud.render(img)
        finally:
            if hud is not None:
                hud.close()
            mgr.detach(weather)
            mgr.detach(perf)
            weather.close()
            perf.close()

    def test_align_hud_opens_outside_widget_and_stays_inside_screen(self):
        from PySide6.QtCore import QRect
        from app.core.screen_metrics import get_screen_for_widget

        weather = WeatherCard(scale=1.0)
        hud = None
        try:
            screen = get_screen_for_widget(weather)
            avail = screen.availableGeometry()
            # Encosta o widget na borda direita da tela: o HUD deve abrir à esquerda, fora do widget e dentro da tela
            weather.move(avail.right() - weather.width() + 10, avail.top() + 80)
            weather.show()
            hud = AlignHudWindow(weather, theme=THEME_DARK)
            r = card_rect(weather)
            w_rect = QRect(int(r.l), int(r.t), int(r.w), int(r.h))
            h_rect = hud.geometry()

            self.assertFalse(h_rect.intersects(w_rect))
            self.assertGreaterEqual(h_rect.left(), avail.left())
            self.assertLessEqual(h_rect.right(), avail.right())
            self.assertGreaterEqual(h_rect.top(), avail.top())
            self.assertLessEqual(h_rect.bottom(), avail.bottom())
        finally:
            if hud is not None:
                hud.close()
            weather.close()

    def test_align_hud_remembers_last_option_and_dismisses_on_unrelated_click(self):
        from unittest import mock
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QWidget
        from app.core import widget_animator

        mgr = anchor_manager()
        weather = WeatherCard(scale=1.0)
        perf = PerformanceCard(scale=0.85)
        unrelated = QWidget()
        hud1 = hud2 = None
        try:
            weather.move(120, 120)
            perf.move(500, 300)
            weather.show()
            perf.show()
            mgr._windows["weather"] = weather
            mgr._windows["performance"] = perf

            hud1 = AlignHudWindow(weather, theme=THEME_DARK)
            hud1.action_bar.button("stack_right").click()
            hud1.action_bar.button("match_size").click()
            hud1.slider.live_value_changed.emit(16.0)
            hud1.slider.interaction_finished.emit()
            hud1.close()

            # Reabrir o HUD lembra exatamente a última opção ativa (stack_right + match_size + gap 16)
            hud2 = AlignHudWindow(weather, theme=THEME_DARK)
            self.assertTrue(hud2.action_bar.button("stack_right").isChecked())
            self.assertTrue(hud2.action_bar.button("match_size").isChecked())
            self.assertFalse(hud2.action_bar.button("stack_left").isChecked())
            self.assertEqual(hud2.slider.value(), 16)

            # Sem animações: clique em widget da pilha mantém aberto; clique fora fecha
            with mock.patch.object(widget_animator, "animations_enabled", return_value=False):
                hud2.present()
                self.assertTrue(hud2.isVisible())
                ev = QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    QPointF(5, 5),
                    QPointF(5, 5),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                hud2.eventFilter(perf, ev)
                self.assertTrue(hud2.isVisible())       # membro da pilha relacionada: continua aberto

                hud2.eventFilter(unrelated, ev)
                self.assertFalse(hud2.isVisible())      # clique fora da pilha: fecha!

                # Regressão: clicar/arrastar o widget e depois clicar fora (desktop/outro app) também fecha
                hud2.present()
                self.assertTrue(hud2.isVisible())
                hud2.eventFilter(weather, ev)           # clicou no widget -> continua aberto
                self.assertTrue(hud2.isVisible())
                hud2.eventFilter(QApplication.instance(), QEvent(QEvent.Type.ApplicationDeactivate))
                self.assertFalse(hud2.isVisible())      # perdeu foco do app -> fecha!

                # E se o widget da pilha desativar sem foco voltar para a pilha -> fecha no próximo tick
                hud2.present()
                self.assertTrue(hud2.isVisible())
                with mock.patch.object(QApplication, "activeWindow", return_value=None):
                    hud2.eventFilter(weather, QEvent(QEvent.Type.WindowDeactivate))
                    QApplication.processEvents()
                self.assertFalse(hud2.isVisible())
        finally:
            for w in (hud1, hud2, unrelated):
                if w is not None:
                    w.close()
            mgr.detach(weather)
            mgr.detach(perf)
            weather.close()
            perf.close()


if __name__ == "__main__":
    unittest.main()
