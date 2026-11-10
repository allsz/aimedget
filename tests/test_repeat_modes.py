"""
Modos de repetição: tradução explícita interface <-> Windows, ordem do ciclo por player
(Spotify difere dos demais) e sincronização do ícone com o estado real do player.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.services.repeat_modes import (
    REPEAT_LIST,
    REPEAT_OFF,
    REPEAT_TRACK,
    gsmtc_to_ui,
    next_repeat_mode,
    repeat_cycle,
    ui_to_gsmtc,
)


class TestMapping(unittest.TestCase):
    def test_ui_to_windows_is_not_swapped(self):
        # Windows: None=0, Track=1, List=2
        self.assertEqual(ui_to_gsmtc(REPEAT_OFF), 0)
        self.assertEqual(ui_to_gsmtc(REPEAT_TRACK), 1)
        self.assertEqual(ui_to_gsmtc(REPEAT_LIST), 2)

    def test_round_trip(self):
        for ui in (REPEAT_OFF, REPEAT_LIST, REPEAT_TRACK):
            self.assertEqual(gsmtc_to_ui(ui_to_gsmtc(ui)), ui)

    def test_unreported_mode_is_minus_one(self):
        self.assertEqual(gsmtc_to_ui(None), -1)
        self.assertEqual(gsmtc_to_ui(9), -1)
        self.assertEqual(gsmtc_to_ui("x"), -1)


class TestCycleOrder(unittest.TestCase):
    def walk(self, provider, steps=4):
        mode, out = REPEAT_OFF, []
        for _ in range(steps):
            mode = next_repeat_mode(provider, mode)
            out.append(mode)
        return out

    def test_spotify_track_first_then_playlist(self):
        self.assertEqual(self.walk("spotify"), [REPEAT_TRACK, REPEAT_LIST, REPEAT_OFF, REPEAT_TRACK])

    def test_other_players_playlist_first_then_track(self):
        for provider in ("apple_music", "deezer", "local", "generic", "youtube_music", ""):
            self.assertEqual(self.walk(provider), [REPEAT_LIST, REPEAT_TRACK, REPEAT_OFF, REPEAT_LIST], provider)

    def test_unknown_current_mode_recovers(self):
        self.assertIn(next_repeat_mode("spotify", 99), repeat_cycle("spotify"))


class TestSkinSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def make(self, provider="generic"):
        from app.widgets.music.skins.fullcover_skin import FullCoverSkin

        skin = FullCoverSkin()
        skin.provider = provider
        return skin

    def test_click_sequence_matches_provider_and_sends_ui_modes(self):
        spot = self.make("spotify")
        sent = []
        spot.command_requested.connect(lambda a, v: sent.append((a, v)))
        for _ in range(3):
            spot.repeat_mode = spot.next_repeat_mode()
            spot.command_requested.emit("repeat", spot.repeat_mode)
        self.assertEqual([v for _, v in sent], [REPEAT_TRACK, REPEAT_LIST, REPEAT_OFF])

        other = self.make("deezer")
        self.assertEqual(other.next_repeat_mode(), REPEAT_LIST)

    def test_icon_follows_real_player_state(self):
        skin = self.make("spotify")
        skin.on_repeat_state(REPEAT_TRACK)       # alterado dentro do próprio player
        self.assertEqual(skin.repeat_mode, REPEAT_TRACK)
        skin.on_repeat_state(REPEAT_OFF)
        self.assertEqual(skin.repeat_mode, REPEAT_OFF)

    def test_player_without_repeat_info_keeps_local_state(self):
        skin = self.make("youtube_music")
        skin.repeat_mode = REPEAT_LIST
        skin.on_repeat_state(-1)
        self.assertEqual(skin.repeat_mode, REPEAT_LIST)

    def test_stale_reading_right_after_click_is_ignored(self):
        skin = self.make("spotify")
        skin.repeat_mode = skin.next_repeat_mode()        # clique: vai para TRACK
        skin.on_repeat_state(REPEAT_OFF)                   # leitura antiga chegando logo depois
        self.assertEqual(skin.repeat_mode, REPEAT_TRACK)   # o ícone não pisca de volta
        skin._repeat_clicked_at = time.monotonic() - 5.0   # passado o prazo, vale a verdade do player
        skin.on_repeat_state(REPEAT_OFF)
        self.assertEqual(skin.repeat_mode, REPEAT_OFF)     # ex.: player web que ignorou o comando

    def test_skin_without_repeat_button_ignores_state(self):
        from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

        vinyl = VinylMusicSkin()
        vinyl.on_repeat_state(REPEAT_TRACK)                # não deve levantar exceção


class TestWorkerIntegration(unittest.TestCase):
    """Garante que o worker real importa e publica o estado de repetição / status de sessão."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_publish_repeat_state_emits_only_on_change(self):
        from app.services.media_worker import WindowsMediaWorker

        w = WindowsMediaWorker()
        self.addCleanup(w.stop)
        got = []
        w.repeat_state_changed.connect(got.append)

        class Info:
            auto_repeat_mode = 1   # Windows: Track

        w._publish_repeat_state(Info())
        w._publish_repeat_state(Info())                    # repetido: sem novo sinal
        Info.auto_repeat_mode = 2                          # Windows: List
        w._publish_repeat_state(Info())
        Info.auto_repeat_mode = None                       # player não informa
        w._publish_repeat_state(Info())
        self.assertEqual(got, [REPEAT_TRACK, REPEAT_LIST, -1])
        w._running = False

    def test_status_name_maps_windows_playback_status(self):
        from app.services.media_worker import PlaybackStatus, _status_name

        class Info:
            def __init__(self, st):
                self.playback_status = st

        self.assertEqual(_status_name(Info(PlaybackStatus.PLAYING)), "playing")
        self.assertEqual(_status_name(Info(PlaybackStatus.PAUSED)), "paused")
        self.assertEqual(_status_name(Info(PlaybackStatus.CHANGING)), "changing")
        self.assertEqual(_status_name(Info(PlaybackStatus.STOPPED)), "other")


if __name__ == "__main__":
    unittest.main()
