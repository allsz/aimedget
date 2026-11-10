"""
Escolha da sessão de mídia: o player que está tocando não pode ter a capa "injetada" por um
player pausado durante a troca de faixa (Windows reporta título vazio / status "mudando").
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.session_selection import (
    CHANGING,
    OTHER,
    PAUSED,
    PLAYING,
    SessionCandidate,
    pick_session,
)


def cand(key, status=PLAYING, score=90, music=True):
    return SessionCandidate(key=key, is_music=music, score=score, status=status, payload=key)


SPOT = "spotify.exe"
APPLE = "applemusic"


class TestPriorityToPlaying(unittest.TestCase):
    def test_playing_beats_paused_even_with_lower_base_score(self):
        chosen, hold = pick_session([cand(APPLE, PAUSED, 90), cand("chrome", PLAYING, 60)], None, 0.0, 10.0)
        self.assertEqual(chosen.key, "chrome")
        self.assertFalse(hold)

    def test_two_playing_uses_base_score(self):
        chosen, _ = pick_session([cand("chrome", PLAYING, 60), cand(SPOT, PLAYING, 90)], None, 0.0, 10.0)
        self.assertEqual(chosen.key, SPOT)

    def test_all_paused_still_selects_something(self):
        chosen, _ = pick_session([cand(APPLE, PAUSED, 90), cand(SPOT, PAUSED, 90)], None, 0.0, 10.0)
        self.assertIsNotNone(chosen)


class TestNoCoverInjection(unittest.TestCase):
    def test_track_change_with_changing_status_keeps_active_player(self):
        # Spotify tocando troca de faixa (status "mudando"); Apple Music pausado com pontuação igual
        chosen, hold = pick_session([cand(APPLE, PAUSED), cand(SPOT, CHANGING)], SPOT, 5.0, 5.2)
        self.assertEqual(chosen.key, SPOT)
        self.assertFalse(hold)

    def test_track_change_with_empty_title_holds_instead_of_leaking(self):
        # No instante da troca o Spotify some como "não-música" (título vazio)
        cands = [cand(APPLE, PAUSED, 90), cand(SPOT, OTHER, -1, music=False)]
        chosen, hold = pick_session(cands, SPOT, sticky_ok_at=5.0, now=5.4)
        self.assertIsNone(chosen)
        self.assertTrue(hold)                       # segura o estado: nada do Apple Music entra

    def test_holds_for_every_poll_cycle_within_grace(self):
        cands = [cand(APPLE, PAUSED, 99), cand(SPOT, OTHER, -1, music=False)]
        for t in (5.35, 5.70, 6.05, 6.40):          # ciclos de 350 ms
            chosen, hold = pick_session(cands, SPOT, 5.0, t)
            self.assertTrue(hold and chosen is None, t)

    def test_releases_after_grace_if_it_never_comes_back(self):
        cands = [cand(APPLE, PAUSED, 90), cand(SPOT, OTHER, -1, music=False)]
        chosen, hold = pick_session(cands, SPOT, sticky_ok_at=5.0, now=9.0)
        self.assertEqual(chosen.key, APPLE)
        self.assertFalse(hold)

    def test_a_player_that_is_actually_playing_can_take_over_during_hold(self):
        cands = [cand(APPLE, PLAYING, 90), cand(SPOT, OTHER, -1, music=False)]
        chosen, hold = pick_session(cands, SPOT, 5.0, 5.4)
        self.assertEqual(chosen.key, APPLE)
        self.assertFalse(hold)

    def test_paused_challenger_never_displaces_current_session(self):
        # Sessão atual pausada e outro player pausado com pontuação maior: nada muda
        chosen, _ = pick_session([cand(APPLE, PAUSED, 99), cand(SPOT, PAUSED, 60)], SPOT, 9.0, 9.1)
        self.assertEqual(chosen.key, SPOT)

    def test_new_playing_player_takes_over_from_paused_current(self):
        chosen, _ = pick_session([cand(APPLE, PLAYING, 90), cand(SPOT, PAUSED, 90)], SPOT, 9.0, 9.1)
        self.assertEqual(chosen.key, APPLE)

    def test_closed_player_is_held_briefly_then_released(self):
        chosen, hold = pick_session([cand(APPLE, PAUSED, 90)], SPOT, 5.0, 5.1)
        self.assertIsNone(chosen)
        self.assertTrue(hold)                      # pode ser só a troca de faixa de um player web
        chosen, hold = pick_session([cand(APPLE, PAUSED, 90)], SPOT, 5.0, 9.0)
        self.assertEqual(chosen.key, APPLE)        # sumiu de vez: cai para o outro player
        self.assertFalse(hold)

    def test_closed_player_with_another_actually_playing_switches_immediately(self):
        chosen, hold = pick_session([cand(APPLE, PLAYING, 90)], SPOT, 5.0, 5.1)
        self.assertEqual(chosen.key, APPLE)
        self.assertFalse(hold)

    def test_nothing_available_returns_none_without_hold(self):
        chosen, hold = pick_session([], None, 0.0, 1.0)
        self.assertIsNone(chosen)
        self.assertFalse(hold)

    def test_video_bug_youtube_session_vanishes_for_one_cycle(self):
        """
        Reproduz o vídeo cover_leaking: YT Music (PWA do Chrome) tocando, Spotify aberto e PAUSADO.
        Na troca de faixa a sessão do Chrome some da lista por um ciclo; antes, o Spotify pausado
        era escolhido e sua capa/título apareciam por ~10 quadros.
        """
        yt = "chrome._crx_cinhimbnkkghhklpknlkffjgod"
        spot_paused = cand(SPOT, PAUSED, 90)
        timeline = [
            [cand(yt, PLAYING, 90), spot_paused],   # tocando
            [cand(yt, PLAYING, 90), spot_paused],
            [spot_paused],                           # a sessão do Chrome some (troca de faixa)
            [spot_paused],                           # e continua ausente no ciclo seguinte
            [cand(yt, PLAYING, 90), spot_paused],   # volta com a faixa nova
        ]
        sticky, ok_at, now, shown = None, 0.0, 10.0, []
        for cands in timeline:
            if sticky and any(c.key == sticky and c.is_music for c in cands):
                ok_at = now
            chosen, hold = pick_session(cands, sticky, ok_at, now)
            if chosen is not None:
                sticky, ok_at = chosen.key, now
                shown.append(chosen.key)
            else:
                shown.append("(segura)" if hold else "(nada)")
            now += 0.35
        self.assertNotIn(SPOT, shown)
        self.assertEqual(shown, [yt, yt, "(segura)", "(segura)", yt])

    def test_title_goes_empty_and_session_vanishes_in_the_same_change(self):
        yt = "chrome._crx_x"
        for third in ([cand(SPOT, PAUSED)], [cand(yt, OTHER, -1, music=False), cand(SPOT, PAUSED)]):
            chosen, hold = pick_session(third, yt, sticky_ok_at=20.0, now=20.35)
            self.assertIsNone(chosen)
            self.assertTrue(hold)

    def test_full_scenario_no_frame_shows_the_other_player(self):
        """Simula a troca de faixa do Spotify ao longo de vários ciclos de 350 ms."""
        timeline = [
            [cand(SPOT, PLAYING), cand(APPLE, PAUSED)],                          # tocando
            [cand(SPOT, CHANGING), cand(APPLE, PAUSED)],                         # troca
            [cand(SPOT, OTHER, -1, music=False), cand(APPLE, PAUSED)],           # título vazio
            [cand(SPOT, OTHER, -1, music=False), cand(APPLE, PAUSED)],
            [cand(SPOT, PLAYING), cand(APPLE, PAUSED)],                          # faixa nova pronta
        ]
        sticky, ok_at, now = None, 0.0, 10.0
        shown = []
        for cands in timeline:
            if sticky and any(c.key == sticky and c.is_music for c in cands):
                ok_at = now
            chosen, hold = pick_session(cands, sticky, ok_at, now)
            if chosen is not None:
                sticky, ok_at = chosen.key, now
                shown.append(chosen.key)
            elif hold:
                shown.append("(segura)")
            now += 0.35
        self.assertNotIn(APPLE, shown)


if __name__ == "__main__":
    unittest.main()
