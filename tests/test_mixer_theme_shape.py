"""
Forma própria do Volume e mixer vinda só do tema: inclinação, placas, faixa e algarismos em imagem.
  python tests/test_mixer_theme_shape.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.theme_art import collect_issues, overflow_margins
from app.core.typography import init_app_font
from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout
from app.widgets.volume_mixer.theme import DEFAULT_THEME, theme_from_dict
from app.widgets.volume_mixer.theme_shape import POP_DURATION_S, art_overflow, pop_amount, tilt_transform
from app.ui_components.fluent_slider import FluentSlider

_app = QApplication.instance() or QApplication([])
init_app_font()

PLATE = {"color": "#e5001c", "corners": [[-7, -16], [31, -20], [4, 23], [-30, 12]]}


def _digit_sheet(folder: str, name: str = "digitos.png") -> None:
    """Folha 0-9 em células de 20x30; o algarismo d ocupa (d + 2) colunas no meio da célula."""
    img = QImage(200, 30, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    for d in range(10):
        p.fillRect(d * 20 + 4, 2, d + 2, 26, QColor("#ffffff"))
    p.end()
    assert img.save(os.path.join(folder, name))


def _parse(data: dict, folder: str | None = None):
    with collect_issues() as issues:
        theme = theme_from_dict(data, folder)
    return theme, issues


class ParsingTests(unittest.TestCase):
    def test_defaults_keep_the_original_look(self):
        self.assertEqual(DEFAULT_THEME.tilt, 0.0)
        self.assertEqual(DEFAULT_THEME.slider_style, "fluent")
        self.assertEqual(DEFAULT_THEME.plates, ())
        self.assertIsNone(DEFAULT_THEME.digits)

    def test_shape_tokens_are_read_without_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            _digit_sheet(tmp)
            theme, issues = _parse({
                "tilt": -6, "slider_style": "bar", "slider_height": 13, "slider_slant": 0.35, "plates": [PLATE],
                "digits": {"image": "digitos.png", "height": 40, "x": 2, "y": 6, "spacing": -3, "tilt": [5, -6, 4]},
            }, tmp)
        self.assertEqual(issues, [])
        self.assertEqual(theme.tilt, -6.0)
        self.assertEqual(theme.slider_style, "bar")
        self.assertEqual(len(theme.plates), 1)
        self.assertEqual(theme.plates[0].corners[1], (31.0, -20.0))
        self.assertEqual(len(theme.digits.glyphs), 10)
        self.assertEqual(theme.digits.tilt, (5.0, -6.0, 4.0))

    def test_digit_cells_are_trimmed_to_the_drawn_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            _digit_sheet(tmp)
            theme, _ = _parse({"digits": {"image": "digitos.png"}}, tmp)
        self.assertAlmostEqual(theme.digits.ratios[0], 2 / 30)
        self.assertAlmostEqual(theme.digits.ratios[9], 11 / 30)

    def test_invalid_values_are_reported_and_ignored(self):
        theme, issues = _parse({
            "tilt": 40, "slider_style": "pill",
            "plates": [{"color": "red", "corners": [[0, 0]] * 4}, {"color": "#fff", "corners": [[0, 0]] * 3}],
        })
        self.assertEqual(theme.tilt, 12.0)
        self.assertEqual(theme.slider_style, "fluent")
        self.assertEqual(theme.plates, ())
        self.assertEqual(len(issues), 4, issues)

    def test_header_and_taper_are_read(self):
        theme, issues = _parse({"header": {"slider": [40, 235], "chevron_x": 244}, "slider_taper": 1.3})
        self.assertEqual(issues, [])
        self.assertEqual(theme.header.slider, (40.0, 235.0))
        self.assertEqual(theme.header.chevron_x, 244.0)
        self.assertEqual(theme.slider_taper, 1.3)
        self.assertIsNone(DEFAULT_THEME.header)

    def test_bad_header_is_reported_and_falls_back(self):
        theme, issues = _parse({"header": {"slider": [100, 110], "chevron_x": "x", "extra": 1}})
        self.assertEqual(theme.header.slider, (45.0, 162.0))
        self.assertEqual(theme.header.chevron_x, 203.0)
        self.assertEqual(len(issues), 3, issues)

    def test_missing_digit_image_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            theme, issues = _parse({"digits": {"image": "nao-existe.png"}}, tmp)
        self.assertIsNone(theme.digits)
        self.assertEqual(len(issues), 1)


class GeometryTests(unittest.TestCase):
    def test_plain_themes_keep_the_old_overflow(self):
        self.assertEqual(art_overflow(DEFAULT_THEME, 240.0, (50.0, 370.0)),
                         overflow_margins((), None, 240.0, 370.0))

    def test_plates_and_tilt_grow_the_overflow(self):
        flat, _ = _parse({"plates": [PLATE]})
        self.assertEqual(art_overflow(flat, 240.0, (50.0,)), (30.0, 20.0, 31.0, 23.0))
        tilted, _ = _parse({"plates": [PLATE], "tilt": -6})
        for plain, grown in zip(art_overflow(flat, 240.0, (50.0, 370.0)), art_overflow(tilted, 240.0, (50.0, 370.0))):
            self.assertGreater(grown, plain)

    def test_the_anchored_edge_stays_put_when_tilted(self):
        card = QRectF(10.0, 20.0, 240.0, 50.0)
        for vertical, y in (("top", 20.0), ("middle", 45.0), ("bottom", 70.0)):
            tf = tilt_transform(card, -6.0, vertical)
            mapped = tf.map(QPointF(130.0, y))
            self.assertAlmostEqual(mapped.x(), 130.0)
            self.assertAlmostEqual(mapped.y(), y)
        self.assertIsNone(tilt_transform(card, 0.0, "bottom"))

    def test_pop_fades_out(self):
        self.assertEqual(pop_amount(0.0), 1.0)
        self.assertGreater(pop_amount(POP_DURATION_S / 2), 0.0)
        self.assertEqual(pop_amount(POP_DURATION_S), 0.0)
        self.assertEqual(pop_amount(5.0), 0.0)


class FlyoutTests(unittest.TestCase):
    def test_bar_slider_tapers_to_the_right(self):
        s = FluentSlider(x_start=0.0, x_end=100.0, cy=20.0)
        s.value = 100
        s.apply_style("bar", 10.0, 0.0, 2.0)
        img = QImage(120, 40, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        s.draw(p)
        p.end()

        def height(x):
            return sum(1 for y in range(40) if img.pixelColor(x, y).alpha() > 128)

        self.assertAlmostEqual(height(5), 10, delta=1)
        self.assertAlmostEqual(height(95), 19, delta=2)

    def _flyout(self, data: dict, folder: str | None = None) -> VolumeMixerFlyout:
        f = VolumeMixerFlyout()
        f._slide_t = 1.0
        f._hide_timer.stop()
        f._apply_theme(_parse(data, folder)[0])
        self.addCleanup(f.deleteLater)
        return f

    def test_window_grows_to_fit_plates_and_tilt(self):
        plain = VolumeMixerFlyout()
        self.addCleanup(plain.deleteLater)
        shaped = self._flyout({"plates": [PLATE], "tilt": -6})
        self.assertGreater(shaped.width(), plain.width())
        self.assertGreater(shaped.height(), plain.height())

    def test_sliders_follow_the_bar_style(self):
        f = self._flyout({"slider_style": "bar", "slider_height": 13, "slider_slant": 0.35})
        self.assertEqual((f.master_slider.style, f.master_slider.track_h, f.master_slider.slant), ("bar", 13.0, 0.35))
        f._apply_theme(DEFAULT_THEME)
        self.assertEqual((f.master_slider.style, f.master_slider.track_h), ("fluent", 4.0))

    def test_header_moves_the_slider_and_the_chevron_hit_area(self):
        f = self._flyout({"header": {"slider": [40, 235], "chevron_x": 244}})
        card = f._card_rect()
        self.assertEqual(f._master_span(card.left()), (card.left() + 40.0, card.left() + 235.0))
        self.assertTrue(f._chevron_hit_rect(card.left(), card.top()).contains(QPointF(card.left() + 255, card.top() + 24)))
        self.assertFalse(f._chevron_hit_rect(card.left(), card.top()).contains(QPointF(card.left() + 210, card.top() + 24)))
        wide = f.width()
        self.assertGreater(wide, VolumeMixerFlyout().width() + 20)   # a janela cresce para o botão que passa do cartão

    def test_mouse_point_is_mapped_back_through_the_tilt(self):
        f = self._flyout({"tilt": -6})
        card = f._card_rect()
        chevron = f._chevron_hit_rect(card.left(), card.top()).center()
        on_screen = f._tilt_transform().map(chevron)        # onde o botão aparece depois de inclinado
        self.assertGreater(abs(on_screen.y() - chevron.y()), 3.0)
        back = f._card_point(on_screen)
        self.assertAlmostEqual(back.x(), chevron.x(), places=3)
        self.assertAlmostEqual(back.y(), chevron.y(), places=3)
        self.assertEqual(self._flyout({})._card_point(chevron), chevron)

    def test_plates_are_painted_outside_the_card(self):
        f = self._flyout({"plates": [PLATE], "card_bg": "#00000000", "border": "#00000000",
                          "shadow": {"color": "#00000000", "blur": 0, "dy": 0}})
        img = QImage(f.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        f.render(p, QPoint(0, 0))
        p.end()
        card = f._card_rect()
        above = img.pixelColor(int(card.center().x()), int(card.top() - 8))
        self.assertEqual((above.red(), above.green(), above.blue(), above.alpha()), (229, 0, 28, 255))

    def test_digits_replace_the_number_and_pop_on_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            _digit_sheet(tmp)
            f = self._flyout({"digits": {"image": "digitos.png", "height": 30}}, tmp)
        img = QImage(f.size(), QImage.Format.Format_ARGB32_Premultiplied)

        def paint():
            img.fill(0)
            p = QPainter(img)
            f.render(p, QPoint(0, 0))
            p.end()

        f.on_master_volume_changed(50, False)
        paint()
        self.assertEqual(f._digits_value, 50)
        self.assertEqual(f._digits_pop_start, 0.0, "o primeiro número aparece sem pulo")
        f.on_master_volume_changed(51, False)
        paint()
        self.assertEqual(f._digits_value, 51)
        self.assertGreater(f._digits_pop_start, 0.0)
        f._anim_timer.stop()


if __name__ == "__main__":
    unittest.main()
