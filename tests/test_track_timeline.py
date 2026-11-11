"""
Firefox troca o título antes da posição: a faixa nova chega por até ~10 s com a posição e a duração da anterior
(registro real: 'Blissful Death' chegou com 8,4 s de 259,1 s de 'Dearly Beloved' e carimbo de 13 s atrás).
A barra não pode nascer adiantada nem herdar a duração da faixa anterior.
"""

import datetime
import unittest
from types import SimpleNamespace

try:
    from PySide6.QtWidgets import QApplication
    from app.services import media_worker as mw
    from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
    from app.widgets.music.skins.fullcover_skin import FullCoverSkin
    from app.widgets.music.skins.ripple_skin import RippleSkin
    from app.widgets.music.skins.vinyl_skin import VinylMusicSkin
except ModuleNotFoundError as exc:   # só falta de dependência; nome errado deve falhar, não pular
    raise unittest.SkipTest(f"dependências indisponíveis: {exc}")

_app = QApplication.instance() or QApplication([])
_NOW = datetime.datetime(2026, 11, 11, 14, 0, 0, tzinfo=datetime.timezone.utc)


def _tl(pos: float, dur: float, age: float):
    td = datetime.timedelta
    return SimpleNamespace(
        position=td(seconds=pos), start_time=td(0), end_time=td(seconds=dur),
        last_updated_time=_NOW - td(seconds=age),
    )


class ResolveTimelineTests(unittest.TestCase):
    def test_old_timeline_after_track_change_is_held_as_unknown(self):
        old = _tl(8.4, 259.1, 13.1)                     # dado de 'Dearly Beloved'
        stale = mw.timeline_signature(old)
        # 'Blissful Death' chega repetindo o mesmo dado: posição e duração desconhecidas
        pos, dur, keep = mw.resolve_track_timeline(mw.timeline_signature(old), stale, 21.5, 259.1)
        self.assertEqual((pos, dur), (0.0, 0.0))
        self.assertEqual(keep, stale)
        # ~10 s depois chega o dado da faixa nova (3,6 s de 156,3 s): passa a valer e a trava some
        new = _tl(3.6, 156.3, 6.0)
        pos, dur, keep = mw.resolve_track_timeline(mw.timeline_signature(new), keep, 9.6, 156.3)
        self.assertEqual((pos, dur, keep), (9.6, 156.3, None))

    def test_player_that_sends_fresh_data_with_the_title_is_untouched(self):
        # Chrome: título e posição chegam juntos, então o dado já é diferente do anterior
        stale = mw.timeline_signature(_tl(120.0, 200.0, 1.0))
        pos, dur, keep = mw.resolve_track_timeline(mw.timeline_signature(_tl(0.2, 180.0, 0.1)), stale, 0.3, 180.0)
        self.assertEqual((pos, dur, keep), (0.3, 180.0, None))

    def test_no_previous_data_means_nothing_is_held(self):
        pos, dur, keep = mw.resolve_track_timeline(mw.timeline_signature(_tl(5.0, 100.0, 1.0)), None, 6.0, 100.0)
        self.assertEqual((pos, dur, keep), (6.0, 100.0, None))


class SkinUnknownDurationTests(unittest.TestCase):
    SKINS = (CapaEmpilhadaSkin, FullCoverSkin, RippleSkin, VinylMusicSkin)

    def _skin(self, cls):
        try:
            return cls(scale=0.5)
        except TypeError:
            return cls()

    def test_new_track_without_duration_resets_the_bar(self):
        for cls in self.SKINS:
            with self.subTest(skin=cls.__name__):
                s = self._skin(cls)
                s._ignore_external_state_until = 0.0
                s._last_seek_sent = -100.0
                s.on_media_updated("Faixa A", "Artista", True, 150.0, 259.1, b"")
                self.assertAlmostEqual(s.duration, 259.1)
                s.on_media_updated("Faixa B", "Artista", True, 0.0, 0.0, b"")   # posição ainda não chegou
                self.assertEqual(s.duration, 0.0)
                self.assertEqual(s.current_time, 0.0)
                s.on_media_updated("Faixa B", "Artista", True, 9.6, 156.3, b"")  # chegou: a barra assume
                self.assertAlmostEqual(s.duration, 156.3)
                self.assertAlmostEqual(s.current_time, 9.6)


def _png(color: str) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    img = QImage(300, 300, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class SkinCoverOfPreviousTrackTests(unittest.TestCase):
    """Vídeo do navegador chega sem capa (o quadro 16:9 é descartado): a capa da faixa anterior não pode ficar."""
    SKINS = (FullCoverSkin, RippleSkin, VinylMusicSkin)   # a Capa Empilhada já avança a pilha para o vinil padrão

    def _skin(self, cls):
        try:
            return cls(scale=0.5)
        except TypeError:
            return cls()

    def test_new_track_without_cover_falls_back_to_default_after_grace(self):
        for cls in self.SKINS:
            with self.subTest(skin=cls.__name__):
                s = self._skin(cls)
                s.on_media_updated("Faixa A", "Artista", True, 10.0, 200.0, _png("red"))
                self.assertIsNotNone(s.album_pixmap)
                s.DEFAULT_COVER_GRACE_S = 60.0
                s.on_media_updated("Video B", "Canal", True, 0.0, 0.0, b"")
                self.assertIsNotNone(s.album_pixmap)        # dentro da carência: segura a anterior (sem piscar)
                s.DEFAULT_COVER_GRACE_S = 0.0
                s.on_media_updated("Video B", "Canal", True, 0.5, 0.0, b"")
                self.assertIsNone(s.album_pixmap)           # passou da carência: capa padrão
                s.on_media_updated("Video B", "Canal", True, 1.0, 180.0, _png("blue"))
                self.assertIsNotNone(s.album_pixmap)        # a busca online achou a capa: ela entra

    def test_track_with_its_own_cover_never_falls_back(self):
        for cls in self.SKINS:
            with self.subTest(skin=cls.__name__):
                s = self._skin(cls)
                s.DEFAULT_COVER_GRACE_S = 0.0
                s.on_media_updated("Faixa A", "Artista", True, 10.0, 200.0, _png("red"))
                s.on_media_updated("Faixa A", "Artista", True, 11.0, 200.0, b"")
                self.assertIsNotNone(s.album_pixmap)


if __name__ == "__main__":
    unittest.main()
