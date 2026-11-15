"""Interações do mixer: roda sobre o slider de um app, clique fora esconde e o clique que mostra não conta como "fora"."""

import dataclasses
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtWidgets import QApplication

from app.services.audio_mixer_service import AppAudioSession
from app.widgets.volume_mixer import mixer_flyout as mf
from app.widgets.volume_mixer.theme import DEFAULT_THEME
from app.widgets.volume_mixer.theme_shape import parse_plates

app = QApplication.instance() or QApplication(sys.argv)


class MixerInteractionTests(unittest.TestCase):
    def setUp(self):
        self.fly = mf.VolumeMixerFlyout()
        self.fly._click_timer.stop()
        icon = QImage(32, 32, QImage.Format.Format_ARGB32)
        icon.fill(0xFF3AA0FF)
        self.fly.on_sessions_updated([
            AppAudioSession(app_id=f"a{i}", name=f"A{i}", volume=50, is_muted=False, icon=icon) for i in range(4)])
        self.volumes, self.master = [], []
        self.fly.app_volume_dragged.connect(lambda app_id, v: self.volumes.append((app_id, v)))
        self.fly.master_volume_dragged.connect(self.master.append)
        # o estado do mouse do sistema, controlado pelo teste
        self.mouse = {"down": False, "pos": QPoint(5, 5)}
        patchers = [mock.patch.object(self.fly, "_buttons_down", side_effect=lambda: self.mouse["down"]),
                    mock.patch.object(mf.QCursor, "pos", side_effect=lambda: self.mouse["pos"])]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.fly.show_osd(50, False)
        self.fly._slide_t = 1.0
        self.addCleanup(self.fly.hide)

    def _expand(self):
        self.fly.toggle_expanded()
        self.fly._expand_t = 1.0
        self.fly._anim_card_h = self.fly._target_expanded_height()

    def _wheel(self, pos, dy):
        ev = QWheelEvent(QPointF(pos), QPointF(self.fly.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, dy),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.fly.wheelEvent(ev)

    def _row_y(self, index):
        card = self.fly._card_rect()
        row = self.fly._rows[index]
        return card.top() + (self.fly.FIRST_ROW_OFFSET_Y - self.fly.ROW_PITCH * 0.5) + self.fly.ROW_PITCH * index + row.MAIN_ROW_CY

    def _click(self, global_pos):
        self.mouse["pos"], self.mouse["down"] = global_pos, True
        self.fly._poll_outside_click()
        self.mouse["down"] = False
        self.fly._poll_outside_click()

    def _inside(self):
        card = self.fly._card_rect()
        return self.fly.mapToGlobal(QPoint(int(card.center().x()), int(card.top() + 20)))

    def _outside(self):
        card = self.fly._card_rect()
        return self.fly.mapToGlobal(QPoint(int(card.center().x()), int(card.top() - 150)))

    # --- Roda do mouse ---

    def test_wheel_over_an_app_slider_changes_that_apps_volume(self):
        self._expand()
        on_slider = QPoint(int(self.fly._card_rect().left() + 110), int(self._row_y(1)))
        self._wheel(on_slider, 120)
        self._wheel(on_slider, 120)
        self._wheel(on_slider, -120)
        self.assertEqual(self.volumes, [("a1", 52), ("a1", 54), ("a1", 52)])
        self.assertEqual([r.slider.value for r in self.fly._rows], [50, 52, 50, 50])
        self.assertEqual(self.master, [])

    def test_wheel_clamps_at_the_limits(self):
        self._expand()
        self.fly._rows[0].slider.value = 99
        on_slider = QPoint(int(self.fly._card_rect().left() + 110), int(self._row_y(0)))
        for _ in range(3):
            self._wheel(on_slider, 120)
        self.assertEqual(self.fly._rows[0].slider.value, 100)

    def test_wheel_on_the_header_still_changes_the_master_volume(self):
        self._expand()
        card = self.fly._card_rect()
        self._wheel(QPoint(int(card.left() + 100), int(card.top() + 20)), 120)
        self.assertEqual(self.master, [52])

    def test_wheel_away_from_the_sliders_does_not_change_any_app_volume(self):
        self._expand()
        self._wheel(QPoint(int(self.fly._card_rect().left() + 18), int(self._row_y(1))), 120)   # coluna do ícone
        self.assertEqual(self.volumes, [])

    # --- Clique fora ---

    def test_click_inside_the_card_keeps_it_open(self):
        self._click(self._inside())
        self.assertFalse(self.fly._is_hiding)

    def test_click_outside_the_card_hides_it_right_away(self):
        self._click(self._outside())
        self.assertTrue(self.fly._is_hiding)
        self.assertEqual(self.fly._slide_target_t, 0.0)

    def test_only_the_press_counts_not_holding_the_button(self):
        self.mouse["down"] = True                                      # já estava apertado antes (ex.: arrasto)
        self.fly._mouse_was_down = True
        self.mouse["pos"] = self._outside()
        self.fly._poll_outside_click()
        self.assertFalse(self.fly._is_hiding)

    def test_tilted_theme_with_plates_chevron_is_inside(self):
        """Regressão (Persona 5): o chevron de um card inclinado cai fora do retângulo reto, mas é do card."""
        theme = dataclasses.replace(
            DEFAULT_THEME, tilt=-6.0,
            plates=parse_plates([{"color": "#e5001c", "corners": [[-7, -16], [31, -20], [4, 23], [-30, 12]]}]))
        self.fly._apply_theme(theme)
        self.fly._slide_t = 1.0
        card = self.fly._card_rect()
        chevron = self.fly._chevron_hit_rect(card.left(), card.top()).center()
        on_screen = self.fly._tilt_transform().map(chevron)            # onde o chevron inclinado realmente aparece
        self._click(self.fly.mapToGlobal(QPoint(int(on_screen.x()), int(on_screen.y()))))
        self.assertFalse(self.fly._is_hiding)
        self._click(self._outside())
        self.assertTrue(self.fly._is_hiding)

    # --- O clique que MOSTRA o flyout não é um "clique fora" (bug: o volume aparecia e sumia na hora) ---

    def test_the_press_that_shows_the_flyout_does_not_hide_it_when_it_was_already_visible(self):
        """O seletor de posição do Hub age ao APERTAR: set_anchor + show_osd, e o monitor via o mesmo aperto."""
        self.mouse["down"] = True
        self.mouse["pos"] = QPoint(5, 5)                               # o cursor está no Hub, fora do card
        self.fly.set_anchor("tr")
        self.fly.show_osd()
        self.fly._poll_outside_click()
        self.assertFalse(self.fly._is_hiding)

    def test_the_press_that_shows_the_flyout_does_not_hide_it_when_it_was_hidden(self):
        self.fly.hide()
        self.mouse["down"] = True
        self.fly.set_anchor("bl")
        self.fly.show_osd()
        self.fly._slide_t = 1.0
        self.fly._poll_outside_click()
        self.assertFalse(self.fly._is_hiding)

    def test_if_the_poll_sees_the_press_before_the_show_request_it_still_ends_up_shown(self):
        self.mouse["down"] = True
        self.mouse["pos"] = QPoint(5, 5)
        self.fly._poll_outside_click()                                 # o monitor chega primeiro...
        self.assertTrue(self.fly._is_hiding)
        self.fly.show_osd()                                            # ...e o pedido do Hub o traz de volta
        self.assertFalse(self.fly._is_hiding)
        self.assertEqual(self.fly._slide_target_t, 1.0)

    def test_a_later_click_outside_still_hides_after_a_show(self):
        self.fly.show_osd()
        self.mouse["down"] = False
        self.fly._poll_outside_click()
        self._click(self._outside())
        self.assertTrue(self.fly._is_hiding)


if __name__ == "__main__":
    unittest.main()
