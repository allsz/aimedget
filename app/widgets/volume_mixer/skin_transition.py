"""
Troca de visual (skin) do mixer com o flyout na tela. Protótipo: mockups/skin-switch-transition.html.

Antes a troca era uma FOTO do card antigo dissolvendo por cima do novo (theme_crossfade). Entre visuais de formatos
diferentes (o "Exclusive" tem figurinhas, o card sobe e a janela cresce) a foto e o card novo ficavam com fileiras
diferentes ao mesmo tempo (fantasma) e as figurinhas apenas sumiam. Aqui o container se transforma no lugar e o
conteúdo troca por dentro, sem sobrepor fileiras:

- Sem figurinhas nos dois lados: MOLA DE MORPH. O cartão (cor, borda, raio, sombra) vai de um visual ao outro na mola
  MORPH 320/20; o conteúdo antigo some e o novo entra logo depois.
- Com figurinhas em um dos lados: ENCOLHE E SALTA. Mesma mola no cartão; as figurinhas antigas se recolhem para dentro
  do card (uma a uma) e as novas saem da borda com um leve excesso, depois que as cores novas assentam.

Duas durações fixas de 200 ms (`DURATION_MS`), escolhidas no protótipo. A mola é normalizada: t=1 é "assentou".

Esta peça só calcula (curvas e fatias de tempo, sem Qt de janela): quem pinta é o `VolumeMixerFlyout`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Optional

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPixmap

from app.core.theme_crossfade import ease_in_out_cubic, ease_out_cubic

DURATION_MS = 200
MORPH = (320.0, 20.0)       # a mola MORPH do app (app/hub/components/city_list.py), mesma massa 1 e Euler semi-implícito
SUBSTEPS = 4
PULL = 0.55                 # quanto a figurinha vai para o centro do card ao se recolher (fração do caminho)
STAGGER = 0.035             # atraso entre figurinhas (fração da duração); o total nunca passa de STAGGER_MAX
STAGGER_MAX = 0.15

# Fatias do tempo (fração da duração): sem lacuna morta entre saída e entrada (evita piscar em trocas rápidas)
CONTENT_OUT_ART, CONTENT_IN_ART = (0.0, 0.35), (0.35, 0.85)
CONTENT_OUT_PLAIN, CONTENT_IN_PLAIN = (0.0, 0.45), (0.35, 0.85)
LEAVE = (0.0, 0.35)
ARRIVE = (0.45, 0.85)


def _clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def _span(t: float, a: float, b: float) -> float:
    return _clamp((t - a) / (b - a))


def ease_back(t: float) -> float:
    """Sobe passando um pouco do alvo (~10%) e assenta: a figurinha "salta"."""
    t = _clamp(t)
    c1 = 2.2
    c3 = c1 + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2


@lru_cache(maxsize=4)
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
    return tuple(samples)


def spring_progress(t: float, kc: tuple[float, float] = MORPH) -> float:
    """Progresso da mola para t em 0..1, onde t=1 é o instante em que ela assentou (pode passar de 1 no caminho)."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    s = _spring_samples(*kc)
    f = t * (len(s) - 1)
    i = int(f)
    return s[i] + (s[i + 1] - s[i]) * (f - i)


def mix_color(a: QColor, b: QColor, f: float) -> QColor:
    f = _clamp(f)
    return QColor(round(a.red() + (b.red() - a.red()) * f), round(a.green() + (b.green() - a.green()) * f),
                  round(a.blue() + (b.blue() - a.blue()) * f), round(a.alpha() + (b.alpha() - a.alpha()) * f))


@dataclass(frozen=True)
class Sample:
    t: float             # 0..1 do relógio
    morph: float         # mola do cartão (pode passar de 1)
    old_content: float   # opacidade do conteúdo antigo (a foto)
    new_content: float   # opacidade do conteúdo novo (pintado ao vivo)


class SkinTransition:
    """Estado de uma troca de visual em curso: os dois visuais, a foto do conteúdo antigo e o relógio."""

    def __init__(self, old, new, photo: Optional[QPixmap], photo_origin: QPointF,
                 duration_ms: int = DURATION_MS, clock: Callable[[], float] = time.perf_counter):
        self.old = old
        self.new = new
        self.photo = photo                  # só o conteúdo (cabeçalho, linhas, número) do visual antigo, sem cartão
        self.photo_origin = QPointF(photo_origin)   # onde o card estava na janela quando a foto foi tirada
        self.uses_art = bool(old.stickers or new.stickers)
        self._duration = max(0.04, duration_ms / 1000.0)
        self._clock = clock
        self._t0: Optional[float] = None

    # --- Relógio ---

    def start(self):
        self._t0 = self._clock()

    def t(self) -> float:
        """0 antes de `start()` (o primeiro quadro é idêntico ao antigo, mesmo se o redesenho demorar)."""
        if self._t0 is None:
            return 0.0
        return _clamp((self._clock() - self._t0) / self._duration)

    def finished(self) -> bool:
        return self.t() >= 1.0

    # --- Curvas ---

    def sample(self) -> Sample:
        t = self.t()
        out, inn = (CONTENT_OUT_ART, CONTENT_IN_ART) if self.uses_art else (CONTENT_OUT_PLAIN, CONTENT_IN_PLAIN)
        return Sample(t, spring_progress(t), 1.0 - ease_out_cubic(_span(t, *out)), ease_out_cubic(_span(t, *inn)))

    @staticmethod
    def _delay(i: int, n: int) -> float:
        return min(STAGGER, STAGGER_MAX / max(1, n - 1)) * i

    def leaving(self, i: int, n: int) -> tuple[float, float, float]:
        """Figurinha do visual antigo: (escala, opacidade, puxão para o centro). Recolhe-se, uma a uma."""
        d = self._delay(i, n)
        q = ease_in_out_cubic(_span(self.t(), LEAVE[0] + d, LEAVE[1] + d))
        return 1.0 - q, 1.0 - q * q, PULL * q

    def arriving(self, i: int, n: int) -> tuple[float, float, float]:
        """Figurinha do visual novo: sai da borda com um leve excesso, depois das cores novas."""
        d = self._delay(i, n)
        q = _span(self.t(), ARRIVE[0] + d, ARRIVE[1] + d)
        s = max(0.0, ease_back(q))
        return s, _clamp(q * 3.0), PULL * (1.0 - s)

    def tilt(self) -> float:
        """Inclinação do card (a do tema `tilt`) acompanhando o cartão."""
        m = self.sample().morph
        return self.old.tilt + (self.new.tilt - self.old.tilt) * m
