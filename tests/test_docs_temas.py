"""
Mantém docs/temas.md honesto: os exemplos marcados com <!-- validar: keylock|mixer|music|timer --> passam no validador,
toda chave de tema aparece nas tabelas e os limites citados batem com o código.
  python tests/test_docs_temas.py
"""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.core import theme_art, theme_package
from app.core.theme_loader import COMMON_KEYS
from app.core.theme_validation import validate_theme_folder
from app.widgets.keylock_osd import theme as kl_theme
from app.widgets.volume_mixer import theme as mx_theme
from app.widgets.music.skins import stack_theme as mu_theme
from app.widgets.music.skins.stack_palette import get_default_pastel_theme
from app.widgets.timer import theme as tm_theme

_app = QApplication.instance() or QApplication([])

DOC = (ROOT / "docs" / "temas.md").read_text(encoding="utf-8")
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
       '<rect width="48" height="48" fill="#00ff00"/></svg>')


def doc_examples():
    pattern = re.compile(r"<!-- validar: (keylock|mixer|music|timer) -->\s*```json\n(.*?)```", re.S)
    return [(m.group(1), m.group(2)) for m in pattern.finditer(DOC)]


def section(title_start: str) -> str:
    """Texto de uma seção `### x.y ...` até o próximo título `##`/`###`."""
    start = DOC.index(title_start)
    nxt = re.search(r"\n#{2,3} ", DOC[start + 5:])
    return DOC[start: start + 5 + nxt.start()] if nxt else DOC[start:]


class DocExamplesTests(unittest.TestCase):
    def test_there_are_examples_for_every_destination(self):
        kinds = [k for k, _ in doc_examples()]
        self.assertGreaterEqual(kinds.count("keylock"), 2)
        self.assertGreaterEqual(kinds.count("mixer"), 2)
        self.assertGreaterEqual(kinds.count("music"), 1)
        self.assertGreaterEqual(kinds.count("timer"), 1)

    def test_every_example_passes_the_validator_with_no_issues(self):
        for container, text in doc_examples():
            with self.subTest(container=container, start=text[:40]):
                data = json.loads(text)   # o exemplo precisa ser JSON puro
                with tempfile.TemporaryDirectory() as tmp:
                    # cria os arquivos que o exemplo cita (png válido ou svg válido, conforme a extensão)
                    for name in set(re.findall(r'"image":\s*"([^"]+)"', text)):
                        path = os.path.join(tmp, name)
                        if name.endswith(".svg"):
                            Path(path).write_text(SVG, encoding="utf-8")
                        else:
                            img = QImage(40, 40, QImage.Format.Format_ARGB32)
                            img.fill(QColor("#ff00ff"))
                            self.assertTrue(img.save(path))
                    Path(tmp, "theme.json").write_text(json.dumps(data), encoding="utf-8")
                    report = validate_theme_folder(tmp, container)
                self.assertEqual(report.errors, [])
                self.assertEqual(report.issues, [], report.issues)
                self.assertTrue(report.applied)


class DocCoverageTests(unittest.TestCase):
    def keys_in(self, text: str) -> set[str]:
        return set(re.findall(r"^\| `([a-z_]+)` \|", text, re.M))

    def test_every_keylock_key_is_documented(self):
        expected = set(kl_theme._COLOR_KEYS) | set(kl_theme._LAYOUT_KEYS) | {"radius", "scale", "auto_scale"} | set(COMMON_KEYS)
        documented = self.keys_in(section("### 3.2"))
        self.assertEqual(expected - documented, set(), "chave sem linha na tabela 3.2")
        self.assertEqual(documented - expected, set(), "a tabela 3.2 cita chave que não existe")

    def test_every_mixer_key_is_documented(self):
        expected = set(mx_theme._COLOR_KEYS) | {"radius", "button_radius"} | set(COMMON_KEYS)
        documented = self.keys_in(section("### 3.3"))
        self.assertEqual(expected - documented, set(), "chave sem linha na tabela 3.3")
        self.assertEqual(documented - expected, set(), "a tabela 3.3 cita chave que não existe")

    def test_every_music_key_is_documented(self):
        expected = set(mu_theme._PALETTE_KEYS) | set(mu_theme._OTHER_COLORS) | {"adaptive"} | set(COMMON_KEYS)
        documented = self.keys_in(section("### 3.8"))
        self.assertEqual(expected - documented, set(), "chave sem linha na tabela 3.8")
        self.assertEqual(documented - expected, set(), "a tabela 3.8 cita chave que não existe")

    def test_every_timer_key_is_documented(self):
        expected = set(tm_theme._COLOR_TO_HUB) | set(tm_theme.EXTRA_COLOR_KEYS) | set(COMMON_KEYS)
        documented = self.keys_in(section("### 3.9"))
        self.assertEqual(expected - documented, set(), "chave sem linha na tabela 3.9")
        self.assertEqual(documented - expected, set(), "a tabela 3.9 cita chave que não existe")

    def test_music_palette_defaults_match_the_code(self):
        palette = get_default_pastel_theme()
        table = section("### 3.8")
        for key, field in mu_theme._PALETTE_KEYS.items():
            c = getattr(palette, field)
            hexed = (f"#{c.red():02x}{c.green():02x}{c.blue():02x}" if c.alpha() == 255
                     else f"#{c.alpha():02x}{c.red():02x}{c.green():02x}{c.blue():02x}")
            row = re.search(rf"^\| `{key}` \|.*$", table, re.M).group(0)
            self.assertIn(hexed, row, f"{key}: o padrão da doc difere do código")

    def test_sticker_fields_are_documented(self):
        text = section("### 3.6")
        for key in theme_art._STICKER_KEYS_STATE:
            self.assertIn(f"`{key}`", text, f"campo de figurinha sem documentação: {key}")

    def test_color_defaults_in_tables_match_the_code(self):
        def hex_of(c: QColor) -> str:
            if c.alpha() == 255:
                return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"
            return f"#{c.alpha():02x}{c.red():02x}{c.green():02x}{c.blue():02x}"

        for module, anchor in ((kl_theme, "### 3.2"), (mx_theme, "### 3.3")):
            table = section(anchor)
            for key in module._COLOR_KEYS:
                row = re.search(rf"^\| `{key}` \|.*$", table, re.M).group(0)
                default = getattr(module.DEFAULT_THEME, key)
                if default is None:      # cor opcional sem padrão próprio (ex.: text_off): a doc explica de onde vem
                    continue
                self.assertIn(hex_of(default), row, f"{key}: o padrão da doc difere do código")

    def test_limits_match_the_code(self):
        self.assertIn(f"Até {theme_art.MAX_STICKERS}", DOC)
        self.assertIn(f"**{theme_art.MAX_FILE_BYTES // (1024 * 1024)} MB** e **{theme_art.MAX_IMAGE_SIDE} px**", DOC)
        self.assertIn(f"tamanho declarado até **{theme_art.MAX_SVG_SIDE} px**", DOC)
        self.assertIn(f"até **{theme_art.MAX_SVG_BYTES // (1024 * 1024)} MB**", DOC)
        self.assertIn(f"até **{theme_package.MAX_FILES} arquivos**", DOC)
        self.assertIn(f"**{theme_package.MAX_PACKAGE_BYTES // (1024 * 1024)} MB**", DOC)
        self.assertIn(f"até {theme_package.MAX_JSON_BYTES // 1024} KB", DOC)
        self.assertIn(f"subpastas até {theme_package.MAX_DEPTH} níveis", DOC)
        self.assertIn(f"1 a {theme_art.MAX_STICKER_SIDE:.0f}", DOC)
        for ext in theme_package.ALLOWED_EXTENSIONS:
            self.assertIn(f"`{ext}`", DOC)
        lo, hi = kl_theme.SCALE_RANGE
        self.assertIn(f"número {lo:g}–{hi:g}", DOC)
        self.assertIn(f"número 0–{mx_theme.EXTRA_NUMBERS['button_radius'][1]:.0f}", DOC)
        self.assertIn(f"número 0–{kl_theme.RADIUS_RANGE[1]:.0f}", DOC)

    def test_anchors_layers_and_fits_are_listed(self):
        for word in (*theme_art.ANCHORS, *theme_art.LAYERS, *theme_art.FITS):
            self.assertIn(word, DOC)


if __name__ == "__main__":
    unittest.main()
