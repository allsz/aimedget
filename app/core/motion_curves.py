"""
Curvas e molas normalizadas para animações por tempo (troca de faixa do Music, troca de skin dos widgets).

As molas seguem o modelo do app (massa 1, Euler semi-implícito, 4 subpassos; `Spring` em
app/hub/components/city_list.py), mas normalizadas: t=1 é "assentou", então quem anima escolhe a duração e a mola só
dá o formato (pode passar de 1 no caminho).
"""

from __future__ import annotations

import math
from functools import lru_cache

MORPH = (320.0, 20.0)
PRESS = (520.0, 20.0)
SLIDE = (420.0, 34.0)
LIFT = (260.0, 24.0)
SETTLE = (380.0, 30.0)
SUBSTEPS = 4


def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def span(t: float, a: float, b: float) -> float:
    """Progresso local de `t` dentro da fatia [a, b] (0 antes, 1 depois)."""
    return clamp((t - a) / (b - a)) if b > a else (1.0 if t >= b else 0.0)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smooth(t: float) -> float:
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


def ease_out(t: float) -> float:
    return 1.0 - (1.0 - clamp(t)) ** 3


def ease_out4(t: float) -> float:
    return 1.0 - (1.0 - clamp(t)) ** 4


def ease_in(t: float) -> float:
    return clamp(t) ** 3


def ease_in_out(t: float) -> float:
    t = clamp(t)
    return 4.0 * t * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def bump(t: float) -> float:
    """0 -> 1 -> 0 (meia senoide)."""
    return math.sin(math.pi * clamp(t))


@lru_cache(maxsize=8)
def _spring_samples(k: float, c: float) -> tuple[float, ...]:
    """A mola de 0 até 1, uma amostra por ms, até assentar (no máximo 2,5 s)."""
    samples = [0.0]
    x = v = 0.0
    dt = 0.001 / SUBSTEPS
    calm = 0
    for _ in range(2500):
        for _ in range(SUBSTEPS):
            v += (-k * (x - 1.0) - c * v) * dt
            x += v * dt
        samples.append(x)
        calm = calm + 1 if (abs(x - 1.0) < 0.003 and abs(v) < 0.02) else 0
        if calm > 25:
            break
    samples.append(1.0)
    return tuple(samples)


def spring(t: float, kc: tuple[float, float] = MORPH) -> float:
    """Mola normalizada: t=1 é "assentou" (no caminho pode passar de 1)."""
    s = _spring_samples(*kc)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    f = t * (len(s) - 1)
    i = int(f)
    return lerp(s[i], s[i + 1], f - i)
