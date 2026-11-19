"""
Curvas e tempos de movimento do Weather Widget, copiados das variáveis `--*` da referência (CSS).

Tudo em segundos e puro (sem Qt): o cartão pede "quanto desta animação já passou" e desenha com o valor.
"""

import math
from functools import lru_cache


def cubic_bezier(x1: float, y1: float, x2: float, y2: float):
    """Igual a `cubic-bezier()` do CSS: devolve f(t) -> progresso, com t em 0..1 (Newton + bisseção)."""

    def _coord(t, a, b):
        # Bezier com P0 = 0 e P3 = 1
        return 3 * a * (1 - t) ** 2 * t + 3 * b * (1 - t) * t ** 2 + t ** 3

    def _deriv(t, a, b):
        return 3 * a * (1 - t) ** 2 + 6 * (b - a) * (1 - t) * t + 3 * (1 - b) * t ** 2

    def ease(x: float) -> float:
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        t = x
        for _ in range(8):
            err = _coord(t, x1, x2) - x
            if abs(err) < 1e-5:
                break
            d = _deriv(t, x1, x2)
            if abs(d) < 1e-6:
                break
            t -= err / d
        if not 0.0 <= t <= 1.0 or abs(_coord(t, x1, x2) - x) > 1e-3:
            lo, hi = 0.0, 1.0
            t = x
            for _ in range(30):
                v = _coord(t, x1, x2)
                if abs(v - x) < 1e-5:
                    break
                if v < x:
                    lo = t
                else:
                    hi = t
                t = (lo + hi) / 2
        return _coord(t, y1, y2)

    return ease


EASE_SMOOTH_OUT = cubic_bezier(0.22, 1.0, 0.36, 1.0)      # abas, morph do dia
EASE_IN_OUT = cubic_bezier(0.42, 0.0, 0.58, 1.0)          # "ease-in-out"
EASE_OUT = cubic_bezier(0.0, 0.0, 0.58, 1.0)              # "ease-out"
EASE_IN = cubic_bezier(0.42, 0.0, 1.0, 1.0)               # "ease-in"
EASE_DIGIT = cubic_bezier(0.34, 1.45, 0.64, 1.0)          # números: passa um pouco e volta

# Durações (s)
TABS_DUR = 0.250
ICON_SWAP_DUR = 0.250
ICON_SWAP_START_SCALE = 0.25
TAB_SWAP_STAGGER = 0.035      # abas da previsão: cada uma começa um pouco depois da vizinha (onda)
TAB_SAME_ICON_SCALE = 0.7     # ícone que não mudou (troca de cidade): encolhe até este tamanho e volta
DIGIT_DUR = 0.500
DIGIT_DISTANCE = 8.0
DIGIT_STAGGER = 0.070
TEXT_SWAP_DUR = 0.150
TEXT_SWAP_Y = 4.0
TEXT_MORPH_DUR = 0.180
TEXT_MORPH_RESIZE_DUR = 0.240
SKY_FADE = 0.700
DRIFT_DUR = 16.0
DRIFT_DISTANCE = 18.0
FLASH_DUR = 7.0
SPIN_DUR = 30.0
FLOAT_DUR = 4.0
FLOAT_DISTANCE = 3.0
DROP_DUR = 1.100
PRESS_SCALE = 0.99
PRESS_DUR = 0.150

# Onda de pontos ao fixar/soltar da área de trabalho (valores escolhidos no protótipo
# mockups/weather-dot-wave.html: "Passing wave", brilho branco)
WAVE_DUR = 0.750       # s
WAVE_GAP = 5.0         # px entre pontos (cartão de 300)
WAVE_BAND = 0.35       # largura da faixa, em fração da diagonal
WAVE_SWITCH_AT = 0.5   # momento da onda em que a janela troca de nível
SETTLE_DUR = 0.300     # sombra encolhendo/crescendo ao trocar de nível


def ease_in_out_cubic(x: float) -> float:
    """O `easeInOut` do protótipo (cúbica), que leva a frente da onda de um canto ao outro."""
    if x < 0.5:
        return 4 * x * x * x
    return 1 - ((-2 * x + 2) ** 3) / 2


def progress(now: float, start: float, duration: float) -> float:
    """0..1 de uma animação que começou em `start` (antes de começar = 0, depois de acabar = 1)."""
    if duration <= 0:
        return 1.0
    return min(1.0, max(0.0, (now - start) / duration))


def alternate(now: float, duration: float, ease=EASE_IN_OUT, reverse: bool = False) -> float:
    """Valor 0..1 de uma animação `infinite alternate` (vai e volta), com a curva aplicada a cada meia-volta."""
    cycle = (now / duration) % 2.0
    x = cycle if cycle <= 1.0 else 2.0 - cycle
    v = ease(x)
    return 1.0 - v if reverse else v


def keyframes(x: float, frames: tuple, ease=None) -> float:
    """Interpola `frames` ((pos, valor), ...) em x (0..1), com `ease` aplicado dentro de cada trecho."""
    if x <= frames[0][0]:
        return frames[0][1]
    for (p0, v0), (p1, v1) in zip(frames, frames[1:]):
        if x <= p1:
            f = 0.0 if p1 == p0 else (x - p0) / (p1 - p0)
            if ease is not None:
                f = ease(f)
            return v0 + (v1 - v0) * f
    return frames[-1][1]


# `wx-flash`: 0%, 86%, 100% -> 0; 88% -> .4; 89% -> .08; 91% -> .3 (ease-out por trecho)
FLASH_FRAMES = ((0.0, 0.0), (0.86, 0.0), (0.88, 0.4), (0.89, 0.08), (0.91, 0.3), (1.0, 0.0))

# `wx-flicker` do raio: 0, 70, 100% -> (1, 1); 74% -> (.55, .97); 78% -> (1, 1.02)
FLICKER_OPACITY = ((0.0, 1.0), (0.70, 1.0), (0.74, 0.55), (0.78, 1.0), (1.0, 1.0))
FLICKER_SCALE = ((0.0, 1.0), (0.70, 1.0), (0.74, 0.97), (0.78, 1.02), (1.0, 1.0))

# `wx-drop` das gotas do ícone: translateY -2 -> 10; opacidade 0 -> 1 (30%) -> 0
DROP_Y = ((0.0, -2.0), (1.0, 10.0))
DROP_OPACITY = ((0.0, 0.0), (0.30, 1.0), (1.0, 0.0))


@lru_cache(maxsize=None)
def golden_spread(i: int) -> float:
    """Atraso/posição determinístico e bem espalhado para a i-ésima partícula (como `(i * 0.618) % 1` da referência)."""
    return (i * 0.6180339887) % 1.0


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def wave(now: float, period: float, phase: float = 0.0) -> float:
    """Seno 0..1 (para cintilar estrelas e balançar flocos)."""
    return 0.5 + 0.5 * math.sin((now / period + phase) * 2 * math.pi)
