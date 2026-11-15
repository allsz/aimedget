"""Movimento da cor de destaque: onda do seletor (só ao arrastar) e pintura "barra de progresso" ao trocar a cor."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.core.config_manager import config_manager
from app.hub.components import accent_wipe, hue_slider as hs
from app.hub.theme import THEME_DARK, resolve_theme

app = QApplication.instance() or QApplication(sys.argv)


def _settle(slider: hs.HueSlider, seconds: float = 2.0):
    for _ in range(int(seconds / 0.016)):
        slider._step(0.016)


class HueSliderWaveTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(hs, "animations_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.slider = hs.HueSlider(hue=200, theme=THEME_DARK)
        self.slider.resize(300, self.slider.height())
        self.slider.show()
        self.addCleanup(self.slider.close)
        self.y = int(self.slider._center_y())

    def _press(self, x):
        QTest.mousePress(self.slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, self.y))

    def _release(self, x):
        QTest.mouseRelease(self.slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, self.y))

    def test_a_plain_click_never_raises_the_wave(self):
        self._press(220)
        _settle(self.slider, 0.5)
        self.assertEqual(self.slider.lift(), 0.0)
        self.assertFalse(self.slider.is_wave_dragging())
        self._release(220)
        _settle(self.slider, 0.5)
        self.assertEqual(self.slider.lift(), 0.0)

    def test_a_tiny_jitter_is_still_a_click(self):
        self._press(150)
        QTest.mouseMove(self.slider, QPoint(150 + int(hs.DRAG_THRESHOLD) - 2, self.y))
        _settle(self.slider, 0.5)
        self.assertEqual(self.slider.lift(), 0.0)
        self._release(152)

    def test_dragging_raises_the_wave_and_releasing_retracts_it_smoothly(self):
        self._press(100)
        for x in range(110, 181, 10):
            QTest.mouseMove(self.slider, QPoint(x, self.y))
        self.assertTrue(self.slider.is_wave_dragging())
        _settle(self.slider, 0.6)
        self.assertGreater(self.slider.lift(), 0.95)

        self._release(180)
        self.assertFalse(self.slider.is_wave_dragging())
        seen = []
        for _ in range(60):
            self.slider._step(0.016)
            seen.append(self.slider.lift())
        self.assertTrue(all(a >= b for a, b in zip(seen, seen[1:])), "a retração não pode oscilar")
        self.assertLess(seen[2], 1.0)      # começou a descer na hora
        self.assertGreater(seen[2], 0.5)   # mas suave, não some de uma vez
        _settle(self.slider, 1.0)
        self.assertEqual(self.slider.lift(), 0.0)

    def test_commit_signal_still_fires_after_a_drag(self):
        committed = []
        self.slider.hueCommitted.connect(committed.append)
        self._press(100)
        QTest.mouseMove(self.slider, QPoint(160, self.y))
        self._release(160)
        self.assertEqual(len(committed), 1)

    def test_keyboard_does_not_raise_the_wave(self):
        self.slider.setFocus()
        QTest.keyClick(self.slider, Qt.Key.Key_Right)
        QTest.keyClick(self.slider, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        _settle(self.slider, 0.3)
        self.assertEqual(self.slider.lift(), 0.0)

    def test_no_wave_when_windows_animations_are_off(self):
        with mock.patch.object(hs, "animations_enabled", return_value=False):
            self._press(100)
            QTest.mouseMove(self.slider, QPoint(180, self.y))
            _settle(self.slider, 0.5)
            self.assertEqual(self.slider.lift(), 0.0)
            self._release(180)

    def test_the_hill_is_a_filled_palette_with_a_flat_base_and_the_knob_on_the_peak(self):
        self._press(100)
        QTest.mouseMove(self.slider, QPoint(200, self.y))
        _settle(self.slider, 0.8)
        img = self.slider.grab().toImage()
        track = self.slider._track_rect()
        kx = int(self.slider._knob_x())
        far = int(track.left()) + 6                                  # longe do pico: a paleta continua só a trilha
        above_far = img.pixelColor(far, int(track.top()) - 6)
        above_peak = img.pixelColor(kx - 30, int(track.top()) - 8)   # logo ao lado do botão, sobre a colina
        self.assertLess(above_far.saturation(), 60)                  # nada acima da trilha lá longe
        self.assertGreater(above_peak.saturation(), 120)             # a paleta cresceu por baixo da curva
        base = img.pixelColor(kx - 30, int(track.bottom()) - 1)
        self.assertGreater(base.saturation(), 120)                   # a base reta continua colorida
        self.assertEqual(img.pixelColor(kx - 30, int(track.bottom()) + 3).saturation() < 60, True)   # e não desce
        knob_y = self.slider._center_y() + self.slider._wave_offset(kx) - hs.KNOB_RISE * self.slider.lift()
        self.assertLess(knob_y, track.top())                         # o botão fica acima da paleta em repouso
        self.assertGreaterEqual(knob_y - hs.KNOB_R * 1.12 - 2, 0.0)  # e a faixa reservada o comporta
        self._release(200)

    def _hill_peak_x(self) -> float:
        """x onde a colina é mais alta (a curva desenhada, com os ombros das pontas)."""
        track = self.slider._track_rect()
        xs = [track.left() + i * 0.5 for i in range(int(track.width() * 2) + 1)]
        return max(xs, key=lambda x: -self.slider._wave_offset(x))

    def test_the_knob_is_always_on_top_of_the_crest_and_follows_when_it_goes_back(self):
        """O pico é exatamente o botão (sem atraso), inclusive ao voltar com ele depois de a animação ter parado."""
        self._press(60)
        QTest.mouseMove(self.slider, QPoint(220, self.y))
        _settle(self.slider, 1.0)                                      # colina inteira, timer já parado
        self.assertFalse(self.slider._timer.isActive())
        self.assertAlmostEqual(self._hill_peak_x(), self.slider._knob_x(), delta=1.0)

        for x in (150, 90, 40, 180):                                   # vai e volta, sem nenhuma animação rodando
            QTest.mouseMove(self.slider, QPoint(x, self.y))
            self.assertAlmostEqual(self._hill_peak_x(), self.slider._knob_x(), delta=1.0, msg=x)
        self._release(180)

    def test_the_knob_sits_at_the_crest_height_everywhere_including_the_extremes(self):
        for x in (0, 3, 40, 150, 260, 297, 299):
            self.slider._hue = self.slider._hue_at(x)
            self.slider._lift = 1.0
            self.slider._wave_drag = True
            img = self.slider.grab().toImage()
            self.assertFalse(img.isNull())
            self.assertAlmostEqual(self.slider._crest_height(), hs.LIFT_PX, delta=0.01)
        self.slider._lift = 0.0
        self.slider._wave_drag = False

    def test_the_hill_ends_in_a_rounded_shoulder_and_a_straight_wall_at_the_bar_end(self):
        """O esboço: nas pontas a colina não achata nem quebra: ombro arredondado e parede reta rente ao fim da barra."""
        track = self.slider._track_rect()
        for hue, end, sign in ((359, track.right(), -1), (0, track.left(), 1)):
            self.slider._hue = hue
            self.slider._lift = 1.0
            h_end = -self.slider._wave_offset(end)
            h_top = -self.slider._wave_offset(end + sign * hs.SHOULDER_W)
            self.assertGreater(h_end, hs.LIFT_PX * 0.4)                 # há parede (a colina não some na ponta)
            self.assertGreater(h_top, h_end + 2.0)                      # e o ombro desce até ela
            xs = [end + sign * i for i in range(0, int(hs.SHOULDER_W * 2) + 1)]
            ys = [-self.slider._wave_offset(x) for x in xs]
            top = ys.index(max(ys))
            self.assertLessEqual(top, hs.SHOULDER_W + 2, "o ponto mais alto fica junto da ponta, no fim do ombro")
            self.assertTrue(all(b >= a - 1e-6 for a, b in zip(ys[:top], ys[1:top + 1])), "do fim da barra até o topo só sobe")
        self.slider._lift = 0.0

    def test_no_step_in_the_hill_except_the_wall_at_the_very_end(self):
        track = self.slider._track_rect()
        for knob_x in (track.left() + 2, track.left() + 30, track.center().x(), track.right() - 30, track.right() - 2):
            self.slider._hue = self.slider._hue_at(knob_x)
            self.slider._lift = 1.0
            xs = [track.left() + i for i in range(0, int(track.width()) + 1)]
            ys = [self.slider._wave_offset(x) for x in xs]
            inner = list(zip(ys[3:-3], ys[4:-3]))                        # fora dos 3 px da parede de cada ponta
            self.assertLess(max(abs(b - a) for a, b in inner), 3.2, f"curva contínua com o botão em {knob_x}")
            self.assertTrue(all(y <= 0.0 for y in ys))                   # nunca abaixo da base
        self.slider._lift = 0.0

    def test_mid_bar_peak_keeps_its_full_height(self):
        self.slider._hue = self.slider._hue_at(self.slider._track_rect().center().x())
        self.slider._lift = 1.0
        self.assertAlmostEqual(self.slider._wave_offset(self.slider._knob_x()), -hs.LIFT_PX, delta=0.01)
        self.slider._lift = 0.0

    def test_at_the_extremes_nothing_sticks_out_past_the_bar_end(self):
        for press, move in ((200, 299), (200, 0)):                      # arrasta até a ponta direita e até a esquerda
            self._press(press)
            QTest.mouseMove(self.slider, QPoint(move, self.y))
            _settle(self.slider, 1.0)
            img = self.slider.grab().toImage()
            track = self.slider._track_rect()
            kx = self.slider._knob_x()
            beside = int(kx - 22) if move > 100 else int(kx + 22)       # ao lado do botão: aqui há colina
            self.assertGreater(img.pixelColor(beside, int(track.top()) - 3).saturation(), 120)
            outside = int(track.right()) + 3 if move > 100 else int(track.left()) - 3   # além do fim da barra
            self.assertLess(img.pixelColor(outside, int(track.top()) - 5).saturation(), 60)
            self._release(move)
            _settle(self.slider, 1.0)

    def test_timer_follows_the_monitor_refresh_rate(self):
        fake = mock.Mock()
        fake.refreshRate.return_value = 144.0
        with mock.patch.object(self.slider, "screen", return_value=fake):
            self._press(100)
            QTest.mouseMove(self.slider, QPoint(180, self.y))
            self.assertEqual(self.slider._timer.interval(), 7)           # a regra em si está em test_refresh_rate.py
            self._release(180)

    def test_wave_paints_without_errors_and_the_knob_rides_the_crest(self):
        self._press(100)
        QTest.mouseMove(self.slider, QPoint(200, self.y))
        _settle(self.slider, 0.6)
        img = self.slider.grab().toImage()
        self.assertFalse(img.isNull())
        kx = self.slider._knob_x()
        self.assertLess(self.slider._wave_offset(kx), -hs.LIFT_PX * 0.9)   # no topo da crista
        self.assertEqual(self.slider._wave_offset(self.slider._track_rect().left()), 0.0)   # a ponta continua reta
        self._release(200)


class AccentWipeTests(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.resize(300, 100)
        self.host.show()
        self.addCleanup(self.host.close)
        self.wipe = accent_wipe.AccentWipe(self.host)
        pm = QPixmap(300, 100)
        pm.fill(QColor("red"))
        self.snapshot = pm

    def _render(self) -> QImage:
        img = QImage(300, 100, QImage.Format.Format_ARGB32)
        img.fill(0)
        self.wipe.render(img)
        return img

    def test_starts_covering_everything_and_uncovers_left_to_right(self):
        self.wipe.start(self.snapshot, [])
        self.wipe._anim.pause()
        self.wipe._on_progress(0.0)
        self.assertEqual(self._render().pixelColor(5, 50).red(), 255)     # nada pintado ainda: foto antiga por cima

        self.wipe._on_progress(0.5)
        img = self._render()
        self.assertEqual(img.pixelColor(20, 50).alpha(), 0)               # à esquerda a cor nova já apareceu
        self.assertEqual(img.pixelColor(290, 50).red(), 255)              # à direita ainda é a antiga

        self.wipe._on_progress(1.0)
        self.assertEqual(self._render().pixelColor(290, 50).alpha(), 0)   # no fim, tudo é a cor nova

    def test_front_edge_is_soft_not_a_hard_line(self):
        self.wipe.start(self.snapshot, [])
        self.wipe._anim.pause()
        self.wipe._on_progress(0.5)
        img = self._render()
        alphas = [img.pixelColor(x, 50).alpha() for x in range(0, 300)]
        self.assertTrue(any(0 < a < 255 for a in alphas), "a borda precisa ter uma faixa de transição")
        self.assertEqual(alphas, sorted(alphas), "a opacidade só cresce da esquerda para a direita")

    def test_excluded_controls_are_never_covered(self):
        from PySide6.QtCore import QRect
        self.wipe.start(self.snapshot, [QRect(200, 20, 60, 40)])
        self.wipe._anim.pause()
        self.wipe._on_progress(0.0)
        img = self._render()
        self.assertEqual(img.pixelColor(230, 40).alpha(), 0)    # o seletor continua vivo
        self.assertEqual(img.pixelColor(230, 90).red(), 255)    # o resto está coberto

    def test_stop_releases_the_layer_and_resizing_cancels_it(self):
        self.wipe.start(self.snapshot, [])
        self.assertTrue(self.wipe.is_running())
        self.wipe.stop()
        self.assertFalse(self.wipe.is_running())
        self.assertFalse(self.wipe.isVisible())

        self.wipe.start(self.snapshot, [])
        self.host.resize(400, 100)   # foto de outro tamanho não serve
        self.assertFalse(self.wipe.is_running())

    def test_does_not_steal_mouse_events(self):
        self.assertTrue(self.wipe.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))


class HubAccentFlowTests(unittest.TestCase):
    def _hub(self):
        from app.hub import hub_window
        patches = [
            mock.patch.object(config_manager, "get_hub_accent", return_value=None),
            mock.patch.object(config_manager, "set_hub_accent"),
            mock.patch.object(hub_window, "animations_enabled", return_value=True),
            mock.patch.object(hub_window.AimedgetHubWindow, "_refresh_icons"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(hub_window.QTimer, "singleShot"):   # sem a consulta real ao GitHub 5 s depois de abrir
            hub = hub_window.AimedgetHubWindow()
        hub.resize(1000, 700)
        hub.show()
        hub.sidebar.select_page("gen")
        app.processEvents()
        self.addCleanup(hub.tray_icon.hide)
        self.addCleanup(hub.close)
        return hub

    def test_a_discrete_choice_paints_the_new_color_with_the_wipe(self):
        hub = self._hub()
        old = hub._current_theme.accent
        hub._change_accent(220, True)                     # clique/teclado/hex: escolha única
        self.assertNotEqual(hub._current_theme.accent, old)   # a cor já está aplicada por baixo
        self.assertTrue(hub._accent_wipe.is_running())
        hub._accent_wipe._anim.setCurrentTime(accent_wipe.DURATION_MS)   # fim da animação, sem esperar tempo real
        self.assertFalse(hub._accent_wipe.is_running())

    def test_repeating_the_same_color_does_not_replay_the_animation(self):
        hub = self._hub()
        hub._change_accent(220, True)
        hub._accent_wipe.stop()
        hub._change_accent(220, True)                     # ex.: soltar o seletor depois de arrastar até aqui
        self.assertFalse(hub._accent_wipe.is_running())

    def test_dragging_does_not_restyle_the_hub_and_the_color_is_painted_on_release(self):
        """Reaplicar o estilo (~70 ms) a cada passo do arrasto derrubava o slider para 30-40 quadros/s."""
        hub = self._hub()
        before = hub._current_theme
        with mock.patch.object(hub, "_apply_theme", wraps=hub._apply_theme) as apply:
            with mock.patch.object(hub.page_gen.hue_slider, "is_wave_dragging", return_value=True):
                for hue in (150, 160, 170, 180):
                    hub._change_accent(hue, False)
            self.assertFalse(hub._accent_timer.isActive())   # nem há timer de aplicação pendente
            apply.assert_not_called()                      # nada foi reaplicado durante o arrasto
            self.assertEqual(hub._current_theme, before)
            self.assertFalse(hub._accent_wipe.is_running())

            hub._change_accent(180, True)                  # soltou: uma troca só, pintada
            self.assertEqual(apply.call_count, 1)
            self.assertTrue(hub._accent_wipe.is_running())
        self.assertEqual(hub._current_theme.accent, resolve_theme(hub._theme_preference, 180).accent)

    def test_live_mode_still_exists_as_an_option(self):
        from app.hub import hub_window
        hub = self._hub()
        with mock.patch.object(hub_window, "LIVE_APPLY_WHILE_DRAGGING", True),                 mock.patch.object(hub.page_gen.hue_slider, "is_wave_dragging", return_value=True):
            hub._change_accent(150, False)
            hub._flush_accent()
            self.assertEqual(hub._current_theme.accent, resolve_theme(hub._theme_preference, 150).accent)
            self.assertFalse(hub._accent_wipe.is_running())   # ao vivo não pinta
            hub._change_accent(150, True)
        self.assertFalse(hub._accent_wipe.is_running())

    def test_no_wipe_when_windows_animations_are_off(self):
        hub = self._hub()
        from app.hub import hub_window
        with mock.patch.object(hub_window, "animations_enabled", return_value=False):
            hub._change_accent(220, True)
        self.assertFalse(hub._accent_wipe.is_running())

    def test_reset_button_is_short_and_explained_in_both_languages(self):
        from app.core.i18n import i18n
        hub = self._hub()
        old = getattr(i18n, "current_language", None)
        try:
            for lang, label, tip in (("pt", "Redefinir", "padrão"), ("en", "Reset", "default")):
                i18n.set_language(lang)
                hub.page_gen.retranslate_ui()
                btn = hub.page_gen.btn_accent_reset
                self.assertEqual(btn.text(), label, lang)
                self.assertIn(tip, btn.toolTip(), lang)
                self.assertEqual(btn.accessibleName(), btn.toolTip(), lang)
        finally:
            i18n.set_language(old or "pt")

    def test_switching_page_cancels_the_stale_snapshot(self):
        hub = self._hub()
        hub._change_accent(220, True)
        self.assertTrue(hub._accent_wipe.is_running())
        hub._on_navigation("ov")
        self.assertFalse(hub._accent_wipe.is_running())


if __name__ == "__main__":
    unittest.main()
