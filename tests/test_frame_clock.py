"""Relógio de quadros compartilhado: uma batida para todas as animações, cada uma no seu ritmo, parado se ninguém anima.

Na suíte inteira, widgets de outros testes podem estar animando: as asserções olham os assinantes DESTE teste (e o
relógio parado só quando ele está sozinho).
"""
import sys
import time

from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.frame_clock import FrameTimer, frame_clock


def _app():
    return QApplication.instance() or QApplication(sys.argv)


def _rate(times):
    return (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else 0.0


def _subscribed(t) -> bool:
    return t in frame_clock()._subs


def test_one_clock_drives_every_subscriber_at_its_own_rate_and_stops_when_idle():
    _app()
    owner = QObject()
    fast, slow = FrameTimer(owner), FrameTimer(owner)
    hits = {"fast": [], "slow": []}
    fast.timeout.connect(lambda: hits["fast"].append(time.perf_counter()))
    slow.timeout.connect(lambda: hits["slow"].append(time.perf_counter()))
    clock = frame_clock()
    others = clock.active_count()
    fast.start(8)
    slow.start(33)
    assert clock.is_running() and clock.interval() <= 8          # bate no menor ritmo pedido
    QTest.qWait(700)
    fast.stop()
    slow.stop()
    assert not _subscribed(fast) and not _subscribed(slow)        # parados saem do relógio
    if others == 0:
        assert not clock.is_running()                             # ninguém anima: relógio parado
    # Cada um no seu ritmo (com folga para o agendador do Windows)
    assert 70 <= _rate(hits["fast"]) <= 135
    assert 24 <= _rate(hits["slow"]) <= 34
    # Mesma batida: cada aviso do lento coincide com um do rápido (um acordar por quadro, não dois)
    shared = sum(1 for s in hits["slow"] if any(abs(s - f) < 0.002 for f in hits["fast"]))
    assert shared >= len(hits["slow"]) - 1


def test_drop_in_semantics_and_dead_owner_is_dropped():
    _app()
    owner = QObject()
    t = FrameTimer(owner)
    assert not t.isActive() and t.interval() == 16
    assert t.timerType() == Qt.TimerType.PreciseTimer
    t.setInterval(20)
    t.start()
    assert t.isActive() and t.interval() == 20
    n = []
    t.timeout.connect(lambda: n.append(1))
    QTest.qWait(10)
    assert n == []                                             # como o QTimer: o 1º aviso vem depois de 1 intervalo
    QTest.qWait(120)
    assert n
    owner.deleteLater()                                        # dono destruído sem stop(): o relógio solta sozinho
    QTest.qWait(80)
    assert all(s is not t for s in frame_clock()._subs)


def test_stop_and_restart_from_inside_the_callback():
    _app()
    owner = QObject()
    t = FrameTimer(owner)
    calls = []

    def cb():
        calls.append(1)
        t.stop()
        if len(calls) < 3:
            t.start(10)

    t.timeout.connect(cb)
    t.start(10)
    QTest.qWait(200)
    assert len(calls) == 3 and not t.isActive() and not _subscribed(t)
