"""Skin do Timer com arte de um pacote: nome do modo montado com as letras, números e botões centrados na arte."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core import skin_packs
from app.core.config_manager import config_manager
from app.core.i18n import i18n
from app.widgets.timer.skins import art_skin as sk
from app.widgets.timer.skins import init_timer_skin_specs, timer_skin_classes
from app.widgets.timer.skins.skin import TimerState, mode_label
from app.widgets.timer.timer_controller import TimerWidgetController
from skin_pack_fixture import fake_skin_pack, pack_data, write_pack


class DiscoveryTests(unittest.TestCase):
    def test_pack_appears_only_when_its_art_is_present(self):
        with tempfile.TemporaryDirectory() as root:
            write_pack(root, "with-art")
            write_pack(root, "no-art", with_art=False)
            self.assertEqual([p.id for p in skin_packs.discover("timer", [root])], ["with-art"])

    def test_nothing_found_without_a_skins_folder(self):
        self.assertEqual(skin_packs.discover("timer", [os.path.join(tempfile.gettempdir(), "nao-existe-skins")]), [])

    def test_broken_or_foreign_packs_are_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            write_pack(root, "other-widget", pack_data(widget="music"))
            write_pack(root, "Bad Name")
            write_pack(root, "windows")                                    # id reservado
            write_pack(root, "escape", pack_data(art={"file": "../arte.png"}))
            os.makedirs(os.path.join(root, "broken"))
            Path(root, "broken", "skin.json").write_text("{ não é json", encoding="utf-8")
            self.assertEqual(skin_packs.discover("timer", [root]), [])

    def test_texts_follow_the_language_and_fall_back(self):
        with tempfile.TemporaryDirectory() as root:
            write_pack(root, "fake")
            pack = skin_packs.discover("timer", [root])[0]
        self.assertEqual(pack.texts("pt"), ("Fake", "Arte de teste"))
        self.assertEqual(pack.texts("es"), ("Fake", "Test art"))


def _star_art(path: str, side: int = 400):
    """Como o Shinra: um quadrado (o cartão) e outro girado 45° cujas pontas passam da borda (`tip_overshoot`)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    k = side / 1932.0                           # px do PNG por unidade da arte (pack_data: size 1932, origem -154)
    img = QImage(side, side, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setPen(QColor(0, 0, 0, 0))
    p.setBrush(QColor("#aa1122"))
    p.drawRect(QRectF(154 * k, 154 * k, 1624 * k, 1624 * k))
    c = side / 2.0
    p.drawPolygon(QPolygonF([QPointF(c, 0), QPointF(side, c), QPointF(c, side), QPointF(0, c)]))
    p.end()
    img.save(path)


class ArtSkinGlowTests(unittest.TestCase):
    """O brilho de ancorado de uma skin de pacote segue a arte (pontas incluídas), não um retângulo arredondado."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        ctx = fake_skin_pack("star")
        self.pack = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        _star_art(self.pack.path("arte.png"))
        sk._looks.pop(self.pack.folder, None)
        self.skin = sk.make_art_skin_class(self.pack)()
        self.addCleanup(self.skin.deleteLater)
        self.skin.set_square_side(self.skin.square_side())   # margem recalculada com o contorno da arte

    def tearDown(self):
        config_manager.config_path, config_manager._data = self._path, self._data

    def test_outline_is_the_art_with_its_tips(self):
        from app.core import anchor_manager as am
        card = self.skin.get_card_rect()
        box = am.card_shape(self.skin).boundingRect()
        tip = sk.look_for(self.pack).tip_overshoot * max(0.8, card.width() / sk.SIDE)
        self.assertAlmostEqual(card.top() - box.top(), tip, delta=2.0)
        self.assertAlmostEqual(am.shape_overhang(self.skin), tip, delta=2.0)

    def test_glow_lights_beyond_the_tip_and_never_inside_the_art(self):
        from app.core import anchor_manager as am
        from app.ui_components.anchor_net import GlowLayer
        self.skin.resize(self.skin.size())
        layer = GlowLayer(self.skin, lambda: am.card_shape(self.skin))
        layer.set_level(1.0, 1.0, None)
        self.assertGreater(layer.extent(), 3.0)           # a janela tem folga em volta das pontas
        img = QImage(layer.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        layer.render(img)
        box = am.card_shape(self.skin).boundingRect()
        cx = int(box.center().x())
        lit = lambda x, y: img.pixelColor(int(x), int(y)).alpha() > 8   # noqa: E731
        self.assertTrue(lit(cx, box.top() - 2))           # além da ponta de cima
        self.assertFalse(lit(cx, box.top() + 6))          # dentro da ponta: nunca pinta na arte
        card = self.skin.get_card_rect()
        self.assertFalse(lit(card.left() + 3, card.center().y() - card.height() * 0.3))   # dentro do cartão


class ArtSkinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        ctx = fake_skin_pack()
        self.pack = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.look = sk.look_for(self.pack)
        self.skin = sk.make_art_skin_class(self.pack)()
        self.addCleanup(self.skin.deleteLater)

    def tearDown(self):
        config_manager.config_path, config_manager._data = self._path, self._data

    def test_registered_and_selectable(self):
        self.assertIn(self.pack.id, timer_skin_classes())
        self.assertIn(self.pack.id, TimerWidgetController.available_skins())
        spec = next(s for s in init_timer_skin_specs() if s.id == self.pack.id)
        self.assertTrue(spec.available)
        self.assertFalse(spec.supports_themes)

    def test_spec_texts_come_from_the_pack(self):
        spec = next(s for s in init_timer_skin_specs() if s.id == self.pack.id)
        self.assertEqual((spec.title, spec.subtitle), self.pack.texts(i18n.current_language))

    def test_digits_are_centered_on_both_axes(self):
        card, scale = self.skin.get_card_rect(), self.skin.get_scale()
        rects, _, _ = self.skin.get_digits_geometry()
        left, right = rects["hours"].left(), rects["seconds"].right()
        self.assertAlmostEqual((left + right) / 2.0, card.center().x(), delta=0.5)
        self.assertAlmostEqual(rects["hours"].center().y(), card.top() + self.look.digits_cy * scale, delta=0.5)
        self.assertAlmostEqual(self.look.digits_cy, 74.0, delta=0.5)   # o centro da arte = o centro do cartão

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
        self.assertGreater(play.center().y(), card.top() + self.look.digits_cy * self.skin.get_scale())

    def test_hit_testing(self):
        from app.core.config_manager import config_manager as cfg
        play, reset = self.skin.get_buttons_geometry()
        self.assertIn(self.skin._hit_test(play.center()), ("play_pause", "play_disabled"))
        self.assertEqual(self.skin._hit_test(reset.center()), "reset")
        rects, _, _ = self.skin.get_digits_geometry()
        self.skin.hovered_time_segment = None
        with mock.patch.object(cfg, "is_timer_smart_hover_enabled", return_value=True):
            self.assertEqual(self.skin._hit_test(rects["minutes"].center()), "time_minutes")
            self.assertEqual(self.skin._hit_test(rects["hours"].center()), "time_hours")
            self.assertEqual(self.skin._hit_test(rects["seconds"].center()), "time_seconds")

    def test_window_has_room_for_the_art_tips(self):
        for side in (self.skin.MIN_WIDTH, 164, self.skin.MAX_WIDTH):
            self.skin.set_square_side(side)
            card = self.skin.get_card_rect()
            tip = self.look.tip_overshoot * self.skin.get_scale()
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
                items, width = sk._layout_label(text, self.look)
                self.assertTrue(items, text)
                self.assertGreater(width, 0)
                img = QImage(164, 164, QImage.Format.Format_ARGB32)
                img.fill(QColor("#000"))
                p = QPainter(img)
                sk.paint_art_timer(p, QRectF(0, 0, 164, 164), state, pack=self.pack)
                p.end()

    def test_portuguese_accents_become_marks_over_plain_letters(self):
        self.assertEqual("".join(b for b, _ in sk._split_accents("CRONÔMETRO")), "CRONOMETRO")
        self.assertIn(("O", "circumflex"), sk._split_accents("CRONÔMETRO"))
        self.assertIn(("I", "acute"), sk._split_accents("CONCLUÍDO"))

    def test_label_stays_inside_the_max_width(self):
        _, width = sk._layout_label("Temporizador", self.look)
        unit = min(self.look.label_unit, self.look.label_max_w / width)
        self.assertLessEqual(width * unit, self.look.label_max_w + 0.01)

    def test_painting_survives_missing_art(self):
        with tempfile.TemporaryDirectory() as root:
            write_pack(root, "no-art", with_art=False, with_letters=False)
            pack = skin_packs.SkinPack(id="no-art", folder=os.path.join(root, "no-art"), widget="timer", name="x",
                                       subtitle={}, data=pack_data())
            img = QImage(164, 164, QImage.Format.Format_ARGB32)
            p = QPainter(img)
            sk.paint_art_timer(p, QRectF(0, 0, 164, 164), TimerState(), pack=pack)
            p.end()

    def test_a_pack_with_odd_values_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            write_pack(root, "odd", pack_data(digits={"cy": "x", "fonts": []}, colors={"ink": 5}, buttons=[]))
            pack = skin_packs.discover("timer", [root])[0]
            look = sk.ArtLook(pack)
        self.assertGreater(look.digits_cy, 0)
        self.assertTrue(look.ink.isValid())


class ControllerFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_saved_pack_skin_without_its_art_falls_back_to_the_default(self):
        self._path, self._data = config_manager.config_path, config_manager._data
        self.addCleanup(lambda: setattr(config_manager, "config_path", self._path))
        self.addCleanup(lambda: setattr(config_manager, "_data", self._data))
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        config_manager.set_timer_active_skin("fake")
        ctrl = TimerWidgetController()
        self.addCleanup(ctrl.skin.deleteLater)
        self.assertEqual(ctrl.active_skin_name, "windows")


if __name__ == "__main__":
    unittest.main()
