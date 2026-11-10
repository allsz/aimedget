"""
Testes do modo estrito (coleta de problemas) e do validador de temas.
Não tocam na config real: só leem pastas temporárias.
  python tests/test_theme_validation.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.core.theme_art import collect_issues, parse_stickers
from app.core.theme_validation import validate_path, validate_theme_folder
from app.widgets.keylock_osd import theme as kl_theme
from app.widgets.volume_mixer import theme as mx_theme

_app = QApplication.instance() or QApplication([])

SVG_OK = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
          '<rect width="48" height="48" fill="#00ff00"/></svg>')
SVG_EXTERNAL = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
                '<image href="outra.png"/></svg>')


class _Folder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text, folder=None):
        base = os.path.join(self.dir, folder) if folder else self.dir
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, name), "w", encoding="utf-8") as f:
            f.write(text)

    def png(self, name, size=(8, 8), folder=None):
        base = os.path.join(self.dir, folder) if folder else self.dir
        os.makedirs(base, exist_ok=True)
        img = QImage(size[0], size[1], QImage.Format.Format_ARGB32)
        img.fill(QColor("#ff00ff"))
        self.assertTrue(img.save(os.path.join(base, name)))

    def theme(self, data, container="keylock", folder=None):
        self.write("theme.json", json.dumps(data), folder)
        return validate_theme_folder(os.path.join(self.dir, folder) if folder else self.dir, container)


class StrictCollectionTests(_Folder):
    def test_clean_theme_reports_nothing(self):
        with collect_issues() as issues:
            kl_theme.theme_from_dict({"card_bg": "#112233", "radius": 10})
        self.assertEqual(issues, [])

    def test_invalid_color_and_number_are_reported_and_ignored(self):
        with collect_issues() as issues:
            theme = kl_theme.theme_from_dict({"accent_x": 1, "card_bg": "vermelho", "radius": "grande"})
        self.assertEqual(theme.card_bg, kl_theme.DEFAULT_THEME.card_bg)
        self.assertEqual(theme.radius, kl_theme.DEFAULT_THEME.radius)
        text = "\n".join(issues)
        self.assertIn("cor inválida em 'card_bg'", text)
        self.assertIn("'radius' precisa ser um número", text)
        self.assertIn("chave desconhecida 'accent_x'", text)

    def test_out_of_range_number_is_reported_as_clamped(self):
        with collect_issues() as issues:
            theme = mx_theme.theme_from_dict({"radius": 999})
        self.assertEqual(theme.radius, 25.0)
        self.assertTrue(any("'radius' fora do limite" in i for i in issues))

    def test_scale_is_unknown_in_the_mixer_but_valid_in_keylock(self):
        with collect_issues() as mixer_issues:
            mx_theme.theme_from_dict({"scale": 1.5})
        self.assertTrue(any("chave desconhecida 'scale'" in i for i in mixer_issues))
        with collect_issues() as kl_issues:
            kl_theme.theme_from_dict({"scale": 1.5, "auto_scale": True})
        self.assertEqual(kl_issues, [])

    def test_name_and_known_keys_are_not_flagged(self):
        with collect_issues() as issues:
            kl_theme.theme_from_dict({"name": "Meu tema", "shadow": True})
        self.assertEqual(issues, [])

    def test_sticker_problems_say_which_sticker(self):
        self.write("ok.svg", SVG_OK)
        self.write("mau.svg", SVG_EXTERNAL)
        stickers = [
            {"image": "ok.svg"},
            {"image": "mau.svg"},
            {"image": "ok.svg", "anchor": "meio"},
            {"image": "faltando.png"},
            "texto solto",
        ]
        with collect_issues() as issues:
            out = parse_stickers(stickers, self.dir)
        self.assertEqual(len(out), 2)  # a 1ª e a 3ª (com âncora corrigida)
        joined = "\n".join(issues)
        self.assertIn("figurinha 2: SVG recusado por referenciar arquivo externo", joined)
        self.assertIn("figurinha 3: 'anchor' inválido", joined)
        self.assertIn("figurinha 4: imagem não encontrada", joined)
        self.assertIn("figurinha 5: precisa ser um objeto", joined)
        self.assertFalse(any(i.startswith("figurinha 1") for i in issues))

    def test_too_many_stickers_is_reported(self):
        self.write("ok.svg", SVG_OK)
        with collect_issues() as issues:
            out = parse_stickers([{"image": "ok.svg"}] * 14, self.dir)
        self.assertEqual(len(out), 12)
        self.assertTrue(any("as 2 últimas foram ignoradas" in i for i in issues))

    def test_unknown_sticker_key_is_reported(self):
        self.write("ok.svg", SVG_OK)
        with collect_issues() as issues:
            parse_stickers([{"image": "ok.svg", "largura": 20}], self.dir)
        self.assertTrue(any("figurinha 1: chave desconhecida 'largura'" in i for i in issues))

    def test_collecting_does_not_leak_between_scopes(self):
        with collect_issues() as first:
            kl_theme.theme_from_dict({"card_bg": "x"})
        with collect_issues() as second:
            kl_theme.theme_from_dict({})
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        kl_theme.theme_from_dict({"card_bg": "x"})  # fora de um coletor não pode quebrar nem vazar
        self.assertEqual(len(first), 1)


class ValidatorTests(_Folder):
    def test_valid_theme_with_art(self):
        self.write("ok.svg", SVG_OK)
        self.png("fundo.png")
        report = self.theme({"name": "Bonito", "card_bg": "#223344", "background": {"image": "fundo.png"},
                             "stickers": [{"image": "ok.svg", "anchor": "top-right"}]})
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.name, "Bonito")
        self.assertEqual(report.sticker_count, 1)
        for token in ("card_bg", "background", "stickers"):
            self.assertIn(token, report.applied)

    def test_missing_theme_json_is_an_error(self):
        report = validate_theme_folder(self.dir, "keylock")
        self.assertFalse(report.usable)
        self.assertIn("theme.json", report.errors[0])

    def test_broken_json_is_an_error_with_hint(self):
        self.write("theme.json", '{"card_bg": "#fff",}')
        report = validate_theme_folder(self.dir, "keylock")
        self.assertFalse(report.usable)
        self.assertIn("não é um JSON válido", report.errors[0])

    def test_json_must_be_an_object(self):
        self.write("theme.json", "[1, 2]")
        report = validate_theme_folder(self.dir, "mixer")
        self.assertFalse(report.usable)

    def test_issues_do_not_make_the_theme_unusable(self):
        report = self.theme({"card_bg": "nao-eh-cor"})
        self.assertTrue(report.usable)
        self.assertFalse(report.ok)

    def test_long_or_bad_name_is_flagged(self):
        self.assertTrue(any("'name'" in i for i in self.theme({"name": "x" * 60}).issues))
        self.assertTrue(any("'name'" in i for i in self.theme({"name": 5}).issues))

    def test_path_traversal_in_image_is_flagged(self):
        report = self.theme({"background": {"image": "../segredo.png"}})
        self.assertTrue(any("dentro da pasta do tema" in i for i in report.issues))

    def test_container_is_detected_from_folder_names(self):
        self.write("theme.json", "{}", folder=os.path.join("themes", "mixer", "meu"))
        reports = validate_path(os.path.join(self.dir, "themes", "mixer", "meu"))
        self.assertEqual(reports[0].container, "mixer")

    def test_undetectable_container_asks_for_the_flag(self):
        self.write("theme.json", "{}")
        with self.assertRaises(ValueError):
            validate_path(self.dir)
        self.assertEqual(validate_path(self.dir, "keylock")[0].container, "keylock")

    def test_multi_target_package_validates_both(self):
        self.write("theme.json", json.dumps({"card_bg": "#112233"}), folder="keylock")
        self.write("theme.json", json.dumps({"accent": "#b46cff"}), folder="mixer")
        reports = validate_path(self.dir)
        self.assertEqual([r.container for r in reports], ["keylock", "mixer"])
        self.assertTrue(all(r.ok for r in reports))

    def test_missing_folder_raises(self):
        with self.assertRaises(FileNotFoundError):
            validate_path(os.path.join(self.dir, "nao-existe"), "keylock")


class CliTests(_Folder):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools" / "validate_theme.py"), *args],
                              capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT), timeout=60)

    def test_exit_codes_and_messages(self):
        self.write("theme.json", json.dumps({"card_bg": "#112233"}))
        ok = self.run_cli(self.dir, "--container", "keylock")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("tudo certo", ok.stdout)

        self.write("theme.json", json.dumps({"card_bg": "azul"}))
        bad = self.run_cli(self.dir, "--container", "keylock")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("[IGNORADO] cor inválida em 'card_bg'", bad.stdout)

        undetected = self.run_cli(self.dir)
        self.assertEqual(undetected.returncode, 2)
        self.assertIn("--container", undetected.stderr)

    def test_json_output(self):
        self.write("theme.json", json.dumps({"radius": "x"}))
        result = self.run_cli(self.dir, "--container", "mixer", "--json")
        data = json.loads(result.stdout)
        self.assertEqual(data[0]["container"], "mixer")
        self.assertFalse(data[0]["ok"])
        self.assertTrue(any("'radius'" in i for i in data[0]["issues"]))


if __name__ == "__main__":
    unittest.main()
