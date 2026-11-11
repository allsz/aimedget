"""
Testes da regra de volume do Music Widget:
- Player de desktop -> sessão do próprio app.
- Navegador -> sessão do navegador.
- Sem correspondência -> None (o bridge usa o volume do sistema).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.services.audio_mixer_service import AppAudioSession
from app.services.player_volume import aumid_candidates, find_session_for_player


def sess(exe_path: str, volume=50, muted=False, system=False):
    import os

    return AppAudioSession(
        app_id=exe_path.lower(),
        name=os.path.splitext(os.path.basename(exe_path))[0],
        volume=volume,
        is_muted=muted,
        icon=QImage(),
        is_system_sounds=system,
    )


SPOTIFY = sess(r"C:\Users\Me\AppData\Roaming\Spotify\Spotify.exe")
CHROME = sess(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
EDGE = sess(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
FIREFOX = sess(r"C:\Program Files\Mozilla Firefox\firefox.exe")
APPLE = sess(r"C:\Program Files\WindowsApps\AppleInc.AppleMusicWin_1.0\AppleMusic.exe")
SYSTEM = sess("system", system=True)
ALL = [SYSTEM, CHROME, SPOTIFY, EDGE, FIREFOX, APPLE]


class TestPlayerMatching(unittest.TestCase):
    def test_desktop_spotify_variants(self):
        for aumid in ("Spotify.exe", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"):
            self.assertIs(find_session_for_player(aumid, "spotify", ALL), SPOTIFY, aumid)

    def test_desktop_apple_music(self):
        aumid = "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"
        self.assertIs(find_session_for_player(aumid, "apple_music", ALL), APPLE)

    def test_browsers_use_browser_volume(self):
        self.assertIs(find_session_for_player("Chrome", "youtube_music", ALL), CHROME)
        self.assertIs(find_session_for_player("MSEdge", "generic", ALL), EDGE)
        # PWA do YouTube Music instalada pelo Chrome
        self.assertIs(find_session_for_player("Chrome._crx_cinhimbnkkghhklpknlkffjgod", "youtube_music", ALL), CHROME)
        # Firefox usa um AUMID em hash
        self.assertIs(find_session_for_player("308046B0AF4A39CB", "generic", ALL), FIREFOX)

    def test_web_spotify_in_browser_stays_on_browser(self):
        # Aba do Spotify Web: provedor "spotify", mas a origem é o Chrome
        self.assertIs(find_session_for_player("Chrome", "spotify", ALL), CHROME)

    def test_provider_fallback_when_aumid_unknown(self):
        self.assertIs(find_session_for_player("weird-id", "spotify", ALL), SPOTIFY)

    def test_no_match_returns_none(self):
        self.assertIsNone(find_session_for_player("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "generic", ALL))
        self.assertIsNone(find_session_for_player("", "generic", ALL))
        self.assertIsNone(find_session_for_player("Spotify.exe", "spotify", []))

    def test_system_sounds_never_selected(self):
        sounds = sess("sons do sistema", system=True)
        sounds.name = "Sons do Sistema"
        self.assertIsNone(find_session_for_player("Sons do Sistema", "generic", [sounds]))

    def test_candidates_strip_publisher_hash(self):
        c = aumid_candidates("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify")
        self.assertIn("spotify", c)
        self.assertNotIn("zpdnekdrzrea0", " ".join(c))


class _Mixer:
    def __init__(self, sessions, master=50, muted=False):
        self.sessions = sessions
        self.master = master
        self.master_muted = muted
        self.app_sets = []
        self.master_sets = []

    def get_cached_sessions(self):
        return list(self.sessions)

    def get_fresh_sessions(self, max_age_s: float = 2.0):   # o bridge pede uma lista recente (mixer fechado)
        return list(self.sessions)

    def set_app_volume(self, app_id, v):
        self.app_sets.append((app_id, v))
        for s in self.sessions:
            if s.app_id == app_id:
                s.volume = v
                if v > 0:
                    s.is_muted = False

    def get_master_volume(self):
        return self.master

    def get_master_mute(self):
        return self.master_muted

    def set_master_volume(self, v, from_ui=True):
        self.master = v
        self.master_sets.append(v)


class _Osd:
    def __init__(self):
        self.calls = []

    def show_for(self, anchor, volume, muted):
        self.calls.append((volume, muted))


class _Worker:
    def __init__(self, aumid, provider="generic"):
        self.current_source_app_id = aumid.lower()
        self._last_provider = provider


class TestBridgeChannel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _bridge(self, mixer, worker):
        from app.hub.service_bridge import HubServiceBridge

        b = QObject()
        b._wheel_remainder = 0.0
        b.audio_service = mixer
        b.music_volume_osd = _Osd()
        b.music_controller = type("C", (), {"skin": object(), "media_worker": worker})()
        b._resolve_music_volume_target = lambda: HubServiceBridge._resolve_music_volume_target(b)
        b.handler = lambda n: HubServiceBridge._on_music_volume_wheel(b, n)
        return b

    def test_spotify_scroll_changes_only_spotify(self):
        spot = sess(r"C:\x\Spotify.exe", volume=40)
        mixer = _Mixer([spot, sess(r"C:\x\chrome.exe", volume=70)], master=80)
        b = self._bridge(mixer, _Worker("Spotify.exe", "spotify"))
        b.handler(-1.0)
        self.assertEqual(mixer.app_sets, [(spot.app_id, 38)])
        self.assertEqual(mixer.master_sets, [])
        self.assertEqual(b.music_volume_osd.calls, [(38, False)])

    def test_browser_scroll_changes_browser(self):
        chrome = sess(r"C:\x\chrome.exe", volume=60)
        mixer = _Mixer([chrome], master=80)
        b = self._bridge(mixer, _Worker("Chrome", "youtube_music"))
        b.handler(1.0)
        self.assertEqual(mixer.app_sets, [(chrome.app_id, 62)])
        self.assertEqual(mixer.master_sets, [])

    def test_unknown_player_falls_back_to_system(self):
        mixer = _Mixer([sess(r"C:\x\chrome.exe")], master=30)
        b = self._bridge(mixer, _Worker("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"))
        b.handler(1.0)
        self.assertEqual(mixer.master_sets, [32])
        self.assertEqual(mixer.app_sets, [])
        self.assertEqual(b.music_volume_osd.calls, [(32, False)])

    def test_app_clamps_and_unmutes(self):
        spot = sess(r"C:\x\Spotify.exe", volume=99, muted=True)
        mixer = _Mixer([spot])
        b = self._bridge(mixer, _Worker("Spotify.exe", "spotify"))
        b.handler(1.0)
        self.assertEqual(spot.volume, 100)
        self.assertFalse(spot.is_muted)


if __name__ == "__main__":
    unittest.main()
