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
