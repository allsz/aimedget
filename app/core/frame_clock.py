"""
Relógio de quadros compartilhado do app.

Antes, cada animação (cartões, skins, molas do Hub, onda de fixar, alinhador...) tinha o próprio QTimer de ~16 ms:
com vários widgets animando, o processo acordava N vezes por quadro, em fases diferentes, e cada janela pintava num
giro diferente do laço de eventos. Agora existe UM relógio: todas as animações avançam no mesmo giro (mesma fase,
um acordar por quadro) e ele para sozinho quando ninguém anima.

`FrameTimer` é um substituto direto do pedaço do QTimer que os laços de animação usam (`timeout`, `start([ms])`,
`stop`, `isActive`, `interval`, `setInterval`, `setTimerType`): trocar `QTimer(self)` por `FrameTimer(self)` basta.
Cada assinante mantém o próprio ritmo (ex.: 33 ms do modo ambiente ao lado de 7 ms de um monitor de 144 Hz): o
relógio bate no menor intervalo pedido e cada um é chamado no seu, com o atraso acumulado compensado (a média fica
exata mesmo quando os ritmos não se dividem).

Não serve para atrasos únicos, consultas periódicas ou debounce: esses continuam com QTimer.
"""

from __future__ import annotations

import time
from typing import List, Optional

from PySide6.QtCore import QCoreApplication, QObject, Qt, QTimer, Signal

try:
    from shiboken6 import isValid as _is_valid
except Exception:  # pragma: no cover
    def _is_valid(obj) -> bool:
        return obj is not None


DEFAULT_INTERVAL_MS = 16


class FrameClock(QObject):
    """O relógio único. Use `frame_clock()`; os assinantes são `FrameTimer`s ativos."""

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._subs: List["FrameTimer"] = []
        self._ticking = False
        self.ticks = 0   # quantas batidas (para testes/diagnóstico)

    # --- Assinantes ---

    def _attach(self, sub: "FrameTimer"):
        if sub not in self._subs:
            self._subs.append(sub)
        self._retime()

    def _detach(self, sub: "FrameTimer"):
        try:
            self._subs.remove(sub)
        except ValueError:
            pass
        self._retime()

    def active_count(self) -> int:
        return sum(1 for s in self._subs if _is_valid(s))

    def is_running(self) -> bool:
        return self._timer.isActive()

    def interval(self) -> int:
        return self._timer.interval()

    def _retime(self):
        self._subs = [s for s in self._subs if _is_valid(s)]
        if not self._subs:
            self._timer.stop()
            return
        iv = max(1, min(s._interval for s in self._subs))
        if self._timer.interval() != iv:
            self._timer.setInterval(iv)
        if not self._timer.isActive():
            self._timer.start()

    # --- Batida ---

    def _tick(self):
        self.ticks += 1
        now = time.perf_counter()
        slack = self._timer.interval() * 0.0005   # meia batida, em segundos
        self._ticking = True
        try:
            for sub in list(self._subs):
                if not _is_valid(sub) or not sub._active:
                    continue
                if now + slack < sub._due:
                    continue
                period = sub._interval / 1000.0
                sub._due += period
                if sub._due < now - period:   # ficou muito para trás (laço travado): recomeça daqui, sem rajada
                    sub._due = now + period
                sub.timeout.emit()
        finally:
            self._ticking = False
            self._retime()


_clock: Optional[FrameClock] = None


def frame_clock() -> FrameClock:
    global _clock
    if _clock is None or not _is_valid(_clock):
        _clock = FrameClock(QCoreApplication.instance())
    return _clock


class FrameTimer(QObject):
    """Substituto do QTimer para laços de animação, movido pelo relógio compartilhado."""

    timeout = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._interval = DEFAULT_INTERVAL_MS
        self._active = False
        self._due = 0.0

    def setTimerType(self, _type):   # o relógio já é preciso
        pass

    def timerType(self):
        return Qt.TimerType.PreciseTimer   # quem bate é o relógio compartilhado, que é PreciseTimer

    def setInterval(self, ms: int):
        ms = max(1, int(ms))
        if ms == self._interval:
            return
        self._interval = ms
        if self._active:
            self._due = min(self._due, time.perf_counter() + ms / 1000.0)
            frame_clock()._retime()

    def interval(self) -> int:
        return self._interval

    def isActive(self) -> bool:
        return self._active

    def start(self, ms: Optional[int] = None):
        if ms is not None:
            self._interval = max(1, int(ms))
        # Como o QTimer: (re)começar conta um intervalo inteiro a partir de agora
        self._due = time.perf_counter() + self._interval / 1000.0
        self._active = True
        frame_clock()._attach(self)

    def stop(self):
        if not self._active:
            return
        self._active = False
        frame_clock()._detach(self)
