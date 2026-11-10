"""
Layout do Caps/Num Lock controlado pelo tema: indicator, show_icon, label_align/size/case, text_off, size
e figurinhas com `state` (acendem/apagam com a tecla). Caso real: o tema "Keycap Digital".
  python tests/test_keylock_layout.py
"""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from app.core.theme_art import collect_issues
from app.core.typography import init_app_font
from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
from app.widgets.keylock_osd.skin import KeyLockState, card_size, natural_size, paint_keylock
from app.widgets.keylock_osd.theme import DEFAULT_THEME, theme_from_dict

init_app_font()

LED = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">'
       '<circle cx="10" cy="10" r="9" fill="#ff0000"/></svg>')
PLAIN = {"card_bg": "#202020", "border": "#202020", "text": "#ffffff", "icon": "#ffffff",
         "off_color": "#00ff00", "on_color": "#00ff00"}


def render(theme, is_on=True, anim=None, label="Caps Lock"):
    state = KeyLockState(label=label, is_on=is_on, anim_val=(1.0 if is_on else 0.0) if anim is None else anim,
                         theme=theme)
    size = natural_size(state)
    img = QImage(int(size.width()) + 2, int(size.height()) + 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    try:
        paint_keylock(p, QRectF(1, 1, size.width(), size.height()), state)
    finally:
        p.end()
    return img


def count_color(img, rgb, tol=40):
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            if all(abs(a - b) <= tol for a, b in zip((c.red(), c.green(), c.blue()), rgb)):
                n += 1
    return n


def md5(img):
    return hashlib.md5(bytes(img.constBits())).hexdigest()


class _Dir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def theme(self, data):
        with collect_issues() as issues:
            th = theme_from_dict(data, self.dir)
        self.issues = list(issues)
        return th


class DefaultsTests(unittest.TestCase):
    def test_defaults_keep_the_original_layout(self):
        th = DEFAULT_THEME
        self.assertEqual((th.indicator, th.show_icon, th.label_align, th.label_size, th.label_case),
                         ("bar", True, "left", 14.0, "none"))
        self.assertIsNone(th.text_off)
        self.assertIsNone(th.size)
        self.assertEqual(natural_size().height(), 50.0)
        self.assertEqual(card_size(th, "Caps Lock").width(), natural_size().width())

    def test_explicit_defaults_render_identically(self):
        explicit = theme_from_dict({**PLAIN, "indicator": "bar", "show_icon": True, "label_align": "left",
                                    "label_size": 14, "label_case": "none"})
        plain = theme_from_dict(PLAIN)
        self.assertEqual(md5(render(explicit)), md5(render(plain)))
        self.assertEqual(md5(render(explicit, False)), md5(render(plain, False)))


class LayoutTokenTests(unittest.TestCase):
    def test_indicator_none_removes_the_bar(self):
        bar = render(theme_from_dict(PLAIN))
        none = render(theme_from_dict({**PLAIN, "indicator": "none"}))
        self.assertGreater(count_color(bar, (0, 255, 0)), 100)
        self.assertEqual(count_color(none, (0, 255, 0)), 0)

    def test_show_icon_false_removes_the_padlock_and_narrows_the_card(self):
        with_icon = theme_from_dict(PLAIN)
        no_icon = theme_from_dict({**PLAIN, "show_icon": False})
        self.assertLess(card_size(no_icon, "Caps Lock").width(), card_size(with_icon, "Caps Lock").width())
        # sem o cadeado e sem texto legível, nada branco sobra no canto esquerdo
        img = render(theme_from_dict({**PLAIN, "show_icon": False, "label_align": "center", "indicator": "none",
                                         "size": [240, 60]}))
        left = img.copy(0, 0, 40, img.height())
        self.assertEqual(count_color(left, (255, 255, 255), 60), 0)

    def test_label_case(self):
        t = lambda v: theme_from_dict({**PLAIN, "label_case": v})
        wide = card_size(t("upper"), "Caps Lock").width()
        low = card_size(t("lower"), "Caps Lock").width()
        self.assertNotEqual(wide, low)   # maiúsculas e minúsculas medem diferente: a largura acompanha o texto

    def test_label_size_changes_the_card_and_the_text(self):
        small = theme_from_dict({**PLAIN, "label_size": 12})
        big = theme_from_dict({**PLAIN, "label_size": 24})
        self.assertGreater(card_size(big, "Caps Lock").width(), card_size(small, "Caps Lock").width())

    def test_centered_label_sits_in_the_middle(self):
        th = theme_from_dict({**PLAIN, "indicator": "none", "show_icon": False, "label_align": "center",
                              "size": [160, 60]})
        img = render(th)
        xs = [x for y in range(img.height()) for x in range(img.width())
              if QColor(img.pixel(x, y)).red() > 200 and QColor(img.pixel(x, y)).blue() > 200]
        self.assertTrue(xs)
        middle = (min(xs) + max(xs)) / 2.0
        self.assertAlmostEqual(middle, img.width() / 2.0, delta=4.0)

    def test_text_off_dims_the_label_when_the_key_is_off(self):
        th = theme_from_dict({**PLAIN, "text_off": "#808080", "indicator": "none", "show_icon": False,
                              "label_align": "center", "size": [160, 60]})
        def brightest(img):
            return max(QColor(img.pixel(x, y)).red() for y in range(img.height()) for x in range(img.width()))
        self.assertGreater(brightest(render(th, True)), 240)
        self.assertLess(brightest(render(th, False)), 160)

    def test_size_is_fixed_and_independent_of_the_text(self):
        th = theme_from_dict({**PLAIN, "size": [150, 56]})
        self.assertEqual((card_size(th, "Caps Lock").width(), card_size(th, "Caps Lock").height()), (150.0, 56.0))
        self.assertEqual(card_size(th, "Num Lock"), card_size(th, "Caps Lock"))

    def test_larger_radius_allowed_with_a_taller_card(self):
        with collect_issues() as issues:
            th = theme_from_dict({"size": [140, 100], "radius": 45})
        self.assertEqual(th.radius, 45.0)
        self.assertEqual(list(issues), [])
        with collect_issues() as issues:
            th = theme_from_dict({"radius": 45})
        self.assertEqual(th.radius, 25.0)
        self.assertTrue(issues)


class InvalidValueTests(unittest.TestCase):
    def check(self, data, needle):
        with collect_issues() as issues:
            th = theme_from_dict(data)
        self.assertTrue(any(needle in m for m in issues), (needle, list(issues)))
        return th

    def test_bad_choices_fall_back_with_a_message(self):
        th = self.check({"indicator": "barra"}, "indicator")
        self.assertEqual(th.indicator, "bar")
        th = self.check({"label_align": "right"}, "label_align")
        self.assertEqual(th.label_align, "left")
        th = self.check({"label_case": "title"}, "label_case")
        self.assertEqual(th.label_case, "none")

    def test_bad_types(self):
        self.assertTrue(self.check({"show_icon": "nao"}, "show_icon").show_icon)
        self.assertEqual(self.check({"label_size": "grande"}, "label_size").label_size, 14.0)
        self.assertIsNone(self.check({"size": [100]}, "size").size)
        self.assertIsNone(self.check({"size": "140x52"}, "size").size)
        self.assertEqual(self.check({"label_size": 99}, "label_size").label_size, 40.0)
        self.assertEqual(self.check({"size": [999, 5]}, "size").size, (400.0, 30.0))
        self.assertIsNone(self.check({"text_off": "cinza"}, "text_off").text_off)


class StickerStateTests(_Dir):
    def setUp(self):
        super().setUp()
        self.write("led.svg", LED)

    def led(self, **extra):
        return {"image": "led.svg", "anchor": "top-left", "x": 20, "y": 20, "width": 20, **extra}

    def base(self, stickers, **extra):
        return self.theme({**PLAIN, "indicator": "none", "show_icon": False, "label_align": "center",
                           "size": [140, 52], "stickers": stickers, **extra})

    def test_on_sticker_only_shows_when_on(self):
        th = self.base([self.led(state="on")])
        self.assertEqual(self.issues, [])
        self.assertGreater(count_color(render(th, True), (255, 0, 0)), 50)
        self.assertEqual(count_color(render(th, False), (255, 0, 0)), 0)

    def test_off_sticker_only_shows_when_off(self):
        th = self.base([self.led(state="off")])
        self.assertEqual(count_color(render(th, True), (255, 0, 0)), 0)
        self.assertGreater(count_color(render(th, False), (255, 0, 0)), 50)

    def test_always_is_the_default(self):
        th = self.base([self.led()])
        self.assertGreater(count_color(render(th, True), (255, 0, 0)), 50)
        self.assertGreater(count_color(render(th, False), (255, 0, 0)), 50)

    def test_crossfade_during_the_animation(self):
        th = self.base([self.led(state="on")])
        full = count_color(render(th, True, anim=1.0), (255, 0, 0), tol=20)
        half = count_color(render(th, True, anim=0.5), (255, 0, 0), tol=20)
        self.assertGreater(full, half)           # a meio caminho está mais fraco

    def test_invalid_state_is_reported(self):
        th = self.base([self.led(state="aceso")])
        self.assertTrue(any("state" in m for m in self.issues), self.issues)
        self.assertEqual(th.stickers[0].state, "always")

    def test_state_is_rejected_in_the_mixer(self):
        from app.widgets.volume_mixer.theme import theme_from_dict as mixer_from_dict
        with collect_issues() as issues:
            th = mixer_from_dict({"stickers": [self.led(state="on")]}, self.dir)
        self.assertTrue(any("state" in m and "Caps" in m for m in issues), list(issues))
        self.assertEqual(th.stickers[0].state, "always")


class FlyoutGeometryTests(_Dir):
    def test_flyout_uses_the_theme_card_size(self):
        from app.widgets.keylock_osd import theme as kl
        fly = KeyLockFlyout()
        try:
            fly.theme = theme_from_dict({"size": [150, 80], "scale": 1.0})
            fly.key_label = "Num Lock"
            fly._recalculate_size()
            self.assertEqual((fly.card_w, fly.card_h), (150.0, 80.0))
            self.assertEqual(fly.height(), int(80 * fly._scale + fly._margins[1] + fly._margins[3]))
            fly.theme = DEFAULT_THEME
            fly._recalculate_size()
            self.assertEqual(fly.card_h, 50.0)
        finally:
            fly.deleteLater()


class KeycapDigitalTests(_Dir):
    """O pedido real: sem barrinha, sem cadeado, nome no meio e o LED da tecla acende."""

    def test_keycap_like_theme_validates_clean(self):
        self.write("led.svg", LED)
        th = self.theme({
            "name": "Keycap", "card_bg": "#303033", "text": "#ffffff", "text_off": "#9a9aa0",
            "indicator": "none", "show_icon": False, "label_align": "center", "label_size": 18,
            "label_case": "lower", "size": [140, 52], "radius": 10,
            "stickers": [{"image": "led.svg", "anchor": "top-left", "x": 14, "y": 13, "width": 14, "state": "on"}],
        })
        self.assertEqual(self.issues, [])
        on, off = render(th, True), render(th, False)
        self.assertGreater(count_color(on, (255, 0, 0)), 20)
        self.assertEqual(count_color(off, (255, 0, 0)), 0)


if __name__ == "__main__":
    unittest.main()
