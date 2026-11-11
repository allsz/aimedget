"""Migração da pasta de dados antiga (WindowsRedesign) para a nova (Aimedget)."""

import os
import tempfile
import unittest
from unittest import mock

from app.core import paths
from app.core.paths import APP_DATA_NAME, LEGACY_APP_DATA_NAME, migrate_legacy_data_dir


def _write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        self.old = os.path.join(self.base, LEGACY_APP_DATA_NAME)
        self.new = os.path.join(self.base, APP_DATA_NAME)

    def tearDown(self):
        self._tmp.cleanup()

    def test_nothing_to_migrate_returns_new_dir_without_creating_it(self):
        self.assertEqual(migrate_legacy_data_dir(self.base), self.new)
        self.assertFalse(os.path.exists(self.new))

    def test_old_dir_is_renamed_keeping_everything(self):
        _write(os.path.join(self.old, "settings.json"), "{}")
        _write(os.path.join(self.old, "themes", "mixer", "lavanda", "theme.json"), "{}")
        self.assertEqual(migrate_legacy_data_dir(self.base), self.new)
        self.assertFalse(os.path.exists(self.old))
        self.assertTrue(os.path.isfile(os.path.join(self.new, "settings.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.new, "themes", "mixer", "lavanda", "theme.json")))

    def test_when_both_exist_nothing_is_overwritten(self):
        _write(os.path.join(self.old, "settings.json"), "antigo")
        _write(os.path.join(self.old, "cover_cache", "a.jpg"), "capa")
        _write(os.path.join(self.new, "settings.json"), "novo")
        self.assertEqual(migrate_legacy_data_dir(self.base), self.new)
        with open(os.path.join(self.new, "settings.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "novo")
        self.assertTrue(os.path.isfile(os.path.join(self.new, "cover_cache", "a.jpg")))   # o que faltava passou
        self.assertTrue(os.path.isfile(os.path.join(self.old, "settings.json")))          # o conflito fica intacto

    def test_failure_keeps_using_the_old_dir(self):
        _write(os.path.join(self.old, "settings.json"), "{}")
        with mock.patch("app.core.paths.os.rename", side_effect=PermissionError("em uso")):
            self.assertEqual(migrate_legacy_data_dir(self.base), self.old)
        self.assertTrue(os.path.isfile(os.path.join(self.old, "settings.json")))

    def test_get_app_data_dir_migrates_once_and_stays_stable(self):
        _write(os.path.join(self.old, "settings.json"), "{}")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": self.base}), mock.patch.object(paths, "_migration_done", False):
            self.assertEqual(paths.get_app_data_dir(), self.new)
            self.assertEqual(paths.get_app_data_dir(), self.new)


if __name__ == "__main__":
    unittest.main()
