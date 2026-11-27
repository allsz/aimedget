"""
Espera o computador acalmar antes de fazer um trabalho que não é urgente (ex.: montar o Hub escondido).

No logon o Windows sobe dezenas de apps ao mesmo tempo. Um prazo fixo ("daqui a 15 s") cai no meio disso: medido no
logon, montar o Hub 15 s depois da partida levou 4,3 s contra ~1 s numa máquina calma, e os widgets na tela
travavam nesse tempo. Aqui o trabalho espera a CPU do sistema inteiro ficar baixa por algumas amostras seguidas.
Se ela nunca acalmar, o trabalho simplesmente não roda (o Hub continua sendo montado ao ser aberto).
"""

from __future__ import annotations

import sys
import time
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer

IDLE_FIRST_DELAY_MS = 8_000      # nem olha a CPU antes disto: o grosso da partida do app já passou
IDLE_POLL_MS = 2_000             # intervalo entre amostras de CPU
IDLE_BUSY_LIMIT = 0.25           # fração da CPU (todos os núcleos) abaixo da qual a máquina conta como calma
IDLE_CALM_SAMPLES = 2            # amostras calmas seguidas exigidas
IDLE_GIVE_UP_MS = 180_000        # desiste (não roda) se a máquina não acalmar neste tempo


class CpuSampler:
    """Uso de CPU do sistema inteiro (0..1) desde a chamada anterior. None na 1ª chamada ou fora do Windows."""

    def __init__(self):
        self._prev: tuple[int, int, int] | None = None

    @staticmethod
    def _times() -> tuple[int, int, int] | None:
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            idle, kernel, user = (wintypes.FILETIME() for _ in range(3))
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return None

            def _t(ft) -> int:
                return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

            return _t(idle), _t(kernel), _t(user)   # o tempo "kernel" inclui o ocioso
        except Exception:
            return None

    def busy(self) -> Optional[float]:
        now = self._times()
        prev, self._prev = self._prev, now
        if prev is None or now is None:
            return None
        d_idle, d_kernel, d_user = (n - p for n, p in zip(now, prev))
        total = d_kernel + d_user
        if total <= 0:
            return None
        return min(1.0, max(0.0, 1.0 - d_idle / total))


class IdleGate(QObject):
    """Chama `callback` uma vez, quando a CPU ficar calma. `cancelled` fica True se desistiu ou foi parado."""

    def __init__(self, callback: Callable[[], None], *, sampler=None, first_delay_ms: int = IDLE_FIRST_DELAY_MS,
                 poll_ms: int = IDLE_POLL_MS, busy_limit: float = IDLE_BUSY_LIMIT,
                 calm_samples: int = IDLE_CALM_SAMPLES, give_up_ms: int = IDLE_GIVE_UP_MS, parent=None):
        super().__init__(parent)
        self._callback = callback
        self._sampler = sampler or CpuSampler()
        self._first_delay_ms = first_delay_ms
        self._poll_ms = poll_ms
        self._busy_limit = busy_limit
        self._calm_needed = calm_samples
        self._give_up_ms = give_up_ms
        self._calm = 0
        self._t0 = 0.0
        self.cancelled = False
        self.fired = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._t0 = time.monotonic()
        self._sampler.busy()   # 1ª leitura só marca o ponto de partida
        self._timer.start(self._first_delay_ms)

    def stop(self):
        self.cancelled = True
        self._timer.stop()

    def waited_ms(self) -> float:
        return (time.monotonic() - self._t0) * 1000.0

    def _tick(self):
        if self.cancelled or self.fired:
            return
        busy = self._sampler.busy()
        # Sem leitura (fora do Windows) não há como saber: não segura o trabalho
        self._calm = self._calm + 1 if (busy is None or busy < self._busy_limit) else 0
        if self._calm >= self._calm_needed:
            self.fired = True
            try:
                from app.core import startup_trace
                startup_trace.amend("idle_wait", self.waited_ms())
            except Exception:
                pass
            self._callback()
            return
        if self.waited_ms() >= self._give_up_ms:
            self.cancelled = True   # a máquina não acalmou: o Hub fica para a primeira abertura
            return
        self._timer.start(self._poll_ms)
