"""
Testes da troca de visual do mixer (mola de morph / encolhe e salta).
  python tests/test_mixer_skin_transition.py
"""

import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from app.core.theme_art import Sticker
from app.core.typography import init_app_font
from app.widgets.volume_mixer import mixer_flyout as mixer_mod
from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout
from app.widgets.volume_mixer.skin_transition import (
    DURATION_MS, SkinTransition, ease_back, mix_color, spring_progress,
)
from app.widgets.volume_mixer.theme import DEFAULT_THEME, LIGHT_DEFAULT_THEME

_app = QApplication.instance() or QApplication([])
init_app_font()


def _stickers(n: int = 4) -> tuple[Sticker, ...]:
    pm = QPixmap(20, 20)
    pm.fill(QColor("#00ff00"))
    anchors = ("top-left", "top-right", "bottom-left", "bottom-right")
    return tuple(Sticker(pm, anchor=anchors[i % 4], x=-6.0 if i % 2 == 0 else 6.0, y=-8.0 if i < 2 else 8.0,
                         width=26.0, height=26.0, layer="above") for i in range(n))


PURPLE = replace(DEFAULT_THEME, card_bg=QColor(150, 90, 214, 248), border=QColor(220, 190, 247), radius=14.0,
                 stickers=_stickers())


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _tx(old, new, clock=None) -> tuple[SkinTransition, FakeClock]:
    clock = clock or FakeClock()
    tx = SkinTransition(old, new, None, QPointF(0, 0), DURATION_MS, clock)
    tx.start()
    return tx, clock


class CurveTests(unittest.TestCase):
    def test_duration_is_200ms(self):
        self.assertEqual(DURATION_MS, 200)

    def test_spring_starts_at_zero_and_settles_at_one(self):
        self.assertEqual(spring_progress(0.0), 0.0)
        self.assertEqual(spring_progress(1.0), 1.0)
        self.assertGreater(spring_progress(0.5), 0.5)       # a mola arranca rápido
        self.assertLess(abs(spring_progress(0.999) - 1.0), 0.02)

    def test_ease_back_overshoots_then_lands(self):
        self.assertEqual(ease_back(0.0), 0.0)
        self.assertAlmostEqual(ease_back(1.0), 1.0)
        self.assertGreater(max(ease_back(i / 50) for i in range(51)), 1.03)

    def test_mix_color_ends_and_clamps(self):
        a, b = QColor(0, 0, 0, 0), QColor(200, 100, 50, 255)
        self.assertEqual(mix_color(a, b, 0.0), a)
        self.assertEqual(mix_color(a, b, 1.0), b)
        self.assertEqual(mix_color(a, b, 1.4), b)


class TransitionTests(unittest.TestCase):
    def test_kind_follows_stickers(self):
        self.assertTrue(SkinTransition(DEFAULT_THEME, PURPLE, None, QPointF(), 200).uses_art)
        self.assertTrue(SkinTransition(PURPLE, DEFAULT_THEME, None, QPointF(), 200).uses_art)
        self.assertFalse(SkinTransition(DEFAULT_THEME, LIGHT_DEFAULT_THEME, None, QPointF(), 200).uses_art)

    def test_first_frame_equals_old_and_last_equals_new(self):
        tx, clock = _tx(DEFAULT_THEME, PURPLE)
        s0 = tx.sample()
        self.assertEqual((s0.morph, s0.old_content, s0.new_content), (0.0, 1.0, 0.0))
        clock.now += 0.2
        s1 = tx.sample()
        self.assertEqual((s1.morph, s1.old_content, s1.new_content), (1.0, 0.0, 1.0))
        self.assertTrue(tx.finished())

    def test_not_started_stays_on_first_frame(self):
        tx = SkinTransition(DEFAULT_THEME, PURPLE, None, QPointF(), 200)
        self.assertEqual(tx.t(), 0.0)
        self.assertFalse(tx.finished())

    def test_rows_never_overlap_with_art(self):
        tx, clock = _tx(DEFAULT_THEME, PURPLE)
        for i in range(101):
            clock.now = 100.0 + 0.2 * i / 100
            s = tx.sample()
            self.assertLess(s.old_content * s.new_content, 1e-9, f"fileiras sobrepostas em t={s.t:.2f}")

    def test_old_content_only_fades_out_and_new_only_in(self):
        tx, clock = _tx(DEFAULT_THEME, LIGHT_DEFAULT_THEME)
        prev_old, prev_new = 1.0, 0.0
        for i in range(1, 101):
            clock.now = 100.0 + 0.2 * i / 100
            s = tx.sample()
            self.assertLessEqual(s.old_content, prev_old + 1e-9)
            self.assertGreaterEqual(s.new_content, prev_new - 1e-9)
            prev_old, prev_new = s.old_content, s.new_content

    def test_stickers_tuck_then_pop(self):
        tx, clock = _tx(PURPLE, DEFAULT_THEME)
        self.assertEqual(tx.leaving(0, 4), (1.0, 1.0, 0.0))       # no começo estão no lugar
        clock.now += 0.2
        self.assertEqual(tx.leaving(0, 4)[0], 0.0)                # no fim sumiram
        tx, clock = _tx(DEFAULT_THEME, PURPLE)
        self.assertEqual(tx.arriving(0, 4)[0], 0.0)               # só saltam depois das cores novas
        clock.now += 0.2
        for i in range(7):                                        # o atraso entre elas não deixa a última sem chegar
            self.assertAlmostEqual(tx.arriving(i, 7)[0], 1.0)
            self.assertEqual(tx.arriving(i, 7)[2], 0.0)

    def test_stagger_is_capped_for_many_stickers(self):
        tx, clock = _tx(DEFAULT_THEME, PURPLE)
        clock.now += 0.2
        self.assertAlmostEqual(tx.arriving(39, 40)[0], 1.0)

    def test_tilt_follows_the_card(self):
        tx, clock = _tx(replace(DEFAULT_THEME, tilt=0.0), replace(DEFAULT_THEME, tilt=-4.0))
        self.assertEqual(tx.tilt(), 0.0)
        clock.now += 0.2
        self.assertEqual(tx.tilt(), -4.0)


class FlyoutTests(unittest.TestCase):
    def setUp(self):
        self.fly = VolumeMixerFlyout()
        self.fly._apply_theme(DEFAULT_THEME)
        self.fly._slide_t = self.fly._slide_target_t = 1.0
        self.fly.show()
        QApplication.processEvents()

    def tearDown(self):
        self.fly.hide()
        self.fly._anim_timer.stop()
        self.fly.deleteLater()

    def _wait_end(self, limit_s: float = 1.5) -> float:
        t0 = time.perf_counter()
        while self.fly._skin_tx is not None and time.perf_counter() - t0 < limit_s:
            QApplication.processEvents()
            time.sleep(0.004)
        took = time.perf_counter() - t0
        while self.fly._anim_timer.isActive() and time.perf_counter() - t0 < limit_s:   # o timer para no quadro seguinte
            QApplication.processEvents()
            time.sleep(0.004)
        return took

    def _render(self) -> QImage:
        img = QImage(self.fly.width(), self.fly.height(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(90, 90, 120))
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPainter
        p = QPainter(img)
        self.fly.render(p, QPoint(0, 0))
        p.end()
        return img

    def test_plain_switch_morphs_and_ends_clean(self):
        self.fly._apply_theme(LIGHT_DEFAULT_THEME)
        tx = self.fly._skin_tx
        self.assertIsNotNone(tx)
        self.assertFalse(tx.uses_art)
        self.assertIs(self.fly.theme, LIGHT_DEFAULT_THEME)         # o tema já vale (linhas, sliders)
        took = self._wait_end()
        self.assertIsNone(self.fly._skin_tx)
        self.assertGreaterEqual(took, 0.12)                        # animou, não pulou
        self.assertLess(took, 0.6)
        self.assertFalse(self.fly._anim_timer.isActive())          # termina limpo: timer parado

    def test_card_color_is_between_old_and_new_midway(self):
        self.fly._apply_theme(LIGHT_DEFAULT_THEME)
        tx = self.fly._skin_tx
        self.assertIsNotNone(tx)
        card = self.fly._card_rect()
        px, py = int(card.left() + 120), int(card.top() + 3)
        first = self._render().pixelColor(px, py)
        self.assertLess(abs(first.red() - DEFAULT_THEME.card_bg.red()), 12)   # primeiro quadro: o card antigo
        tx._clock = lambda: tx._t0 + 0.08                                      # ~40% do caminho
        mid = self._render().pixelColor(px, py)
        self.assertGreater(mid.red(), DEFAULT_THEME.card_bg.red() + 8)
        self.assertLess(mid.red(), LIGHT_DEFAULT_THEME.card_bg.red())

    def test_art_switch_keeps_room_for_old_stickers_then_shrinks(self):
        self.fly._apply_theme(PURPLE)
        self._wait_end()
        big = self.fly._margins
        self.assertGreater(max(big), float(self.fly.SHADOW_MARGIN))
        self.fly._apply_theme(DEFAULT_THEME)
        tx = self.fly._skin_tx
        self.assertIsNotNone(tx)
        self.assertTrue(tx.uses_art)
        self.assertEqual(self.fly._margins, big)                   # a janela segue grande: as figurinhas saem de dentro
        self._wait_end()
        self.assertIsNone(self.fly._skin_tx)
        self.assertEqual(self.fly._margins, (float(self.fly.SHADOW_MARGIN),) * 4)   # depois encolhe
        self.assertFalse(self.fly._glide.is_running())

    def test_switch_in_both_directions_leaves_no_residue(self):
        for theme in (PURPLE, DEFAULT_THEME, PURPLE, LIGHT_DEFAULT_THEME):
            self.fly._apply_theme(theme)
            self._wait_end()
            self.assertIsNone(self.fly._skin_tx)
            self.assertIs(self.fly.theme, theme)
            self.assertFalse(self.fly._content_only)
        self.assertFalse(self.fly._anim_timer.isActive())

    def test_interrupting_a_switch_starts_a_new_one(self):
        self.fly._apply_theme(PURPLE)
        first = self.fly._skin_tx
        self.fly._apply_theme(LIGHT_DEFAULT_THEME)
        self.assertIsNot(self.fly._skin_tx, first)
        self.assertIs(self.fly._skin_tx.old, PURPLE)
        self._wait_end()
        self.assertIsNone(self.fly._skin_tx)

    def test_without_windows_animations_it_applies_at_once(self):
        with mock.patch.object(mixer_mod, "animations_enabled", return_value=False):
            self.fly._apply_theme(PURPLE)
        self.assertIsNone(self.fly._skin_tx)
        self.assertIs(self.fly.theme, PURPLE)

    def test_hidden_flyout_applies_at_once(self):
        self.fly.hide()
        self.fly._apply_theme(PURPLE)
        self.assertIsNone(self.fly._skin_tx)

    def test_mode_switch_keeps_the_mode_crossfade(self):
        self.fly._apply_theme(LIGHT_DEFAULT_THEME, mode_switch=True)
        self.assertIsNone(self.fly._skin_tx)
        self.assertIs(self.fly.theme, LIGHT_DEFAULT_THEME)

    def test_hiding_mid_switch_finishes_it(self):
        self.fly._apply_theme(PURPLE)
        self.assertIsNotNone(self.fly._skin_tx)
        self.fly.hide()
        self.assertIsNone(self.fly._skin_tx)


if __name__ == "__main__":
    unittest.main()
