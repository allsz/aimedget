"""
Testes do tools/pack_theme.py (empacotador) e do diálogo de arquivo não nativo da galeria.
  python tests/test_pack_theme.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.core import theme_package as tp

_app = QApplication.instance() or QApplication([])

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
       '<rect width="48" height="48" fill="#00ff00"/></svg>')


class PackThemeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def folder(self, rel, theme: dict, extra: dict | None = None):
        base = os.path.join(self.root, rel)
        os.makedirs(base, exist_ok=True)
        Path(base, "theme.json").write_text(json.dumps(theme), encoding="utf-8")
        for name, content in (extra or {}).items():
            path = Path(base, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith(".png"):
                img = QImage(8, 8, QImage.Format.Format_ARGB32)
                img.fill(QColor("#ff00ff"))
                self.assertTrue(img.save(str(path)))
            else:
                path.write_bytes(content if isinstance(content, bytes) else str(content).encode("utf-8"))
        return base

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "pack_theme.py"), *args], capture_output=True,
                           text=True, encoding="utf-8", cwd=str(ROOT), timeout=90)
        return r.returncode, r.stdout, r.stderr

    def names(self, path):
        with zipfile.ZipFile(path) as zf:
            return sorted(zf.namelist())

    def test_packs_a_single_theme_folder(self):
        folder = self.folder("keylock/meu", {"name": "Meu Tema", "card_bg": "#112233",
                                             "stickers": [{"image": "s.svg"}]}, {"s.svg": SVG})
        out = os.path.join(self.root, "saida.aimskin")
        code, stdout, _ = self.run_cli(folder, "-o", out)
        self.assertEqual(code, 0, stdout)
        self.assertEqual(self.names(out), ["keylock/s.svg", "keylock/theme.json"])
        self.assertIn("Pacote gerado", stdout)
        self.assertIn("pronto para instalar", stdout)

    def test_default_output_is_next_to_the_folder_named_after_the_theme(self):
        folder = self.folder("keylock/pasta", {"name": "Pôr do Sol"})
        code, stdout, _ = self.run_cli(folder)
        self.assertEqual(code, 0, stdout)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "keylock", "por-do-sol.aimskin")))

    def test_packs_both_flyouts_from_a_pack_folder(self):
        self.folder("pacote/keylock", {"name": "Par", "radius": 5})
        self.folder("pacote/mixer", {"name": "Par", "accent": "#ff00ff"})
        out = os.path.join(self.root, "par.aimskin")
        code, stdout, _ = self.run_cli(os.path.join(self.root, "pacote"), "-o", out)
        self.assertEqual(code, 0, stdout)
        self.assertEqual(self.names(out), ["keylock/theme.json", "mixer/theme.json"])

    def test_issues_block_the_package_unless_allowed(self):
        folder = self.folder("mixer/ruim", {"name": "Ruim", "accent": "azul"})
        out = os.path.join(self.root, "ruim.aimskin")
        code, stdout, _ = self.run_cli(folder, "-o", out)
        self.assertEqual(code, 1)
        self.assertIn("Nada foi gerado", stdout)
        self.assertIn("cor inválida em 'accent'", stdout)
        self.assertFalse(os.path.exists(out))
        code, _stdout, _ = self.run_cli(folder, "-o", out, "--allow-issues")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out))

    def test_errors_always_block(self):
        base = os.path.join(self.root, "keylock", "sem-json")
        os.makedirs(base)
        code, stdout, _ = self.run_cli(base, "--container", "keylock", "--allow-issues", "-o",
                                       os.path.join(self.root, "x.aimskin"))
        self.assertEqual(code, 1)
        self.assertIn("[ERRO]", stdout)

    def test_unused_and_left_out_files_are_reported(self):
        folder = self.folder("keylock/t", {"name": "T", "background": {"image": "fundo.png"}},
                             {"fundo.png": 1, "sobra.png": 1, "projeto.psd": b"8BPS", ".oculto.png": b"x"})
        out = os.path.join(self.root, "t.aimskin")
        code, stdout, _ = self.run_cli(folder, "-o", out)
        self.assertEqual(code, 0, stdout)
        self.assertIn("sobra.png: nenhum campo 'image'", stdout)
        self.assertIn("[FORA DO PACOTE] projeto.psd", stdout)
        self.assertIn("[FORA DO PACOTE] .oculto.png", stdout)
        self.assertEqual(self.names(out), ["keylock/fundo.png", "keylock/sobra.png", "keylock/theme.json"])

    def test_usage_errors(self):
        code, _o, err = self.run_cli(os.path.join(self.root, "nao-existe"), "--container", "keylock")
        self.assertEqual(code, 2)
        self.assertIn("não existe", err)
        loose = self.folder("qualquer", {"name": "X"})
        code, _o, err = self.run_cli(loose)
        self.assertEqual(code, 2)
        self.assertIn("--container", err)

    def test_the_generated_package_imports_back(self):
        folder = self.folder("keylock/ida", {"name": "Ida e Volta", "card_bg": "#223344"})
        out = os.path.join(self.root, "ida.aimskin")
        self.assertEqual(self.run_cli(folder, "-o", out)[0], 0)
        report = tp.analyze_package(out)
        try:
            self.assertEqual((report.name, report.theme_id), ("Ida e Volta", "ida-e-volta"))
            self.assertTrue(report.targets[0].report.ok)
        finally:
            report.close()

    def test_pack_folders_adds_name_and_refuses_bad_input(self):
        folder = self.folder("k", {"radius": 3})
        out = os.path.join(self.root, "n.aimskin")
        tp.pack_folders([("keylock", folder)], out, name="Nome Dado")
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(json.loads(zf.read("keylock/theme.json"))["name"], "Nome Dado")
        with self.assertRaises(tp.PackageError):
            tp.pack_folders([], out)
        with self.assertRaises(tp.PackageError):
            tp.pack_folders([("keylock", os.path.join(self.root, "vazio"))], out)
        with self.assertRaises(ValueError):
            tp.pack_folders([("keylock", folder), ("keylock", folder)], out)


class NativeDialogTests(unittest.TestCase):
    """O seletor é o nativo do Windows (Explorer). Só é seguro com a thread principal em STA: ver test_com_apartment."""

    def setUp(self):
        from app.hub.components import theme_gallery
        self.gallery = theme_gallery
        self._old = theme_gallery._last_dir
        theme_gallery._last_dir = ""

    def tearDown(self):
        self.gallery._last_dir = self._old

    def test_open_starts_in_downloads_and_remembers_the_folder(self):
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog, QWidget
        with tempfile.TemporaryDirectory() as tmp:
            chosen = os.path.join(tmp, "x.aimskin")
            with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(chosen, "")) as m:
                parent = QWidget()
                self.assertEqual(self.gallery._file_dialog(parent, "t", save=False), chosen)
                self.assertEqual(self.gallery._file_dialog(parent, "t", save=False), chosen)
            first, second = m.call_args_list[0].args[2], m.call_args_list[1].args[2]
            self.assertNotEqual(first, tmp)          # primeira vez: Downloads (ou vazio se o SO não tiver)
            self.assertEqual(second, tmp)            # depois: a última pasta usada

    def test_cancel_returns_empty_and_keeps_the_last_folder(self):
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog, QWidget
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=("", "")),                 mock.patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
            parent = QWidget()
            self.assertEqual(self.gallery._file_dialog(parent, "t", save=False), "")
            self.assertEqual(self.gallery._file_dialog(parent, "t", save=True, suggested="x.aimskin"), "")
        self.assertEqual(self.gallery._last_dir, "")

    def test_save_suggests_the_name_and_adds_the_extension(self):
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog, QWidget
        with tempfile.TemporaryDirectory() as tmp:
            self.gallery._last_dir = tmp
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(os.path.join(tmp, "meu"), "")) as m:
                path = self.gallery._file_dialog(QWidget(), "t", save=True, suggested="tema.aimskin")
            self.assertEqual(m.call_args.args[2], os.path.join(tmp, "tema.aimskin"))
            self.assertTrue(path.endswith(".aimskin"))



if __name__ == "__main__":
    unittest.main()
