"""Detecção de música no navegador: Firefox (AUMID em hash), vídeos aceitos e capa de vídeo descartada."""

import unittest
from types import SimpleNamespace

try:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QGuiApplication, QImage
    from app.services import media_worker as mw
except ModuleNotFoundError as exc:   # winrt só existe com as dependências do app instaladas
    raise unittest.SkipTest(f"media_worker indisponível: {exc}")


def _png(w: int, h: int) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class BrowserAppIdTests(unittest.TestCase):
    def test_firefox_hash_aumid_is_a_browser(self):
        self.assertTrue(mw.is_browser_app_id("308046b0af4a39cb"))
        self.assertTrue(mw.is_browser_app_id("308046B0AF4A39CB"))

    def test_named_browsers_and_non_browsers(self):
        self.assertTrue(mw.is_browser_app_id("chrome"))
        self.assertTrue(mw.is_browser_app_id("msedge"))
        self.assertFalse(mw.is_browser_app_id("spotify.exe"))
        self.assertFalse(mw.is_browser_app_id(""))


class ClassifyBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QGuiApplication.instance() or QGuiApplication([])

    def _classify(self, title, artist, thumb, app_id="308046b0af4a39cb"):
        worker = mw.WindowsMediaWorker.__new__(mw.WindowsMediaWorker)   # sem iniciar a thread/GSMTC
        session = SimpleNamespace(source_app_user_model_id=app_id)
        props = SimpleNamespace(title=title, artist=artist, album_title="", track_number=0)
        info = SimpleNamespace(playback_status=mw.PlaybackStatus.PLAYING)
        return worker._classify_session(session, props, info, thumb)

    def test_video_with_widescreen_cover_is_accepted_in_firefox(self):
        ok, provider, score = self._classify("ハープでかぜのさかなのうた / ゼルダの伝説夢をみる島", "Nana Harp", _png(320, 180))
        self.assertTrue(ok)
        self.assertEqual(provider, "youtube_music")

    def test_square_cover_scores_higher_than_a_video_frame(self):
        _, _, square = self._classify("Faixa", "Artista", _png(300, 300))
        _, _, wide = self._classify("Faixa", "Artista", _png(320, 180))
        self.assertGreater(square, wide)

    def test_clear_non_music_is_still_rejected(self):
        ok, _, _ = self._classify("Gameplay Zelda parte 3", "Canal", _png(320, 180))
        self.assertFalse(ok)

    def test_video_frame_detection(self):
        self.assertTrue(mw.WindowsMediaWorker._is_video_frame(_png(320, 180)))
        self.assertFalse(mw.WindowsMediaWorker._is_video_frame(_png(300, 300)))
        self.assertFalse(mw.WindowsMediaWorker._is_video_frame(b""))


if __name__ == "__main__":
    unittest.main()
