"""Skin Shinra do Timer: arte própria, nome do modo montado com as letras, números e botões centrados no losango."""

import os
import sys
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.i18n import TRANSLATIONS, i18n
from app.widgets.timer.skins import init_timer_skin_specs
from app.widgets.timer.skins import shinra_skin as sk
from app.widgets.timer.skins.skin import TimerState, mode_label
from app.widgets.timer.timer_controller import TimerWidgetController


class ShinraSkinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        self.skin = sk.ShinraTimerSkin()
        self.addCleanup(self.skin.deleteLater)

    def tearDown(self):
        config_manager.config_path, config_manager._data = self._path, self._data

    def test_registered_and_selectable(self):
        self.assertIn("shinra", TimerWidgetController.AVAILABLE_SKINS)
        spec = next(s for s in init_timer_skin_specs() if s.id == "shinra")
        self.assertTrue(spec.available)

    @unittest.skipUnless(os.path.isdir(sk.SKIN_DIR), "a arte da Shinra é distribuída à parte (assets/skins/shinra)")
    def test_assets_ship_with_the_skin(self):
        self.assertTrue(os.path.exists(sk.ART_FILE))
        meta = sk._letters_meta()
        for ch in "abcdefghijklmnopqrstuvwxyz":
            self.assertIn(f"lower_{ch}", meta)
            self.assertIn(f"upper_initial_{ch.upper()}", meta)
            self.assertTrue(os.path.exists(os.path.join(sk.LETTERS_DIR, f"lower_{ch}.png")))

    def test_digits_are_centered_on_both_axes(self):
        card, scale = self.skin.get_card_rect(), self.skin.get_scale()
        rects, _, _ = self.skin.get_digits_geometry()
        left, right = rects["hours"].left(), rects["seconds"].right()
        self.assertAlmostEqual((left + right) / 2.0, card.center().x(), delta=0.5)
        self.assertAlmostEqual(rects["hours"].center().y(), card.top() + sk.DIGITS_CY * scale, delta=0.5)
        self.assertAlmostEqual(sk.DIGITS_CY, 74.0, delta=0.5)   # o centro do losango = o centro do cartão

    def test_digit_cells_do_not_shift_when_the_time_changes(self):
        self.skin.current_seconds = 0
        a, _, _ = self.skin.get_digits_geometry()
        self.skin.current_seconds = 3600 * 8 + 60 * 11 + 11
        b, _, _ = self.skin.get_digits_geometry()
        for key in a:
            self.assertAlmostEqual(a[key].left(), b[key].left(), delta=0.01)
            self.assertAlmostEqual(a[key].width(), b[key].width(), delta=0.01)

    def test_buttons_are_centered_as_a_group(self):
        card = self.skin.get_card_rect()
        play, reset = self.skin.get_buttons_geometry()
        self.assertAlmostEqual((play.center().x() + reset.center().x()) / 2.0, card.center().x(), delta=0.5)
        self.assertAlmostEqual(play.center().y(), reset.center().y(), delta=0.01)
        self.assertGreater(play.center().y(), card.top() + sk.DIGITS_CY * self.skin.get_scale())   # abaixo dos números

    def test_hit_testing(self):
        play, reset = self.skin.get_buttons_geometry()
        self.assertIn(self.skin._hit_test(play.center()), ("play_pause", "play_disabled"))
        self.assertEqual(self.skin._hit_test(reset.center()), "reset")
        rects, _, _ = self.skin.get_digits_geometry()
        self.skin.hovered_time_segment = None
        with mock.patch.object(config_manager, "is_timer_smart_hover_enabled", return_value=True):
            self.assertEqual(self.skin._hit_test(rects["minutes"].center()), "time_minutes")
            self.assertEqual(self.skin._hit_test(rects["hours"].center()), "time_hours")
            self.assertEqual(self.skin._hit_test(rects["seconds"].center()), "time_seconds")

    def test_window_has_room_for_the_diamond_tips(self):
        for side in (self.skin.MIN_WIDTH, 164, self.skin.MAX_WIDTH):
            self.skin.set_square_side(side)
            card = self.skin.get_card_rect()
            tip = sk.TIP_OVERSHOOT * self.skin.get_scale()
            self.assertGreaterEqual(card.top() - tip, 0.0)
            self.assertGreaterEqual(self.skin.width() - card.right(), tip)
            self.assertEqual(self.skin.square_side(), side)   # a margem não muda o quadrado

    def test_labels_render_in_every_language_and_mode(self):
        for lang in ("pt", "en"):
            for state in (TimerState(), TimerState(mode="stopwatch"), TimerState(mode="alarm"),
                          TimerState(mode="alarm", is_running=True, alarm_time=7 * 3600 + 1800),
                          TimerState(current_seconds=0, target_duration=300), TimerState(mode="alarm", alarm_finished=True)):
                with mock.patch.object(i18n, "_current_lang", lang):
                    text = mode_label(state)
                items, width = sk._layout_label(text)
                self.assertTrue(items, text)
                self.assertGreater(width, 0)
                img = QImage(164, 164, QImage.Format.Format_ARGB32)
                img.fill(QColor("#000"))
                p = QPainter(img)
                sk.paint_shinra_timer(p, QRectF(0, 0, 164, 164), state)
                p.end()

    def test_portuguese_accents_become_marks_over_plain_letters(self):
        parts = dict(sk._split_accents("CRONÔMETRO"))
        self.assertEqual("".join(b for b, _ in sk._split_accents("CRONÔMETRO")), "CRONOMETRO")
        self.assertIn(("O", "circumflex"), sk._split_accents("CRONÔMETRO"))
        self.assertIn(("I", "acute"), sk._split_accents("CONCLUÍDO"))
        self.assertTrue(parts)

    def test_label_stays_inside_the_max_width(self):
        _, width = sk._layout_label("Temporizador")
        unit = min(sk.LABEL_UNIT, sk.LABEL_MAX_W / width)
        self.assertLessEqual(width * unit, sk.LABEL_MAX_W + 0.01)

    def test_painting_survives_missing_art(self):
        with mock.patch.object(sk, "ART_FILE", os.path.join(tempfile.gettempdir(), "nao-existe.png")), \
                mock.patch.dict(sk._pixmaps, {}, clear=True):
            img = QImage(164, 164, QImage.Format.Format_ARGB32)
            p = QPainter(img)
            sk.paint_shinra_timer(p, QRectF(0, 0, 164, 164), TimerState())
            p.end()

    def test_translations_have_the_skin_subtitle_in_both_languages(self):
        for lang in ("pt", "en"):
            self.assertIn("skin_shinra_sub", TRANSLATIONS[lang])


if __name__ == "__main__":
    unittest.main()
