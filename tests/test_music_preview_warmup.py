"""As miniaturas da página Música são montadas em segundo plano, uma por volta do laço (não no 1º clique)."""
import sys

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.widgets.music.skins import specs


def test_warm_previews_builds_every_skin_one_turn_at_a_time(monkeypatch):
    QApplication.instance() or QApplication(sys.argv)
    specs.init_music_skin_specs()
    monkeypatch.setattr(specs, "_cached_instances", {})
    built = []
    real = specs._get_headless
    monkeypatch.setattr(specs, "_get_headless", lambda sid, loader: built.append(sid) or real(sid, loader))

    specs.warm_previews(delay_ms=0)
    assert built == []                         # nada no clique/na chamada: só depois, no laço de eventos
    QApplication.processEvents()
    assert len(built) <= 1                     # uma por volta do laço, sem travar
    for _ in range(50):
        if len(built) == len(specs._loaders):
            break
        QTest.qWait(5)
    assert sorted(built) == sorted(specs._loaders)
    assert set(specs._cached_instances) == set(specs._loaders)

    built.clear()
    specs.warm_previews(delay_ms=0)            # já aquecidas: não refaz nada
    QTest.qWait(20)
    assert built == []
