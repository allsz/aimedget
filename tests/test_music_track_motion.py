"""
Troca de faixa animada nas skins Ecos, Capa Completa e Vinil (app/widgets/music/skins/track_motion.py).
Protótipo: mockups/music-track-change.html.
"""
import sys
from unittest import mock

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.widgets.music.skins import track_motion as tm
from app.widgets.music.skins.fullcover_skin import FullCoverSkin
from app.widgets.music.skins.ripple_skin import RippleSkin
from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

SKINS = {"ripple": RippleSkin, "fullcover": FullCoverSkin, "vinyl": VinylMusicSkin}


def _png(color: str) -> bytes:
    img = QImage(300, 300, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


RED, BLUE = _png("red"), _png("blue")


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch):
    """Nada de gravar a escolha do efeito na configuração do usuário."""
    store: dict = {}
    monkeypatch.setattr(config_manager, "get_music_track_effect", lambda skin, default: store.get(skin, default))
    monkeypatch.setattr(config_manager, "set_music_track_effect", lambda skin, effect: store.__setitem__(skin, effect))
    yield store


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _skin(cls, clock, allowed=True, effect=None):
    QApplication.instance() or QApplication(sys.argv)
    skin = cls(scale=0.5)
    skin.timer.stop()
    skin._motion_allowed = lambda: allowed
    if effect:
        skin.track_effect = effect
    skin.on_media_updated("Track A", "Artist A", True, 120.0, 200.0, RED)   # 1ª sincronização: sem animação
    skin.last_tick = clock.t
    return skin


def _advance(skin, clock, seconds, fps=60):
    """Roda o quadro da skin (o mesmo do timer) por `seconds`, com o relógio simulado."""
    tick = skin._on_physics_tick if isinstance(skin, VinylMusicSkin) else skin._on_tick
    frames = []
    for _ in range(int(seconds * fps)):
        clock.t += 1.0 / fps
        tick()
        frames.append(skin)
    return frames


@pytest.mark.parametrize("skin_id", list(SKINS))
def test_defaults_are_the_chosen_effects(skin_id):
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(SKINS[skin_id], clock)
    assert skin.track_effect == {"ripple": "spin", "fullcover": "zoom", "vinyl": "hop"}[skin_id]
    skin.deleteLater()


def test_first_sync_does_not_animate():
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(RippleSkin, clock)
    assert not skin._motion.busy
    skin.deleteLater()


@pytest.mark.parametrize("skin_id,effect", [(s, e) for s, effects in tm.EFFECTS.items() for e in effects])
def test_every_effect_animates_paints_and_ends_clean(skin_id, effect):
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(SKINS[skin_id], clock, effect=effect)
        skin.on_media_updated("Track B", "Artist B", True, 0.0, 180.0, BLUE)
        assert skin._motion.busy and skin._motion.p == 0.0     # anima (não pula)
        seen = []
        for _ in range(int(tm.DURATION_S[effect] * 60) + 4):
            clock.t += 1.0 / 60.0
            (skin._on_physics_tick if skin_id == "vinyl" else skin._on_tick)()
            seen.append(skin._motion_p())
            if len(seen) % 6 == 0:
                assert not skin.grab().isNull()                # cada efeito pinta no meio do caminho
        for d in (1, -1):                                      # e no sentido "anterior" também
            skin._motion.hold(skin._motion_snapshot(), clock.t, d, effect)
            skin._motion.go(clock.t)
            skin._motion.p = 0.5
            assert not skin.grab().isNull()
        skin._motion.cancel()
    assert any(0.2 < p < 0.8 for p in seen)                    # passou pelo meio
    assert seen[-1] == 1.0 and not skin._motion.busy           # terminou e limpou o estado antigo
    skin.deleteLater()


@pytest.mark.parametrize("skin_id", list(SKINS))
def test_without_windows_animations_the_change_is_instant(skin_id):
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(SKINS[skin_id], clock, allowed=False)
        skin.on_media_updated("Track B", "Artist B", True, 0.0, 180.0, BLUE)
    assert not skin._motion.busy
    assert skin._shown_progress(skin._live_progress()) == 0.0   # barra já no começo da faixa nova
    skin.deleteLater()


def test_animations_off_in_windows_is_respected():
    QApplication.instance() or QApplication(sys.argv)
    skin = RippleSkin(scale=0.5)
    skin.timer.stop()
    with mock.patch.object(tm, "animations_enabled", lambda: False), mock.patch.object(skin, "isVisible", lambda: True):
        skin.on_media_updated("Track A", "Artist A", True, 120.0, 200.0, RED)
        skin.on_media_updated("Track B", "Artist B", True, 0.0, 180.0, BLUE)
    assert not skin._motion.busy
    skin.deleteLater()


def test_new_track_waits_briefly_for_its_cover_then_starts_anyway():
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(FullCoverSkin, clock)
        skin.on_media_updated("Track B", "Artist B", True, 0.0, 180.0, RED)   # capa ainda é a antiga
        assert skin._motion.pending
        _advance(skin, clock, tm.COVER_WAIT_S / 2)
        assert skin._motion.pending and skin._motion.p == 0.0                # segura o estado antigo parado
        skin.on_media_updated("Track B", "Artist B", True, 0.1, 180.0, BLUE)  # a capa chegou: começa
        assert skin._motion.busy and not skin._motion.pending
        skin._motion.cancel()
        skin.on_media_updated("Track C", "Artist C", True, 0.0, 180.0, BLUE)  # mesma capa (mesmo álbum)
        _advance(skin, clock, tm.COVER_WAIT_S + 0.05)
        assert skin._motion.busy and not skin._motion.pending                # passou o tempo: começa sem ela
    skin.deleteLater()


def test_cover_found_later_animates_without_moving_the_text():
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(RippleSkin, clock)
        skin.on_media_updated("Track A", "Artist A", True, 121.0, 200.0, BLUE)   # só a capa mudou
        assert skin._motion.busy and not skin._motion.pending
        skin._motion.p = 0.3
        calls = []
        with mock.patch.object(skin, "_draw_title_line", lambda p, text, a, dy: calls.append((text, a, dy))), \
                mock.patch.object(skin, "_draw_artist_line", lambda p, text, a, dy: calls.append((text, a, dy))):
            skin._paint_track_text(None)
    assert calls == [("Track A", 1.0, 0.0), ("Artist A", 1.0, 0.0)]
    skin.deleteLater()


def test_text_swaps_old_out_and_new_in():
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(FullCoverSkin, clock)
        skin.on_media_updated("Track B", "Artist B", True, 0.0, 180.0, BLUE)
        skin._motion.p = 0.3
        calls = []
        with mock.patch.object(skin, "_draw_title_line", lambda p, text, a, dy: calls.append(text)), \
                mock.patch.object(skin, "_draw_artist_line", lambda p, text, a, dy: calls.append(text)):
            skin._paint_track_text(None)
    assert "Track A" in calls and "Track B" in calls        # os dois títulos juntos no meio da troca
    skin.deleteLater()


@pytest.mark.parametrize("skin_id", list(SKINS))
def test_progress_bar_glides_back_without_a_jump(skin_id):
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(SKINS[skin_id], clock)
        skin.on_media_updated("Track B", "Artist B", True, 0.0, 180.0, BLUE)
        values = [skin._shown_progress(skin._live_progress())]
        for _ in range(80):
            clock.t += 1.0 / 60.0
            (skin._on_physics_tick if skin_id == "vinyl" else skin._on_tick)()
            values.append(skin._shown_progress(skin._live_progress()))
    assert values[0] == pytest.approx(0.6)                    # começa onde a faixa antiga estava (120/200)
    steps = [b - a for a, b in zip(values, values[1:])]
    assert max(abs(s) for s in steps) < 0.08                  # sem salto entre quadros
    assert values[-1] < 0.02                                  # assenta no começo da faixa nova
    skin.deleteLater()


def test_vinyl_needle_hop_leaves_the_groove_and_lands_on_the_new_start():
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(VinylMusicSkin, clock)
        skin.arm_state, skin.is_playing = "on", True
        _advance(skin, clock, 0.1)
        start = skin.arm_current_angle
        skin.on_media_updated("Track B", "Artist B", True, 0.0, 180.0, BLUE)
        angles, spins = [], []
        for _ in range(int(tm.DURATION_S["hop"] * 60) + 4):
            before = skin.vinyl_angle
            clock.t += 1.0 / 60.0
            skin._on_physics_tick()
            angles.append(skin.arm_current_angle)
            spins.append((skin.vinyl_angle - before) % 360.0)
    assert start > 20.0                                       # estava no fim da faixa antiga (drift)
    assert min(angles) < 11.5                                 # saiu do disco
    assert max(abs(b - a) for a, b in zip(angles, angles[1:])) < 2.0   # sem estalo
    assert angles[-1] == pytest.approx(skin._compute_target_play_angle(), abs=0.05)
    assert max(spins) > 2.5 * min(spins)                      # o disco acelerou e voltou
    skin.deleteLater()


def test_menu_lists_the_skin_effects_and_saves_the_choice(_isolated_config):
    clock = Clock()
    with mock.patch("time.perf_counter", clock):
        skin = _skin(VinylMusicSkin, clock)
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        assert skin._populate_skin_effects_menu(menu, True)
        assert len(menu.actions()) == 4
        skin.on_media_updated("Track B", "Artist B", True, 0.0, 180.0, BLUE)
        skin._motion.cancel()
        menu.actions()[2].trigger()                           # "Virar selo"
    assert skin.track_effect == "flip" and _isolated_config["vinyl"] == "flip"
    assert skin._motion.busy and skin._motion.effect == "flip"   # prévia: repete a última troca
    skin.deleteLater()


def test_spring_is_normalized_and_overshoots():
    assert tm.spring(0.0) == 0.0 and tm.spring(1.0) == 1.0
    assert max(tm.spring(i / 200) for i in range(201)) > 1.0  # MORPH passa do ponto e assenta
