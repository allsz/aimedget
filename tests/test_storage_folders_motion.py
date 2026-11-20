"""
Aba Storage: adicionar/remover pasta anima sem tremor. A linha, a lista, o cartão e o que vem abaixo têm de andar JUNTOS,
quadro a quadro (antes o cartão atendia o pedido de layout um quadro depois da linha: tremida e animações descasadas).
"""

import shutil
import tempfile
import time
import unittest

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.services import storage_service as ss

_app = QApplication.instance() or QApplication([])


class StorageFoldersMotionTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(config_manager._data.get("storage_widget", {}))
        self._orig_save = config_manager._save
        self._orig_refresh = ss.StorageService.refresh
        config_manager._save = lambda *a, **k: None
        ss.StorageService.refresh = lambda self, force=False: None
        self.dirs = [tempfile.mkdtemp() for _ in range(3)]
        config_manager._data["storage_widget"] = {"folders": [{"name": "A", "path": self.dirs[0]}]}
        from app.hub.storage_page import StoragePage
        self.page = StoragePage()
        self.page.resize(900, 1100)
        self.page.show()
        self._pump(0.15)

    def tearDown(self):
        self.page.close()
        ss.StorageService.refresh = self._orig_refresh
        config_manager._data["storage_widget"] = self._saved
        config_manager._save = self._orig_save
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _pump(self, sec, probe=None):
        out, end = [], time.time() + sec
        while time.time() < end:
            QCoreApplication.processEvents()
            if probe:
                out.append(probe())
            time.sleep(0.004)
        return out

    def _probe(self):
        p = self.page
        fold = p.fold_empty_folders.height() if p.fold_empty_folders.isVisible() else 0
        rows = sum(r.height() for r in p.folder_list._rows + p.folder_list._leaving)
        idx = p.content_layout.indexOf(p.folders_card)
        below = p.content_layout.itemAt(idx + 1).widget()
        return (p.folders_card.height(), p.folder_list.height(), fold, rows,
                below.y() - p.folders_card.y() - p.folders_card.height())

    def assertTogether(self, samples):
        cards = [s[0] for s in samples]
        self.assertEqual(len({s[0] - s[1] - s[2] for s in samples}), 1, "o cartão não acompanha a lista e o aviso de vazio")
        self.assertEqual({s[1] - s[3] for s in samples}, {0}, "a lista não acompanha a altura das linhas")
        self.assertEqual(len({s[4] for s in samples}), 1, "o cartão de baixo não acompanha o cartão de pastas")
        up = all(b >= a - 1 for a, b in zip(cards, cards[1:]))
        down = all(b <= a + 1 for a, b in zip(cards, cards[1:]))
        self.assertTrue(up or down, "a altura do cartão foi e voltou")
        self.assertNotEqual(cards[0], cards[-1])

    def test_add_folder(self):
        self.page.service.add_folder(self.dirs[1])
        self.assertTogether(self._pump(0.9, self._probe))
        self.assertEqual(self.page.folder_list.count(), 2)

    def test_remove_folder(self):
        self.page.service.add_folder(self.dirs[1])
        self._pump(0.9)
        self.page.folder_list._rows[0].btn_remove.click()
        self.assertTogether(self._pump(1.6, self._probe))
        self.assertEqual(self.page.folder_list.count(), 1)

    def test_remove_last_and_add_back_from_empty(self):
        self.page.folder_list._rows[0].btn_remove.click()
        self.assertTogether(self._pump(1.6, self._probe))
        self.assertTrue(self.page.fold_empty_folders.isVisible())
        self.page.service.add_folder(self.dirs[0])
        self.assertTogether(self._pump(1.0, self._probe))
        self.assertFalse(self.page.fold_empty_folders.isVisible())


if __name__ == "__main__":
    unittest.main()
