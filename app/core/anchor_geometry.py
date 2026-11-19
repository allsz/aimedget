"""
Geometria da ancoragem de widgets (sem Qt, testável sozinha).

Protótipo e valores escolhidos: `mockups/anchor-net-snap.html`.

- `candidate(d, t)`: quão perto o retângulo arrastado `d` está de `t` e onde o ímã o colocaria. Encostar (contato)
  e alinhar (topo, base ou centro) são coisas separadas: só os dois juntos dão o "travado" (`lock`).
- `focus_seg(a, o)`: o trecho da borda de `a` que está de frente para `o` (a parte da rede que acende).
- Árvore de junção: cada vez que dois grupos se juntam nasce um nó {A, B, eixo, alinhamento, folga} que diz como o
  CONTORNO de B encosta no contorno de A. `layout` refaz o grupo a partir dos tamanhos atuais (redimensionar um
  membro mantém a folga e o alinhamento), `prune` tira um membro sem mexer nos outros e `to_json`/`from_json`
  guardam o grupo na configuração. As folhas são as chaves dos widgets ("music", "weather"...), não as janelas,
  então trocar a skin do widget de música não desfaz o grupo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple, Union

# Valores escolhidos no protótipo (px lógicos de tela)
GAP = 10.0          # folga entre dois widgets encostados
SNAP = 15.0         # distância em que o ímã puxa (contato e alinhamento)
REACH = 280.0       # alcance: a rede começa a aparecer a esta distância e a onda vai até este raio
CELL = 18.0         # lado de cada quadrado da rede
WAVE_HEIGHT = 2.0   # altura da onda (px)
RIPPLES = 0         # ondulações atrás da crista (0 = só a onda principal)
WAVE_SPEED = 1.0    # velocidade da onda (1 = ~1,5 s)
PROXIMITY_MAX = 0.85  # brilho máximo sem estar alinhado: o cheio fica reservado ao "travado"

AXES = ("x", "y")


@dataclass(frozen=True)
class Rect:
    l: float
    t: float
    r: float
    b: float

    @property
    def w(self) -> float:
        return self.r - self.l

    @property
    def h(self) -> float:
        return self.b - self.t

    @staticmethod
    def of(x: float, y: float, w: float, h: float) -> "Rect":
        return Rect(float(x), float(y), float(x) + float(w), float(y) + float(h))

    def moved(self, dx: float, dy: float) -> "Rect":
        return Rect(self.l + dx, self.t + dy, self.r + dx, self.b + dy)

    def grown(self, m: float) -> "Rect":
        return Rect(self.l - m, self.t - m, self.r + m, self.b + m)


def union(rects: Iterable[Rect]) -> Rect:
    rs = list(rects)
    return Rect(min(r.l for r in rs), min(r.t for r in rs), max(r.r for r in rs), max(r.b for r in rs))


def clamp(v: float, a: float, b: float) -> float:
    return a if v < a else b if v > b else v


def smooth(x: float) -> float:
    x = clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def ease_out(t: float) -> float:
    return 1.0 - (1.0 - clamp(t, 0.0, 1.0)) ** 3


def dist_to_rect(x: float, y: float, r: Rect) -> float:
    return math.hypot(max(r.l - x, 0.0, x - r.r), max(r.t - y, 0.0, y - r.b))


Seg = Tuple[float, float, float, float]


def dist_to_seg(x: float, y: float, s: Seg) -> float:
    x1, y1, x2, y2 = s
    dx, dy = x2 - x1, y2 - y1
    ll = dx * dx + dy * dy
    k = clamp(((x - x1) * dx + (y - y1) * dy) / ll, 0.0, 1.0) if ll else 0.0
    return math.hypot(x - (x1 + dx * k), y - (y1 + dy * k))


def _mid_1d(a1: float, a2: float, b1: float, b2: float) -> float:
    lo, hi = max(a1, b1), min(a2, b2)
    if lo <= hi:
        return (lo + hi) / 2.0
    return (a2 + b1) / 2.0 if a2 < b1 else (b2 + a1) / 2.0


def _nearest_idx(values) -> int:
    return min(range(len(values)), key=lambda i: abs(values[i]))


@dataclass
class Candidate:
    dist: float                 # distância entre os retângulos (0 = se tocam/sobrepõem)
    b: float                    # brilho da rede 0..1 (1 só quando travado)
    lock: bool = False          # encostado E alinhado: soltar aqui junta os dois
    sx: float = 0.0             # deslocamento do ímã a aplicar no arrastado
    sy: float = 0.0
    ax: Optional[str] = None    # 'x' = lado a lado, 'y' = um em cima do outro
    ai: int = -1                # alinhamento: 0 início, 1 fim, 2 centro
    d_first: bool = False       # o arrastado fica à esquerda/em cima do alvo
    origin: Optional[Tuple[float, float]] = None   # meio do ponto de encaixe (início da onda)
    seam: Optional[Seg] = None  # a emenda entre os dois, já com o ímã aplicado


def proximity(dist: float, gap: float = GAP, reach: float = REACH) -> float:
    return (1.0 - clamp(max(0.0, dist - gap) / reach, 0.0, 1.0)) ** 2 * PROXIMITY_MAX


def candidate(d: Rect, t: Rect, gap: float = GAP, snap: float = SNAP, reach: float = REACH) -> Candidate:
    """Proximidade de `d` (arrastado) a `t` e o encaixe que o ímã faria."""
    dx = max(t.l - d.r, d.l - t.r, 0.0)
    dy = max(t.t - d.b, d.t - t.b, 0.0)
    dist = math.hypot(dx, dy)
    res = Candidate(dist=dist, b=proximity(dist, gap, reach))
    opts = []
    if d.b > t.t - snap * 2 and d.t < t.b + snap * 2:          # faixas verticais se cruzam: lado a lado
        al = [t.t - d.t, t.b - d.b, (t.t + t.b) / 2 - (d.t + d.b) / 2]
        ai = _nearest_idx(al)
        opts.append(("x", (t.r + gap) - d.l, al[ai], ai, False))
        opts.append(("x", (t.l - gap) - d.r, al[ai], ai, True))
    if d.r > t.l - snap * 2 and d.l < t.r + snap * 2:          # faixas horizontais se cruzam: empilhado
        al = [t.l - d.l, t.r - d.r, (t.l + t.r) / 2 - (d.l + d.r) / 2]
        ai = _nearest_idx(al)
        opts.append(("y", (t.b + gap) - d.t, al[ai], ai, False))
        opts.append(("y", (t.t - gap) - d.b, al[ai], ai, True))
    if not opts:
        return res
    ax, c, a, ai, d_first = min(opts, key=lambda o: abs(o[1]))
    contact = abs(c) < snap
    aligned = abs(a) < snap and abs(c) < snap * 2.5
    if ax == "x":
        res.sx, res.sy = (c if contact else 0.0), (a if aligned else 0.0)
    else:
        res.sy, res.sx = (c if contact else 0.0), (a if aligned else 0.0)
    res.ax, res.ai, res.d_first = ax, ai, d_first
    res.lock = contact and aligned
    if res.lock:
        res.b = 1.0
    ds = d.moved(res.sx, res.sy)
    ox, oy = _mid_1d(ds.l, ds.r, t.l, t.r), _mid_1d(ds.t, ds.b, t.t, t.b)
    res.origin = (ox, oy)
    if ax == "x":
        res.seam = (ox, max(ds.t, t.t), ox, min(ds.b, t.b))
    else:
        res.seam = (max(ds.l, t.l), oy, min(ds.r, t.r), oy)
    return res


def better(c: Candidate, cur: Optional[Candidate]) -> bool:
    """Ordem de preferência: travado primeiro, depois o mais próximo."""
    if cur is None:
        return True
    if c.lock != cur.lock:
        return c.lock
    return c.dist < cur.dist - 0.01


def focus_seg(a: Rect, o: Rect) -> Seg:
    """O trecho da borda de `a` de frente para `o` (ou o canto mais próximo)."""
    ix1, ix2 = max(a.l, o.l), min(a.r, o.r)
    iy1, iy2 = max(a.t, o.t), min(a.b, o.b)
    if ix1 <= ix2 and iy1 <= iy2:
        cx, cy = (o.l + o.r) / 2, (o.t + o.b) / 2
        return (cx, cy, cx, cy)
    if ix1 <= ix2:
        y = a.b if o.t >= a.b else a.t
        return (ix1, y, ix2, y)
    if iy1 <= iy2:
        x = a.r if o.l >= a.r else a.l
        return (x, iy1, x, iy2)
    x = a.r if o.l >= a.r else a.l
    y = a.b if o.t >= a.b else a.t
    return (x, y, x, y)


# --- Árvore de junção -------------------------------------------------------------------------------------------


@dataclass
class Join:
    """B encosta em A (A à esquerda/em cima) pelo eixo `ax`; `ai` 0/1/2 = início/fim/centro, 3 = deslocamento `off`."""
    A: "Tree"
    B: "Tree"
    ax: str
    ai: int
    off: float
    gap: float


Tree = Union[str, Join]


def members(tree: Tree) -> list:
    if isinstance(tree, str):
        return [tree]
    return members(tree.A) + members(tree.B)


def join_from_rects(first: Tree, second: Tree, ax: str, rects: Dict[str, Rect], tol: float = 0.6) -> Join:
    """Lê da geometria ATUAL como o contorno de `second` encosta no de `first`."""
    f = union(rects[k] for k in members(first))
    s = union(rects[k] for k in members(second))
    if ax == "x":
        fs, fe, ss, se = f.t, f.b, s.t, s.b
        gap = s.l - f.r
    else:
        fs, fe, ss, se = f.l, f.r, s.l, s.r
        gap = s.t - f.b
    if abs(ss - fs) < tol:
        ai = 0
    elif abs(se - fe) < tol:
        ai = 1
    elif abs((ss + se) / 2 - (fs + fe) / 2) < tol:
        ai = 2
    else:
        ai = 3
    return Join(first, second, ax, ai, ss - fs, gap)


def _layout(tree: Tree, sizes: Dict[str, Tuple[float, float]]):
    if isinstance(tree, str):
        w, h = sizes[tree]
        return {tree: (0.0, 0.0)}, Rect(0.0, 0.0, w, h)
    pa, a = _layout(tree.A, sizes)
    pb, b = _layout(tree.B, sizes)
    if tree.ax == "x":
        sx = a.r + tree.gap - b.l
        sy = (a.t - b.t if tree.ai == 0 else a.b - b.b if tree.ai == 1
              else (a.t + a.b) / 2 - (b.t + b.b) / 2 if tree.ai == 2 else a.t + tree.off - b.t)
    else:
        sy = a.b + tree.gap - b.t
        sx = (a.l - b.l if tree.ai == 0 else a.r - b.r if tree.ai == 1
              else (a.l + a.r) / 2 - (b.l + b.r) / 2 if tree.ai == 2 else a.l + tree.off - b.l)
    out = dict(pa)
    for k, (x, y) in pb.items():
        out[k] = (x + sx, y + sy)
    return out, union([a, b.moved(sx, sy)])


def layout(tree: Tree, sizes: Dict[str, Tuple[float, float]], root: str, root_pos: Tuple[float, float]):
    """Posições (canto superior esquerdo de cada cartão) do grupo inteiro, com `root` parado em `root_pos`."""
    rel, _bounds = _layout(tree, sizes)
    rx, ry = rel[root]
    dx, dy = root_pos[0] - rx, root_pos[1] - ry
    return {k: (x + dx, y + dy) for k, (x, y) in rel.items()}


def prune(tree: Tree, key: str, rects: Dict[str, Rect]) -> Optional[Tree]:
    """Tira `key` da árvore. Onde um lado perdeu um membro o contorno mudou: a relação é relida da geometria."""
    if isinstance(tree, str):
        return None if tree == key else tree
    a, b = prune(tree.A, key, rects), prune(tree.B, key, rects)
    if a is None:
        return b
    if b is None:
        return a
    if a is tree.A and b is tree.B:
        return tree
    return join_from_rects(a, b, tree.ax, rects)


def to_json(tree: Tree):
    if isinstance(tree, str):
        return tree
    return {"A": to_json(tree.A), "B": to_json(tree.B), "ax": tree.ax, "ai": tree.ai,
            "off": round(tree.off, 2), "gap": round(tree.gap, 2)}


def from_json(data) -> Optional[Tree]:
    """Lê uma árvore salva; devolve None se estiver malformada (a configuração pode ter sido editada à mão)."""
    try:
        if isinstance(data, str):
            return data
        a, b = from_json(data["A"]), from_json(data["B"])
        if a is None or b is None or data["ax"] not in AXES:
            return None
        tree = Join(a, b, data["ax"], int(data["ai"]), float(data["off"]), float(data["gap"]))
        keys = members(tree)
        return tree if len(keys) == len(set(keys)) else None
    except (KeyError, TypeError, ValueError):
        return None
