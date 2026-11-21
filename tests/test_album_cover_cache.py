"""
Faixas do mesmo álbum dividem a capa: a imagem é baixada uma vez por álbum (não por faixa). Singles, com álbum
próprio, continuam ganhando a própria capa. As etiquetas de álbum do player permitem achar a capa sem rede.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

try:
    from app.services import media_worker as mw
except ModuleNotFoundError as exc:   # só falta de dependência; nome errado deve falhar, não pular
    raise unittest.SkipTest(f"dependências indisponíveis: {exc}")


def _img(tag: str) -> bytes:
    return (tag.encode() * 2000)[:4096]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AlbumCoverCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patches = [
            mock.patch.object(mw, "get_app_data_dir", lambda: self.tmp),
            mock.patch.object(mw, "_HD_ART_CACHE", {}),
            mock.patch.object(mw, "_ALBUM_ART_CACHE", {}),
            mock.patch.object(mw, "_ALBUM_LINKS", {}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # Resultado da busca do Deezer por faixa: título -> (id do álbum, url da capa)
        self.catalog = {
            "Undrunk": (101, "https://cdn/brown.jpg"),
            "Residuals": (101, "https://cdn/brown.jpg"),
            "Holy Blindfold": (101, "https://cdn/brown.jpg"),
            "Single Song": (202, "https://cdn/single.jpg"),
        }
        self.downloads: list[str] = []
        self.searches = 0

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            self.searches += 1
            title = next((t for t in self.catalog if mw.urllib.parse.quote(t) in url), None)
            if title is None:
                return _Resp(json.dumps({"data": []}).encode())
            alb_id, cover = self.catalog[title]
            return _Resp(json.dumps({"data": [{"album": {"id": alb_id, "cover_big": cover}}]}).encode())

        def fake_download(url):
            self.downloads.append(url)
            return _img(url)

        for p in (
            mock.patch.object(mw.urllib.request, "urlopen", fake_urlopen),
            mock.patch.object(mw, "_download", fake_download),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _forget_memory(self):
        """Simula reabrir o app: só o disco sobrevive."""
        mw._HD_ART_CACHE.clear()
        mw._ALBUM_ART_CACHE.clear()
        mw._ALBUM_LINKS.clear()

    def test_tracks_of_same_album_download_cover_once(self):
        a = mw.fetch_online_album_art("Undrunk", "Chris Brown")
        b = mw.fetch_online_album_art("Residuals", "Chris Brown")
        c = mw.fetch_online_album_art("Holy Blindfold", "Chris Brown")
        self.assertEqual(self.downloads, ["https://cdn/brown.jpg"])
        self.assertTrue(a)
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        # Uma imagem só no disco para o álbum inteiro
        imgs = [f for f in os.listdir(self.tmp + "/cover_cache") if f.endswith(".img")]
        self.assertEqual(len(imgs), 1)

    def test_single_gets_its_own_cover(self):
        alb = mw.fetch_online_album_art("Undrunk", "Chris Brown")
        single = mw.fetch_online_album_art("Single Song", "Chris Brown")
        self.assertEqual(self.downloads, ["https://cdn/brown.jpg", "https://cdn/single.jpg"])
        self.assertNotEqual(alb, single)

    def test_player_album_tag_skips_network_for_next_tracks(self):
        tag = mw.album_tag_key("BROWN", "Chris Brown")
        mw.fetch_online_album_art("Undrunk", "Chris Brown", tag)
        searches_before = self.searches
        got = mw.cached_cover("Residuals|Chris Brown", tag)
        self.assertEqual(got, _img("https://cdn/brown.jpg"))
        self.assertEqual(self.searches, searches_before)
        self.assertEqual(len(self.downloads), 1)

    def test_album_cache_survives_restart(self):
        tag = mw.album_tag_key("BROWN", "Chris Brown")
        mw.fetch_online_album_art("Undrunk", "Chris Brown", tag)
        self._forget_memory()
        # Pela etiqueta, sem busca
        self.assertEqual(mw.cached_cover("Residuals|Chris Brown", tag), _img("https://cdn/brown.jpg"))
        self._forget_memory()
        # Faixa já vista, sem etiqueta: pelo apontamento da faixa
        self.assertEqual(mw.cached_cover("Undrunk|Chris Brown"), _img("https://cdn/brown.jpg"))
        # Faixa nova do mesmo álbum, sem etiqueta: busca o texto, mas não baixa a imagem de novo
        mw.fetch_online_album_art("Residuals", "Chris Brown")
        self.assertEqual(len(self.downloads), 1)

    def test_native_cover_stored_once_per_album_tag(self):
        tag = mw.album_tag_key("BROWN", "Chris Brown")
        native = _img("native")
        mw.store_album_cover(tag, native, aliases=("Undrunk|Chris Brown",))
        self._forget_memory()
        self.assertEqual(mw.cached_cover("Residuals|Chris Brown", tag), native)
        self.assertEqual(mw.cached_cover("Undrunk|Chris Brown"), native)

    def test_legacy_per_track_cover_still_read(self):
        legacy = _img("legacy")
        mw._save_cover_to_disk("Old Song|Chris Brown", legacy)
        self.assertEqual(mw.cached_cover("Old Song|Chris Brown"), legacy)

    def test_album_tag_key_needs_album_and_known_artist(self):
        self.assertEqual(mw.album_tag_key("", "Chris Brown"), "")
        self.assertEqual(mw.album_tag_key("BROWN", "", "Artista Desconhecido"), "")
        self.assertEqual(mw.album_tag_key("BROWN", "", "Chris Brown"), mw.album_tag_key(" brown ", "CHRIS  BROWN"))
        # Mesmo nome de álbum, artistas diferentes: chaves diferentes
        self.assertNotEqual(mw.album_tag_key("Greatest Hits", "A"), mw.album_tag_key("Greatest Hits", "B"))


if __name__ == "__main__":
    unittest.main()
