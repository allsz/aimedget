"""
Filtro da abertura automática do Music Widget: níveis A/B (abrem sozinhos) e C (aparecem, mas não abrem sozinhos).

Os casos vêm de uma coleta REAL (modo AIMEDGET_MEDIA_DIAG) com os dados que cada site/app manda ao Windows.
"""

import unittest
from types import SimpleNamespace

try:
    from PySide6.QtGui import QGuiApplication
    from app.services import media_worker as mw
except ModuleNotFoundError as exc:   # winrt só existe com as dependências do app instaladas
    raise unittest.SkipTest(f"media_worker indisponível: {exc}")

CHROME = "Chrome"
YTM_PWA = "Chrome._crx_cinhimbnkkghhklpknlkffjgod"
WORKADVENTURE_PWA = "Chrome._crx_igagklbaajinjbaolgkfkeiljo"
ZUNE = "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"


class TierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QGuiApplication.instance() or QGuiApplication([])

    def _classify(self, app_id, title, artist="", album="", track=0, playing=True):
        worker = mw.WindowsMediaWorker.__new__(mw.WindowsMediaWorker)
        session = SimpleNamespace(source_app_user_model_id=app_id)
        props = SimpleNamespace(title=title, artist=artist, album_title=album, track_number=track)
        status = mw.PlaybackStatus.PLAYING if playing else mw.PlaybackStatus.PAUSED
        info = SimpleNamespace(playback_status=status)
        return worker._classify_session(session, props, info, b"")

    def assertAutoOpens(self, *args, **kwargs):
        ok, _, _, auto_open = self._classify(*args, **kwargs)
        self.assertTrue(ok)
        self.assertTrue(auto_open, f"deveria abrir sozinho: {args}")

    def assertVisibleOnly(self, *args, **kwargs):
        ok, _, _, auto_open = self._classify(*args, **kwargs)
        self.assertTrue(ok, f"deveria aparecer se o widget for aberto: {args}")
        self.assertFalse(auto_open, f"não deveria abrir sozinho: {args}")

    # --- Nível A/B: abrem sozinhos ---

    def test_youtube_music_installed_app(self):
        self.assertAutoOpens(YTM_PWA, "What's Love", "Chris Brown")

    def test_spotify_web_is_recognised_by_its_album(self):
        self.assertAutoOpens(CHROME, "Dearly Beloved - KINGDOM HEARTS III Version", "Yoko Shimomura", "KINGDOM HEARTS - III, II")

    def test_youtube_topic_channel(self):
        self.assertAutoOpens(CHROME, "Faixa", "Artista - Topic")

    def test_tagged_local_file_in_media_player(self):
        self.assertAutoOpens(ZUNE, "Holy Angel", "Chris Brown", "Before The Party", track=4)

    def test_untagged_local_file_that_looks_like_artist_dash_title(self):
        self.assertAutoOpens(ZUNE, "Brent Faiyaz - butterflies. (Part 1 Only)")

    def test_dedicated_players(self):
        self.assertAutoOpens("Spotify.exe", "Faixa", "Artista")
        self.assertAutoOpens("foobar2000.exe", "Faixa", "Artista")

    # --- Nível C: aparecem, não abrem sozinhos ---

    def test_unknown_installed_web_app_work_adventure(self):
        self.assertVisibleOnly(WORKADVENTURE_PWA, "WorkAdventure VIRTUAL WORKPLACES", "WorkAdventure")

    def test_plain_youtube_video(self):
        self.assertVisibleOnly(CHROME, "O DESBLOQUEIO DO SWITCH 2 ESTÁ FORA DE CONTROLE", "Senhor Linguica")

    def test_x_video(self):
        self.assertVisibleOnly(CHROME, "Fixing a Claude-generated UI with obsessive", "Haz")

    def test_kick_and_twitch_streams(self):
        self.assertVisibleOnly(CHROME, "daniels Live Stream - Watch Live on KICK")
        self.assertVisibleOnly(CHROME, "Red Bull Ladeira Abaixo Edição Geek", "Baiano")

    def test_soundcloud_in_a_browser_tab_is_not_distinguishable(self):
        # Sem álbum e com capa quadrada, é igual a uma live: fica no nível C (a lista de permissão do Hub resolveria)
        self.assertVisibleOnly(CHROME, "KALEO - Still No Good (LIVE at United Reality)", "BMN")

    def test_untagged_video_in_media_player(self):
        # O Media Player também toca vídeo e manda só o título
        self.assertVisibleOnly(ZUNE, "take final")

    def test_paused_state_keeps_the_tier(self):
        self.assertVisibleOnly(WORKADVENTURE_PWA, "WorkAdventure VIRTUAL WORKPLACES", "WorkAdventure", playing=False)
        self.assertAutoOpens(YTM_PWA, "What's Love", "Chris Brown", playing=False)

    # --- Precisão ---

    def test_audio_extension_must_be_a_real_extension(self):
        self.assertFalse(mw._AUDIO_EXT_RE.search("o apex.middle"))     # ".ape"/".mid" dentro de outra palavra
        self.assertTrue(mw._AUDIO_EXT_RE.search("minha musica.mp3"))
        self.assertTrue(mw._AUDIO_EXT_RE.search("som.WAV"))

    def test_nothing_is_music_without_a_title(self):
        ok, _, _, auto_open = self._classify(CHROME, "")
        self.assertFalse(ok)
        self.assertFalse(auto_open)


if __name__ == "__main__":
    unittest.main()
