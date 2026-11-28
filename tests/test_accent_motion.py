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
import pytest

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

    def test_the_wall_grows_continuously_as_the_knob_approaches_the_end(self):
        """A parede nas pontas "enche" aos poucos: sem salto entre posições vizinhas do botão, em qualquer largura."""
        for width in (180, 272, 360):
            self.slider.resize(width, self.slider.height())
            self.slider._lift = 1.0
            left, right = self.slider._flat_ends()
            prev = None
            for hue in range(0, 361):
                self.slider._hue = hue
                wall = -self.slider._wave_offset(right)
                if prev is not None:
                    self.assertLess(abs(wall - prev), 1.0, f"parede saltou: largura={width} hue={hue}")
                prev = wall
        self.slider._lift = 0.0

    def test_no_wall_until_the_fall_reaches_the_end_and_full_crest_at_the_extreme(self):
        self.slider._lift = 1.0
        left, right = self.slider._flat_ends()
        self.slider._hue = self.slider._hue_at(right - hs.WAVE_HALF_W - 2)
        self.assertAlmostEqual(self.slider._wave_offset(right), 0.0, delta=0.01)      # longe: sem parede
        self.slider._hue = self.slider._hue_at(right)
        self.assertGreater(-self.slider._wave_offset(right), hs.LIFT_PX * 0.95)       # na ponta: parede quase cheia
        self.slider._lift = 0.0

    def test_the_knob_is_always_on_the_crest_even_at_the_extremes(self):
        self.slider._lift = 1.0
        rest = self.slider._center_y() - hs.LIFT_PX - hs.KNOB_RISE
        for hue in (0, 1, 90, 180, 270, 359, 360):
            self.slider._hue = hue
            self.assertAlmostEqual(self.slider._knob_y(), rest, delta=0.01, msg=hue)
            self.assertAlmostEqual(self._hill_peak_x(), self.slider._knob_x(), delta=1.0, msg=hue)
        self.slider._lift = 0.0

    def test_the_rounded_bar_ends_are_not_covered_even_with_the_knob_at_the_extremes(self):
        for x_press, x_move in ((200, 299), (100, 0)):
            self._press(x_press)
            QTest.mouseMove(self.slider, QPoint(x_move, self.y))
            _settle(self.slider, 1.0)
            img = self.slider.grab().toImage()
            track = self.slider._track_rect()
            # o canto da extremidade OPOSTA ao botão (o botão cobre o da ponta onde ele está)
            corner_x = int(track.left()) + 1 if x_move > 100 else int(track.right()) - 1
            self.assertLess(img.pixelColor(corner_x, int(track.top())).saturation(), 60, "canto de cima redondo (vazio)")
            self.assertGreater(img.pixelColor(corner_x, int(track.top()) + 5).saturation(), 120)
            self._release(x_move)
            _settle(self.slider, 1.0)

    def test_mid_bar_peak_keeps_its_full_height(self):
        self.slider._hue = self.slider._hue_at(self.slider._track_rect().center().x())
        self.slider._lift = 1.0
        self.assertAlmostEqual(self.slider._wave_offset(self.slider._knob_x()), -hs.LIFT_PX, delta=0.01)
        self.slider._lift = 0.0

    def test_the_bar_keeps_its_rounded_ends_while_the_hill_is_up(self):
        """Regressão: a base da colina preenchia os cantos arredondados de cima da barra quando a onda ligava."""
        self._press(150)
        QTest.mouseMove(self.slider, QPoint(160, self.y))              # botão no meio: as pontas da colina estão em zero
        _settle(self.slider, 1.0)
        self.assertGreater(self.slider.lift(), 0.95)
        img = self.slider.grab().toImage()
        track = self.slider._track_rect()
        top = int(track.top())
        for x in (int(track.left()) + 1, int(track.right()) - 2):
            corner = img.pixelColor(x, top)                            # o canto de cima de cada ponta: vazio (redondo)
            self.assertLess(corner.saturation(), 60, f"canto quadrado em x={x}")
            self.assertGreater(img.pixelColor(x, top + 5).saturation(), 120)   # e o meio da ponta segue colorido
        self._release(160)

    def test_with_the_knob_at_the_end_the_wall_is_filled_next_to_the_knob(self):
        self._press(200)
        QTest.mouseMove(self.slider, QPoint(299, self.y))              # botão na ponta direita: parede cheia
        _settle(self.slider, 1.0)
        img = self.slider.grab().toImage()
        left, right = self.slider._flat_ends()
        track = self.slider._track_rect()
        self.assertGreater(img.pixelColor(int(right) - 3, int(track.top()) - 6).saturation(), 120)   # parede preenchida
        self._release(299)

    def test_the_wall_meets_the_end_of_the_bar_with_a_rounded_top(self):
        """A parede sobe do FIM da barra (não antes) e arredonda para dentro da onda: sem quina nem degrau."""
        track = self.slider._track_rect()
        cy = self.slider._center_y()
        self.slider._lift = 1.0
        for hue in (0, 20, 340, 359):
            self.slider._hue = hue
            for end, sign in ((track.left(), 1.0), (track.right(), -1.0)):
                self.assertAlmostEqual(self.slider._top_y(end), cy, delta=0.01)      # nasce no fim da barra, no centro
                r = self.slider._end_radius(end)
                ys = [self.slider._top_y(end + sign * i * 0.25) for i in range(int(r * 4) + 12)]
                self.assertLess(max(abs(b - a) for a, b in zip(ys[1:], ys[2:])), 3.0, f"degrau: hue={hue}")
                # a borda encontra a onda sem mudar de altura: fora do canto é só trilha + onda
                x_in = end + sign * (r + 1.0)
                self.assertAlmostEqual(self.slider._top_y(x_in), track.top() + self.slider._wave_offset(x_in), delta=0.01)
        self.slider._hue = 180                                                     # sem onda na ponta: o canto da barra
        self.assertAlmostEqual(self.slider._end_radius(track.right()), hs.TRACK_H / 2.0, delta=0.01)
        self.slider._lift = 0.0

    @pytest.mark.native
    def test_the_knob_ring_is_never_clipped_at_the_ends_of_the_bar(self):
        """Regressão: o anel branco de foco do botão (já crescido) era cortado pela borda do slider nas extremidades."""
        self.slider.setFocus()
        for x_press, x_move in ((200, 0), (100, 299)):                  # botão na ponta esquerda e na direita
            self._press(x_press)
            QTest.mouseMove(self.slider, QPoint(x_move, self.y))
            _settle(self.slider, 1.0)
            img = self.slider.grab().toImage()
            ring_r = (hs.KNOB_R + 1.5) * (1.0 + hs.KNOB_GROW)
            kx = self.slider._knob_x()
            self.assertGreaterEqual(kx - ring_r - 0.75, 0.0, "o anel cabe à esquerda")
            self.assertLessEqual(kx + ring_r + 0.75, self.slider.width(), "o anel cabe à direita")
            col = self.slider.width() - 1 if kx > 100 else 0              # a coluna de pixels da borda do widget
            for y in range(img.height()):
                self.assertLess(img.pixelColor(col, y).lightness(), 90, f"anel tocando a borda em y={y}")
            self._release(x_move)
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

    def test_carved_area_is_painted_by_the_wave_even_inside_an_excluded_margin(self):
        """A margem do seletor invadia o pé dos círculos de tema: só o arco de baixo do anel ficava ao vivo."""
        from PySide6.QtCore import QRect
        self.wipe.start(self.snapshot, [QRect(200, 20, 60, 40)], [QRect(200, 20, 60, 10)])
        self.wipe._anim.pause()
        self.wipe._on_progress(0.0)
        img = self._render()
        self.assertEqual(img.pixelColor(230, 25).red(), 255)    # dentro do `carve`: coberto, como o resto da foto
        self.assertEqual(img.pixelColor(230, 40).alpha(), 0)    # o seletor de verdade continua vivo

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

    def test_no_theme_circle_is_ever_half_live_half_covered(self):
        """Vídeo do bug: o anel do 4º círculo ganhava só um arco novo (a margem do seletor invadia o pé dele) e o
        resto só mudava quando a onda chegava. Nenhum círculo pode ficar em parte na zona ao vivo."""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QRegion
        hub = self._hub()
        live = QRegion()
        for r in hub._wipe_excluded_rects():
            live = live.united(QRegion(r))
        for r in hub._wipe_carved_rects():
            live = live.subtracted(QRegion(r))
        buttons = hub.page_gen._theme_group.buttons
        self.assertEqual(len(buttons), 4)
        for key, b in buttons.items():
            rect = QRect(b.mapTo(hub.shell, QPoint(0, 0)), b.size())
            self.assertFalse(live.intersects(rect), key)
        self.assertTrue(live.intersects(QRect(hub.page_gen.hue_slider.mapTo(hub.shell, QPoint(0, 0)),
                                              hub.page_gen.hue_slider.size())))   # o seletor segue ao vivo

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
