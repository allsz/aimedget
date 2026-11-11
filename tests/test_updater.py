"""
Atualizador: escolhe o INSTALADOR da release (nunca o .zip portátil nem outro .exe), confere o SHA-256 publicado pelo
GitHub e só se aplica numa cópia instalada (o portátil e o modo de desenvolvimento nunca se sobrescrevem).
"""

import hashlib
import http.server
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication

from app.services import updater_service as up

RELEASE_ASSETS = [
    {"name": "Aimedget-1.0.1-portable.zip", "browser_download_url": "https://x/zip"},
    {"name": "Aimedget.exe", "browser_download_url": "https://x/loose-exe"},
    {"name": "Aimedget-Setup-1.0.1.exe", "browser_download_url": "https://x/setup", "digest": "sha256:ABCDEF"},
    {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/sums"},
]


class AssetSelectionTests(unittest.TestCase):
    def test_picks_the_installer_even_when_another_exe_comes_first(self):
        asset = up.pick_installer_asset(RELEASE_ASSETS)
        self.assertEqual(asset["name"], "Aimedget-Setup-1.0.1.exe")

    def test_no_installer_means_no_asset(self):
        self.assertIsNone(up.pick_installer_asset(RELEASE_ASSETS[:2]))
        self.assertIsNone(up.pick_installer_asset([]))

    def test_sha256_from_github_digest(self):
        self.assertEqual(up.asset_sha256(RELEASE_ASSETS[2]), "abcdef")
        self.assertEqual(up.asset_sha256(RELEASE_ASSETS[0]), "")
        self.assertEqual(up.asset_sha256({"digest": "md5:123"}), "")


class InstalledBuildTests(unittest.TestCase):
    def test_dev_and_portable_never_self_update(self):
        self.assertFalse(up.is_installed_build())                       # rodando do código-fonte
        self.assertFalse(up.UpdaterService.apply_update_and_restart("x.exe"))
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", str(Path(__file__))):
            self.assertFalse(up.is_installed_build())                   # congelado, mas sem desinstalador ao lado

    def test_installed_build_has_the_inno_uninstaller_next_to_it(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "Aimedget.exe")
            open(exe, "wb").close()
            open(os.path.join(d, "unins000.exe"), "wb").close()
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", exe):
                self.assertTrue(up.is_installed_build())


class _Payload(http.server.BaseHTTPRequestHandler):
    body = b"instalador falso" * 1000

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


class DownloadIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication(sys.argv)
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Payload)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/setup.exe"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _download(self, sha: str):
        worker = up.DownloadWorker(self.url, sha)
        result = {}
        worker.download_finished.connect(lambda p: result.setdefault("ok", p))
        worker.download_failed.connect(lambda e: result.setdefault("err", e))
        worker.run()   # direto na thread do teste: os sinais chegam na hora
        return result

    def test_matching_hash_is_accepted(self):
        res = self._download(hashlib.sha256(_Payload.body).hexdigest().upper())
        self.assertIn("ok", res)
        os.remove(res["ok"])

    def test_tampered_download_is_rejected_and_deleted(self):
        res = self._download("0" * 64)
        self.assertIn("err", res)
        self.assertFalse(os.path.exists(os.path.join(os.environ.get("TEMP", ""), "Aimedget-Setup-update.exe")))


if __name__ == "__main__":
    unittest.main()
