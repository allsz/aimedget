"""
Testes do motor de temas: SVG (e sua segurança), camadas, sombras, margem automática da janela,
escala do Caps e seleção de temas.
  python tests/test_theme_engine.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core import theme_art
from app.core.config_manager import config_manager
from app.core.theme_art import (
    CardShadow, overflow_margins, paint_card_shadow, parse_card_shadow, parse_stickers, svg_is_safe,
)
from app.core.typography import init_app_font
from app.widgets.keylock_osd import theme as kl_theme
from app.widgets.volume_mixer import theme as mx_theme

_app = QApplication.instance() or QApplication([])
init_app_font()

SVG_GREEN = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
             '<rect width="48" height="48" fill="#00ff00"/></svg>')
SVG_INTERNAL_REF = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                    'viewBox="0 0 48 48" width="48" height="48"><defs><rect id="a" width="48" height="48" fill="#ff0000"/>'
                    '</defs><use xlink:href="#a"/></svg>')


def _rgb(c: QColor):
    return (c.red(), c.green(), c.blue())


class _Dir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)


class SvgSafetyTests(unittest.TestCase):
    def test_plain_and_internal_references_are_safe(self):
        self.assertTrue(svg_is_safe(SVG_GREEN.encode()))
        self.assertTrue(svg_is_safe(SVG_INTERNAL_REF.encode()))
        self.assertTrue(svg_is_safe(b'<svg><rect fill="url(#grad)"/></svg>'))

    def test_dangerous_content_is_rejected(self):
        bad = [
            b'<svg><script>alert(1)</script></svg>',
            b'<svg><image href="file:///C:/segredo.png"/></svg>',
            b'<svg><image xlink:href="http://x.com/a.png"/></svg>',
            b'<svg><image href="outra.png"/></svg>',
            b'<svg><image href="data:image/png;base64,AAAA"/></svg>',
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>',
            b'<svg><foreignObject><div/></foreignObject></svg>',
            b'<svg><rect style="fill:url(http://x.com/a)"/></svg>',
            b"<svg><rect fill=\"url('file:a.png')\"/></svg>",
        ]
        for data in bad:
            self.assertFalse(svg_is_safe(data), data)


class SvgStickerTests(_Dir):
    def test_svg_sticker_loads_with_requested_size_and_colors(self):
        self.write("a.svg", SVG_GREEN)
        st = parse_stickers([{"image": "a.svg", "width": 20}], self.dir)[0]
        self.assertEqual((st.width, st.height), (20, 20))
        self.assertEqual(st.pixmap.width(), 20 * theme_art.SUPERSAMPLE)  # rasterizado em 2x
        self.assertEqual(_rgb(st.pixmap.toImage().pixelColor(5, 5)), (0, 255, 0))

    def test_render_scale_raises_the_raster_resolution(self):
        self.write("a.svg", SVG_GREEN)
        st = parse_stickers([{"image": "a.svg", "width": 20}], self.dir, render_scale=2.0)[0]
        self.assertEqual(st.pixmap.width(), 20 * theme_art.SUPERSAMPLE * 2)

    def test_native_size_comes_from_the_svg(self):
        self.write("a.svg", SVG_GREEN)
        st = parse_stickers([{"image": "a.svg"}], self.dir)[0]
        self.assertEqual((st.width, st.height), (48, 48))

    def test_internal_references_render(self):
        self.write("a.svg", SVG_INTERNAL_REF)
        st = parse_stickers([{"image": "a.svg", "width": 10}], self.dir)[0]
        self.assertEqual(_rgb(st.pixmap.toImage().pixelColor(5, 5)), (255, 0, 0))

    def test_unsafe_invalid_and_oversized_svgs_are_skipped(self):
        self.write("script.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><script/></svg>')
        self.write("ext.svg", '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                              'width="8" height="8"><image xlink:href="C:/x.png"/></svg>')
        self.write("broken.svg", "isto nao e svg")
        self.write("huge.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="99999" height="99999"/>')
        for name in ("script.svg", "ext.svg", "broken.svg", "huge.svg"):
            self.assertEqual(parse_stickers([{"image": name}], self.dir), (), name)

    def test_svg_file_size_limit(self):
        self.write("a.svg", SVG_GREEN)
        old = theme_art.MAX_SVG_BYTES
        theme_art.MAX_SVG_BYTES = 10
        try:
            self.assertEqual(parse_stickers([{"image": "a.svg"}], self.dir), ())
        finally:
            theme_art.MAX_SVG_BYTES = old

    def test_svg_path_cannot_escape_the_theme_folder(self):
        outside = os.path.join(self.dir, "fora.svg")
        with open(outside, "w", encoding="utf-8") as f:
            f.write(SVG_GREEN)
        sub = os.path.join(self.dir, "tema")
        os.makedirs(sub)
        self.assertEqual(parse_stickers([{"image": "../fora.svg"}], sub), ())

    def test_svg_is_not_accepted_as_background(self):
        self.write("a.svg", SVG_GREEN)
        self.assertIsNone(theme_art.parse_background({"image": "a.svg"}, self.dir))


class StickerLayerAndShadowTests(_Dir):
    def test_layers(self):
        self.write("a.svg", SVG_GREEN)
        items = [{"image": "a.svg", "layer": l} for l in ("behind", "below", "above", "xyz")]
        self.assertEqual([s.layer for s in parse_stickers(items, self.dir)], ["behind", "below", "above", "above"])

    def test_sticker_shadow_grows_the_image_and_adds_soft_pixels(self):
        self.write("a.svg", SVG_GREEN)
        plain = parse_stickers([{"image": "a.svg", "width": 20}], self.dir)[0]
        shad = parse_stickers([{"image": "a.svg", "width": 20, "shadow": True}], self.dir)[0]
        self.assertGreater(shad.width, plain.width)
        self.assertGreater(shad.pixmap.width(), plain.pixmap.width())
        img = shad.pixmap.toImage()
        k = shad.pixmap.width() / shad.width
        # logo abaixo do quadrado verde há sombra translúcida (e não transparência total)
        pad = (shad.width - 20) / 2
        px = img.pixelColor(img.width() // 2, int((pad + 20 + 1.0) * k))
        self.assertTrue(0 < px.alpha() < 255, px.getRgb())

    def test_shadow_options_and_invalid_values(self):
        self.write("a.svg", SVG_GREEN)
        big = parse_stickers([{"image": "a.svg", "width": 20, "shadow": {"blur": 4, "dy": 3, "color": "#ff0000"}}], self.dir)[0]
        small = parse_stickers([{"image": "a.svg", "width": 20, "shadow": True}], self.dir)[0]
        self.assertGreater(big.width, small.width)
        junk = parse_stickers([{"image": "a.svg", "width": 20, "shadow": "sim"}], self.dir)[0]
        self.assertEqual(junk.width, 20)  # valor inválido = sem sombra
        self.assertEqual(parse_stickers([{"image": "a.svg", "width": 20, "shadow": False}], self.dir)[0].width, 20)


class CardShadowTests(unittest.TestCase):
    def test_parse(self):
        self.assertIsNone(parse_card_shadow(None))
        self.assertIsNone(parse_card_shadow(False))
        self.assertIsNone(parse_card_shadow("x"))
        self.assertIsNotNone(parse_card_shadow(True))
        sh = parse_card_shadow({"color": "#46198c96", "blur": 13, "dy": 5})
        self.assertEqual((sh.blur, sh.dy), (13.0, 5.0))
        self.assertEqual(sh.color.alpha(), 0x46)
        self.assertEqual(parse_card_shadow({"blur": 9999}).blur, 60.0)  # limitado

    def _paint(self, w, h, sh, radius=10.0):
        img = QImage(int(w) + 200, int(h) + 200, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        paint_card_shadow(p, QRectF(100, 100, w, h), radius, sh)
        p.end()
        return img

    def test_shadow_surrounds_the_card_and_fades_out(self):
        sh = CardShadow(color=QColor(0, 0, 0, 200), blur=12.0, dy=0.0)
        img = self._paint(120, 60, sh)
        inside = img.pixelColor(160, 130).alpha()
        edge = img.pixelColor(100, 130).alpha()
        outside = img.pixelColor(100 - 3, 130).alpha()   # a sombra se espalha ~0,5 x blur além da borda
        far = img.pixelColor(2, 2).alpha()
        self.assertGreater(inside, edge)
        self.assertGreater(edge, outside)
        self.assertGreater(outside, 0)
        self.assertLess(far, 3)

    def test_dy_moves_the_shadow_down(self):
        sh = CardShadow(color=QColor(0, 0, 0, 200), blur=12.0, dy=10.0)
        img = self._paint(120, 60, sh)
        above = img.pixelColor(160, 100 - 8).alpha()
        below = img.pixelColor(160, 160 + 8).alpha()
        self.assertGreater(below, above)

    def test_works_for_any_card_size_including_animated_heights(self):
        sh = CardShadow(color=QColor(0, 0, 0, 120), blur=11.0, dy=4.0)
        for h in (50, 51, 73, 120, 166, 370):
            img = self._paint(240, h, sh, radius=14.0)
            self.assertGreater(img.pixelColor(220, 100 + h // 2).alpha(), 0, h)  # centro coberto, sem buracos

    def test_transparent_shadow_paints_nothing(self):
        img = self._paint(100, 60, CardShadow(color=QColor(0, 0, 0, 0)))
        self.assertEqual(img.pixelColor(150, 130).alpha(), 0)


class OverflowTests(_Dir):
    def test_no_art_no_overflow(self):
        self.assertEqual(overflow_margins((), None, 135, 50), (0.0, 0.0, 0.0, 0.0))

    def test_sticker_overflow_per_side(self):
        self.write("a.svg", SVG_GREEN)
        st = parse_stickers([{"image": "a.svg", "width": 20, "anchor": "top", "x": 0, "y": -15}], self.dir)
        l, t, r, b = overflow_margins(st, None, 135, 50)
        self.assertAlmostEqual(t, 25.0)   # centro 15 acima da borda + meio sticker (10)
        self.assertEqual((l, r), (0.0, 0.0))
        self.assertEqual(b, 0.0)

    def test_rotation_enlarges_the_box(self):
        self.write("a.svg", SVG_GREEN)
        flat = parse_stickers([{"image": "a.svg", "width": 20, "anchor": "top", "y": -10}], self.dir)
        tilt = parse_stickers([{"image": "a.svg", "width": 20, "anchor": "top", "y": -10, "rotation": 45}], self.dir)
        self.assertGreater(overflow_margins(tilt, None, 135, 50)[1], overflow_margins(flat, None, 135, 50)[1])

    def test_shadow_reach(self):
        sh = CardShadow(color=QColor(0, 0, 0, 100), blur=10.0, dy=6.0)
        l, t, r, b = overflow_margins((), sh, 135, 50)
        self.assertEqual((l, r), (20.0, 20.0))
        self.assertEqual((t, b), (14.0, 26.0))


class ThemeScaleAndTokensTests(_Dir):
    def test_scale_is_parsed_clamped_and_drives_sticker_resolution(self):
        self.write("a.svg", SVG_GREEN)
        t = kl_theme.theme_from_dict({"scale": 2, "stickers": [{"image": "a.svg", "width": 10}]}, self.dir)
        self.assertEqual(t.scale, 2.0)
        self.assertEqual(t.stickers[0].pixmap.width(), 10 * theme_art.SUPERSAMPLE * 2)
        self.assertEqual(kl_theme.theme_from_dict({"scale": 99}).scale, 3.0)
        self.assertEqual(kl_theme.theme_from_dict({"scale": 0.1}).scale, 0.75)
        self.assertEqual(kl_theme.theme_from_dict({"scale": "grande"}).scale, 1.0)

    def test_new_mixer_tokens(self):
        t = mx_theme.theme_from_dict({"divider": "#68ffffff", "thumb_outer": "#ffffff", "button_radius": 99,
                                      "shadow": {"blur": 22, "dy": 9}})
        self.assertEqual(t.divider.alpha(), 0x68)
        self.assertEqual(t.thumb_outer, QColor("#ffffff"))
        self.assertEqual(t.button_radius, 13.0)
        self.assertEqual(t.shadow.blur, 22.0)
        d = mx_theme.DEFAULT_THEME
        self.assertEqual(_rgb(d.thumb_outer), (69, 69, 69))
        self.assertEqual(_rgb(d.divider), (49, 49, 49))
        self.assertIsNone(d.shadow)


class ThemeSelectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir, self._old_path = config_manager.config_dir, config_manager.config_path
        self._old_themes = config_manager._data.get("themes")
        config_manager.config_dir = self._tmp.name
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")  # nunca grava a config real
        config_manager._data.pop("themes", None)
        kl_theme.reset_cache()
        self.base = kl_theme.loader.themes_dir()

    def tearDown(self):
        config_manager.config_dir, config_manager.config_path = self._old_dir, self._old_path
        config_manager._data.pop("themes", None)
        if self._old_themes is not None:
            config_manager._data["themes"] = self._old_themes
        kl_theme.reset_cache()
        self._tmp.cleanup()

    def theme(self, folder, data):
        d = os.path.join(self.base, folder) if folder else self.base
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "theme.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_listing(self):
        self.theme("lavanda", {"name": "Lavanda", "on_color": "#b46cff"})
        self.theme("sem-nome", {"on_color": "#ff0000"})
        self.theme("", {"on_color": "#00ff00"})
        os.makedirs(os.path.join(self.base, "vazia"))               # pasta sem theme.json: ignorada
        ids = [(t.id, t.name) for t in kl_theme.loader.list_themes()]
        self.assertEqual(ids, [("app", "Aimedget"), ("default", ""), ("custom", ""), ("lavanda", "Lavanda"), ("sem-nome", "sem-nome")])

    def test_without_choice_it_keeps_the_previous_behaviour(self):
        self.assertEqual(kl_theme.loader.active_id(), "app")   # instalação nova: tema Aimedget
        self.theme("", {"on_color": "#00ff00"})
        self.assertEqual(kl_theme.loader.active_id(), "custom")
        self.assertEqual(kl_theme.load_user_theme().on_color, QColor("#00ff00"))

    def test_choosing_a_theme_loads_it_and_persists(self):
        self.theme("lavanda", {"on_color": "#b46cff"})
        self.theme("", {"on_color": "#00ff00"})
        kl_theme.loader.set_active("lavanda")
        self.assertEqual(config_manager.get_theme_choice("keylock"), "lavanda")
        self.assertEqual(kl_theme.load_user_theme().on_color, QColor("#b46cff"))
        kl_theme.loader.set_active("default")
        self.assertIs(kl_theme.load_user_theme(), kl_theme.DEFAULT_THEME)  # "padrão" vence o tema solto
        with open(config_manager.config_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["themes"]["keylock"], "default")

    def test_containers_choose_independently(self):
        kl_theme.loader.set_active("lavanda")
        self.assertIsNone(config_manager.get_theme_choice("mixer"))

    def test_missing_or_malicious_ids_fall_back_to_default(self):
        for bad in ("nao_existe", "../fora", "..", "a/b", ".oculto"):
            config_manager.set_theme_choice("keylock", bad)
            kl_theme.reset_cache()
            self.assertIs(kl_theme.load_user_theme(), kl_theme.DEFAULT_THEME, bad)

    def test_theme_folder_assets_and_hot_reload(self):
        self.theme("lavanda", {"stickers": [{"image": "a.svg", "width": 10}]})
        with open(os.path.join(self.base, "lavanda", "a.svg"), "w", encoding="utf-8") as f:
            f.write(SVG_GREEN)
        kl_theme.loader.set_active("lavanda")
        first = kl_theme.load_user_theme()
        self.assertEqual(len(first.stickers), 1)
        self.assertIs(kl_theme.load_user_theme(), first)
        path = os.path.join(self.base, "lavanda", "a.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(SVG_INTERNAL_REF)
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 5))
        self.assertIsNot(kl_theme.load_user_theme(), first)

    def test_root_theme_does_not_see_other_theme_folders_as_its_own_files(self):
        self.theme("", {"on_color": "#00ff00"})
        first = kl_theme.load_user_theme()
        self.theme("lavanda", {"on_color": "#b46cff"})   # mexer em OUTRO tema não deve recarregar este
        self.assertIs(kl_theme.load_user_theme(), first)


class CapsFlyoutGeometryTests(_Dir):
    def _flyout(self, theme):
        from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
        f = KeyLockFlyout()
        f.theme = theme
        f._recalculate_size()
        f.position_on_screen()
        return f

    def test_scale_enlarges_the_window_and_keeps_the_card_centered(self):
        base = self._flyout(kl_theme.DEFAULT_THEME)
        big = self._flyout(kl_theme.theme_from_dict({"scale": 2}))
        self.assertEqual(big.width() - 32, 2 * (base.width() - 32))
        self.assertEqual(big.height() - 38 - 16, 2 * 50)
        screen = QApplication.primaryScreen().availableGeometry()
        ml, _mt, mr, _mb = big._margins
        card_center = big.x() + ml + (big.width() - ml - mr) / 2
        self.assertAlmostEqual(card_center, screen.x() + screen.width() / 2, delta=1.0)

    def test_stickers_make_room_and_card_stays_put(self):
        self.write("a.svg", SVG_GREEN)
        plain = self._flyout(kl_theme.DEFAULT_THEME)
        art = kl_theme.theme_from_dict(
            {"stickers": [{"image": "a.svg", "width": 30, "anchor": "top-left", "x": -20, "y": -25},
                          {"image": "a.svg", "width": 30, "anchor": "bottom-right", "x": 20, "y": 25}]}, self.dir)
        f = self._flyout(art)
        ml, mt, mr, mb = f._margins
        self.assertGreater(ml, 16)
        self.assertGreater(mt, 16)
        self.assertGreater(mr, 16)
        self.assertGreater(f.width(), plain.width())
        # o CARD fica no mesmo lugar da tela; a arte que pende sob ele sobe o conjunto em vez de cair na barra de tarefas
        card_x = f.x() + ml
        self.assertAlmostEqual(card_x, plain.x() + 16, delta=1.0)
        self.assertGreater(f._art_bottom, 0)
        self.assertAlmostEqual(f._get_default_target_y() + mt + 50 + f._art_bottom,
                               plain._get_default_target_y() + 16 + 50, delta=0.01)

    def test_art_is_not_clipped_by_the_window(self):
        self.write("a.svg", SVG_GREEN)
        art = kl_theme.theme_from_dict(
            {"stickers": [{"image": "a.svg", "width": 20, "anchor": "top", "y": -22}]}, self.dir)
        f = self._flyout(art)
        f._popup_progress = f._popup_target = 1.0
        img = QImage(f.width(), f.height(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        try:
            f.render(p, QPoint(0, 0))
        finally:
            p.end()
        ml, mt, _mr, _mb = f._margins
        cx = int(ml + f.card_w / 2)
        self.assertEqual(_rgb(img.pixelColor(cx, int(mt - 22))), (0, 255, 0))   # a figurinha, FORA do card, está na janela

    def test_stacking_clears_the_mixer_artwork(self):
        f = self._flyout(kl_theme.DEFAULT_THEME)
        f.on_mixer_geometry_changed(500.0, True)
        y_plain = f._target_win_y
        self.write("a.svg", SVG_GREEN)
        art = kl_theme.theme_from_dict({"stickers": [{"image": "a.svg", "width": 20, "anchor": "bottom", "y": 15}]}, self.dir)
        g = self._flyout(art)
        g.on_mixer_geometry_changed(500.0, True)
        self.assertLess(g._target_win_y + g._margins[1] + 50 + g._art_bottom, 500.0 - 10 + 0.01)
        self.assertLess(g._target_win_y, y_plain)  # sobe para a arte pendente não encostar no Mixer


class MixerFlyoutGeometryTests(_Dir):
    def _flyout(self, theme):
        from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout
        m = VolumeMixerFlyout()
        m._apply_theme(theme)
        m._slide_t = 1.0
        m._anim_card_h = 50.0
        return m

    def test_card_stays_centered_and_aligned_when_art_adds_margins(self):
        self.write("a.svg", SVG_GREEN)
        plain = self._flyout(mx_theme.DEFAULT_THEME)
        art = mx_theme.theme_from_dict(
            {"shadow": {"blur": 20, "dy": 8},
             "stickers": [{"image": "a.svg", "width": 40, "anchor": "top", "y": -20, "layer": "behind"},
                          {"image": "a.svg", "width": 40, "anchor": "left", "x": -12}]}, self.dir)
        m = self._flyout(art)
        ml, mt, mr, mb = m._margins
        self.assertGreater(mt, 14)
        self.assertGreater(ml, 14)
        r, r0 = m._card_rect(), plain._card_rect()
        self.assertAlmostEqual(m.x() + r.left(), plain.x() + r0.left(), delta=1.0)        # mesmo X do card na tela
        self.assertAlmostEqual(m.y() + r.bottom(), plain.y() + r0.bottom() - m._art_bottom, delta=1.0)
        self.assertEqual(m._card_rect().width(), 240.0)

    def test_visual_top_includes_the_art_so_the_caps_stacks_above_it(self):
        self.write("a.svg", SVG_GREEN)
        art = mx_theme.theme_from_dict(
            {"stickers": [{"image": "a.svg", "width": 40, "anchor": "top", "y": -20}]}, self.dir)
        m = self._flyout(art)
        plain = self._flyout(mx_theme.DEFAULT_THEME)
        m.show(); plain.show()
        try:
            self.assertAlmostEqual(plain.get_card_screen_top() - m.get_card_screen_top(), m._art_top, delta=1.0)
            self.assertGreater(m._art_top, 0)
        finally:
            m.hide(); plain.hide()

    def test_default_theme_margins_are_the_original_ones(self):
        m = self._flyout(mx_theme.DEFAULT_THEME)
        self.assertEqual(m._margins, (14.0, 14.0, 14.0, 14.0))
        self.assertEqual((m._art_top, m._art_bottom), (0.0, 0.0))


    def test_switching_theme_while_visible_resizes_the_window_and_keeps_the_card_in_place(self):
        """Regressão: trocar de tema no Hub com o flyout na tela deixava a janela pequena e cortava o card."""
        self.write("a.svg", SVG_GREEN)
        art = mx_theme.theme_from_dict(
            {"shadow": {"blur": 20, "dy": 8},
             "stickers": [{"image": "a.svg", "width": 40, "anchor": "top", "y": -20, "layer": "behind"},
                          {"image": "a.svg", "width": 40, "anchor": "bottom-left", "x": 20, "y": 16}]}, self.dir)
        for expanded in (False, True):
            m = self._flyout(mx_theme.DEFAULT_THEME)
            m._apply_window_canvas_size(expanded_canvas=expanded)
            m._anim_card_h = float(m.EXPANDED_MAX_H if expanded else m.COLLAPSED_H)
            m.show()
            try:
                r0 = m._card_rect()
                before = (m.x() + r0.left(), m.y() + r0.bottom())
                m._apply_theme(art)                                    # com o flyout VISÍVEL
                ml, mt, mr, mb = m._margins
                max_h = m.EXPANDED_MAX_H if expanded else m.COLLAPSED_H
                self.assertEqual(m.width(), int(m.CARD_W + ml + mr), expanded)
                self.assertEqual(m.height(), int(max_h + mt + mb + m.SLIDE_TRAVEL_PX), expanded)
                r = m._card_rect()
                self.assertGreaterEqual(r.left(), ml - 0.01)
                self.assertGreaterEqual(r.top(), mt - 0.01 if expanded is False else 0)
                self.assertLessEqual(r.right(), m.width())
                self.assertLessEqual(r.bottom(), m.height())
                self.assertAlmostEqual(m.x() + r.left(), before[0], delta=1.0)                       # mesmo X na tela
                self.assertAlmostEqual(m.y() + r.bottom(), before[1] - m._art_bottom, delta=1.0)     # base só sobe pela arte pendente
                m._apply_theme(mx_theme.DEFAULT_THEME)                                              # e de volta ao padrão
                self.assertEqual(m._margins, (14.0, 14.0, 14.0, 14.0))
                r2 = m._card_rect()
                self.assertAlmostEqual(m.x() + r2.left(), before[0], delta=1.0)
                self.assertAlmostEqual(m.y() + r2.bottom(), before[1], delta=1.0)
            finally:
                m.hide()


class AutoScaleTests(_Dir):
    def test_parse_flag(self):
        self.assertFalse(kl_theme.theme_from_dict({}).auto_scale)
        self.assertTrue(kl_theme.theme_from_dict({"auto_scale": True}).auto_scale)
        self.assertFalse(kl_theme.theme_from_dict({"auto_scale": False}).auto_scale)
        self.assertFalse(kl_theme.theme_from_dict({"auto_scale": "sim"}).auto_scale)   # inválido = desligado

    def test_effective_scale(self):
        from unittest import mock
        with mock.patch.object(kl_theme, "screen_ratio", return_value=0.75):
            auto = kl_theme.theme_from_dict({"scale": 1.4, "auto_scale": True})
            fixed = kl_theme.theme_from_dict({"scale": 1.4})
            self.assertAlmostEqual(kl_theme.effective_scale(auto), 1.05)
            self.assertAlmostEqual(kl_theme.effective_scale(fixed), 1.4)               # sem auto_scale: fixo em px
            self.assertEqual(kl_theme.effective_scale(kl_theme.DEFAULT_THEME), 1.0)    # o Padrão nunca escala sozinho
        with mock.patch.object(kl_theme, "screen_ratio", return_value=1.0):             # 1440p: exatamente o escolhido
            self.assertAlmostEqual(kl_theme.effective_scale(auto), 1.4)

    def test_screen_ratio_is_sane(self):
        self.assertTrue(0.5 <= kl_theme.screen_ratio() <= 1.75)

    def test_flyout_follows_the_screen(self):
        from unittest import mock
        from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout

        def card_px(ratio):
            with mock.patch.object(kl_theme, "screen_ratio", return_value=ratio):
                f = KeyLockFlyout()
                f.theme = kl_theme.theme_from_dict({"scale": 1.4, "auto_scale": True})
                f._recalculate_size()
                ml, mt, mr, mb = f._margins
                return f.width() - ml - mr, f.height() - mt - mb, f.card_w
        w1440, h1440, card_w = card_px(1.0)
        w1080, h1080, _ = card_px(0.75)
        w4k, _h4k, _ = card_px(1.5)
        self.assertAlmostEqual(w1440, card_w * 1.4, delta=1.0)
        self.assertAlmostEqual(w1080 / w1440, 0.75, delta=0.02)      # 1080p ocupa a mesma fração da tela
        self.assertAlmostEqual(h1080 / h1440, 0.75, delta=0.03)
        self.assertAlmostEqual(w4k / w1440, 1.5, delta=0.02)

    def test_stickers_are_prepared_for_this_screen(self):
        from unittest import mock
        self.write("a.svg", SVG_GREEN)
        data = {"scale": 1.0, "auto_scale": True, "stickers": [{"image": "a.svg", "width": 10}]}
        with mock.patch.object(kl_theme, "screen_ratio", return_value=1.5):
            big = kl_theme.theme_from_dict(data, self.dir).stickers[0].pixmap.width()
        with mock.patch.object(kl_theme, "screen_ratio", return_value=1.0):
            normal = kl_theme.theme_from_dict(data, self.dir).stickers[0].pixmap.width()
        self.assertEqual(normal, 10 * theme_art.SUPERSAMPLE)
        self.assertEqual(big, 10 * theme_art.SUPERSAMPLE * 1.5)       # mais pixels onde a figurinha será maior

    def test_loader_reloads_when_the_screen_changes(self):
        from unittest import mock
        tmp = tempfile.TemporaryDirectory()
        old_dir, old_path = config_manager.config_dir, config_manager.config_path
        old_themes = config_manager._data.get("themes")
        config_manager.config_dir = tmp.name
        config_manager.config_path = os.path.join(tmp.name, "settings.json")
        config_manager._data.pop("themes", None)
        kl_theme.reset_cache()
        try:
            folder = os.path.join(kl_theme.loader.themes_dir(), "t")
            os.makedirs(folder)
            with open(os.path.join(folder, "theme.json"), "w", encoding="utf-8") as f:
                json.dump({"scale": 1.4, "auto_scale": True}, f)
            kl_theme.loader.set_active("t")
            with mock.patch.object(kl_theme, "screen_ratio", return_value=1.0):
                a = kl_theme.load_user_theme()
                self.assertIs(kl_theme.load_user_theme(), a)
            with mock.patch.object(kl_theme, "screen_ratio", return_value=0.75):
                self.assertIsNot(kl_theme.load_user_theme(), a)        # resolução mudou: prepara de novo
        finally:
            config_manager.config_dir, config_manager.config_path = old_dir, old_path
            config_manager._data.pop("themes", None)
            if old_themes is not None:
                config_manager._data["themes"] = old_themes
            kl_theme.reset_cache()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
