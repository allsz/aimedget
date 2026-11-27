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
from typing import Optional

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

EXPAND_DIRS = ("l", "r", "u", "d")
DEFAULT_EXPAND = "lrud"


def normalize_expand(raw: Optional[str]) -> str:
    """Normaliza a string de direções do D-pad para a ordem canônica ('l','r','u','d'); nunca fica vazia."""
    if not isinstance(raw, str):
        return DEFAULT_EXPAND
    low = raw.lower()
    out = "".join(d for d in EXPAND_DIRS if d in low)
    return out or DEFAULT_EXPAND


def expand_axis(expand: str) -> str:
    """'x' (só horizontal), 'y' (só vertical) ou 'both' (2D menor área)."""
    e = normalize_expand(expand)
    has_h = ("l" in e) or ("r" in e)
    has_v = ("u" in e) or ("d" in e)
    if has_h and not has_v:
        return "x"
    if has_v and not has_h:
        return "y"
    return "both"


def expand_pivot(expand: str) -> tuple[float, float]:
    """Fração de deslocamento (dx/dW, dy/dH) ao crescer: 0=cresce dir/baixo, -1=esq/cima, -0.5=ambos os lados."""
    e = normalize_expand(expand)
    l, r, u, d = ("l" in e), ("r" in e), ("u" in e), ("d" in e)
    px = -1.0 if (l and not r) else (-0.5 if (l and r) else 0.0)
    py = -1.0 if (u and not d) else (-0.5 if (u and d) else 0.0)
    return px, py


def reachable_bounds(
    card: tuple[float, float, float, float],
    current: tuple[float, float, float, float],
    screens: list[tuple[float, float, float, float]],
    allow_overflow: bool,
) -> tuple[float, float, float, float]:
    """
    Limites alcançáveis (l, t, r, b) para crescimento automático.
    - `allow_overflow=False` (ou monitor único): fica dentro de `current` (área útil do monitor atual, sem barra de tarefas).
    - `allow_overflow=True`: estende para monitores vizinhos que encostam no eixo correspondente; o vazio puro é SEMPRE parede.
    """
    cl, ct, cr, cb = current
    if not allow_overflow or len(screens) <= 1:
        return cl, ct, cr, cb
    _xl, yt, _xr, yb = card
    xl, _yt, xr, _yb = card
    l, t, r, b = cl, ct, cr, cb
    tol = 2.0
    changed = True
    while changed:
        changed = False
        for sl, st, sr, sb in screens:
            # Vizinho horizontal (compartilha faixa vertical com o cartão)
            if sb > yt + 1.0 and st < yb - 1.0:
                if sl <= r + tol and sr > r:
                    r = sr
                    changed = True
                if sr >= l - tol and sl < l:
                    l = sl
                    changed = True
            # Vizinho vertical (compartilha faixa horizontal com o cartão)
            if sr > xl + 1.0 and sl < xr - 1.0:
                if st <= b + tol and sb > b:
                    b = sb
                    changed = True
                if sb >= t - tol and st < t:
                    t = st
                    changed = True
    return l, t, r, b


def clamp_shift(
    box: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
) -> tuple[float, float]:
    """Menor deslocamento (dx, dy) para manter `box` (l, t, r, b) dentro de `bounds` (l, t, r, b)."""
    bl, bt, br, bb = box
    al, at, ar, ab = bounds
    bw, bh = br - bl, bb - bt
    aw, ah = ar - al, ab - at
    if bw <= aw:
        dx = max(0.0, al - bl) - max(0.0, br - ar)
    else:
        dx = al - bl
    if bh <= ah:
        dy = max(0.0, at - bt) - max(0.0, bb - ab)
    else:
        dy = at - bt
    return dx, dy

# Histerese da troca de colunas: um layout já na tela só é trocado por um de MAIS linhas quando o anel dele cai abaixo
# de 82% do melhor (para MENOS linhas a troca continua em 90%). Sem a faixa 82-90%, arrastar o canto perto do limite
# fazia o cartão pular entre 1 e 2 linhas a cada pixel.
KEEP = 0.82
SWITCH = 1.04       # e só troca por um de MENOS linhas com o anel 4% acima do limite (90% ou D_MIN)
GROWN_KEEP = 1.08   # cartão crescido (anel no mínimo): fica com o layout da tela até 8% mais área que o menor


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


def _fit(n: int, W: float, H: float, header: bool, names: bool, prefer: Optional[int] = None) -> tuple[int, int, float]:
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

    def floor_ok(d: float) -> bool:
        # Abaixo de D_MIN o cartão teria de crescer além do ponteiro: só vale se nenhum layout cabe sem crescer
        return d >= D_MIN or best < D_MIN

    ok = [x for x in cands if x[2] >= best * 0.9 and floor_ok(x[2])]
    ok.sort(key=lambda x: (x[1], -x[2]))
    choice = ok[0]
    if prefer is not None and prefer != choice[0]:
        cur = next((x for x in cands if x[0] == prefer), None)
        if cur is not None and cur[2] >= best * KEEP and floor_ok(cur[2]):
            if cur[1] <= choice[1]:
                return cur                              # trocar daria mais linhas: fica com o que está na tela
            if choice[2] < max(best * 0.9, D_MIN) * SWITCH:
                return cur                              # menos linhas, mas ainda no limite: espera passar dele
    return choice


def solve(n: int, W: float, H: float, header: bool = True, names: bool = True,
          prefer: Optional[int] = None, expand: str = DEFAULT_EXPAND) -> tuple[int, int, float, float, float, bool]:
    """(colunas, linhas, anel, largura, altura, cresceu) para `n` dispositivos num cartão W x H. `prefer`: colunas do
    layout que já está na tela (histerese, ver KEEP). `expand`: direções ativas do D-pad ('l','r','u','d')."""
    n = max(1, int(n))
    W = clamp(float(W), *[MIN_SIZE[0], MAX_SIZE[0]])
    H = clamp(float(H), *[MIN_SIZE[1], MAX_SIZE[1]])
    c, r, d = _fit(n, W, H, header, names, prefer)
    if d >= D_MIN:
        return c, r, d, W, H, False
    d = D_MIN
    axis = expand_axis(expand)
    if axis == "y":
        # Trava largura em W (respeita largura herdada da pilha) e cresce só na vertical
        max_cc = 1
        for cc in range(1, n + 1):
            if math.ceil(d * (cc + (cc + 1) * K)) <= W + 0.5:
                max_cc = cc
            else:
                break
        rr = math.ceil(n / max_cc)
        w = max(W, float(math.ceil(d * (max_cc + (max_cc + 1) * K))))
        h = max(H, float(math.ceil(_top(header) + _need_h(d, rr, names, header))))
        return max_cc, rr, d, w, h, True
    if axis == "x":
        # Trava altura em H e cresce só na horizontal
        max_rr = 1
        for rr in range(1, n + 1):
            if math.ceil(_top(header) + _need_h(d, rr, names, header)) <= H + 0.5:
                max_rr = rr
            else:
                break
        cc = math.ceil(n / max_rr)
        rr = math.ceil(n / cc)
        w = max(W, float(math.ceil(d * (cc + (cc + 1) * K))))
        h = max(H, float(math.ceil(_top(header) + _need_h(d, rr, names, header))))
        return cc, rr, d, w, h, True
    best = None
    options = {}
    for cc in range(1, n + 1):
        rr = math.ceil(n / cc)
        w = max(W, math.ceil(d * (cc + (cc + 1) * K)))
        h = max(H, math.ceil(_top(header) + _need_h(d, rr, names, header)))
        area = w * h
        options[cc] = (cc, rr, w, h, area)
        if best is None or area < best[4] - 1 or (abs(area - best[4]) <= 1 and rr < best[1]):
            best = (cc, rr, w, h, area)
    # Mesma histerese no cartão crescido: sem ela, a menor área alterna entre largo e alto a cada pixel
    cur = options.get(prefer) if prefer is not None else None
    if cur is not None and cur[4] <= best[4] * GROWN_KEEP:
        best = cur
    cc, rr, w, h, _a = best
    return cc, rr, d, float(w), float(h), True


def compute(n: int, W: float, H: float, header: bool = True, names: bool = True, odd: str = ODD_CENTER,
            prefer: Optional[int] = None, expand: str = DEFAULT_EXPAND) -> Layout:
    """Layout completo: tamanho final do cartão, anel e o canto de cada anel."""
    if n <= 0:
        W = clamp(float(W), MIN_SIZE[0], MAX_SIZE[0])
        H = clamp(float(H), MIN_SIZE[1], MAX_SIZE[1])
        return Layout(W=W, H=H, d=D_MIN, cols=0, rows=0, gap_x=0.0, gap_y=0.0, cells=(), top=_top(header))
    c, r, d, W2, H2, grown = solve(n, W, H, header, names, prefer, expand=expand)
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
