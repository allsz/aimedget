"""
Testes do pacote .aimskin: análise segura, relatório, instalação (substituir/cópia) e exportação.
Isolam config_manager (config_dir, config_path e a chave "themes") em pastas temporárias.
  python tests/test_theme_package.py
"""

import json
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.core import theme_package as tp
from app.core.config_manager import config_manager
from app.core.theme_package import PackageError, analyze_package, export_theme, install_package, slugify

_app = QApplication.instance() or QApplication([])

SVG_OK = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
          '<rect width="48" height="48" fill="#00ff00"/></svg>')
SVG_EXTERNAL = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
                '<image href="outra.png"/></svg>')


def png_bytes() -> bytes:
    import io
    from PySide6.QtCore import QBuffer, QIODevice
    img = QImage(8, 8, QImage.Format.Format_ARGB32)
    img.fill(QColor("#ff00ff"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self._old = (config_manager.config_dir, config_manager.config_path, config_manager._data.get("themes"))
        self.cfg = os.path.join(self.root, "cfg")
        os.makedirs(self.cfg)
        config_manager.config_dir = self.cfg
        config_manager.config_path = os.path.join(self.cfg, "settings.json")
        config_manager._data.pop("themes", None)
        self._reports = []

    def tearDown(self):
        for r in self._reports:
            r.close()
        config_manager.config_dir, config_manager.config_path = self._old[0], self._old[1]
        config_manager._data.pop("themes", None)
        if self._old[2] is not None:
            config_manager._data["themes"] = self._old[2]
        self._tmp.cleanup()

    def zip(self, entries: dict, name="t.aimskin") -> str:
        path = os.path.join(self.root, name)
        with zipfile.ZipFile(path, "w") as zf:
            for arc, content in entries.items():
                zf.writestr(arc, content)
        return path

    def analyze(self, entries: dict):
        report = analyze_package(self.zip(entries))
        self._reports.append(report)
        return report

    def themes(self, container):
        return os.path.join(self.cfg, "themes", container)


KL = json.dumps({"name": "Lavanda Teste", "card_bg": "#331144"})
MX = json.dumps({"name": "Lavanda Teste", "accent": "#b46cff"})


class AnalysisTests(_Base):
    def test_multi_target_package(self):
        r = self.analyze({"keylock/theme.json": KL, "mixer/theme.json": MX})
        self.assertEqual([t.container for t in r.targets], ["keylock", "mixer"])
        self.assertTrue(all(t.installable and t.report.ok for t in r.targets))
        self.assertEqual((r.name, r.theme_id), ("Lavanda Teste", "lavanda-teste"))
        self.assertFalse(r.has_collision)

    def test_single_container_folder(self):
        r = self.analyze({"mixer/theme.json": MX})
        self.assertEqual([t.container for t in r.targets], ["mixer"])

    def test_root_theme_json_with_container_key(self):
        r = self.analyze({"theme.json": json.dumps({"name": "X", "container": "keylock", "radius": 4}),
                          "fundo.png": png_bytes()})
        self.assertEqual([t.container for t in r.targets], ["keylock"])
        self.assertTrue(r.targets[0].report.ok, r.targets[0].report.issues)
        self.assertTrue(os.path.isfile(os.path.join(r.targets[0].folder, "fundo.png")))

    def test_root_theme_json_without_container_is_refused(self):
        with self.assertRaisesRegex(PackageError, "container"):
            self.analyze({"theme.json": KL})

    def test_mixing_root_json_and_folders_is_refused(self):
        with self.assertRaisesRegex(PackageError, "mistura"):
            self.analyze({"theme.json": json.dumps({"container": "mixer"}), "keylock/theme.json": KL})

    def test_wrapper_folder_is_stripped(self):
        r = self.analyze({"Lavanda/keylock/theme.json": KL, "Lavanda/mixer/theme.json": MX})
        self.assertEqual([t.container for t in r.targets], ["keylock", "mixer"])

    def test_no_theme_found(self):
        with self.assertRaisesRegex(PackageError, "nenhum tema"):
            self.analyze({"leiame.txt": "oi"})

    def test_not_a_zip(self):
        p = os.path.join(self.root, "x.aimskin")
        Path(p).write_bytes(b"isto nao e um zip")
        with self.assertRaisesRegex(PackageError, "não é um pacote"):
            analyze_package(p)

    def test_target_without_theme_json_is_listed_but_not_installable(self):
        r = self.analyze({"keylock/theme.json": KL, "mixer/fundo.png": png_bytes()})
        by = {t.container: t for t in r.targets}
        self.assertTrue(by["keylock"].installable)
        self.assertFalse(by["mixer"].installable)
        self.assertIn("theme.json", by["mixer"].report.errors[0])

    def test_ignored_files_say_why(self):
        r = self.analyze({"keylock/theme.json": KL, "keylock/programa.exe": b"MZ", "keylock/notas.txt": "x",
                          "keylock/a/b/c/d/e/f.png": png_bytes()})
        reasons = dict(r.ignored_files)
        self.assertIn("tipo de arquivo não permitido", reasons["keylock/programa.exe"])
        self.assertIn("tipo de arquivo não permitido", reasons["keylock/notas.txt"])
        self.assertIn("pasta funda demais", reasons["keylock/a/b/c/d/e/f.png"])
        self.assertFalse(os.path.exists(os.path.join(r.targets[0].folder, "programa.exe")))

    def test_files_outside_flyout_folders_are_ignored(self):
        r = self.analyze({"keylock/theme.json": KL, "outra/coisa.png": png_bytes()})
        self.assertIn(("outra/coisa.png", "fora das pastas keylock/ e mixer/"), r.ignored_files)

    def test_unsafe_svg_and_bad_values_are_reported_not_installed_silently(self):
        theme = json.dumps({"name": "N", "card_bg": "azul", "stickers": [{"image": "mau.svg"}, {"image": "ok.svg"}]})
        r = self.analyze({"keylock/theme.json": theme, "keylock/mau.svg": SVG_EXTERNAL, "keylock/ok.svg": SVG_OK})
        rep = r.targets[0].report
        self.assertTrue(rep.usable)
        self.assertFalse(rep.ok)
        text = "\n".join(rep.issues)
        self.assertIn("cor inválida em 'card_bg'", text)
        self.assertIn("figurinha 1: SVG recusado", text)
        self.assertEqual(rep.sticker_count, 1)

    def test_oversized_file_is_ignored_with_reason_and_reference_is_flagged(self):
        theme = json.dumps({"background": {"image": "gigante.png"}})
        with mock.patch.object(tp, "MAX_FILE_BYTES", 1024):
            r = self.analyze({"keylock/theme.json": theme, "keylock/gigante.png": b"0" * 5000})
        self.assertIn("arquivo grande demais", dict(r.ignored_files)["keylock/gigante.png"])
        self.assertTrue(any("imagem não encontrada" in i for i in r.targets[0].report.issues))

    def test_collision_is_detected(self):
        os.makedirs(os.path.join(self.themes("keylock"), "lavanda-teste"))
        r = self.analyze({"keylock/theme.json": KL, "mixer/theme.json": MX})
        by = {t.container: t for t in r.targets}
        self.assertTrue(by["keylock"].exists)
        self.assertFalse(by["mixer"].exists)
        self.assertTrue(r.has_collision)

    def test_reserved_ids_are_never_used(self):
        r = self.analyze({"keylock/theme.json": json.dumps({"name": "Default"})})
        self.assertEqual(r.theme_id, "default-tema")

    def test_nothing_is_installed_by_analyzing(self):
        self.analyze({"keylock/theme.json": KL})
        self.assertFalse(os.path.exists(self.themes("keylock")))


class SecurityTests(_Base):
    def refuses(self, entries, pattern):
        with self.assertRaisesRegex(PackageError, pattern):
            self.analyze(entries)

    def test_path_traversal(self):
        self.refuses({"keylock/theme.json": KL, "keylock/../../fora.png": b"x"}, r"\.\.")

    def test_backslash_traversal(self):
        self.refuses({"keylock/theme.json": KL, "keylock\\..\\..\\fora.png": b"x"}, r"\.\.")

    def test_absolute_paths(self):
        self.refuses({"/etc/x.json": "{}"}, "absoluto")
        self.refuses({"C:/Windows/x.json": "{}"}, "absoluto")
        self.refuses({"C:\\Windows\\x.json": "{}"}, "absoluto")

    def test_alternate_data_stream_and_forbidden_chars(self):
        self.refuses({"keylock/theme.json:segredo": "x"}, "proibido")
        self.refuses({"keylock/a*b.png": b"x"}, "proibido")

    def test_windows_reserved_names(self):
        self.refuses({"keylock/theme.json": KL, "keylock/CON.png": b"x"}, "reservado")
        self.refuses({"keylock/theme.json": KL, "keylock/nul": b"x"}, "reservado")

    def test_trailing_dot_or_space(self):
        self.refuses({"keylock/theme.json": KL, "keylock/a.png.": b"x"}, "inválido")

    def test_symlink(self):
        path = os.path.join(self.root, "link.aimskin")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("keylock/theme.json", KL)
            info = zipfile.ZipInfo("keylock/atalho.png")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "C:/segredo.png")
        with self.assertRaisesRegex(PackageError, "atalho"):
            analyze_package(path)

    def test_duplicate_names_case_insensitive(self):
        path = os.path.join(self.root, "dup.aimskin")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("keylock/theme.json", KL)
            zf.writestr("keylock/A.png", b"1")
            zf.writestr("keylock/a.PNG", b"2")
        with self.assertRaisesRegex(PackageError, "duas vezes"):
            analyze_package(path)

    def test_too_many_files(self):
        entries = {f"keylock/{i}.png": b"x" for i in range(tp.MAX_FILES + 1)}
        self.refuses(entries, "arquivos demais")

    def test_total_size_by_header(self):
        with mock.patch.object(tp, "MAX_TOTAL_BYTES", 10_000):
            self.refuses({"keylock/theme.json": KL, "keylock/a.png": b"0" * 8000, "keylock/b.png": b"0" * 8000},
                         "grande demais depois de aberto")

    def test_lying_header_is_refused_cleanly(self):
        """Cabeçalho que mente sobre o tamanho: o zipfile só lê o declarado e acusa CRC; vira recusa clara."""
        path = self.zip({"keylock/theme.json": KL, "keylock/a.png": b"0" * 3000})
        real_infolist = zipfile.ZipFile.infolist

        def lying(self_zf):
            infos = real_infolist(self_zf)
            for i in infos:
                if i.filename.endswith("a.png"):
                    i.file_size = 10   # mente: diz 10 bytes
            return infos

        with mock.patch.object(zipfile.ZipFile, "infolist", lying):
            with self.assertRaisesRegex(PackageError, "corrompido"):
                analyze_package(path)

    def test_truncated_zip_is_refused_cleanly(self):
        path = self.zip({"keylock/theme.json": KL, "keylock/a.png": os.urandom(4000)})
        data = Path(path).read_bytes()
        Path(path).write_bytes(data[: len(data) // 2])
        with self.assertRaisesRegex(PackageError, "não é um pacote|corrompido"):
            analyze_package(path)

    def test_encrypted_member(self):
        path = self.zip({"keylock/theme.json": KL})
        data = bytearray(Path(path).read_bytes())
        # liga o bit de criptografia (bit 0 das flags) nos dois cabeçalhos do zip
        for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            i = data.find(sig)
            data[i + off] |= 0x1
        Path(path).write_bytes(bytes(data))
        with self.assertRaisesRegex(PackageError, "senha"):
            analyze_package(path)

    def test_failed_analysis_cleans_the_temp_folder(self):
        before = {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("aimskin-")}
        with self.assertRaises(PackageError):
            self.analyze({"keylock/../x.json": "{}"})
        after = {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("aimskin-")}
        self.assertEqual(before, after)

    def test_package_file_too_big(self):
        p = self.zip({"keylock/theme.json": KL})
        with mock.patch.object(tp, "MAX_PACKAGE_BYTES", 10):
            with self.assertRaisesRegex(PackageError, "grande demais"):
                analyze_package(p)


class InstallTests(_Base):
    def pack(self, **kw):
        entries = {"keylock/theme.json": KL, "keylock/fundo.png": png_bytes(), "mixer/theme.json": MX}
        entries.update(kw)
        return self.analyze(entries)

    def test_install_both_and_files_land_in_theme_folders(self):
        r = self.pack()
        out = install_package(r, ["keylock", "mixer"])
        self.assertEqual({(i.container, i.theme_id, i.replaced) for i in out},
                         {("keylock", "lavanda-teste", False), ("mixer", "lavanda-teste", False)})
        self.assertTrue(os.path.isfile(os.path.join(self.themes("keylock"), "lavanda-teste", "fundo.png")))
        self.assertTrue(os.path.isfile(os.path.join(self.themes("mixer"), "lavanda-teste", "theme.json")))

    def test_install_only_the_chosen_target(self):
        r = self.pack()
        out = install_package(r, ["mixer"])
        self.assertEqual([i.container for i in out], ["mixer"])
        self.assertFalse(os.path.exists(self.themes("keylock")))

    def test_nothing_chosen_is_an_error(self):
        with self.assertRaises(PackageError):
            install_package(self.pack(), [])

    def test_replace_is_default_and_swaps_files(self):
        old = os.path.join(self.themes("keylock"), "lavanda-teste")
        os.makedirs(old)
        Path(old, "theme.json").write_text("{}", encoding="utf-8")
        Path(old, "velho.png").write_bytes(b"x")
        out = install_package(self.pack(), ["keylock"])
        self.assertTrue(out[0].replaced)
        self.assertFalse(os.path.exists(os.path.join(old, "velho.png")))
        self.assertTrue(os.path.isfile(os.path.join(old, "fundo.png")))
        leftovers = [d for d in os.listdir(self.themes("keylock")) if d.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_copy_mode_makes_a_new_id_and_renames(self):
        old = os.path.join(self.themes("keylock"), "lavanda-teste")
        os.makedirs(old)
        Path(old, "theme.json").write_text('{"name": "Original"}', encoding="utf-8")
        out = install_package(self.pack(), ["keylock", "mixer"], mode=tp.COPY)
        self.assertEqual({i.theme_id for i in out}, {"lavanda-teste-2"})
        self.assertTrue(all(not i.replaced for i in out))
        data = json.loads(Path(self.themes("keylock"), "lavanda-teste-2", "theme.json").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "Lavanda Teste (2)")
        self.assertEqual(json.loads(Path(old, "theme.json").read_text(encoding="utf-8"))["name"], "Original")
        out2 = install_package(self.pack(), ["keylock"], mode=tp.COPY)
        self.assertEqual(out2[0].theme_id, "lavanda-teste-3")

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            install_package(self.pack(), ["keylock"], mode="talvez")

    def test_not_installable_target_is_skipped(self):
        r = self.analyze({"keylock/theme.json": KL, "mixer/fundo.png": png_bytes()})
        with self.assertRaises(PackageError):
            install_package(r, ["mixer"])

    def test_failed_swap_restores_the_old_theme(self):
        old = os.path.join(self.themes("keylock"), "lavanda-teste")
        os.makedirs(old)
        Path(old, "theme.json").write_text('{"name": "Antigo"}', encoding="utf-8")
        real_rename = os.rename

        def flaky(src, dst):
            if os.path.basename(src).startswith(".novo-"):
                raise OSError("disco cheio")
            return real_rename(src, dst)

        with mock.patch("os.rename", flaky):
            with self.assertRaises(PackageError):
                install_package(self.pack(), ["keylock"])
        self.assertEqual(json.loads(Path(old, "theme.json").read_text(encoding="utf-8"))["name"], "Antigo")
        self.assertEqual([d for d in os.listdir(self.themes("keylock")) if d.startswith(".")], [])

    def test_installed_theme_is_discovered_by_the_loader(self):
        from app.widgets.keylock_osd import theme as kl_theme
        install_package(self.pack(), ["keylock"])
        ids = [t.id for t in kl_theme.loader.list_themes()]
        self.assertIn("lavanda-teste", ids)
        self.assertEqual(kl_theme.loader.theme_for("lavanda-teste").card_bg, QColor("#331144"))


class ExportTests(_Base):
    def make(self, container, theme_id, files):
        folder = os.path.join(self.themes(container), theme_id) if theme_id != "custom" else self.themes(container)
        os.makedirs(folder, exist_ok=True)
        for name, content in files.items():
            p = os.path.join(folder, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            Path(p).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))

    def test_roundtrip_export_then_import(self):
        self.make("keylock", "meu", {"theme.json": KL, "fundo.png": png_bytes(), "img/estrela.svg": SVG_OK,
                                     "lixo.exe": b"MZ", ".oculto.png": b"x"})
        dest = os.path.join(self.root, "meu.aimskin")
        n = export_theme("keylock", "meu", dest)
        self.assertEqual(n, 3)
        with zipfile.ZipFile(dest) as zf:
            self.assertEqual(sorted(zf.namelist()),
                             ["keylock/fundo.png", "keylock/img/estrela.svg", "keylock/theme.json"])
        r = analyze_package(dest)
        self._reports.append(r)
        self.assertEqual([t.container for t in r.targets], ["keylock"])
        self.assertEqual(r.ignored_files, [])
        # o id importado vem do NOME do tema (slug), não do nome da pasta de quem exportou
        self.assertEqual(r.theme_id, "lavanda-teste")
        self.assertFalse(r.targets[0].exists)

    def test_export_adds_a_name_when_missing_and_keeps_existing_ones(self):
        self.make("keylock", "sem-nome", {"theme.json": json.dumps({"radius": 5})})
        self.make("keylock", "com-nome", {"theme.json": json.dumps({"name": "Bonito", "radius": 5})})
        for tid, title, expected in (("sem-nome", "Meu Tema", "Meu Tema"), ("com-nome", "Outro", "Bonito")):
            dest = os.path.join(self.root, f"{tid}.aimskin")
            export_theme("keylock", tid, dest, name=title)
            with zipfile.ZipFile(dest) as zf:
                data = json.loads(zf.read("keylock/theme.json"))
            self.assertEqual(data["name"], expected)
            self.assertEqual(data["radius"], 5)
        # sem `name` informado, vale o id do tema; e o id importado independe do nome do arquivo
        dest = os.path.join(self.root, "qualquer-nome-de-arquivo.aimskin")
        export_theme("keylock", "sem-nome", dest)
        r = analyze_package(dest)
        self._reports.append(r)
        self.assertEqual(r.theme_id, "sem-nome")

    def test_export_pair_in_one_package_roundtrips_as_multi_target(self):
        self.make("keylock", "par", {"theme.json": KL, "a.png": png_bytes()})
        self.make("mixer", "par", {"theme.json": MX})
        dest = os.path.join(self.root, "par.aimskin")
        self.assertEqual(tp.export_themes([("keylock", "par"), ("mixer", "par")], dest), 3)
        r = analyze_package(dest)
        self._reports.append(r)
        self.assertEqual([t.container for t in r.targets], ["keylock", "mixer"])
        self.assertTrue(tp.has_theme("mixer", "par"))
        self.assertFalse(tp.has_theme("mixer", "naoexiste"))
        self.assertFalse(tp.has_theme("mixer", "default"))
        with self.assertRaises(PackageError):
            tp.export_themes([], dest)
        with self.assertRaises(ValueError):
            tp.export_themes([("mixer", "par"), ("mixer", "par")], dest)

    def test_export_does_not_include_other_themes_nested_in_the_custom_root(self):
        self.make("keylock", "custom", {"theme.json": KL, "fundo.png": png_bytes()})
        self.make("keylock", "outro", {"theme.json": MX, "secreto.png": png_bytes()})
        dest = os.path.join(self.root, "c.aimskin")
        export_theme("keylock", "custom", dest)
        with zipfile.ZipFile(dest) as zf:
            self.assertEqual(sorted(zf.namelist()), ["keylock/fundo.png", "keylock/theme.json"])

    def test_default_and_missing_cannot_be_exported(self):
        with self.assertRaises(PackageError):
            export_theme("keylock", "default", os.path.join(self.root, "x.aimskin"))
        with self.assertRaises(PackageError):
            export_theme("keylock", "nao-existe", os.path.join(self.root, "x.aimskin"))
        with self.assertRaises(PackageError):
            export_theme("keylock", "../x", os.path.join(self.root, "x.aimskin"))


class SlugTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(slugify("Lavanda BT21!"), "lavanda-bt21")
        self.assertEqual(slugify("Pôr do Sol"), "por-do-sol")
        self.assertEqual(slugify("???"), "tema")
        self.assertEqual(slugify("../../x"), "x")


if __name__ == "__main__":
    unittest.main()
