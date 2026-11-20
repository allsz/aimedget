"""Botão direito no alto-falante do volume principal: gaveta dos dispositivos PADRÃO do Windows (Saída/Entrada),
com o mixer recolhido ou expandido, animada (sem pulos e sem tremida) e na hora sem as animações do Windows."""

import dataclasses
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from app.services.audio_endpoint_service import AudioEndpoint, AudioEndpointService
from app.services.audio_mixer_service import AppAudioSession
from app.widgets.volume_mixer import mixer_flyout as mf
from app.widgets.volume_mixer.theme import DEFAULT_THEME
from app.widgets.volume_mixer.theme_shape import parse_plates

app = QApplication.instance() or QApplication(sys.argv)

FRAME = 1.0 / 120.0


def _outputs(default="spk"):
    return [
        AudioEndpoint("__default__", "Padrão do Windows", "output", True),
        AudioEndpoint("spk", "Speakers", "output", default == "spk"),
        AudioEndpoint("hp", "Headphones", "output", default == "hp"),
        AudioEndpoint("hdmi", "Monitor", "output", default == "hdmi"),
    ]


def _inputs(default="mic"):
    return [
        AudioEndpoint("__default__", "Padrão do Windows", "input", True),
        AudioEndpoint("mic", "Microphone", "input", default == "mic"),
        AudioEndpoint("cam", "Webcam mic", "input", default == "cam"),
    ]


class MasterDeviceDrawerTests(unittest.TestCase):
    def setUp(self):
        self.clock = [1000.0]
        clock_patch = mock.patch("time.perf_counter", side_effect=lambda: self.clock[0])
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        anim_patch = mock.patch.object(mf, "animations_enabled", return_value=True)
        self.anim = anim_patch.start()
        self.addCleanup(anim_patch.stop)

        self.fly = mf.VolumeMixerFlyout()
        self.fly._click_timer.stop()
        buttons = mock.patch.object(self.fly, "_buttons_down", return_value=False)
        buttons.start()
        self.addCleanup(buttons.stop)
        icon = QImage(32, 32, QImage.Format.Format_ARGB32)
        icon.fill(0xFF3AA0FF)
        self.fly.on_sessions_updated([
            AppAudioSession(app_id=f"a{i}", name=f"A{i}", volume=50, is_muted=False, icon=icon) for i in range(3)])
        self.fly.on_endpoints_updated(_outputs(), _inputs())
        self.defaults, self.mutes = [], []
        self.fly.default_device_changed.connect(lambda flow, dev: self.defaults.append((flow, dev)))
        self.fly.master_mute_toggled.connect(lambda: self.mutes.append(True))
        self.fly.show_osd(50, False)
        self.fly._slide_t = 1.0
        self.fly._slide_target_t = 1.0
        self.addCleanup(self.fly.hide)

    # --- ajudantes ---

    def _press(self, pt: QPointF, button=Qt.MouseButton.LeftButton):
        ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pt, self.fly.mapToGlobal(pt), button, button,
                         Qt.KeyboardModifier.NoModifier)
        self.fly.mousePressEvent(ev)

    def _speaker(self) -> QPointF:
        card = self.fly._card_rect()
        on_card = self.fly._speaker_hit_rect(card.left(), card.top()).center()
        tf = self.fly._tilt_transform()
        return tf.map(on_card) if tf is not None else on_card

    def _run(self, seconds=0.6) -> list[float]:
        """Avança o relógio quadro a quadro e devolve a altura do card em cada quadro."""
        heights = []
        for _ in range(int(seconds / FRAME)):
            self.clock[0] += FRAME
            self.fly._on_tick()
            heights.append(self.fly._card_rect().height())
        return heights

    def _expand(self):
        self.fly.toggle_expanded()
        self._run()
        self.assertAlmostEqual(self.fly._expand_t, 1.0)

    def _drawer_h(self, n_devices: int) -> float:
        d = self.fly._master_drawer
        return 26.0 + 34.0 + n_devices * d.ITEM_H + 8.0 + d.GAP

    def assertMonotonic(self, values, increasing=True):
        for a, b in zip(values, values[1:]):
            if increasing:
                self.assertGreaterEqual(b, a - 1e-6, f"a altura recuou ({a:.2f} -> {b:.2f}): tremida")
            else:
                self.assertLessEqual(b, a + 1e-6, f"a altura voltou a crescer ({a:.2f} -> {b:.2f}): tremida")

    # --- lista de dispositivos ---

    def test_lists_only_real_devices_and_marks_the_windows_default(self):
        d = self.fly._master_drawer
        self.assertEqual([e.device_id for e in d.output_endpoints], ["spk", "hp", "hdmi"])
        self.assertEqual([e.device_id for e in d.input_endpoints], ["mic", "cam"])
        self.assertEqual(d.selected_output_id, "spk")
        self.assertEqual(d.selected_input_id, "mic")
        self.fly.on_endpoints_updated(_outputs(default="hp"), _inputs(default="cam"))
        self.assertEqual(d.selected_output_id, "hp")
        self.assertEqual(d.selected_input_id, "cam")

    # --- mixer recolhido ---

    def test_right_click_on_speaker_opens_the_drawer_in_the_collapsed_mixer_with_motion(self):
        self.assertFalse(self.fly.is_expanded)
        self._press(self._speaker(), Qt.MouseButton.RightButton)
        self.assertTrue(self.fly._master_drawer.is_routing_open)
        self.assertEqual(self.mutes, [], "botão direito não silencia")
        heights = self._run()
        final = self.fly.COLLAPSED_H + self._drawer_h(3)
        self.assertAlmostEqual(heights[-1], final, delta=0.5)
        self.assertLess(heights[0], final - 10.0, "o card pulou direto para a altura final")
        self.assertMonotonic(heights, increasing=True)
        self.assertFalse(self.fly.is_expanded, "abrir a gaveta não expande o mixer de apps")
        self.assertFalse(self.fly._anim_timer.isActive(), "a animação termina limpa")

        self._press(self._speaker(), Qt.MouseButton.RightButton)
        heights = self._run()
        self.assertFalse(self.fly._master_drawer.is_routing_open)
        self.assertAlmostEqual(heights[-1], self.fly.COLLAPSED_H, delta=0.5)
        self.assertMonotonic(heights, increasing=False)

    def test_left_click_on_speaker_still_mutes(self):
        self._press(self._speaker(), Qt.MouseButton.LeftButton)
        self.assertEqual(self.mutes, [True])
        self.assertFalse(self.fly._master_drawer.is_routing_open)

    def test_choosing_a_device_sets_the_windows_default_for_each_flow(self):
        self.fly.toggle_master_drawer()
        self._run()
        d = self.fly._master_drawer
        card = self.fly._card_rect()
        y_top = d.y_top_for(card.top() + self.fly.HEADER_H)
        self._press(d._item_rect(card.left(), y_top, 1).center())          # Headphones
        self.assertEqual(self.defaults, [("output", "hp")])
        self.assertEqual(d.selected_output_id, "hp")

        self._press(d._tab_rect(card.left(), y_top, "input").center())    # aba Entrada
        self._run()
        self.assertAlmostEqual(self.fly._card_rect().height(), self.fly.COLLAPSED_H + self._drawer_h(2), delta=0.5)
        card = self.fly._card_rect()   # ancorado embaixo: o topo do card andou ao encolher
        y_top = d.y_top_for(card.top() + self.fly.HEADER_H)
        self._press(d._item_rect(card.left(), y_top, 1).center())          # Webcam mic
        self.assertEqual(self.defaults[-1], ("input", "cam"))

    def test_close_button_closes_the_drawer(self):
        self.fly.toggle_master_drawer()
        self._run()
        d = self.fly._master_drawer
        card = self.fly._card_rect()
        self._press(d._close_btn_rect(card.left(), d.y_top_for(card.top() + self.fly.HEADER_H)).center())
        self.assertFalse(d.is_routing_open)
        self._run()
        self.assertAlmostEqual(self.fly._card_rect().height(), self.fly.COLLAPSED_H, delta=0.5)

    def test_without_windows_animations_it_opens_and_closes_at_once(self):
        self.anim.return_value = False
        self._press(self._speaker(), Qt.MouseButton.RightButton)
        self.assertAlmostEqual(self.fly._card_rect().height(), self.fly.COLLAPSED_H + self._drawer_h(3), delta=0.5)
        self._press(self._speaker(), Qt.MouseButton.RightButton)
        self.assertAlmostEqual(self.fly._card_rect().height(), self.fly.COLLAPSED_H, delta=0.5)

    def test_reopening_the_flyout_starts_with_the_drawer_closed(self):
        self.fly.toggle_master_drawer()
        self._run()
        self.fly.hide()
        self.fly.show_osd(50, False)
        self.assertFalse(self.fly._master_drawer.is_routing_open)
        self.assertEqual(self.fly._master_drawer.extra_height(), 0.0)

    # --- mixer expandido ---

    def test_in_the_expanded_mixer_the_drawer_pushes_the_app_list_down(self):
        self._expand()
        y0 = self.fly._card_rect().top()
        rows_before = self.fly._list_rows_top(y0) - y0
        start_h = self.fly._card_rect().height()
        self._press(self._speaker(), Qt.MouseButton.RightButton)
        heights = self._run()
        self.assertTrue(self.fly.is_expanded)
        y0 = self.fly._card_rect().top()
        self.assertAlmostEqual(self.fly._list_rows_top(y0) - y0 - rows_before, self._drawer_h(3), delta=0.5)
        self.assertAlmostEqual(heights[-1], min(self.fly.EXPANDED_MAX_H, start_h + self._drawer_h(3)), delta=0.5)
        self.assertMonotonic(heights, increasing=True)

    def test_accordion_between_the_master_drawer_and_app_drawers(self):
        self._expand()
        self.fly.toggle_master_drawer()
        self._run()
        card = self.fly._card_rect()
        row = self.fly._rows[0]
        cy = self.fly._list_rows_top(card.top()) + row.MAIN_ROW_CY
        self._press(row.icon_hit_rect(card.left(), cy).center(), Qt.MouseButton.RightButton)
        self.assertTrue(row.is_routing_open)
        self.assertFalse(self.fly._master_drawer.is_routing_open, "abrir a gaveta de um app fecha a do principal")
        self._run()
        self.fly.toggle_master_drawer()
        self.assertFalse(row.is_routing_open, "abrir a do principal fecha a do app")

    def test_collapsing_the_mixer_keeps_the_drawer_open(self):
        self._expand()
        self.fly.toggle_master_drawer()
        self._run()
        self.fly.toggle_expanded()
        heights = self._run()
        self.assertTrue(self.fly._master_drawer.is_routing_open)
        self.assertAlmostEqual(heights[-1], self.fly.COLLAPSED_H + self._drawer_h(3), delta=0.5)

    # --- skins ---

    def test_tilted_skin_right_click_still_hits_the_speaker(self):
        theme = dataclasses.replace(
            DEFAULT_THEME, tilt=-6.0,
            plates=parse_plates([{"color": "#e5001c", "corners": [[-7, -16], [31, -20], [4, 23], [-30, 12]]}]))
        self.fly._apply_theme(theme)
        self._press(self._speaker(), Qt.MouseButton.RightButton)
        self.assertTrue(self.fly._master_drawer.is_routing_open)
        self.assertIs(self.fly._master_drawer.theme, theme, "a gaveta segue o tema do mixer")
        heights = self._run()
        self.assertMonotonic(heights, increasing=True)

    def test_drawer_fades_out_with_the_card_when_the_flyout_hides(self):
        """Regressão: a gaveta trocava a opacidade do pintor por 100% e ficava sólida enquanto o card sumia; o Windows
        então a apagava parada no lugar ao esconder a janela (sem o deslize de saída)."""
        from app.ui_components.pill_switch import PillSwitch
        self.fly.toggle_master_drawer()
        self._run()
        seen = []
        real_draw = PillSwitch.draw

        def spy(sw, p):
            seen.append(p.opacity())
            real_draw(sw, p)

        self.fly._hide_now()
        tops = []
        with mock.patch.object(PillSwitch, "draw", spy):
            for _ in range(10):
                self.clock[0] += FRAME
                self.fly._on_tick()
                tops.append(self.fly._card_rect().top())
                seen.clear()
                self.fly.grab()
                card_opacity = min(1.0, self.fly._slide_t * 1.15)
                if seen:
                    self.assertLessEqual(max(seen), card_opacity + 1e-3, "a gaveta não acompanhou o fade do card")
        self.assertGreater(tops[-1], tops[0] + 10.0, "o card (com a gaveta) desliza para fora")

    def test_painting_with_the_drawer_open_does_not_fail(self):
        self.fly.toggle_master_drawer()
        self._run()
        self.fly.grab()   # pinta de verdade (gaveta + cabeçalho com destaque)


class DefaultDeviceDetectionTests(unittest.TestCase):
    def test_a_new_windows_default_is_reported_even_with_the_same_devices(self):
        with mock.patch.object(AudioEndpointService, "refresh_endpoints"), \
                mock.patch.object(AudioEndpointService, "_init_winrt_policy"):
            svc = AudioEndpointService()
        svc._poll_timer.stop()
        if not svc._ole32:
            self.skipTest("só no Windows")
        events = []
        svc.endpoints_updated.connect(lambda: events.append(True))
        state = {"out": _outputs("spk")}
        flows = lambda _enum, flow_idx, flow_name: state["out"] if flow_idx == 0 else _inputs()
        with mock.patch.object(svc, "_enum_flow", side_effect=flows):
            svc.refresh_endpoints()
            self.assertEqual(len(events), 1)
            svc.refresh_endpoints()
            self.assertEqual(len(events), 1, "nada mudou: sem aviso")
            state["out"] = _outputs("hp")
            svc.refresh_endpoints()
            self.assertEqual(len(events), 2, "só o padrão mudou: o mixer precisa saber")

    def test_choosing_windows_default_pseudo_item_is_ignored(self):
        with mock.patch.object(AudioEndpointService, "refresh_endpoints"), \
                mock.patch.object(AudioEndpointService, "_init_winrt_policy"):
            svc = AudioEndpointService()
        svc._poll_timer.stop()
        self.assertFalse(svc.set_default_device("output", "__default__"))


if __name__ == "__main__":
    unittest.main()
