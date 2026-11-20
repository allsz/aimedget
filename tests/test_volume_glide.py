"""Volume vindo de fora (troca de dispositivo, teclas de volume) desliza em 180 ms ease-out e o número conta junto;
arrastar e a roda continuam na hora; sem as animações do Windows também vai na hora."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.services.audio_mixer_service import AppAudioSession
from app.ui_components import fluent_slider as fs
from app.widgets.volume_mixer import mixer_flyout as mf

app = QApplication.instance() or QApplication(sys.argv)

FRAME = 1.0 / 120.0


class SliderGlideTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(fs, "animations_enabled", return_value=True)
        self.anim = patcher.start()
        self.addCleanup(patcher.stop)
        self.s = fs.FluentSlider(0.0, 100.0, 10.0)
        self.s.value = 22

    def _frames(self, seconds):
        shown = []
        for _ in range(int(round(seconds / FRAME))):
            self.s.step_animation(FRAME)
            shown.append((self.s.thumb_x(), self.s.display_value()))
        return shown

    def test_glides_in_180ms_with_ease_out_and_the_number_counts(self):
        self.s.glide_to(78)
        self.assertEqual(self.s.value, 78, "o valor de verdade já é o novo")
        self.assertEqual(self.s.display_value(), 22, "o desenho ainda não pulou")
        frames = self._frames(0.090)
        mid_x, mid_n = frames[-1]
        self.assertTrue(22 < mid_n < 78, "o número conta junto")
        # ease-out: na metade do tempo já passou da metade do caminho
        self.assertGreater(mid_x, 50.0)
        rest = self._frames(0.100)
        xs = [x for x, _ in frames + rest]
        self.assertEqual(xs, sorted(xs), "só anda para frente")
        self.assertEqual(self.s.display_value(), 78)
        self.assertAlmostEqual(self.s.thumb_x(), 78.0)
        self.assertFalse(self.s.is_gliding())
        self.assertFalse(self.s.step_animation(FRAME), "termina limpo")

    def test_retarget_mid_glide_starts_from_where_it_is(self):
        self.s.glide_to(78)
        self._frames(0.05)
        here = self.s.thumb_x()
        self.s.glide_to(30)
        self.s.step_animation(FRAME)
        self.assertLess(abs(self.s.thumb_x() - here), 10.0, "sem salto ao mudar de alvo no meio")
        self._frames(0.2)
        self.assertEqual(self.s.display_value(), 30)

    def test_setting_the_value_directly_is_instant(self):
        self.s.glide_to(78)
        self.s.value = 40       # arrasto / roda
        self.assertEqual(self.s.display_value(), 40)
        self.assertFalse(self.s.is_gliding())

    def test_without_windows_animations_it_jumps(self):
        self.anim.return_value = False
        self.s.glide_to(78)
        self.assertEqual(self.s.display_value(), 78)
        self.assertFalse(self.s.is_gliding())


class MixerGlideTests(unittest.TestCase):
    def setUp(self):
        self.clock = [500.0]
        for target in ("time.perf_counter",):
            p = mock.patch(target, side_effect=lambda: self.clock[0])
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(fs, "animations_enabled", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.fly = mf.VolumeMixerFlyout()
        self.fly._click_timer.stop()
        p = mock.patch.object(self.fly, "_buttons_down", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.icon = QImage(32, 32, QImage.Format.Format_ARGB32)
        self.icon.fill(0xFF3AA0FF)
        self.fly.on_sessions_updated([AppAudioSession("a", "A", 20, False, self.icon)])
        self.fly.show_osd(22, False)
        self.fly._slide_t = self.fly._slide_target_t = 1.0
        self._run(0.3)
        self.addCleanup(self.fly.hide)

    def _run(self, seconds):
        for _ in range(int(round(seconds / FRAME))):
            self.clock[0] += FRAME
            self.fly._on_tick()

    def test_master_volume_from_a_device_switch_glides(self):
        self.fly._anim_timer.stop()
        self.fly.on_master_volume_changed(78, False)
        self.assertTrue(self.fly._anim_timer.isActive(), "o relógio da animação liga sozinho")
        self.assertEqual(self.fly.master_slider.display_value(), 22)
        self._run(0.09)
        self.assertTrue(22 < self.fly.master_slider.display_value() < 78)
        self._run(0.15)
        self.assertEqual(self.fly.master_slider.display_value(), 78)
        self._run(0.05)
        self.assertFalse(self.fly._anim_timer.isActive(), "termina limpo")

    def test_echo_of_the_users_own_wheel_does_not_glide_back(self):
        self.fly.master_slider.value = 30       # roda / arrasto: na hora
        self.fly.on_master_volume_changed(30, False)
        self.assertFalse(self.fly.master_slider.is_gliding())

    def test_app_volume_from_outside_glides(self):
        self.fly.on_sessions_updated([AppAudioSession("a", "A", 80, False, self.icon)])
        row = self.fly._rows[0]
        self.assertEqual(row.volume, 80)
        self.assertEqual(row.slider.display_value(), 20)
        self._run(0.25)
        self.assertEqual(row.slider.display_value(), 80)

    def test_painting_mid_glide(self):
        self.fly.on_master_volume_changed(78, False)
        self._run(0.05)
        self.fly.grab()


if __name__ == "__main__":
    unittest.main()
