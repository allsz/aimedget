"""A mudança automática de tamanho do widget de música anima (não pisca) e termina limpa."""

import time
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

_app = QApplication.instance() or QApplication([])


def _pump(skin, limit_s=3.0):
    sizes = []
    end = time.perf_counter() + limit_s
    while skin.is_scale_animating() and time.perf_counter() < end:
        _app.processEvents()
        sizes.append(skin.scale)
        time.sleep(0.004)
    return sizes


class ScaleAnimationTests(unittest.TestCase):
    def test_animates_through_intermediate_sizes_and_ends_on_target(self):
        skin = VinylMusicSkin(scale=0.4)
        skin.show()
        _app.processEvents()
        with mock.patch("app.widgets.music.skins.base_skin.animations_enabled", return_value=True):
            skin.animate_scale_to(0.7)
            self.assertTrue(skin.is_scale_animating())
            self.assertAlmostEqual(skin.scale, 0.4, places=3)   # não pulou no primeiro instante
            sizes = _pump(skin)
        self.assertGreater(len(set(round(s, 3) for s in sizes)), 5)   # passou por vários tamanhos
        self.assertFalse(skin.is_scale_animating())
        self.assertAlmostEqual(skin.scale, 0.7, places=3)
        self.assertLessEqual(max(sizes), 0.7 + 0.005)   # sem passar do alvo
        self.assertEqual(skin.width(), skin._window_size()[0])   # a janela termina no tamanho certo
        skin.close()

    def test_without_animations_changes_at_once(self):
        skin = VinylMusicSkin(scale=0.4)
        skin.show()
        with mock.patch("app.widgets.music.skins.base_skin.animations_enabled", return_value=False):
            skin.animate_scale_to(0.7)
        self.assertFalse(skin.is_scale_animating())
        self.assertAlmostEqual(skin.scale, 0.7, places=3)
        skin.close()

    def test_hidden_widget_settles_and_hiding_mid_animation_finishes(self):
        skin = VinylMusicSkin(scale=0.4)
        skin.animate_scale_to(0.6)   # oculto: na hora
        self.assertAlmostEqual(skin.scale, 0.6, places=3)
        skin.show()
        with mock.patch("app.widgets.music.skins.base_skin.animations_enabled", return_value=True):
            skin.animate_scale_to(0.45)
            skin.hide()
        self.assertFalse(skin.is_scale_animating())
        self.assertAlmostEqual(skin.scale, 0.45, places=3)
        skin.close()

    def test_live_drag_cancels_animation(self):
        skin = VinylMusicSkin(scale=0.4)
        skin.show()
        with mock.patch("app.widgets.music.skins.base_skin.animations_enabled", return_value=True):
            skin.animate_scale_to(0.7)
            skin.stop_scale_animation()
        self.assertFalse(skin.is_scale_animating())
        skin.close()


if __name__ == "__main__":
    unittest.main()
