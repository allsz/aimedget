"""
Passo 4 dos temas de widget: validador, pacote .aimskin, galeria do Hub e aplicação ao vivo para os destinos
"music" (Capa Empilhada) e "timer" (skin Aimedget).
"""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.theme_loader import APP_ID, DEFAULT_ID
from app.core.theme_package import analyze_package, export_themes, install_package
from app.core.theme_validation import CONTAINERS, detect_container, validate_path, validate_theme_folder
from app.hub.theme import THEME_DARK
from app.widgets.music.skins import stack_theme
from app.widgets.timer import theme as timer_theme

_app = QApplication.instance() or QApplication(sys.argv)

MUSIC = json.dumps({"name": "Lavanda", "card_bg": "#f3ecff", "accent": "#9b5de5"})
TIMER = json.dumps({"name": "Lavanda", "card_bg": "#f3ecff", "accent": "#9b5de5"})
KEYS = json.dumps({"name": "Lavanda", "on_color": "#b46cff"})


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self._old = (config_manager.config_dir, config_manager.config_path, config_manager._data.get("themes"))
        self.cfg = os.path.join(self.root, "cfg")
        os.makedirs(self.cfg)
        config_manager.config_dir = self.cfg
        config_manager.config_path = os.path.join(self.cfg, "settings.json")
        config_manager._data.pop("themes", None)
        for loader in (stack_theme.loader, timer_theme.loader):
            loader.reset()
            loader._preview_cache.clear()

    def tearDown(self):
        config_manager.config_dir, config_manager.config_path = self._old[0], self._old[1]
        config_manager._data.pop("themes", None)
        if self._old[2] is not None:
            config_manager._data["themes"] = self._old[2]
        for loader in (stack_theme.loader, timer_theme.loader):
            loader.reset()
        self._tmp.cleanup()

    def zip(self, entries: dict, name="t.aimskin") -> str:
        path = os.path.join(self.root, name)
        with zipfile.ZipFile(path, "w") as zf:
            for arc, content in entries.items():
                zf.writestr(arc, content)
        return path

    def folder(self, *parts, data: str) -> str:
        path = os.path.join(self.root, *parts)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "theme.json"), "w", encoding="utf-8") as f:
            f.write(data)
        return path


class ValidationTests(_Isolated):
    def test_new_containers_are_known(self):
        self.assertEqual(CONTAINERS, ("keylock", "mixer", "music", "timer"))

    def test_music_and_timer_folders_validate_with_the_widget_code(self):
        music = validate_theme_folder(self.folder("m", data=MUSIC), "music")
        self.assertTrue(music.ok, music.issues)
        self.assertIn("palette", music.applied)
        timer = validate_theme_folder(self.folder("t", data=TIMER), "timer")
        self.assertTrue(timer.ok, timer.issues)
        self.assertIn("colors", timer.applied)

    def test_wrong_key_is_reported(self):
        rep = validate_theme_folder(self.folder("t", data=json.dumps({"on_color": "#fff"})), "timer")
        self.assertFalse(rep.ok)
        self.assertIn("on_color", "\n".join(rep.issues))

    def test_shadow_is_reported_and_ignored_instead_of_breaking_the_theme(self):
        for container in ("music", "timer"):
            data = json.dumps({"accent": "#9b5de5", "shadow": {"color": "#80000000"}})
            rep = validate_theme_folder(self.folder(container, data=data), container)
            self.assertTrue(rep.usable, rep.errors)
            self.assertIn("'shadow' não existe nos widgets", "\n".join(rep.issues))

    def test_container_is_deduced_from_folder_names(self):
        self.assertEqual(detect_container(self.folder("themes", "music", "lav", data=MUSIC)), "music")
        pack = os.path.join(self.root, "pack")
        self.folder("pack", "music", data=MUSIC)
        self.folder("pack", "timer", data=TIMER)
        reports = validate_path(pack)
        self.assertEqual(sorted(r.container for r in reports), ["music", "timer"])


class PackageTests(_Isolated):
    def test_multi_target_package_with_all_four_destinations(self):
        report = analyze_package(self.zip({"keylock/theme.json": KEYS, "mixer/theme.json": KEYS.replace("on_color", "accent"),
                                           "music/theme.json": MUSIC, "timer/theme.json": TIMER}))
        try:
            self.assertEqual([t.container for t in report.targets], ["keylock", "mixer", "music", "timer"])
            installed = install_package(report, ["music", "timer"])
        finally:
            report.close()
        self.assertEqual({i.container for i in installed}, {"music", "timer"})
        stack_theme.loader.set_active(installed[0].theme_id)
        self.assertEqual(stack_theme.load_user_theme().palette.accent_main.name(), "#9b5de5")

    def test_loose_theme_json_can_target_a_widget(self):
        data = json.dumps({"container": "timer", "name": "Só timer", "accent": "#9b5de5"})
        report = analyze_package(self.zip({"theme.json": data}))
        try:
            self.assertEqual([t.container for t in report.targets], ["timer"])
            self.assertTrue(report.targets[0].report.ok, report.targets[0].report.issues)
        finally:
            report.close()

    def test_reserved_app_id_is_never_used_for_an_import(self):
        report = analyze_package(self.zip({"timer/theme.json": json.dumps({"name": "App"})}))
        try:
            self.assertNotEqual(report.theme_id, APP_ID)
        finally:
            report.close()

    def test_export_roundtrip_of_a_widget_pack(self):
        for container, data in (("music", MUSIC), ("timer", TIMER)):
            self.folder("cfg", "themes", container, "lavanda", data=data)
        out = os.path.join(self.root, "lav.aimskin")
        export_themes([("music", "lavanda"), ("timer", "lavanda")], out)
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(sorted(zf.namelist()), ["music/theme.json", "timer/theme.json"])


class GalleryTests(_Isolated):
    def build(self, loader, container, make_spec, subtitle_key, default_key, appliers=None):
        from app.hub.components.theme_gallery import ThemeGalleryCard
        applied = []
        card = ThemeGalleryCard(loader, container, make_spec, lambda: applied.append(container), THEME_DARK,
                                appliers=appliers, subtitle_key=subtitle_key, default_title_key=default_key)
        card.resize(900, 300)
        self.addCleanup(card.deleteLater)
        return card, applied

    def test_music_gallery_names_the_default_cover_colors_and_has_no_app_theme(self):
        from app.core.i18n import t
        from app.widgets.music.skins.stack_theme_specs import make_theme_spec
        self.folder("cfg", "themes", "music", "lavanda", data=MUSIC)
        card, applied = self.build(stack_theme.loader, "music", make_theme_spec,
                                   "theme_picker_sub_music", "theme_default_music")
        self.assertEqual(list(card._cards), [DEFAULT_ID, "lavanda"])            # sem o "Aimedget" dos flyouts
        self.assertEqual(card._cards[DEFAULT_ID]._spec.title, t("theme_default_music"))
        self.assertEqual(card.sub.text(), t("theme_picker_sub_music"))
        card._cards["lavanda"].clicked.emit("lavanda")
        self.assertEqual(stack_theme.loader.active_id(), "lavanda")
        self.assertEqual(applied, ["music"])

    def test_timer_gallery_thumbnails_render(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter
        from app.widgets.timer.theme_specs import make_theme_spec
        self.folder("cfg", "themes", "timer", "lavanda", data=TIMER)
        card, _ = self.build(timer_theme.loader, "timer", make_theme_spec,
                             "theme_picker_sub_timer", "theme_default_timer")
        spec = card._cards["lavanda"]._spec
        state = spec.mock_state()
        size = spec.natural_size(state)
        img = QImage(int(size.width()), int(size.height()), QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        spec.paint(p, QRectF(0, 0, size.width(), size.height()), state, THEME_DARK)
        p.end()
        self.assertEqual(img.pixelColor(30, 140).name(), "#f3ecff")   # fundo do cartão com a cor do tema

    def test_music_thumbnail_does_not_leak_into_the_skin_thumbnail(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter
        from app.widgets.music.skins.stack_theme_specs import _headless, make_theme_spec
        spec = make_theme_spec("lav", "Lavanda", stack_theme.theme_from_dict(json.loads(MUSIC)))
        before = _headless().skin_theme
        img = QImage(490, 240, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        spec.paint(p, QRectF(0, 0, 490, 240), spec.mock_state(), THEME_DARK)
        p.end()
        self.assertIs(_headless().skin_theme, before)

    def test_export_from_one_page_takes_the_same_theme_from_every_destination(self):
        from app.widgets.timer.theme_specs import make_theme_spec
        for container, data in (("keylock", KEYS), ("music", MUSIC), ("timer", TIMER)):
            self.folder("cfg", "themes", container, "lavanda", data=data)
        card, _ = self.build(timer_theme.loader, "timer", make_theme_spec,
                             "theme_picker_sub_timer", "theme_default_timer")
        out = os.path.join(self.root, "x.aimskin")
        with mock.patch("app.hub.components.theme_gallery.show_message"):
            self.assertTrue(card.export_to("lavanda", out))
        with zipfile.ZipFile(out) as zf:
            tops = sorted({n.split("/")[0] for n in zf.namelist()})
        self.assertEqual(tops, ["keylock", "music", "timer"])

    def test_builtin_default_cannot_be_exported_and_says_its_name(self):
        from app.core.i18n import t
        from app.widgets.timer.theme_specs import make_theme_spec
        card, _ = self.build(timer_theme.loader, "timer", make_theme_spec,
                             "theme_picker_sub_timer", "theme_default_timer")
        with mock.patch("app.hub.components.theme_gallery.show_message") as shown, \
             mock.patch("app.hub.components.theme_gallery._file_dialog") as dialog:
            card._export()
        dialog.assert_not_called()
        self.assertIn(t("theme_default_timer"), shown.call_args.args[3])


class LiveApplyTests(_Isolated):
    def fake_bridge(self, active_skin="vinyl"):
        """Só o que apply_*_theme usa do bridge (o bridge de verdade liga serviços de áudio, mídia e teclado)."""
        reloaded = []
        skin = SimpleNamespace(reload_skin_theme=lambda: reloaded.append(True))
        controller = SimpleNamespace(active_skin_name=active_skin, skin=skin)
        fake = SimpleNamespace(music_controller=controller, timer_controller=SimpleNamespace(skin=skin))
        fake.set_music_skin = mock.Mock(side_effect=lambda name: setattr(controller, "active_skin_name", name))
        fake.set_music_skin_active = mock.Mock(return_value=True)
        return fake, reloaded

    def apply_music(self, fake, active_skins):
        from app.hub.service_bridge import HubServiceBridge
        with mock.patch.object(config_manager, "get_active_widget_skins", return_value=list(active_skins)):
            HubServiceBridge.apply_music_theme(fake)

    def test_choosing_a_music_theme_switches_to_the_stacked_skin(self):
        self.folder("cfg", "themes", "music", "lavanda", data=MUSIC)
        stack_theme.loader.set_active("lavanda")
        fake, reloaded = self.fake_bridge()
        self.apply_music(fake, ["vinyl", "capa_empilhada"])
        fake.set_music_skin.assert_called_once_with("capa_empilhada")
        fake.set_music_skin_active.assert_not_called()
        self.assertEqual(reloaded, [True])

    def test_disabled_stacked_skin_is_enabled_first(self):
        self.folder("cfg", "themes", "music", "lavanda", data=MUSIC)
        stack_theme.loader.set_active("lavanda")
        fake, _ = self.fake_bridge()
        self.apply_music(fake, ["vinyl"])
        fake.set_music_skin_active.assert_called_once_with("capa_empilhada", True)

    def test_default_music_theme_keeps_the_current_skin(self):
        stack_theme.loader.set_active(DEFAULT_ID)
        fake, reloaded = self.fake_bridge()
        self.apply_music(fake, ["vinyl", "capa_empilhada"])
        fake.set_music_skin.assert_not_called()
        self.assertEqual(reloaded, [True])

    def test_timer_theme_is_applied_live(self):
        from app.hub.service_bridge import HubServiceBridge
        fake, reloaded = self.fake_bridge()
        HubServiceBridge.apply_timer_theme(fake)
        self.assertEqual(reloaded, [True])

    def test_appliers_cover_every_destination(self):
        from app.hub.service_bridge import HubServiceBridge
        fake = SimpleNamespace(trigger_test_keylock=mock.Mock(), trigger_test_volume=mock.Mock(),
                               apply_music_theme=mock.Mock(), apply_timer_theme=mock.Mock())
        self.assertEqual(set(HubServiceBridge.theme_appliers(fake)), set(CONTAINERS))


if __name__ == "__main__":
    unittest.main()
