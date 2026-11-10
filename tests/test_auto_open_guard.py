"""
Dispensa da abertura automática: esconder o widget com Win+Alt+M durante a música não pode
fazê-lo reaparecer "porque a música está tocando". Termina com 30 s parado, mídia sumindo,
outro player ou abertura manual.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app.core.widget_animator as wa
from app.core.config_manager import config_manager
from app.widgets.music.auto_open_guard import PAUSE_RESET_S, AutoOpenDismissal

NO_MEDIA = "Nenhuma mídia ativa"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class TestRule(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.d = AutoOpenDismissal(clock=self.clock)

    def test_inactive_by_default_and_observe_is_noop(self):
        self.assertFalse(self.d.active)
        self.d.observe(True, True, "spotify")
        self.assertFalse(self.d.active)

    def test_stays_while_playing_and_across_track_changes(self):
        self.d.dismiss("spotify", playing=True)
        for _ in range(50):
            self.clock.t += 5
            self.d.observe(True, True, "spotify")        # músicas passando por minutos
        self.assertTrue(self.d.active)

    def test_short_pause_keeps_dismissal_and_long_pause_ends_it(self):
        self.d.dismiss("spotify", playing=True)
        self.d.observe(True, False, "spotify")           # pausou
        self.clock.t += PAUSE_RESET_S - 1
        self.d.observe(True, False, "spotify")
        self.assertTrue(self.d.active)                   # 29 s: ainda a mesma sessão
        self.clock.t += 1
        self.d.observe(True, False, "spotify")
        self.assertFalse(self.d.active)                  # 30 s: sessão encerrada

    def test_resume_before_30s_resets_the_idle_clock(self):
        self.d.dismiss("spotify", playing=True)
        self.d.observe(True, False, "spotify")
        self.clock.t += 25
        self.d.observe(True, True, "spotify")            # voltou a tocar
        self.clock.t += 25
        self.d.observe(True, False, "spotify")           # pausa nova: relógio recomeça
        self.clock.t += 25
        self.d.observe(True, False, "spotify")
        self.assertTrue(self.d.active)

    def test_media_gone_ends_it(self):
        self.d.dismiss("spotify", playing=True)
        self.d.observe(False, False, "")
        self.assertFalse(self.d.active)

    def test_other_player_playing_ends_it(self):
        self.d.dismiss("spotify", playing=True)
        self.d.observe(True, True, "chrome._crx_x")
        self.assertFalse(self.d.active)

    def test_other_player_paused_does_not_end_it(self):
        self.d.dismiss("spotify", playing=True)
        self.d.observe(True, False, "chrome._crx_x")
        self.assertTrue(self.d.active)

    def test_dismissed_while_already_paused_counts_from_that_moment(self):
        self.d.dismiss("spotify", playing=False)
        self.clock.t += PAUSE_RESET_S
        self.d.observe(True, False, "spotify")
        self.assertFalse(self.d.active)


class _FakeWorker(QObject):
    media_updated = Signal(str, str, bool, float, float, object, str)
    _last_is_playing = False
    _last_title = ""
    current_source_app_id = "spotify.exe"
    _last_provider = "spotify"

    def send_command(self, *a):
        pass


class TestController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._orig = wa.animations_enabled
        wa.animations_enabled = lambda: False              # saltos instantâneos: foco na lógica
        self._path, self._data = config_manager.config_path, config_manager._data
        config_manager.config_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config_manager._data = config_manager._default_config()
        config_manager.set_auto_launch_enabled(True)
        config_manager.set_auto_hide_enabled(False)

        from app.widgets.music.music_controller import MusicWidgetController

        self.worker = _FakeWorker()
        self.c = MusicWidgetController(media_worker=self.worker)
        self.clock = Clock()
        self.c._dismissal._clock = self.clock

    def tearDown(self):
        self.c.skin.close()
        wa.animations_enabled = self._orig
        config_manager.config_path, config_manager._data = self._path, self._data

    def update(self, playing=True, title="Faixa", source="spotify.exe", n=1):
        self.worker.current_source_app_id = source
        for _ in range(n):
            self.c._handle_auto_launch_lifecycle(title, "Artista", playing, 1.0, 100.0, b"", "spotify")
            self.clock.t += 0.35

    def test_music_starting_opens_widget(self):
        self.update()
        self.assertTrue(self.c.is_shown())

    def test_hotkey_hide_during_music_stays_hidden(self):
        self.update()
        self.c.hide(by_user=True)
        self.update(n=200)                                 # ~70 s de música tocando
        self.assertFalse(self.c.is_shown())
        self.assertFalse(self.c.skin.isVisible())

    def test_track_changes_do_not_reopen(self):
        self.update()
        self.c.hide(by_user=True)
        for i in range(10):
            self.update(title=f"Faixa {i}", n=3)
        self.assertFalse(self.c.skin.isVisible())

    def test_after_30s_pause_the_next_play_opens_again(self):
        self.update()
        self.c.hide(by_user=True)
        self.update(playing=False, n=int(31 / 0.35) + 2)   # pausado > 30 s
        self.assertFalse(self.c.skin.isVisible())
        self.update(playing=True)                          # deu play de novo
        self.assertTrue(self.c.is_shown())

    def test_pause_shorter_than_30s_keeps_it_hidden(self):
        self.update()
        self.c.hide(by_user=True)
        self.update(playing=False, n=int(10 / 0.35))
        self.update(playing=True, n=5)
        self.assertFalse(self.c.skin.isVisible())

    def test_media_disappearing_then_music_opens_again(self):
        self.update()
        self.c.hide(by_user=True)
        self.update(playing=False, title=NO_MEDIA)
        self.update(playing=True, title="Outra", n=2)
        self.assertTrue(self.c.is_shown())

    def test_other_player_starting_opens_it(self):
        self.update()
        self.c.hide(by_user=True)
        self.update(title="Do Chrome", source="chrome._crx_yt", n=2)
        self.assertTrue(self.c.is_shown())

    def test_hotkey_show_wins_and_relatches_on_next_hide(self):
        self.update()
        self.c.hide(by_user=True)
        self.update(n=3)
        self.assertFalse(self.c.skin.isVisible())
        self.c.show(is_manual=True)                        # Win+Alt+M de novo
        self.assertTrue(self.c.is_shown())
        self.update(n=3)
        self.assertTrue(self.c.is_shown())                 # segue aberto
        self.c.hide(by_user=True)
        self.update(n=10)
        self.assertFalse(self.c.skin.isVisible())

    def test_hide_by_user_without_any_media_does_not_latch(self):
        self.c.show(is_manual=True)                         # aberto à mão, nada tocando
        self.c.hide(by_user=True)
        self.update(n=2)                                    # música começa depois
        self.assertTrue(self.c.is_shown())

    def test_non_user_hides_do_not_latch(self):
        self.update()
        self.c.hide(soft=True)                              # timeout automático
        self.update(n=2)
        self.assertTrue(self.c.is_shown())

    def test_toggling_the_auto_open_setting_clears_dismissal(self):
        self.update()
        self.c.hide(by_user=True)
        self.c.on_auto_launch_changed(True)
        self.update(n=2)
        self.assertTrue(self.c.is_shown())

    def test_update_during_hide_animation_does_not_reverse_it(self):
        wa.animations_enabled = lambda: True
        self.update()
        QTest.qWait(260)
        self.c.hide(by_user=True)                           # começa a sair (160 ms)
        self.assertTrue(self.c.is_hiding())
        self.update(n=1)                                    # chega mídia no meio da saída
        QTest.qWait(260)
        self.assertFalse(self.c.skin.isVisible())

    def test_bridge_toggle_uses_the_user_path(self):
        from app.hub.service_bridge import HubServiceBridge

        self.update()
        b = QObject()
        b.music_controller = self.c
        HubServiceBridge.toggle_music_widget(b)             # esconde (is_shown -> hide(by_user=True))
        self.update(n=20)
        self.assertFalse(self.c.skin.isVisible())
        HubServiceBridge.toggle_music_widget(b)             # mostra
        self.assertTrue(self.c.is_shown())


if __name__ == "__main__":
    unittest.main()
