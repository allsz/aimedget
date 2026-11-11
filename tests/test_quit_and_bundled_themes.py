"""
1.0.2:
- "Encerrar" na bandeja fecha TUDO de uma vez (antes, o Qt 6 às vezes cancelava porque o Hub recusa o fechamento
  para ficar na bandeja). O X da janela só esconde com "Manter na bandeja"; sem ele, encerra o app inteiro.
- Temas que vêm com o app são copiados para a pasta do usuário uma vez, sem sobrescrever nem voltar se apagados.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager


class _IsolatedConfig(unittest.TestCase):
    KEYS = ("themes_seeded", "hub")

    def setUp(self):
        self._saved = {k: json.loads(json.dumps(config_manager._data[k])) for k in self.KEYS if k in config_manager._data}
        self._patch = mock.patch.object(config_manager, "_save")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for k in self.KEYS:
            config_manager._data.pop(k, None)
        config_manager._data.update(self._saved)


class QuitTests(_IsolatedConfig):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        super().setUp()
        from app.hub import hub_window as hw

        self.hw = hw
        with mock.patch.object(hw.QTimer, "singleShot"):   # sem a consulta de atualização de 5 s depois de abrir
            self.win = hw.AimedgetHubWindow()

    def tearDown(self):
        self.win.tray_icon.hide()
        super().tearDown()

    def test_tray_quit_exits_the_loop_directly(self):
        with mock.patch.object(self.hw.QApplication, "exit") as exit_, \
             mock.patch.object(self.hw.QApplication, "quit") as quit_:
            self.win.tray_icon.act_exit.trigger()
            exit_.assert_called_once_with(0)
            quit_.assert_not_called()   # quit() negocia com as janelas e podia ser cancelado

    def test_window_accepts_closing_once_quitting(self):
        config_manager.set_keep_in_tray_enabled(True)
        with mock.patch.object(self.hw.QApplication, "exit"):
            self.win.quit_app()
        ev = QCloseEvent()
        self.win.closeEvent(ev)
        self.assertTrue(ev.isAccepted())

    def test_x_with_keep_in_tray_only_hides(self):
        config_manager.set_keep_in_tray_enabled(True)
        self.win.show()
        ev = QCloseEvent()
        with mock.patch.object(self.hw.QTimer, "singleShot") as later:
            self.win.closeEvent(ev)
            later.assert_not_called()
        self.assertFalse(ev.isAccepted())
        self.assertFalse(self.win.isVisible())

    def test_x_without_keep_in_tray_quits_everything(self):
        config_manager.set_keep_in_tray_enabled(False)
        ev = QCloseEvent()
        with mock.patch.object(self.hw.QTimer, "singleShot") as later:
            self.win.closeEvent(ev)
            self.assertTrue(ev.isAccepted())
            later.assert_called_once_with(0, self.win.quit_app)


class BundledThemesTests(_IsolatedConfig):
    def setUp(self):
        super().setUp()
        config_manager._data.pop("themes_seeded", None)
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "bundled")
        self.dest = os.path.join(self.tmp, "user_themes")
        theme = os.path.join(self.src, "keylock", "keycap-digital")
        os.makedirs(theme)
        with open(os.path.join(theme, "theme.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "Keycap Digital"}, f)
        open(os.path.join(theme, "fundo.png"), "wb").close()
        os.makedirs(os.path.join(self.src, "keylock", "sem-theme-json"))   # pasta qualquer: ignorada

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def seed(self):
        from app.core.bundled_themes import seed_bundled_themes
        return seed_bundled_themes(self.src, self.dest)

    def test_first_run_copies_the_theme(self):
        self.assertEqual(self.seed(), ["keylock/keycap-digital"])
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "keylock", "keycap-digital", "fundo.png")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "keylock", "sem-theme-json")))

    def test_never_overwrites_a_theme_the_user_already_has(self):
        mine = os.path.join(self.dest, "keylock", "keycap-digital")
        os.makedirs(mine)
        with open(os.path.join(mine, "theme.json"), "w", encoding="utf-8") as f:
            f.write('{"name": "editado por mim"}')
        self.assertEqual(self.seed(), [])
        with open(os.path.join(mine, "theme.json"), encoding="utf-8") as f:
            self.assertIn("editado por mim", f.read())

    def test_deleted_by_the_user_does_not_come_back(self):
        self.seed()
        shutil.rmtree(os.path.join(self.dest, "keylock", "keycap-digital"))
        self.assertEqual(self.seed(), [])
        self.assertFalse(os.path.exists(os.path.join(self.dest, "keylock", "keycap-digital")))

    def test_missing_bundle_folder_is_harmless(self):
        from app.core.bundled_themes import seed_bundled_themes
        self.assertEqual(seed_bundled_themes(os.path.join(self.tmp, "nao-existe"), self.dest), [])

    def test_the_shipped_keycap_theme_is_valid(self):
        from app.core.bundled_themes import BUNDLED_THEMES_DIR
        from app.widgets.keylock_osd import theme as kl_theme

        folder = os.path.join(BUNDLED_THEMES_DIR, "keylock", "keycap-digital")
        with open(os.path.join(folder, "theme.json"), encoding="utf-8") as f:
            data = json.load(f)
        theme = kl_theme.theme_from_dict(data, folder)
        self.assertEqual(data["name"], "Keycap Digital")
        self.assertTrue(theme.stickers)          # o LED aceso carregou do lado do theme.json
        self.assertIsNotNone(theme.background)
        self.assertFalse(os.path.exists(os.path.join(BUNDLED_THEMES_DIR, "keylock", "Little Star")))


if __name__ == "__main__":
    unittest.main()
