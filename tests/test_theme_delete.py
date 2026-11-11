"""
Exclusão de temas pelo Hub: apaga a pasta, devolve a escolha ao Padrão, protege os temas que vêm com o app,
confirma antes (Enter cancela) e oferece exportar uma cópia. E a escolha salva de um tema apagado por fora é limpa
sozinha (sem o aviso repetir a cada abertura).
"""

import json
import os
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from app.core import bundled_themes
from app.core.config_manager import config_manager
from app.core.theme_loader import APP_ID, CUSTOM_ID, DEFAULT_ID
from app.hub.components import theme_gallery
from app.hub.components.message_dialog import MessageDialog
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.hub.theme import THEME_DARK
from app.widgets.keylock_osd import theme as kl_theme
from app.widgets.keylock_osd.theme_specs import make_theme_spec as kl_spec
from tests.test_theme_gallery import _Isolated

_app = QApplication.instance() or QApplication([])


class LoaderDeleteTests(_Isolated):
    def test_deleting_the_active_theme_removes_the_folder_and_goes_back_to_the_default(self):
        folder = self.make_theme(kl_theme.loader, "roxo", {"card_bg": "#331144"})
        kl_theme.loader.set_active("roxo")
        kl_theme.loader.delete("roxo")
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(kl_theme.loader.active_id(), kl_theme.loader.fallback_id())
        self.assertEqual(kl_theme.loader.fallback_id(), APP_ID)   # Caps Lock: o "Padrão" de instalação nova

    def test_deleting_a_theme_not_in_use_keeps_the_choice(self):
        self.make_theme(kl_theme.loader, "roxo", {})
        self.make_theme(kl_theme.loader, "verde", {})
        kl_theme.loader.set_active("verde")
        kl_theme.loader.delete("roxo")
        self.assertEqual(kl_theme.loader.active_id(), "verde")

    def test_loose_root_theme_removes_only_its_file(self):
        root = kl_theme.loader.themes_dir()
        sub = self.make_theme(kl_theme.loader, "roxo", {})
        with open(kl_theme.loader.path(), "w", encoding="utf-8") as f:
            json.dump({"name": "Solto"}, f)
        kl_theme.loader.delete(CUSTOM_ID)
        self.assertFalse(os.path.exists(kl_theme.loader.path()))
        self.assertTrue(os.path.isdir(root) and os.path.isdir(sub))   # os outros temas da pasta ficam

    def test_builtin_and_bundled_themes_are_protected(self):
        for theme_id in (DEFAULT_ID, APP_ID):
            self.assertTrue(kl_theme.loader.is_protected(theme_id))
            with self.assertRaises(ValueError):
                kl_theme.loader.delete(theme_id)
        # Keycap Digital vem com o app: mesmo copiado para a pasta do usuário, não sai pelo Hub
        self.assertTrue(bundled_themes.is_bundled("keylock", "keycap-digital"))
        folder = self.make_theme(kl_theme.loader, "keycap-digital", {})
        self.assertTrue(kl_theme.loader.is_protected("keycap-digital"))
        with self.assertRaises(ValueError):
            kl_theme.loader.delete("keycap-digital")
        self.assertTrue(os.path.isdir(folder))

    def test_unsafe_or_missing_ids_are_refused(self):
        for bad in ("../fora", "..", "a/b", "nao_existe"):
            with self.assertRaises(ValueError):
                kl_theme.loader.delete(bad)


class StaleChoiceTests(_Isolated):
    def test_choice_of_a_theme_deleted_outside_the_hub_is_cleared_once(self):
        config_manager.set_theme_choice("keylock", "sumiu")
        with self.assertLogs("app.core.theme_loader", level="WARNING") as logs:
            self.assertIs(kl_theme.loader.load(), kl_theme.DEFAULT_THEME)   # o mesmo visual de antes
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(config_manager.get_theme_choice("keylock"), DEFAULT_ID)
        kl_theme.loader.reset()
        with self.assertNoLogs("app.core.theme_loader", level="WARNING"):    # na próxima abertura, silêncio
            self.assertIs(kl_theme.loader.load(), kl_theme.DEFAULT_THEME)


class GalleryDeleteTests(_Isolated):
    def build(self):
        applied = []
        card = ThemeGalleryCard(kl_theme.loader, "keylock", kl_spec, lambda: applied.append(1), THEME_DARK)
        return card, applied

    def test_confirmed_delete_removes_the_card_and_applies_the_default(self):
        folder = self.make_theme(kl_theme.loader, "roxo", {"name": "Roxo"})
        kl_theme.loader.set_active("roxo")
        card, applied = self.build()
        with mock.patch.object(theme_gallery, "confirm_destructive", return_value="yes") as ask:
            card._delete()
        self.assertIn("Roxo", ask.call_args.args[3])                # o nome aparece na pergunta
        self.assertFalse(os.path.exists(folder))
        self.assertNotIn("roxo", card._cards)
        self.assertEqual(applied, [1])                              # o flyout mostra o padrão na hora

    def test_cancel_keeps_everything(self):
        folder = self.make_theme(kl_theme.loader, "roxo", {})
        kl_theme.loader.set_active("roxo")
        card, applied = self.build()
        with mock.patch.object(theme_gallery, "confirm_destructive", return_value="no"):
            card._delete()
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual((kl_theme.loader.active_id(), applied), ("roxo", []))

    def test_export_first_deletes_only_after_a_successful_export(self):
        folder = self.make_theme(kl_theme.loader, "roxo", {})
        kl_theme.loader.set_active("roxo")
        card, _ = self.build()
        target = os.path.join(self._tmp.name, "copia.aimskin")
        with mock.patch.object(theme_gallery, "confirm_destructive", return_value="extra"), \
             mock.patch.object(theme_gallery, "_file_dialog", return_value=""):
            card._delete()                                          # cancelou o salvar: nada é apagado
        self.assertTrue(os.path.isdir(folder))
        with mock.patch.object(theme_gallery, "confirm_destructive", return_value="extra"), \
             mock.patch.object(theme_gallery, "_file_dialog", return_value=target), \
             mock.patch.object(theme_gallery, "show_message"):
            card._delete()
        self.assertTrue(os.path.isfile(target))
        self.assertFalse(os.path.exists(folder))

    def test_protected_theme_shows_a_message_and_asks_nothing(self):
        kl_theme.loader.set_active(DEFAULT_ID)
        card, _ = self.build()
        with mock.patch.object(theme_gallery, "confirm_destructive") as ask, \
             mock.patch.object(theme_gallery, "show_message") as msg:
            card._delete()
        ask.assert_not_called()
        msg.assert_called_once()


class DestructiveDialogTests(unittest.TestCase):
    def test_enter_cancels_and_there_are_three_choices(self):
        d = MessageDialog(None, THEME_DARK, "t", "x", "warning", yes="Excluir", no="Cancelar",
                          extra="Exportar e excluir", safe_default=True)
        self.assertTrue(d.btn_no.isDefault())
        self.assertFalse(d.btn_ok.isDefault())
        d.btn_extra.click()
        self.assertEqual(d.result(), MessageDialog.EXTRA)


if __name__ == "__main__":
    unittest.main()
