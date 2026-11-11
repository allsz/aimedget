"""
Testes da galeria de temas do Hub: miniaturas independentes do flyout vivo, seleção e selo "EM USO".
Isolam config_manager (config_dir, config_path e a chave "themes") em pastas temporárias.
  python tests/test_theme_gallery.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.typography import init_app_font
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.hub.theme import THEME_DARK
from app.widgets.keylock_osd import theme as kl_theme
from app.widgets.keylock_osd.theme_specs import make_theme_spec as kl_spec
from app.widgets.volume_mixer import theme as mx_theme
from app.widgets.volume_mixer.specs import _get_headless_volume_mixer, paint_volume
from app.widgets.volume_mixer.theme_specs import make_theme_spec as mx_spec

_app = QApplication.instance() or QApplication([])
init_app_font()

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
       '<rect width="48" height="48" fill="#00ff00"/></svg>')


def render(spec, size=None):
    state = spec.mock_state()
    nat = spec.natural_size(state) if callable(spec.natural_size) else spec.natural_size
    w, h = int(nat.width()), int(nat.height())
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    try:
        spec.paint(p, QRectF(0, 0, nat.width(), nat.height()), state, None)
    finally:
        p.end()
    return img


def opaque_in(img: QImage, x0, y0, x1, y1) -> bool:
    return any(img.pixelColor(x, y).alpha() > 0
               for x in range(max(0, x0), min(img.width(), x1))
               for y in range(max(0, y0), min(img.height(), y1)))


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = (config_manager.config_dir, config_manager.config_path, config_manager._data.get("themes"))
        config_manager.config_dir = self._tmp.name
        config_manager.config_path = os.path.join(self._tmp.name, "settings.json")
        # Estes testes cobrem temas de pasta; o Aimedget (padrão de instalação nova) tem testes próprios
        config_manager._data["themes"] = {"keylock": "default", "mixer": "default"}
        for loader in (kl_theme.loader, mx_theme.loader):
            loader.reset()
            loader._preview_cache.clear()

    def tearDown(self):
        config_manager.config_dir, config_manager.config_path = self._old[0], self._old[1]
        config_manager._data.pop("themes", None)
        if self._old[2] is not None:
            config_manager._data["themes"] = self._old[2]
        self._tmp.cleanup()

    def make_theme(self, loader, theme_id, data, svg=False):
        folder = os.path.join(loader.themes_dir(), theme_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "theme.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        if svg:
            with open(os.path.join(folder, "s.svg"), "w", encoding="utf-8") as f:
                f.write(SVG)
        return folder


class ThemeForTests(_Isolated):
    def test_theme_for_does_not_touch_active_choice_or_live_cache(self):
        self.make_theme(kl_theme.loader, "roxo", {"card_bg": "#331144"})
        live_before = kl_theme.loader.load()
        theme = kl_theme.loader.theme_for("roxo")
        self.assertEqual(theme.card_bg, QColor("#331144"))
        self.assertEqual(kl_theme.loader.active_id(), "default")
        self.assertIs(kl_theme.loader.load(), live_before)

    def test_same_object_until_files_change(self):
        folder = self.make_theme(kl_theme.loader, "roxo", {"card_bg": "#331144"})
        first = kl_theme.loader.theme_for("roxo")
        self.assertIs(kl_theme.loader.theme_for("roxo"), first)
        with open(os.path.join(folder, "theme.json"), "w", encoding="utf-8") as f:
            json.dump({"card_bg": "#112233", "radius": 3}, f)
        self.assertIsNot(kl_theme.loader.theme_for("roxo"), first)

    def test_default_missing_and_unsafe_ids_give_default(self):
        d = kl_theme.loader.default
        self.assertIs(kl_theme.loader.theme_for("default"), d)
        self.assertIs(kl_theme.loader.theme_for("nao-existe"), d)
        self.assertIs(kl_theme.loader.theme_for("../x"), d)


class KeylockThumbnailTests(_Isolated):
    def test_art_that_overflows_the_card_is_inside_the_thumbnail(self):
        self.make_theme(kl_theme.loader, "arte", {
            "stickers": [{"image": "s.svg", "anchor": "top-right", "x": 4, "y": -10, "width": 30}]}, svg=True)
        themed = kl_theme.loader.theme_for("arte")
        plain = render(kl_spec("default", "Padrão", kl_theme.DEFAULT_THEME))
        img = render(kl_spec("arte", "Arte", themed))
        self.assertGreater(img.height(), plain.height())            # ganhou espaço em cima para a figurinha
        self.assertTrue(opaque_in(img, img.width() - 12, 0, img.width(), 8))   # e ela está lá (verde)
        self.assertGreater(img.pixelColor(img.width() - 6, 3).green(), 150)

    def test_scale_makes_the_thumbnail_larger(self):
        self.make_theme(kl_theme.loader, "grande", {"scale": 2.0})
        base = kl_spec("default", "x", kl_theme.DEFAULT_THEME)
        big = kl_spec("grande", "x", kl_theme.loader.theme_for("grande"))
        nb, ng = base.natural_size(base.mock_state()), big.natural_size(big.mock_state())
        self.assertGreater(ng.width(), nb.width() * 1.8)

    def test_does_not_change_live_flyout_state(self):
        self.make_theme(kl_theme.loader, "x", {"card_bg": "#ff0000"})
        before = kl_theme.loader.load()
        render(kl_spec("x", "x", kl_theme.loader.theme_for("x")))
        self.assertIs(kl_theme.loader.load(), before)


class MixerThumbnailTests(_Isolated):
    def test_default_thumbnail_matches_legacy_paint(self):
        """O Visual Padrão na galeria é o mesmo desenho da miniatura da Visão geral (dentro da região do card)."""
        spec = mx_spec("default", "Padrão", mx_theme.DEFAULT_THEME)
        new = render(spec)
        old = QImage(new.size(), QImage.Format.Format_ARGB32)
        old.fill(QColor(0, 0, 0, 0))
        p = QPainter(old)
        try:
            paint_volume(p, QRectF(0, 0, new.width(), new.height()), None, None)
        finally:
            p.end()
        self.assertEqual(new, old)

    def test_theme_is_applied_during_paint_and_default_restored_after(self):
        self.make_theme(mx_theme.loader, "verde", {"card_bg": "#00aa00"})
        themed = mx_theme.loader.theme_for("verde")
        img = render(mx_spec("verde", "Verde", themed))
        c = img.pixelColor(img.width() - 24, img.height() - 24)   # canto interno do card: só o fundo
        self.assertGreater(c.green(), c.red() + 40)   # o fundo do card ficou verde
        self.assertIs(_get_headless_volume_mixer().theme, mx_theme.DEFAULT_THEME)

    def test_sticker_overflow_gets_room_and_appears(self):
        self.make_theme(mx_theme.loader, "arte", {
            "stickers": [{"image": "s.svg", "anchor": "top-right", "x": 6, "y": -20, "width": 40,
                          "shadow": False}]}, svg=True)
        themed = mx_theme.loader.theme_for("arte")
        plain = mx_spec("default", "x", mx_theme.DEFAULT_THEME)
        spec = mx_spec("arte", "x", themed)
        self.assertGreater(spec.natural_size(themed).height(), plain.natural_size(plain.mock_state()).height())
        img = render(spec)
        self.assertTrue(any(img.pixelColor(x, y).green() > 150 and img.pixelColor(x, y).red() < 80
                            for x in range(img.width() - 40, img.width()) for y in range(0, 20)))

    def test_live_flyout_is_a_different_object(self):
        from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout
        live = VolumeMixerFlyout()
        self.assertIsNot(live, _get_headless_volume_mixer())


class GalleryCardTests(_Isolated):
    def build(self, loader=None, make=None, container="keylock", appliers=None):
        loader = loader or kl_theme.loader
        applied = []
        card = ThemeGalleryCard(loader, container, make or kl_spec, lambda: applied.append(1), THEME_DARK,
                                appliers=appliers)
        card.resize(900, 300)
        return card, applied

    def test_one_card_per_theme_without_menu_toggle(self):
        self.make_theme(kl_theme.loader, "a", {"name": "Alfa"})
        self.make_theme(kl_theme.loader, "b", {"name": "Beta"})
        card, _ = self.build()
        self.assertEqual(list(card._cards), ["app", "default", "a", "b"])
        for c in card._cards.values():
            self.assertIsNone(c.toggle_switch)
        self.assertEqual(card._cards["a"]._spec.title, "Alfa")

    def test_click_selects_saves_and_calls_on_applied(self):
        self.make_theme(kl_theme.loader, "a", {})
        card, applied = self.build()
        self.assertTrue(card._cards["default"].is_selected())
        card._cards["a"].clicked.emit("a")
        self.assertEqual(kl_theme.loader.active_id(), "a")
        self.assertTrue(card._cards["a"].is_selected())
        self.assertFalse(card._cards["default"].is_selected())
        self.assertEqual(applied, [1])

    def test_missing_saved_theme_marks_default(self):
        config_manager.set_theme_choice("keylock", "sumiu")
        card, _ = self.build()
        self.assertTrue(card._cards["default"].is_selected())

    def test_refresh_keeps_cards_when_nothing_changed_and_rebuilds_when_it_did(self):
        self.make_theme(kl_theme.loader, "a", {})
        card, _ = self.build()
        before = card._cards["a"]
        card.refresh()
        self.assertIs(card._cards["a"], before)
        self.make_theme(kl_theme.loader, "b", {})
        card.refresh()
        self.assertIn("b", card._cards)

    def test_works_for_the_mixer_too(self):
        self.make_theme(mx_theme.loader, "m", {"name": "Meu"})
        card, _ = self.build(mx_theme.loader, mx_spec, "mixer")
        self.assertEqual(list(card._cards), ["app", "default", "m"])
        card.grab()   # pinta tudo (miniaturas inclusas) sem erro
        self.assertIs(_get_headless_volume_mixer().theme, mx_theme.DEFAULT_THEME)


class ImportExportUiTests(_Isolated):
    KL = json.dumps({"name": "Pacote", "card_bg": "#112233"})
    MX = json.dumps({"name": "Pacote", "accent": "#aa00ff"})

    def build(self, container="keylock", appliers=None):
        loader, make = (kl_theme.loader, kl_spec) if container == "keylock" else (mx_theme.loader, mx_spec)
        calls = []
        appl = appliers if appliers is not None else {
            "keylock": lambda: calls.append("keylock"), "mixer": lambda: calls.append("mixer")}
        card = ThemeGalleryCard(loader, container, make, lambda: None, THEME_DARK, appliers=appl)
        card.resize(900, 300)
        return card, calls

    def package(self, entries):
        import zipfile
        path = os.path.join(self._tmp.name, "p.aimskin")
        with zipfile.ZipFile(path, "w") as zf:
            for k, v in entries.items():
                zf.writestr(k, v)
        return path

    def run_import(self, card, path, chosen=None, mode="replace", accept=True):
        """Importa sem abrir diálogo de verdade: troca o exec() do diálogo pela escolha do 'usuário'."""
        from unittest import mock
        from PySide6.QtWidgets import QDialog

        def fake_exec(dialog):
            if chosen is not None:
                for c, box in dialog._checks.items():
                    box.setChecked(c in chosen)
            dialog.mode = mode
            return QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected

        with mock.patch("app.hub.components.theme_gallery.ThemeImportDialog.exec", fake_exec):
            return card.import_package(path)

    def test_import_installs_selects_and_shows_the_flyouts(self):
        card, calls = self.build()
        ok = self.run_import(card, self.package({"keylock/theme.json": self.KL, "mixer/theme.json": self.MX}))
        self.assertTrue(ok)
        self.assertEqual(kl_theme.loader.active_id(), "pacote")
        self.assertEqual(mx_theme.loader.active_id(), "pacote")
        self.assertTrue(card._cards["pacote"].is_selected())
        self.assertCountEqual(calls, ["keylock", "mixer"])

    def test_user_can_choose_only_one_target(self):
        card, calls = self.build()
        self.run_import(card, self.package({"keylock/theme.json": self.KL, "mixer/theme.json": self.MX}),
                        chosen=["mixer"])
        self.assertEqual(mx_theme.loader.active_id(), "pacote")
        self.assertEqual(kl_theme.loader.active_id(), "default")
        self.assertEqual(calls, ["mixer"])
        self.assertNotIn("pacote", card._cards)   # esta página é do keylock: nada novo aqui

    def test_cancel_installs_nothing(self):
        card, calls = self.build()
        ok = self.run_import(card, self.package({"keylock/theme.json": self.KL}), accept=False)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(os.path.join(kl_theme.loader.themes_dir(), "pacote")))
        self.assertEqual(calls, [])

    def test_collision_replaces_by_default_and_copy_makes_a_second_theme(self):
        card, _ = self.build()
        pkg = self.package({"keylock/theme.json": self.KL})
        self.run_import(card, pkg)
        self.run_import(card, pkg)                                   # padrão: substitui
        self.assertEqual([t.id for t in kl_theme.loader.list_themes() if t.id.startswith("pacote")], ["pacote"])
        self.run_import(card, pkg, mode="copy")                      # cópia só quando o usuário confirma
        ids = [t.id for t in kl_theme.loader.list_themes() if t.id.startswith("pacote")]
        self.assertEqual(ids, ["pacote", "pacote-2"])
        self.assertEqual(kl_theme.loader.active_id(), "pacote-2")

    def test_bad_package_shows_an_error_and_changes_nothing(self):
        from unittest import mock
        card, calls = self.build()
        bad = self.package({"keylock/theme.json": self.KL, "keylock/../fora.png": b"x"})
        with mock.patch("app.hub.components.theme_gallery.show_message") as warn:
            self.assertFalse(card.import_package(bad))
        self.assertEqual(warn.call_count, 1)
        self.assertIn("..", warn.call_args.args[3])
        self.assertEqual(calls, [])

    def test_export_roundtrip_through_the_gallery(self):
        from unittest import mock
        card, _ = self.build()
        self.run_import(card, self.package({"keylock/theme.json": self.KL}))
        out = os.path.join(self._tmp.name, "amigo")
        with mock.patch("app.hub.components.theme_gallery.show_message") as info:
            self.assertTrue(card.export_to("pacote", out))   # a extensão é completada
        self.assertTrue(os.path.isfile(out + ".aimskin"))
        self.assertEqual(info.call_count, 1)

    def test_export_takes_the_same_theme_from_the_other_flyout_too(self):
        import zipfile
        from unittest import mock
        card, _ = self.build()
        self.run_import(card, self.package({"keylock/theme.json": self.KL, "mixer/theme.json": self.MX}))
        self.make_theme(kl_theme.loader, "so-caps", {"name": "So Caps"})
        out = os.path.join(self._tmp.name, "par.aimskin")
        with mock.patch("app.hub.components.theme_gallery.show_message") as info:
            card.export_to("pacote", out)
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(sorted(zf.namelist()), ["keylock/theme.json", "mixer/theme.json"])
        self.assertIn("Volume e mixer", info.call_args.args[3])
        out2 = os.path.join(self._tmp.name, "um.aimskin")
        card.refresh()
        with mock.patch("app.hub.components.theme_gallery.show_message"):
            card.export_to("so-caps", out2)
        with zipfile.ZipFile(out2) as zf:
            self.assertEqual(zf.namelist(), ["keylock/theme.json"])

    def test_export_default_is_refused_with_a_message(self):
        from unittest import mock
        card, _ = self.build()
        with mock.patch("app.hub.components.theme_gallery.show_message") as info:
            card._export()
        self.assertEqual(info.call_count, 1)

    def test_dialog_shows_applied_ignored_and_collision(self):
        from app.core.theme_package import analyze_package
        from app.hub.components.theme_import_dialog import ThemeImportDialog
        os.makedirs(os.path.join(kl_theme.loader.themes_dir(), "pacote"))
        theme = json.dumps({"name": "Pacote", "card_bg": "azul", "radius": 6})
        report = analyze_package(self.package({"keylock/theme.json": theme, "keylock/lixo.exe": b"MZ",
                                               "mixer/fundo.png": b"x"}))
        try:
            dlg = ThemeImportDialog(report, THEME_DARK)
            texts = "\n".join(label.text() for label in dlg.findChildren(type(dlg.heading)))
            self.assertIn("Será aplicado: radius", texts)
            self.assertIn("cor inválida em 'card_bg'", texts)
            self.assertIn("lixo.exe", texts)
            self.assertIn("Já existe um tema com este nome", texts)
            self.assertIn("Não pode ser instalado", texts)          # o alvo mixer não tem theme.json
            self.assertEqual(dlg.chosen_containers, ["keylock"])    # só o instalável vem marcado
            self.assertEqual(dlg.btn_ok.text(), "Substituir e aplicar")   # substituir é o padrão
            self.assertTrue(dlg.btn_copy.isEnabled())
            dlg._checks["keylock"].setChecked(False)
            self.assertFalse(dlg.btn_ok.isEnabled())                # nada marcado: não instala
        finally:
            report.close()


class OverviewFollowsActiveTheme(_Isolated):
    """O card de cada flyout na Personalização mostra o tema em uso, como o Music Player mostra a skin ativa."""

    def test_flyout_cards_show_the_active_theme_and_follow_changes(self):
        from app.hub.pages import OverviewPage
        from app.widgets.keylock_osd import KEYLOCK_SPEC
        from app.widgets.volume_mixer.specs import init_volume_spec

        page = OverviewPage(theme=THEME_DARK)
        # Padrão: miniatura e rótulo originais
        self.assertIs(page.keys_card._spec, KEYLOCK_SPEC)
        self.assertIs(page.vol_card._spec, init_volume_spec())

        self.make_theme(kl_theme.loader, "neon", {"name": "Neon", "card_bg": "#112233"})
        self.make_theme(mx_theme.loader, "areia", {"name": "Areia"})
        kl_theme.loader.set_active("neon")
        mx_theme.loader.set_active("areia")
        page._refresh_flyout_cards()   # o que o showEvent faz ao voltar para a página
        self.assertEqual((page.keys_card._spec.id, page.keys_card.skin_label), ("neon", "Neon"))
        self.assertEqual((page.vol_card._spec.id, page.vol_card.skin_label), ("areia", "Areia"))
        self.assertIn("Neon", page.keys_card.lbl_subtitle.text())

        # Nada mudou: a mesma spec (a miniatura não é redesenhada à toa)
        spec = page.keys_card._spec
        page._refresh_flyout_cards()
        self.assertIs(page.keys_card._spec, spec)

        # Tema escolhido que sumiu da pasta: volta ao padrão, como o flyout
        import shutil
        shutil.rmtree(os.path.join(kl_theme.loader.themes_dir(), "neon"))
        page._refresh_flyout_cards()
        self.assertIs(page.keys_card._spec, KEYLOCK_SPEC)


if __name__ == "__main__":
    unittest.main()
