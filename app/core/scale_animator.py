"""
Leva um tamanho (escala) até o alvo com uma mola, em vez de trocar no corte.

Usado por todo widget flutuante (Music, Clima, Desempenho): a mudança automática de tamanho, os presets e o botão
Automático do Hub passam por aqui. A mola é a do tamanho (320/30, massa 1, Euler semi-implícito com 4 subpassos): assenta
sem passar do alvo, porque a janela é em pixels inteiros e um quique faria o contorno tremer.
"""

import time
from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QWidget

from app.core.refresh_rate import refresh_interval_ms
from app.core.frame_clock import FrameTimer

SCALE_SPRING = (320.0, 30.0)
SUBSTEPS = 4


class ScaleAnimator(QObject):
    def __init__(self, owner: QWidget, apply: Callable[[float], None], spring=SCALE_SPRING, tolerance: float = 0.0015):
        super().__init__(owner)
        self._owner = owner
        self._apply = apply
        self._k, self._c = spring
        self._tol = tolerance
        self._x = self._v = self._target = 0.0
        self._dir = 1.0
        self._last = 0.0
        self._timer = FrameTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_frame)

    @property
    def target(self) -> float:
        return self._target

    def is_active(self) -> bool:
        return self._timer.isActive()

    def start(self, current: float, target: float):
        """Anima de `current` até `target`; se já está animando, só troca o alvo (a velocidade se mantém)."""
        self._target = float(target)
        if not self._timer.isActive():
            self._x, self._v = float(current), 0.0
            self._last = time.perf_counter()
            self._timer.setInterval(refresh_interval_ms(self._owner))   # taxa do monitor onde o widget está agora
            self._timer.start()
        self._dir = 1.0 if self._target >= self._x else -1.0   # lado de onde vem: cruzar o alvo = chegou

    def stop(self):
        """Para onde está (o usuário assumiu o controle)."""
        self._timer.stop()

    def finish(self):
        """Pula para o alvo (widget oculto, animações desligadas)."""
        if self._timer.isActive():
            self._timer.stop()
            self._apply(self._target)

    def _on_frame(self):
        now = time.perf_counter()
        dt = min(now - self._last, 1.0 / 30.0)
        self._last = now
        sub = dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            a = -self._k * (self._x - self._target) - self._c * self._v
            self._v += a * sub
            self._x += self._v * sub
        # A 320/30 é levemente subamortecida (passaria ~0,2% do alvo e voltaria 1 px): ao cruzar o alvo, para nele.
        crossed = (self._target - self._x) * self._dir <= 0.0
        if crossed or (abs(self._x - self._target) < self._tol and abs(self._v) < self._tol * 13.0):
            self._timer.stop()
            self._apply(self._target)
        else:
            self._apply(self._x)
