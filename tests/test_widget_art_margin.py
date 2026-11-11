"""
Figurinhas que passam da borda nos widgets (Música e Timer): a janela ganha uma margem transparente só quando o
tema pede, o cartão fica exatamente onde estava e cliques/alça/posição continuam falando do cartão.
"""

import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.widget_theme import MAX_ART_MARGIN, art_margin_px
from app.hub.theme import THEME_DARK
from app.widgets.music.skins import stack_theme
from app.widgets.timer import theme as timer_theme

_app = QApplication.instance() or QApplication(sys.argv)


def _sticker(anchor="top-right", x=-4.0, y=-6.0, width=30.0, **extra):
    from app.core.theme_art import Sticker
    from PySide6.QtGui import QPixmap
    pm = QPixmap(8, 8)
    pm.fill(QColor("#ff00ff"))
    return Sticker(pixmap=pm, anchor=anchor, x=x, y=y, width=width, height=width, **extra)


class MarginMathTests(unittest.TestCase):
    def test_no_stickers_or_all_inside_means_no_margin(self):
        self.assertEqual(art_margin_px((), 148, 148), 0)
        inside = _sticker("center", 0, 0, 20)
        self.assertEqual(art_margin_px((inside,), 148, 148), 0)

    def test_sticker_past_the_edge_asks_for_the_overflow(self):
        # centro em (148 - 4, -6) com 30 de largura: passa 6 + 15 = 21 do topo e 4 + 15 - ... da direita
        m = art_margin_px((_sticker(),), 148, 148)
        self.assertGreaterEqual(m, 20)
        self.assertLessEqual(m, 22)

    def test_free_space_is_discounted_and_scale_applied(self):
        base = art_margin_px((_sticker(),), 148, 148)
        self.assertEqual(art_margin_px((_sticker(),), 148, 148, free=8), base - 8)
        self.assertGreater(art_margin_px((_sticker(),), 148, 148, k=2.0), base)

    def test_margin_is_capped(self):
        self.assertEqual(art_margin_px((_sticker(x=0, y=-500, width=200),), 148, 148), MAX_ART_MARGIN)


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = (config_manager.config_dir, config_manager.config_path, config_manager._data.get("themes"),
                     config_manager._data)
        config_manager.config_dir = self._tmp.name
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")
        config_manager._data = config_manager._default_config()
        for loader in (stack_theme.loader, timer_theme.loader):
            loader.reset()

    def tearDown(self):
        config_manager.config_dir, config_manager.config_path = self._old[0], self._old[1]
        config_manager._data = self._old[3]
        for loader in (stack_theme.loader, timer_theme.loader):
            loader.reset()
        self._tmp.cleanup()

    def install(self, loader, theme_id, data):
        folder = os.path.join(loader.themes_dir(), theme_id)
        os.makedirs(folder, exist_ok=True)
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(QColor("#ff00ff"))
        img.save(os.path.join(folder, "s.png"))
        with open(os.path.join(folder, "theme.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        loader.set_active(theme_id)

    @staticmethod
    def click(widget, pos: QPointF, event_type=QEvent.Type.MouseButtonPress):
        ev = QMouseEvent(event_type, pos, widget.mapToGlobal(pos), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, ev)


PEEK = {"stickers": [{"image": "s.png", "anchor": "top-right", "x": -4, "y": -10, "width": 30}]}
INSIDE = {"stickers": [{"image": "s.png", "anchor": "center", "width": 12}]}


class MusicMarginTests(_Isolated):
    def make(self):
        from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
        skin = CapaEmpilhadaSkin(scale=0.5)
        skin.timer.stop()
        self.addCleanup(skin.close)
        return skin

    def test_without_peeking_art_the_window_is_exactly_the_card(self):
        skin = self.make()
        self.assertEqual(skin.art_margin, 0)
        self.assertEqual((skin.width(), skin.height()), (490, 240))
        self.install(stack_theme.loader, "i", dict(INSIDE, adaptive=True))
        skin.reload_skin_theme()
        self.assertEqual(skin.art_margin, 0)

    def test_peeking_art_grows_the_window_but_not_the_card(self):
        skin = self.make()
        self.install(stack_theme.loader, "p", dict(PEEK, adaptive=True))
        skin.reload_skin_theme()
        m = skin.art_margin
        self.assertGreater(m, 0)
        self.assertEqual(skin._card_size(), (490, 240))
        self.assertEqual((skin.width(), skin.height()), (490 + 2 * m, 240 + 2 * m))
        self.assertEqual(skin.card_rect().topLeft().toPoint(), QPoint(m, m))

    def test_card_stays_put_when_the_theme_changes_and_back(self):
        skin = self.make()
        skin.move(300, 200)
        before = skin.card_origin()
        self.install(stack_theme.loader, "p", dict(PEEK, adaptive=True))
        skin.reload_skin_theme()
        self.assertEqual(skin.card_origin(), before)
        stack_theme.loader.set_active("default")
        skin.reload_skin_theme()
        self.assertEqual(skin.art_margin, 0)
        self.assertEqual(skin.card_origin(), before)
        self.assertEqual(skin.pos(), QPoint(300, 200))

    def test_card_stays_put_when_the_scale_changes(self):
        skin = self.make()
        self.install(stack_theme.loader, "p", dict(PEEK, adaptive=True))
        skin.reload_skin_theme()
        skin.move(300, 200)
        origin = skin.card_origin()
        skin.set_scale(0.7, save_preference=False)
        self.assertEqual(skin.card_origin(), origin)
        self.assertEqual(skin.width(), skin._card_size()[0] + 2 * skin.art_margin)

    def test_move_card_to_and_saved_position_are_about_the_card(self):
        skin = self.make()
        self.install(stack_theme.loader, "p", dict(PEEK, adaptive=True))
        skin.reload_skin_theme()
        skin.move_card_to(500, 400)
        self.assertEqual(skin.card_origin(), QPoint(500, 400))
        self.assertEqual(skin.pos(), QPoint(500 - skin.art_margin, 400 - skin.art_margin))
        skin._toggle_remember_position(True)
        self.assertEqual(config_manager.get_music_saved_position(), (500, 400))

    def test_buttons_and_grip_follow_the_card(self):
        skin = self.make()
        self.install(stack_theme.loader, "p", dict(PEEK, adaptive=True))
        skin.reload_skin_theme()
        m = skin.art_margin
        self.assertEqual(skin._hit_test(skin.rect_main.center()), "main")
        self.assertEqual(skin._hit_test(QPointF(skin.rect_main.center().x() - m, skin.rect_main.center().y() - m)),
                         None if skin.rect_main.contains(QPointF(skin.rect_main.center().x() - m,
                                                                skin.rect_main.center().y() - m)) is False else "main")
        card = skin.card_rect()
        self.assertTrue(skin.is_in_resize_grip(QPointF(card.right() - 4, card.bottom() - 4)))
        self.assertFalse(skin.is_in_resize_grip(QPointF(skin.width() - 1, skin.height() - 1)))   # na margem
        self.assertFalse(skin.is_in_resize_grip(QPointF(10, 10)))

    def test_seek_bar_maps_the_card_not_the_window(self):
        skin = self.make()
        skin.duration = 200.0
        self.install(stack_theme.loader, "p", dict(PEEK, adaptive=True))
        skin.reload_skin_theme()
        s, m = skin.scale, skin.art_margin
        skin._seek_to_x(m + (skin.BAR_X + skin.BAR_W / 2) * s)    # meio da barra
        self.assertAlmostEqual(skin.current_time, 100.0, delta=0.5)

    def test_art_really_paints_outside_the_card(self):
        skin = self.make()
        folder = os.path.join(stack_theme.loader.themes_dir(), "p")
        self.install(stack_theme.loader, "p", dict(PEEK, adaptive=True))
        skin.reload_skin_theme()
        img = QImage(skin.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        skin.render(img, QPoint(0, 0))
        m = skin.art_margin
        # Centro da figurinha: âncora top-right, x=-4, y=-10 (px do cartão); o cartão começa em (m, m)
        cx, cy = m + 490 - 4, m - 10
        self.assertGreater(img.pixelColor(cx, cy).alpha(), 0)
        self.assertLess(cy, m, "o centro da figurinha tem de estar na margem, acima do cartão")
        self.assertEqual(img.pixelColor(2, skin.height() - 3).alpha(), 0)   # o resto da margem é transparente

    def test_osd_anchors_to_the_card(self):
        from app.widgets.music.volume_osd import EDGE_GAP, SHADOW_MARGIN, MusicVolumeOSD
        skin = self.make()
        self.install(stack_theme.loader, "p", dict(PEEK, adaptive=True))
        skin.reload_skin_theme()
        skin.move(100, 120)
        skin.show()
        osd = MusicVolumeOSD()
        self.addCleanup(osd.hide)
        osd.show_for(skin, 50, False)
        body_x = osd.x() + SHADOW_MARGIN
        self.assertEqual(body_x, skin.card_origin().x() + skin._card_size()[0] + EDGE_GAP)

    def test_thumbnail_includes_the_margin_and_restores_the_skin(self):
        from app.widgets.music.skins.stack_theme_specs import _headless, make_theme_spec
        theme = stack_theme.theme_from_dict(dict(PEEK, adaptive=True), self._folder_with_png())
        spec = make_theme_spec("p", "P", theme)
        size = spec.natural_size(spec.mock_state())
        before = (_headless().art_margin, _headless().size())
        self.assertGreater(size.width(), 490)
        self.assertEqual((_headless().art_margin, _headless().size()), before)

    def _folder_with_png(self):
        folder = os.path.join(self._tmp.name, "art")
        os.makedirs(folder, exist_ok=True)
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(QColor("#ff00ff"))
        img.save(os.path.join(folder, "s.png"))
        return folder


class TimerMarginTests(_Isolated):
    def make(self, side=164):
        from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
        skin = WindowsTimerSkin(width=side, height=side)
        self.addCleanup(skin.close)
        return skin

    def test_without_peeking_art_nothing_changes(self):
        skin = self.make()
        self.assertEqual(skin.art_margin, 0)
        self.assertEqual((skin.width(), skin.square_side()), (164, 164))
        self.install(timer_theme.loader, "i", INSIDE)
        skin.reload_skin_theme()
        self.assertEqual(skin.art_margin, 0)

    def test_small_overflow_fits_in_the_existing_shadow_padding(self):
        skin = self.make()
        self.install(timer_theme.loader, "s", {"stickers": [{"image": "s.png", "anchor": "top-left", "x": 6, "y": 6,
                                                              "width": 20}]})
        skin.reload_skin_theme()
        self.assertEqual(skin.art_margin, 0)    # passa ~4 px: cabe nos 8 px de folga que já existem

    def test_peeking_art_grows_the_window_but_not_the_square(self):
        skin = self.make()
        skin.move(300, 200)
        origin = skin.square_origin()
        self.install(timer_theme.loader, "p", PEEK)
        skin.reload_skin_theme()
        m = skin.art_margin
        self.assertGreater(m, 0)
        self.assertEqual(skin.square_side(), 164)
        self.assertEqual(skin.width(), 164 + 2 * m)
        self.assertEqual(skin.square_origin(), origin)
        self.assertEqual(skin.get_card_rect().left(), skin.SHADOW_PAD + m)
        timer_theme.loader.set_active("default")
        skin.reload_skin_theme()
        self.assertEqual((skin.art_margin, skin.width(), skin.pos()), (0, 164, QPoint(300, 200)))

    def test_initial_size_from_settings_is_the_square(self):
        self.install(timer_theme.loader, "p", PEEK)
        timer_theme.loader.reset()
        skin = self.make(side=200)
        self.assertEqual(skin.square_side(), 200)
        self.assertEqual(skin.width(), 200 + 2 * skin.art_margin)

    def test_resizing_keeps_the_corner_and_saves_the_square(self):
        self.install(timer_theme.loader, "p", PEEK)
        timer_theme.loader.reset()
        skin = self.make()
        skin.move(300, 200)
        skin.show()
        origin = skin.square_origin()
        grip = skin.get_resize_grip_rect().center()
        self.click(skin, grip)
        moved = QMouseEvent(QEvent.Type.MouseMove, grip + QPointF(40, 40), skin.mapToGlobal(grip) + QPointF(40, 40),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(skin, moved)
        self.assertEqual(skin.square_side(), 164 + 40)
        self.assertEqual(skin.square_origin(), origin)
        self.assertEqual(skin.width(), skin.square_side() + 2 * skin.art_margin)
        self.click(skin, grip + QPointF(40, 40), QEvent.Type.MouseButtonRelease)
        self.assertEqual(config_manager.get_timer_saved_size(), (204, 204))

    def test_buttons_still_hit_inside_the_card(self):
        self.install(timer_theme.loader, "p", PEEK)
        timer_theme.loader.reset()
        skin = self.make()
        play, reset = skin.get_buttons_geometry()
        self.assertEqual(skin._hit_test(play.center()), "play_pause")
        self.assertEqual(skin._hit_test(reset.center()), "reset")

    def test_art_really_paints_outside_the_card(self):
        self.install(timer_theme.loader, "p", PEEK)
        timer_theme.loader.reset()
        skin = self.make()
        skin.update_theme(THEME_DARK)
        img = QImage(skin.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        skin.render(img, QPoint(0, 0))
        pad = skin.SHADOW_PAD + skin.art_margin       # o cartão começa depois da folga da sombra e da margem
        cx, cy = round(pad + 148 * skin.get_scale() - 4 * skin.get_scale()), round(pad - 10 * skin.get_scale())
        self.assertGreater(img.pixelColor(cx, cy).alpha(), 0)
        self.assertLess(cy, pad, "o centro da figurinha tem de estar fora do cartão, acima dele")

    def test_saved_position_is_the_square_origin(self):
        self.install(timer_theme.loader, "p", PEEK)
        timer_theme.loader.reset()
        skin = self.make()
        skin.move_square_to(500, 400)
        skin._toggle_remember_position(True)
        self.assertEqual(config_manager.get_timer_saved_position(), (500, 400))

    def test_thumbnail_includes_the_margin(self):
        from app.widgets.timer.theme_specs import make_theme_spec
        folder = os.path.join(self._tmp.name, "art")
        os.makedirs(folder, exist_ok=True)
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(QColor("#ff00ff"))
        img.save(os.path.join(folder, "s.png"))
        peek = timer_theme.theme_from_dict(PEEK, folder)
        plain = timer_theme.theme_from_dict({}, folder)
        spec_peek, spec_plain = make_theme_spec("p", "P", peek), make_theme_spec("n", "N", plain)
        self.assertGreater(spec_peek.natural_size(peek).width(), spec_plain.natural_size(plain).width())
        self.assertEqual(spec_plain.natural_size(plain).width(), 164)


if __name__ == "__main__":
    unittest.main()
