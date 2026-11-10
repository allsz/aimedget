"""
Testes da arte de tema (fundo e figurinhas) usada pelos flyouts.
  python tests/test_theme_art.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core import theme_art
from app.core.config_manager import config_manager
from app.widgets.keylock_osd import theme as theme_mod
from app.widgets.keylock_osd.skin import KeyLockState, natural_size, paint_keylock
from app.widgets.keylock_osd.theme import DEFAULT_THEME, load_user_theme, theme_from_dict

_app = QApplication.instance() or QApplication([])

RED, GREEN, BLUE = "#ff0000", "#00ff00", "#0000ff"


def make_png(path: str, w: int, h: int, color: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    assert img.save(path)


class _TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "theme")
        os.makedirs(self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def png(self, name, w=20, h=20, color=RED):
        make_png(os.path.join(self.dir, name), w, h, color)


class LoadPixmapTests(_TmpDirCase):
    def test_loads_valid_image(self):
        self.png("a.png", 30, 10)
        pm = theme_art.load_pixmap(self.dir, "a.png")
        self.assertEqual((pm.width(), pm.height()), (30, 10))

    def test_subfolder_is_allowed(self):
        make_png(os.path.join(self.dir, "assets", "a.png"), 5, 5, RED)
        self.assertIsNotNone(theme_art.load_pixmap(self.dir, "assets/a.png"))

    def test_rejects_parent_traversal(self):
        make_png(os.path.join(self._tmp.name, "fora.png"), 5, 5, RED)
        self.assertIsNone(theme_art.load_pixmap(self.dir, "../fora.png"))

    def test_rejects_absolute_path(self):
        other = os.path.join(self._tmp.name, "abs.png")
        make_png(other, 5, 5, RED)
        self.assertIsNone(theme_art.load_pixmap(self.dir, other))

    def test_rejects_unknown_extension_and_missing_file(self):
        with open(os.path.join(self.dir, "x.exe"), "wb") as f:
            f.write(b"MZ")
        self.assertIsNone(theme_art.load_pixmap(self.dir, "x.exe"))
        self.assertIsNone(theme_art.load_pixmap(self.dir, "nao_existe.png"))

    def test_rejects_non_string_and_empty(self):
        for bad in (None, 5, "", "   ", ["a.png"]):
            self.assertIsNone(theme_art.load_pixmap(self.dir, bad))

    def test_rejects_corrupt_image(self):
        with open(os.path.join(self.dir, "ruim.png"), "wb") as f:
            f.write(b"isto nao e um png")
        self.assertIsNone(theme_art.load_pixmap(self.dir, "ruim.png"))

    def test_rejects_oversized_dimensions(self):
        self.png("grande.png", theme_art.MAX_IMAGE_SIDE + 1, 4)
        self.assertIsNone(theme_art.load_pixmap(self.dir, "grande.png"))

    def test_rejects_oversized_file(self):
        self.png("a.png")
        old = theme_art.MAX_FILE_BYTES
        theme_art.MAX_FILE_BYTES = 10
        try:
            self.assertIsNone(theme_art.load_pixmap(self.dir, "a.png"))
        finally:
            theme_art.MAX_FILE_BYTES = old


class ParseTests(_TmpDirCase):
    def test_sticker_size_rules(self):
        self.png("s.png", 40, 20)
        native = theme_art.parse_stickers([{"image": "s.png"}], self.dir)[0]
        self.assertEqual((native.width, native.height), (40, 20))
        by_w = theme_art.parse_stickers([{"image": "s.png", "width": 10}], self.dir)[0]
        self.assertEqual((by_w.width, by_w.height), (10, 5))   # mantém a proporção
        by_h = theme_art.parse_stickers([{"image": "s.png", "height": 10}], self.dir)[0]
        self.assertEqual((by_h.width, by_h.height), (20, 10))
        both = theme_art.parse_stickers([{"image": "s.png", "width": 8, "height": 8}], self.dir)[0]
        self.assertEqual((both.width, both.height), (8, 8))

    def test_invalid_fields_fall_back(self):
        self.png("s.png")
        st = theme_art.parse_stickers(
            [{"image": "s.png", "anchor": "meio", "layer": "x", "opacity": "alta", "rotation": None}], self.dir
        )[0]
        self.assertEqual((st.anchor, st.above, st.opacity, st.rotation), ("center", True, 1.0, 0.0))

    def test_values_are_clamped(self):
        self.png("s.png")
        st = theme_art.parse_stickers(
            [{"image": "s.png", "width": 99999, "x": 99999, "opacity": 7}], self.dir
        )[0]
        self.assertEqual(st.width, theme_art.MAX_STICKER_SIDE)
        self.assertEqual(st.x, theme_art.MAX_OFFSET)
        self.assertEqual(st.opacity, 1.0)

    def test_sticker_limit_and_bad_entries_are_skipped(self):
        self.png("s.png")
        items = [{"image": "s.png"}] * 20 + ["lixo"]
        self.assertEqual(len(theme_art.parse_stickers(items, self.dir)), theme_art.MAX_STICKERS)
        mixed = [{"image": "nao_existe.png"}, "lixo", {"image": "s.png"}]
        self.assertEqual(len(theme_art.parse_stickers(mixed, self.dir)), 1)

    def test_wrong_container_types(self):
        self.assertEqual(theme_art.parse_stickers({"image": "x"}, self.dir), ())
        self.assertIsNone(theme_art.parse_background("fundo.png", self.dir))
        self.assertIsNone(theme_art.parse_background({"image": "nao_existe.png"}, self.dir))

    def test_theme_without_base_dir_ignores_art(self):
        self.png("s.png")
        t = theme_from_dict({"stickers": [{"image": "s.png"}], "background": {"image": "s.png"}})
        self.assertEqual(t, DEFAULT_THEME)

    def test_bad_art_does_not_break_colors(self):
        t = theme_from_dict({"on_color": "#b46cff", "stickers": "oi", "background": 3}, self.dir)
        self.assertEqual(t.on_color, QColor("#b46cff"))
        self.assertIsNone(t.background)


def _render(theme, label="Caps Lock", on=False, anim=0.0):
    st = KeyLockState(label=label, is_on=on, anim_val=anim, theme=theme)
    sz = natural_size(st)
    img = QImage(int(sz.width()) + 80, 130, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(90, 90, 120))
    p = QPainter(img)
    paint_keylock(p, QRectF(40, 40, sz.width(), sz.height()), st)
    p.end()
    return img, sz


def _rgb(c: QColor):
    return (c.red(), c.green(), c.blue())


class PaintTests(_TmpDirCase):
    def test_background_covers_card_and_respects_rounded_corners(self):
        self.png("bg.png", 64, 32, RED)
        t = theme_from_dict({"background": {"image": "bg.png"}}, self.dir)
        img, sz = _render(t)
        self.assertEqual(_rgb(img.pixelColor(40 + int(sz.width()) - 20, 40 + 5)), (255, 0, 0))
        # o canto extremo fica fora do arredondado: continua mostrando o fundo da janela
        self.assertEqual(_rgb(img.pixelColor(41, 41)), (90, 90, 120))

    def test_background_opacity_blends_with_card(self):
        self.png("bg.png", 16, 16, RED)
        t = theme_from_dict({"background": {"image": "bg.png", "opacity": 0.5}}, self.dir)
        img, sz = _render(t)
        px = img.pixelColor(40 + int(sz.width()) - 20, 40 + 5)
        self.assertTrue(100 < px.red() < 200 and px.green() < 100, _rgb(px))

    def test_background_cover_crops_instead_of_distorting(self):
        # imagem 2x1 com metade esquerda vermelha e direita azul; num card ~2.6:1 o corte central
        # mostra as duas metades, e o stretch também — mas cover não pode inventar uma terceira cor
        img = QImage(200, 100, QImage.Format.Format_ARGB32)
        img.fill(QColor(BLUE))
        p = QPainter(img)
        p.fillRect(0, 0, 100, 100, QColor(RED))
        p.end()
        img.save(os.path.join(self.dir, "split.png"))
        t = theme_from_dict({"background": {"image": "split.png", "fit": "cover"}}, self.dir)
        out, sz = _render(t)
        left = _rgb(out.pixelColor(40 + 15, 40 + 25))
        right = _rgb(out.pixelColor(40 + int(sz.width()) - 15, 40 + 25))
        self.assertEqual(left, (255, 0, 0))
        self.assertEqual(right, (0, 0, 255))

    def test_sticker_anchor_and_offset(self):
        self.png("s.png", 10, 10, GREEN)
        t = theme_from_dict(
            {"stickers": [{"image": "s.png", "anchor": "top-right", "x": 5, "y": -5}]}, self.dir
        )
        img, sz = _render(t)
        cx, cy = 40 + int(sz.width()) + 5, 40 - 5
        self.assertEqual(_rgb(img.pixelColor(cx, cy)), (0, 255, 0))      # centro da figurinha, fora do card
        self.assertEqual(_rgb(img.pixelColor(cx - 12, cy)), (90, 90, 120))  # fora da figurinha

    def test_sticker_layers_order(self):
        # 'above' cobre o texto; 'below' fica sob ele (o pixel do centro do texto mantém a cor do texto)
        self.png("s.png", 200, 50, GREEN)
        above = theme_from_dict({"stickers": [{"image": "s.png", "anchor": "center", "layer": "above"}]}, self.dir)
        below = theme_from_dict({"stickers": [{"image": "s.png", "anchor": "center", "layer": "below"}]}, self.dir)
        img_a, sz = _render(above)
        img_b, _ = _render(below)

        def count_green(img):
            n = 0
            for x in range(40, 40 + int(sz.width())):
                for y in range(40, 40 + int(sz.height())):
                    if _rgb(img.pixelColor(x, y)) == (0, 255, 0):
                        n += 1
            return n

        self.assertGreater(count_green(img_a), count_green(img_b))  # 'below' é parcialmente coberto pelo conteúdo

    def test_no_art_renders_same_as_default(self):
        a, _ = _render(DEFAULT_THEME)
        b, _ = _render(theme_from_dict({}, self.dir))
        self.assertEqual(bytes(a.constBits()), bytes(b.constBits()))


class AntialiasingTests(_TmpDirCase):
    def _checkerboard(self, name="check.png", side=512):
        """Tabuleiro 1px preto/branco: bem reduzido vira cinza uniforme; mal reduzido, serrilha."""
        even = bytes([255, 0] * (side // 2))
        odd = bytes([0, 255] * (side // 2))
        data = b"".join(even if y % 2 == 0 else odd for y in range(side))
        gray = QImage(data, side, side, side, QImage.Format.Format_Grayscale8).copy()
        assert gray.convertToFormat(QImage.Format.Format_ARGB32).save(os.path.join(self.dir, name))

    def test_large_sticker_is_presampled_for_smooth_downscale(self):
        self._checkerboard()
        st = theme_art.parse_stickers([{"image": "check.png", "width": 23}], self.dir)[0]
        self.assertEqual(st.pixmap.width(), 23 * theme_art.SUPERSAMPLE)  # pré-reduzido, não 512

        out = QImage(60, 60, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(QColor(128, 128, 128))
        p = QPainter(out)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        theme_art.paint_stickers(p, QRectF(0, 0, 60, 60), (st,), above=True)
        p.end()
        vals = [out.pixelColor(x, y).red() for x in range(24, 37) for y in range(24, 37)]
        self.assertLess(max(vals) - min(vals), 12, "serrilhado: o tabuleiro deveria virar cinza liso")

    def test_small_image_is_not_upscaled(self):
        self.png("pequena.png", 10, 10)
        st = theme_art.parse_stickers([{"image": "pequena.png", "width": 40}], self.dir)[0]
        self.assertEqual((st.pixmap.width(), st.pixmap.height()), (10, 10))

    def test_presample_keeps_transparency_without_dark_fringes(self):
        img = QImage(256, 256, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setBrush(QColor(255, 255, 255))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(40, 40, 176, 176)
        p.end()
        img.save(os.path.join(self.dir, "disco.png"))
        st = theme_art.parse_stickers([{"image": "disco.png", "width": 32}], self.dir)[0]
        out = st.pixmap.toImage()
        for x in range(out.width()):
            c = out.pixelColor(x, out.height() // 2)
            if 0 < c.alpha() < 255:  # pixel de borda: a cor não pode escurecer em direção ao preto
                self.assertGreater(c.red(), 200, f"franja escura na borda: {c.getRgb()}")

    def test_background_scaled_cache_is_reused_per_size(self):
        self.png("bg.png", 600, 300, RED)
        bg = theme_art.parse_background({"image": "bg.png"}, self.dir)
        a = theme_art._background_for_size(bg, 130.0, 48.0)
        self.assertIs(theme_art._background_for_size(bg, 130.0, 48.0), a)
        b = theme_art._background_for_size(bg, 128.0, 48.0)  # outro rótulo = outra largura
        self.assertIsNot(a, b)
        self.assertLessEqual(len(bg._scaled), theme_art._BG_CACHE_MAX)


class LiveReloadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = config_manager.config_dir
        config_manager.config_dir = self._tmp.name
        self._old_cfg_path = config_manager.config_path
        self._old_themes = config_manager._data.get("themes")
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")  # nunca lê/grava a config real
        config_manager._data.pop("themes", None)                                    # sem tema escolhido
        theme_mod.reset_cache()
        self.dir = os.path.dirname(theme_mod.theme_path())
        os.makedirs(self.dir)

    def tearDown(self):
        config_manager.config_dir = self._old_dir
        config_manager.config_path = self._old_cfg_path
        config_manager._data.pop("themes", None)
        if self._old_themes is not None:
            config_manager._data["themes"] = self._old_themes
        theme_mod.reset_cache()
        self._tmp.cleanup()

    def test_reloads_when_only_an_image_changes(self):
        with open(os.path.join(self.dir, "theme.json"), "w", encoding="utf-8") as f:
            json.dump({"background": {"image": "bg.png"}}, f)
        make_png(os.path.join(self.dir, "bg.png"), 8, 8, RED)
        first = load_user_theme()
        self.assertEqual(first.background.pixmap.toImage().pixelColor(0, 0).red(), 255)

        self.assertIs(load_user_theme(), first)  # nada mudou: reaproveita o cache

        make_png(os.path.join(self.dir, "bg.png"), 8, 8, BLUE)
        path = os.path.join(self.dir, "bg.png")
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 5))
        second = load_user_theme()
        self.assertIsNot(second, first)
        self.assertEqual(second.background.pixmap.toImage().pixelColor(0, 0).blue(), 255)


if __name__ == "__main__":
    unittest.main()
