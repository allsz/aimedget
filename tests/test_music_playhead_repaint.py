"""Tocando, as skins só redesenham quando a barra/o tempo exibido mudam (não o cartão inteiro 60x/s)."""
import sys
from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication

from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
from app.widgets.music.skins.fullcover_skin import FullCoverSkin
from app.widgets.music.skins.ripple_skin import RippleSkin


@pytest.mark.parametrize("cls", [FullCoverSkin, RippleSkin, CapaEmpilhadaSkin])
def test_playing_repaints_only_when_the_playhead_visibly_moves(cls):
    QApplication.instance() or QApplication(sys.argv)
    skin = cls(scale=0.5)
    skin.timer.stop()
    skin.provider = "spotify"          # com ícone do app: sem a onda animada (que pede quadros contínuos)
    skin.is_playing, skin.is_dragging_bar = True, False
    skin.duration, skin.current_time = 600.0, 10.0
    clock = {"t": 100.0}
    skin.last_tick = clock["t"]
    with mock.patch("time.perf_counter", lambda: clock["t"]), mock.patch.object(skin, "update") as upd:
        for _ in range(120):           # 2 s a 60 Hz
            clock["t"] += 1.0 / 60.0
            skin._on_tick()
        frames = upd.call_count
    assert skin.current_time == pytest.approx(12.0, abs=0.05)   # o tempo segue avançando a cada tique
    assert 2 <= frames <= 20, frames                            # redesenha quando muda (seg. e barra), não 120x
    skin.deleteLater()


def test_skin_timer_follows_the_monitor_refresh_rate():
    QApplication.instance() or QApplication(sys.argv)
    from app.core.refresh_rate import refresh_interval_ms
    skin = FullCoverSkin(scale=0.5)
    skin.show()
    QApplication.processEvents()
    assert skin.timer.isActive() and skin.timer.interval() == refresh_interval_ms(skin)
    skin.hide()
    assert not skin.timer.isActive()
    skin.deleteLater()


def _skin_at(cls, current, duration=240.0):
    QApplication.instance() or QApplication(sys.argv)
    skin = cls(scale=0.5)
    skin.timer.stop()
    skin.duration, skin.current_time = duration, current
    skin.is_dragging_bar, skin.pressed_btn, skin._last_seek_sent = False, None, 0.0
    return skin


@pytest.mark.parametrize("cls", [FullCoverSkin, RippleSkin, CapaEmpilhadaSkin])
def test_position_sync_jumps_on_big_drift_eases_on_small_and_ignores_noise(cls):
    skin = _skin_at(cls, 50.0)
    now = 1000.0
    assert skin._sync_playback_position(50.05, 240.0, False, now) is False   # ruído < 0.15 s: nada
    assert skin.current_time == 50.0
    assert skin._sync_playback_position(50.5, 240.0, False, now) is True     # desvio pequeno: corrige 35% do desvio
    assert skin.current_time == pytest.approx(50.0 + 0.5 * 0.35)
    assert skin._sync_playback_position(90.0, 240.0, False, now) is True     # desvio > 1.5 s: salta
    assert skin.current_time == 90.0
    assert skin._sync_playback_position(5.0, 200.0, True, now) is True       # faixa nova: vai para a posição dela
    assert skin.current_time == 5.0
    skin.deleteLater()


@pytest.mark.parametrize("cls", [FullCoverSkin, RippleSkin, CapaEmpilhadaSkin])
def test_position_sync_is_paused_while_dragging_or_right_after_a_seek(cls):
    skin = _skin_at(cls, 50.0)
    skin.is_dragging_bar = True
    assert skin._sync_playback_position(120.0, 240.0, False, 1000.0) is False
    skin.is_dragging_bar, skin._last_seek_sent = False, 999.5
    assert skin._sync_playback_position(120.0, 240.0, False, 1000.0) is False   # < 1.5 s do último seek enviado
    assert skin.current_time == 50.0
    assert skin._sync_playback_position(120.0, 240.0, False, 1002.0) is True
    skin.deleteLater()
