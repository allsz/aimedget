"""
Motor de layout do Battery Widget (sem Qt, testável). Protótipo e valores: `mockups/battery-layout-v3.html`.

O usuário escolhe o tamanho do cartão arrastando o canto (livre). Para cada número de colunas possível, acha o maior
anel que cabe na largura e na altura e fica com o layout de menos linhas cujo anel está a 10% do melhor. O espaço é
dividido por igual nos dois eixos (borda, anel, anel, borda). Se o melhor anel ficaria menor que `D_MIN`, o anel fica
em `D_MIN` e o cartão cresce pela menor área que cabe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

K = 0.55            # folga horizontal mínima, em fração do anel (borda = entre = borda)
M = 0.30            # folga vertical mínima, em fração do anel
D_MIN = 52.0        # anel mínimo antes de o cartão crescer
D_MAX = 96.0
HEAD_H = 46.0       # faixa do cabeçalho (topo 24 + linha 22, como o nome do lugar no Clima)

# Espaço vertical ÓTICO: o olho mede do texto, não da caixa da linha. As folgas iguais vão da linha de base do título
# ao topo do anel, da linha de base de um nome ao anel de baixo e da linha de base do último nome à borda de baixo
# (sem nomes: da borda do anel; sem título: da borda de cima). Métricas da Inter (hhea): subida 0,969 em, descida
# 0,2415 em; a linha de base fica onde o pintor a põe ao centralizar o texto na linha.
ASC, DESC = 0.969, 0.2415
HEAD_FS, HEAD_TOP, HEAD_LH = 16.0, 24.0, 22.0


def baseline_in_line(fs: float, lh: float) -> float:
    return (lh - (ASC + DESC) * fs) / 2.0 + ASC * fs


HEAD_BASE = HEAD_TOP + baseline_in_line(HEAD_FS, HEAD_LH)   # ~40,8: linha de base do título
CAP = 0.727                                                  # altura da maiúscula da Inter, em em
# Margem das BORDAS: o que o olho vê entre a borda de cima e o topo das letras do título (~29). A borda de baixo (e a
# de cima, sem título) nunca fica com menos que isso: num cartão apertado, os anéis encolhem para abrir espaço.
EDGE = HEAD_BASE - CAP * HEAD_FS
DEFAULT_SIZE = (300.0, 262.0)   # o cartão do Clima/Desempenho
MIN_SIZE = (150.0, 120.0)
MAX_SIZE = (1200.0, 900.0)

ODD_CENTER = "center"
ODD_LEFT = "left"


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass(frozen=True)
class Typo:
    fs: float      # corpo do nome do dispositivo
    gap: float     # anel -> nome
    lh: float      # altura da linha do nome
    dot: float     # bolinha de carregando (72% da altura da maiúscula)

    @property
    def block(self) -> float:
        return self.gap + self.lh

    @property
    def vis(self) -> float:
        """Do pé do anel até a linha de base do nome (o que conta para o espaço ótico); 0 sem nomes."""
        return self.gap + baseline_in_line(self.fs, self.lh) if self.lh > 0 else 0.0


def typo(d: float, names: bool = True) -> Typo:
    """Tudo o que é tipográfico acompanha o anel; sem nomes, o bloco do nome some do cálculo."""
    fs = clamp(d * 0.14, 11.0, 13.0)
    lh = round(fs * 1.3)
    gap = max(6.0, round(d * 0.1))
    dot = max(4.0, round(fs * 0.727 * 0.72))
    if not names:
        return Typo(fs, 0.0, 0.0, dot)
    return Typo(fs, gap, lh, dot)


def _gap_counts(rows: int, header: bool) -> tuple[int, int]:
    """(folgas internas, folgas de borda). Com título, a de cima é interna (título -> anel); sem, é borda."""
    return (rows, 1) if header else (rows - 1, 2)


def _need_h(d: float, rows: int, names: bool, header: bool = True) -> float:
    inner, edges = _gap_counts(rows, header)
    return rows * (d + typo(d, names).vis) + inner * M * d + edges * max(M * d, EDGE)


def vertical_gaps(free: float, rows: int, header: bool) -> tuple[float, float]:
    """(folga interna, folga de borda) para o espaço livre `free`. Iguais quando sobra espaço; apertado, as bordas
    ficam em EDGE e só as internas diminuem."""
    inner_n, edge_n = _gap_counts(rows, header)
    even = free / (rows + 1)
    if even >= EDGE or inner_n == 0:
        return even, even
    return (free - edge_n * EDGE) / inner_n, EDGE


def _top(header: bool) -> float:
    return HEAD_BASE if header else 0.0


@dataclass(frozen=True)
class Layout:
    W: float
    H: float
    d: float
    cols: int
    rows: int
    gap_x: float
    gap_y: float                                   # folga interna (título -> anel, entre linhas)
    edge_y: float = 0.0                            # folga de borda (último nome -> baixo; sem título, também o topo)
    cells: tuple = field(default_factory=tuple)    # (x, y) do canto do anel, na ordem dos dispositivos
    grown: bool = False
    top: float = HEAD_H

    def typo(self, names: bool = True) -> Typo:
        return typo(self.d, names)


def _fit(n: int, W: float, H: float, header: bool, names: bool) -> tuple[int, int, float]:
    hc = H - _top(header)
    cands = []
    for c in range(1, n + 1):
        r = math.ceil(n / c)
        hi = min(W / (c + (c + 1) * K), D_MAX)
        if _need_h(hi, r, names, header) <= hc:
            d = hi
        else:
            lo = 0.0
            for _ in range(28):
                mid = (lo + hi) / 2.0
                if _need_h(mid, r, names, header) <= hc:
                    lo = mid
                else:
                    hi = mid
            d = lo
        cands.append((c, r, d))
    best = max(d for _c, _r, d in cands)
    ok = [x for x in cands if x[2] >= best * 0.9]
    ok.sort(key=lambda x: (x[1], -x[2]))
    return ok[0]


def solve(n: int, W: float, H: float, header: bool = True, names: bool = True) -> tuple[int, int, float, float, float, bool]:
    """(colunas, linhas, anel, largura, altura, cresceu) para `n` dispositivos num cartão W x H."""
    n = max(1, int(n))
    W = clamp(float(W), *[MIN_SIZE[0], MAX_SIZE[0]])
    H = clamp(float(H), *[MIN_SIZE[1], MAX_SIZE[1]])
    c, r, d = _fit(n, W, H, header, names)
    if d >= D_MIN:
        return c, r, d, W, H, False
    d = D_MIN
    best = None
    for cc in range(1, n + 1):
        rr = math.ceil(n / cc)
        w = max(W, math.ceil(d * (cc + (cc + 1) * K)))
        h = max(H, math.ceil(_top(header) + _need_h(d, rr, names, header)))
        area = w * h
        if best is None or area < best[4] - 1 or (abs(area - best[4]) <= 1 and rr < best[1]):
            best = (cc, rr, w, h, area)
    cc, rr, w, h, _a = best
    return cc, rr, d, float(w), float(h), True


def compute(n: int, W: float, H: float, header: bool = True, names: bool = True, odd: str = ODD_CENTER) -> Layout:
    """Layout completo: tamanho final do cartão, anel e o canto de cada anel."""
    if n <= 0:
        W = clamp(float(W), MIN_SIZE[0], MAX_SIZE[0])
        H = clamp(float(H), MIN_SIZE[1], MAX_SIZE[1])
        return Layout(W=W, H=H, d=D_MIN, cols=0, rows=0, gap_x=0.0, gap_y=0.0, cells=(), top=_top(header))
    c, r, d, W2, H2, grown = solve(n, W, H, header, names)
    ty = typo(d, names)
    top = _top(header)
    gap_x = (W2 - c * d) / (c + 1)
    gap_y, edge_y = vertical_gaps(H2 - top - r * (d + ty.vis), r, header)
    first = gap_y if header else edge_y
    cells = []
    for i in range(n):
        row, col = divmod(i, c)
        in_row = (n - row * c) if row == r - 1 else c
        if in_row < c and odd == ODD_CENTER:
            g = (W2 - in_row * d) / (in_row + 1)
            x = g + col * (d + g)
        else:
            x = gap_x + col * (d + gap_x)
        y = top + first + row * (d + ty.vis + gap_y)
        cells.append((x, y))
    return Layout(W=W2, H=H2, d=d, cols=c, rows=r, gap_x=gap_x, gap_y=gap_y, edge_y=edge_y, cells=tuple(cells),
                  grown=grown, top=top)
