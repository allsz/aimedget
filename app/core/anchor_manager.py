"""
AnchorManager - ancorar widgets uns aos outros (alinhar, empilhar e mover juntos).

Protótipo e valores escolhidos: `mockups/anchor-net-snap.html`. Geometria pura em `anchor_geometry.py`, desenho da
rede em `app/ui_components/anchor_net.py`.

Como funciona
- Clique direito num widget > "Ancorar". Ao arrastar outro widget (ou o próprio ancorado) para perto, uma rede de
  quadrados aparece só na borda que vai encostar e fica mais forte com a proximidade; o ímã puxa para encostar
  (folga de GAP px) e alinhar (topo, base ou centro). Com os dois travados a rede fica no brilho máximo; soltar ali
  junta os widgets num grupo e a rede some numa onda que sai do meio do ponto de encaixe.
- Um grupo se move junto (arrastar qualquer membro), aceita outro widget encostado no contorno inteiro (o lado de
  uma pilha) e se refaz quando um membro muda de tamanho: a folga e o alinhamento se mantêm a cada quadro.
- O grupo é guardado na configuração pelas CHAVES dos widgets ("music", "timer", "weather", "performance"), não
  pelas janelas: trocar a skin da música não desfaz a pilha, e ao reabrir o app (ou quando um widget reaparece) ele
  volta para o lugar dele na pilha.
- `animations_enabled()` falso: o ímã encaixa na hora, a rede aparece/some sem transição e não há onda.

Ganchos nas janelas (uma linha cada): `drag_to` no lugar do `move` do arraste, `drag_end` ao soltar, `register` ao
mostrar, `member_resized` ao mudar de escala e `add_anchor_actions` no menu de contexto.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import shiboken6
from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget
from app.core.refresh_rate import refresh_interval_ms

from app.core import anchor_geometry as geo
from app.core.anchor_geometry import CELL, REACH, Rect, clamp, dist_to_rect, dist_to_seg, smooth
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.widget_animator import animations_enabled
from app.core.frame_clock import FrameTimer

KNOWN_KEYS = ("music", "timer", "weather", "performance", "storage", "battery")
NET_STYLES = ("dots", "lines", "both")
BOOM_STYLES = ("ring", "sweep")
DEFAULT_NET_STYLE = "dots"
DEFAULT_BOOM = "ring"

FRAME_MS = 16
BOOM_DUR = 1.5 / geo.WAVE_SPEED   # s
GLOW_PERIOD = 2.8                 # s: um pulso lento do brilho da borda enquanto o widget está ancorado
GLOW_RATE = 7.0                   # 1/s: o brilho acende/apaga suavemente (sem piscar)
ACCENT_TTL = 1.0                  # s: a cor de destaque do app é relida no máximo uma vez por segundo
PULSE_FRAME_MS = 33               # só o pulso pede quadros: 30 fps bastam e custam pouco
MAGNET_RATE = 22.0                # 1/s: quão rápido o ímã puxa
GAIN_RATE = 12.0                  # 1/s: rede acendendo/apagando
FOCUS_RATE = 14.0                 # 1/s: a parte acesa seguindo a borda
ARRANGE_SPRING = (420.0, 34.0)    # SLIDE: os widgets alinhados deslizam até o lugar (massa 1, 4 subpassos)
ARRANGE_SUBSTEPS = 4
NET_MARGIN = max(CELL * 4, round(REACH * 0.75 / CELL) * CELL)   # até onde a rede de aproximação vai da borda


def net_style() -> str:
    v = config_manager.get_anchor("net_style", DEFAULT_NET_STYLE)
    return v if v in NET_STYLES else DEFAULT_NET_STYLE


def boom_style() -> str:
    v = config_manager.get_anchor("boom", DEFAULT_BOOM)
    return v if v in BOOM_STYLES else DEFAULT_BOOM


# --- Adaptadores: as três famílias de janela (FloatingCard, skins de música, skins do timer) ----------------------


def _alive(w) -> bool:
    return w is not None and shiboken6.isValid(w)


def _local_card(w) -> QRectF:
    fn = getattr(w, "card_rect", None) or getattr(w, "get_card_rect")
    return QRectF(fn())


def card_rect(w) -> Rect:
    """Cartão visível na tela (sem sombra/margem de arte e sem o deslocamento da animação de surgir)."""
    r = _local_card(w)
    p = w.rest_pos()
    return Rect.of(p.x() + r.x(), p.y() + r.y(), r.width(), r.height())


def card_radius(w) -> float:
    if hasattr(w, "_card_radius") and isinstance(getattr(w, "_scale", None), (int, float)):
        return float(w._card_radius) * float(w._scale)
    if hasattr(w, "CARD_RADIUS") and isinstance(getattr(w, "scale", None), (int, float)):
        return float(w.CARD_RADIUS) * float(w.scale)
    r = _local_card(w)
    return min(r.width(), r.height()) * 0.12


def move_card(w, x: float, y: float):
    """Põe o cartão de `w` com o canto em (x, y) da tela, respeitando a animação de surgir/sumir em curso."""
    r = _local_card(w)
    target = QPoint(int(round(x - r.x())), int(round(y - r.y())))
    glide = getattr(w, "_position_glide", None)
    if glide is not None:
        glide.stop()
    animator = getattr(w, "animator", None)
    if animator is not None:
        animator.move_rest(target)
    else:
        w.move(target)


def _window_target(w, x: float, y: float) -> QPoint:
    r = _local_card(w)
    return QPoint(int(round(x - r.x())), int(round(y - r.y())))


def move_cards(items):
    """
    Move vários cartões (um grupo) de uma vez. No Windows as janelas vão num só lote (DeferWindowPos): o Windows
    aplica todas juntas, então os membros nunca aparecem um quadro separados. Janela oculta, no meio da animação de
    surgir/sumir ou de um deslize vai pelo caminho normal (uma por vez), assim como tudo se o lote falhar.
    """
    from app.core import desktop_layer

    batch, single = [], []
    for w, x, y in items:
        if not _alive(w):
            continue
        animator = getattr(w, "animator", None)
        glide = getattr(w, "_position_glide", None)
        busy = (animator is not None and animator.is_animating()) or (glide is not None and glide.is_running())
        if busy or not w.isVisible():
            single.append((w, x, y))
            continue
        target = _window_target(w, x, y)
        if target != w.pos():
            batch.append((w, x, y, target))

    if len(batch) > 1 and desktop_layer.IS_WINDOWS:
        native = []
        for w, _x, _y, target in batch:
            rect = desktop_layer.native_window_rect(int(w.winId()))
            if rect is None:
                break
            cur, dpr = w.pos(), w.devicePixelRatioF()
            native.append((int(w.winId()), rect[0] + round((target.x() - cur.x()) * dpr),
                           rect[1] + round((target.y() - cur.y()) * dpr)))
        if len(native) == len(batch) and desktop_layer.defer_move(native):
            for w, _x, _y, target in batch:
                if w.pos() != target:      # o Qt não acompanhou (ex.: telas com escalas diferentes): corrige
                    w.move(target)
            batch = []
    for w, x, y, *_ in batch + single:
        move_card(w, x, y)


def _persist(w):
    fn = getattr(w, "anchor_position_committed", None)
    if fn is not None:
        fn()


# --- Estado ------------------------------------------------------------------------------------------------------


@dataclass(eq=False)
class Group:
    tree: geo.Tree
    anchored: bool = False
    gain: float = 0.0                      # brilho atual da rede de aproximação (0 = invisível)
    focus: Optional[geo.Seg] = None        # trecho aceso (segue a borda com suavidade)
    prox: Optional[dict] = None            # durante um arraste: {b, lock, seam, focus}
    glow: float = 0.0                      # brilho da borda do modo ancorado (0 = apagado, 1 = aceso)

    def keys(self) -> list:
        return geo.members(self.tree)


@dataclass
class _Drag:
    key: str
    group: Group
    start: Dict[str, tuple]
    base: Dict[str, tuple] = field(default_factory=dict)
    target: tuple = (0.0, 0.0)
    cur: tuple = (0.0, 0.0)
    best: Optional[geo.Candidate] = None
    best_group: Optional[Group] = None


@dataclass
class _Boom:
    t0: float
    U: Rect
    origin: tuple
    ax: str
    focus: Optional[geo.Seg]
    style: str
    pinned: bool = False      # o grupo está na área de trabalho: a onda também fica lá (não por cima dos apps)


class AnchorManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._windows: Dict[str, QWidget] = {}
        self._groups: Dict[str, Group] = {}
        self._sizes: Dict[str, tuple] = {}
        self._drag: Optional[_Drag] = None
        self._boom: Optional[_Boom] = None
        self._dirty = False
        self._layer_sync = False
        self._overlay = None
        self._arrange: Optional[dict] = None   # alinhamento em curso: {group, root, ref, save, st: {key: [x, y, vx, vy]}}
        self._clock = FrameTimer(self)
        self._clock.setTimerType(Qt.TimerType.PreciseTimer)
        self._clock.setInterval(FRAME_MS)
        self._clock.timeout.connect(self._tick)
        self._last = time.perf_counter()
        self._load()

    # --- Persistência ---

    def _load(self):
        sizes = config_manager.get_anchor("sizes", {}) or {}
        if isinstance(sizes, dict):
            for k, v in sizes.items():
                if k in KNOWN_KEYS and isinstance(v, (list, tuple)) and len(v) == 2:
                    self._sizes[k] = (float(v[0]), float(v[1]))
        for data in config_manager.get_anchor("groups", []) or []:
            tree = geo.from_json(data)
            if tree is None:
                continue
            keys = geo.members(tree)
            if len(keys) < 2 or any(k not in KNOWN_KEYS or k in self._groups for k in keys):
                continue
            g = Group(tree)
            for k in keys:
                self._groups[k] = g

    def _save(self):
        seen, out = set(), []
        for g in self._groups.values():
            if id(g) in seen or len(g.keys()) < 2:
                continue
            seen.add(id(g))
            out.append(geo.to_json(g.tree))
        config_manager.set_anchor("groups", out)
        config_manager.set_anchor("sizes", {k: [round(w, 1), round(h, 1)] for k, (w, h) in self._sizes.items()})

    # --- Consultas ---

    def window(self, key: str) -> Optional[QWidget]:
        w = self._windows.get(key)
        return w if _alive(w) else None

    def group_of(self, key: str) -> Group:
        g = self._groups.get(key)
        if g is None:
            g = self._groups[key] = Group(key)
        return g

    def groups(self) -> list:
        out, seen = [], set()
        for g in self._groups.values():
            if id(g) not in seen:
                seen.add(id(g))
                out.append(g)
        return out

    def _key(self, w) -> Optional[str]:
        key = getattr(w, "ANCHOR_KEY", None)
        return key if key in KNOWN_KEYS and self.window(key) is w else None

    def is_anchored(self, w) -> bool:
        key = self._key(w)
        return bool(key and self.group_of(key).anchored)

    def is_grouped(self, w) -> bool:
        key = self._key(w)
        return bool(key and len(self.group_of(key).keys()) > 1)

    def is_busy(self) -> bool:
        return self._clock.isActive()

    # --- Registro ---

    def register(self, w):
        """Chamado ao mostrar a janela do widget. Num grupo, ela volta ao lugar dela em relação aos outros membros."""
        key = getattr(w, "ANCHOR_KEY", None)
        if key not in KNOWN_KEYS or not w.isWindow() or w.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen):
            return
        self._windows[key] = w
        r = card_rect(w)
        self._sizes[key] = (r.w, r.h)
        g = self.group_of(key)
        if len(g.keys()) > 1 and not (self._drag and key in self._drag.start):
            root = next((k for k in g.keys() if k != key and self.window(k) is not None
                         and self.window(k).isVisible()), None)
            if root is not None:
                self._reflow(g, root)

    def member_resized(self, w):
        """A escala de um membro mudou: o grupo se refaz em volta dele (ele fica parado, os outros acompanham)."""
        key = self._key(w)
        if key is None:
            return
        r = card_rect(w)
        self._sizes[key] = (r.w, r.h)
        g = self.group_of(key)
        if self._arranging(g):
            return          # o alinhamento em curso refaz o grupo a cada quadro com os tamanhos novos
        if len(g.keys()) > 1 and not (self._drag and self._drag.group is g):
            self._reflow(g, key)

    def _rects_of(self, g: Group) -> Optional[Dict[str, Rect]]:
        """Retângulos de todos os membros: os que têm janela pela tela, os ausentes pela árvore e o último tamanho."""
        rects, root = {}, None
        for k in g.keys():
            w = self.window(k)
            if w is not None:
                rects[k] = card_rect(w)
                root = root or k
        if root is None:
            return None
        missing = [k for k in g.keys() if k not in rects]
        if missing:
            sizes = {k: ((rects[k].w, rects[k].h) if k in rects else self._sizes.get(k)) for k in g.keys()}
            if any(v is None for v in sizes.values()):
                return None
            pos = geo.layout(g.tree, sizes, root, (rects[root].l, rects[root].t))
            for k in missing:
                rects[k] = Rect.of(pos[k][0], pos[k][1], *sizes[k])
        return rects

    def _reflow(self, g: Group, root: str):
        sizes = {}
        for k in g.keys():
            w = self.window(k)
            if w is not None:
                r = card_rect(w)
                sizes[k] = self._sizes[k] = (r.w, r.h)
            elif k in self._sizes:
                sizes[k] = self._sizes[k]
            else:
                return
        rr = card_rect(self.window(root))
        moves = []
        for k, (x, y) in geo.layout(g.tree, sizes, root, (rr.l, rr.t)).items():
            w = self.window(k)
            if k != root and w is not None:
                cur = card_rect(w)
                if abs(cur.l - x) > 0.5 or abs(cur.t - y) > 0.5:
                    moves.append((w, x, y))
        move_cards(moves)

    # --- Menu ---

    def set_anchored(self, w, anchored: bool):
        key = self._key(w)
        if key is None:
            return
        g = self.group_of(key)
        if g.anchored == bool(anchored):
            return
        g.anchored = bool(anchored)
        self._wake()   # o brilho da borda acende (ou apaga) suavemente; sem animações do Windows, na hora

    # --- Alinhamento & Igualar tamanho ---

    def current_gap_of(self, w) -> float:
        """Retorna a folga atual (px) do grupo de `w`, ou `geo.GAP` (10 px) se ainda não estiver agrupado."""
        key = self._key(w)
        if key is None:
            return float(geo.GAP)
        tree = self.group_of(key).tree
        if isinstance(tree, geo.Join):
            return float(tree.gap)
        return float(geo.GAP)

    @staticmethod
    def match_widget_size(w, target_w: Optional[float] = None, target_h: Optional[float] = None,
                          animate: bool = False) -> None:
        """
        Ajusta a escala/lado de `w` para igualar a largura ou altura alvo, respeitando os limites do widget. Com
        `animate` o tamanho vai com a mola de escala do widget (sem animações do Windows, na hora).
        """
        if target_w is None and target_h is None:
            return
        animate = animate and animations_enabled() and w.isVisible()
        if hasattr(w, "match_card_size"):
            # Cartão de tamanho livre (Bateria): muda só a largura OU a altura, sem escala
            w.match_card_size(target_w, target_h, animate=animate)
            return
        if hasattr(w, "set_square_side") and hasattr(w, "MIN_WIDTH") and hasattr(w, "MAX_WIDTH"):
            target = target_w if target_w is not None else target_h
            side = max(int(w.MIN_WIDTH), min(int(w.MAX_WIDTH), int(round(target))))
            config_manager.save_timer_size(side, side)
            if animate and abs(w.square_side() - side) >= 1:
                from app.core.scale_animator import ScaleAnimator
                anim = getattr(w, "_align_side_anim", None)
                if anim is None:
                    anim = w._align_side_anim = ScaleAnimator(w, lambda v, w=w: w.set_square_side(int(round(v))),
                                                              tolerance=0.5)
                anim.start(float(w.square_side()), float(side))
            else:
                w.set_square_side(side)
            return
        if hasattr(w, "_card_w") and hasattr(w, "_card_h") and hasattr(w, "set_scale"):
            base = float(w._card_w) if target_w is not None else float(w._card_h)
            target = float(target_w if target_w is not None else target_h)
            if base > 0:
                scale = target / base
                if animate and hasattr(w, "animate_scale_to"):
                    w.animate_scale_to(scale)
                else:
                    w.set_scale(scale)
                    scale = w._scale
                sig = getattr(w, "scale_changed", None)
                if sig is not None:
                    sig.emit(scale)      # o controller grava o tamanho (e segue animando até ele)
            return
        if hasattr(w, "canvas_w") and hasattr(w, "canvas_h") and hasattr(w, "set_scale"):
            base = float(w.canvas_w) if target_w is not None else float(w.canvas_h)
            target = float(target_w if target_w is not None else target_h)
            if base > 0:
                if animate and hasattr(w, "animate_scale_to"):
                    w.animate_scale_to(target / base, save_preference=True)
                else:
                    w.set_scale(target / base, save_preference=True)

    @staticmethod
    def _size_busy(w) -> bool:
        """O tamanho de `w` ainda está animando (mola de escala do widget ou a do lado do timer)?"""
        fn = getattr(w, "is_scale_animating", None)
        if fn is not None and fn():
            return True
        anim = getattr(w, "_align_side_anim", None)
        return anim is not None and anim.is_active()

    def _visible(self, k: str) -> bool:
        w = self.window(k)
        return w is not None and w.isVisible()

    def nearest_key(self, ref_key: str) -> Optional[str]:
        """O widget visível mais perto do cartão de `ref_key` (distância entre as bordas), fora do grupo dele."""
        ref = self.window(ref_key)
        if ref is None:
            return None
        R = card_rect(ref)
        mine = set(self.group_of(ref_key).keys())
        best, best_d = None, None
        for k in KNOWN_KEYS:
            if k in mine or not self._visible(k):
                continue
            O = card_rect(self.window(k))
            d = math.hypot(max(0.0, O.l - R.r, R.l - O.r), max(0.0, O.t - R.b, R.t - O.b))
            if best_d is None or d < best_d:
                best, best_d = k, d
        return best

    def _align_target_keys(self, ref_key: str) -> list[str]:
        """
        Chaves dos widgets que entram no alinhamento: o grupo atual; sem grupo, só o widget mais próximo (com o grupo
        dele, se tiver). Nunca todos os widgets da tela: quem não foi escolhido não é puxado de longe.
        """
        g = self.group_of(ref_key)
        if len(g.keys()) > 1:
            keys = [k for k in g.keys() if self._visible(k)]
        else:
            near = self.nearest_key(ref_key)
            keys = [ref_key] + ([k for k in self.group_of(near).keys() if self._visible(k)] if near else [])
        if ref_key not in keys:
            keys.insert(0, ref_key)
        else:
            # Mantém o widget clicado como referência no início da lista
            keys = [ref_key] + [k for k in keys if k != ref_key]
        return keys

    def align_widgets(
        self,
        ref_widget,
        axis: str = "y",
        align: int = 0,
        gap: float = geo.GAP,
        match_size: bool = False,
        save: bool = True,
    ) -> None:
        """Alinha perfeitamente os widgets no eixo escolhido (`'y'` empilhado, `'x'` lado a lado) e opcionalmente iguala o tamanho."""
        if self.window(getattr(ref_widget, "ANCHOR_KEY", "")) is not ref_widget:
            self.register(ref_widget)
        ref_key = self._key(ref_widget)
        if ref_key is None or axis not in geo.AXES:
            return

        keys = self._align_target_keys(ref_key)
        if len(keys) < 2:
            return

        self._finish_arrange()      # um alinhamento anterior ainda deslizando termina no lugar dele
        ref_rect = card_rect(ref_widget)
        animate = save and animations_enabled() and ref_widget.isVisible()

        # Monta árvore limpa preservando a ordem (ref_widget primeiro) e a folga exata
        tree: geo.Tree = keys[0]
        for k in keys[1:]:
            tree = geo.Join(tree, k, axis, int(align), 0.0, float(gap))

        # Remove os membros de grupos antigos (que tenham outros widgets fora de `keys`) e os reúne no grupo alinhado
        key_set = set(keys)
        old_anchored = self.group_of(ref_key).anchored
        new_group = Group(tree, anchored=old_anchored)
        for k in keys:
            old = self._groups.get(k)
            if old is not None and old is not new_group and len(old.keys()) > 1:
                if any(m not in key_set for m in old.keys()):
                    rects = self._rects_of(old)
                    rem = geo.prune(old.tree, k, rects) if rects is not None else None
                    if rem is not None:
                        old.tree = rem
            self._groups[k] = new_group
            w = self.window(k)
            if w is not None:
                r = card_rect(w)
                self._sizes[k] = (r.w, r.h)
        self._unify_layer(new_group, ref_widget)

        if animate:
            # Uma linha do tempo só: os tamanhos vão com a mola de escala e as posições deslizam (mola SLIDE) até o
            # lugar calculado a cada quadro com os tamanhos daquele quadro.
            st = {}
            for k in keys:
                w = self.window(k)
                if w is not None and k != ref_key:
                    r = card_rect(w)
                    st[k] = [r.l, r.t, 0.0, 0.0]
            self._arrange = {"group": new_group, "root": ref_key, "ref": ref_widget, "save": save, "st": st}
        if match_size:
            for k in keys[1:]:
                w = self.window(k)
                if w is None:
                    continue
                if axis == "y":
                    self.match_widget_size(w, target_w=ref_rect.w, animate=animate)
                else:
                    self.match_widget_size(w, target_h=ref_rect.h, animate=animate)
        if animate:
            self._wake()
            return
        self._reflow(new_group, ref_key)
        if save:
            self.commit_group_layout(ref_widget)

    # --- Alinhamento animado ---

    def _arranging(self, g: Optional[Group] = None) -> bool:
        a = self._arrange
        return a is not None and (g is None or a["group"] is g)

    def _finish_arrange(self):
        """Leva o alinhamento em curso ao fim na hora (arraste novo, outro alinhamento): tudo no lugar e salvo."""
        a, self._arrange = self._arrange, None
        if a is None:
            return
        if self._visible(a["root"]):
            self._reflow(a["group"], a["root"])
        if a["save"] and _alive(a["ref"]):
            self.commit_group_layout(a["ref"])

    def _step_arrange(self, dt: float) -> bool:
        """Um quadro do deslize do alinhamento. Devolve True enquanto ainda há movimento."""
        a = self._arrange
        g, root = a["group"], a["root"]
        rw = self.window(root)
        if rw is None or not rw.isVisible() or any(self._groups.get(k) is not g for k in a["st"]):
            self._finish_arrange()
            return False
        sizes = {}
        for k in g.keys():
            w = self.window(k)
            if w is not None:
                r = card_rect(w)
                sizes[k] = self._sizes[k] = (r.w, r.h)
            elif k in self._sizes:
                sizes[k] = self._sizes[k]
            else:
                self._finish_arrange()
                return False
        rr = card_rect(rw)
        goal = geo.layout(g.tree, sizes, root, (rr.l, rr.t))
        kk, cc = ARRANGE_SPRING
        sub = dt / ARRANGE_SUBSTEPS
        moves, settled = [], True
        for k, s in a["st"].items():
            w = self.window(k)
            if w is None or k not in goal:
                continue
            gx, gy = goal[k]
            for _ in range(ARRANGE_SUBSTEPS):
                s[2] += (-kk * (s[0] - gx) - cc * s[2]) * sub
                s[3] += (-kk * (s[1] - gy) - cc * s[3]) * sub
                s[0] += s[2] * sub
                s[1] += s[3] * sub
            if abs(s[0] - gx) < 0.5 and abs(s[1] - gy) < 0.5 and abs(s[2]) < 8.0 and abs(s[3]) < 8.0:
                s[0], s[1], s[2], s[3] = gx, gy, 0.0, 0.0
            else:
                settled = False
            moves.append((w, s[0], s[1]))
        move_cards(moves)
        if settled and not any(self._size_busy(w) for k in g.keys() if (w := self.window(k)) is not None):
            self._finish_arrange()
            return False
        return True

    def set_group_gap(self, ref_widget, gap: float, save: bool = True) -> None:
        """Atualiza em tempo real a folga (px) entre os widgets do grupo de `ref_widget`."""
        key = self._key(ref_widget)
        if key is None:
            return
        g = self.group_of(key)
        if len(g.keys()) < 2:
            return

        def _update_gap(node: geo.Tree) -> None:
            if isinstance(node, geo.Join):
                node.gap = float(gap)
                _update_gap(node.A)
                _update_gap(node.B)

        _update_gap(g.tree)
        if self._arranging(g):
            return          # o deslize em curso já vai para a folga nova
        self._reflow(g, key)
        if save:
            self.commit_group_layout(ref_widget)

    def commit_group_layout(self, ref_widget) -> None:
        """Grava em disco a árvore do grupo e as posições lembradas dos membros (chamado ao soltar o slider)."""
        key = self._key(ref_widget)
        if key is None:
            return
        g = self.group_of(key)
        for k in g.keys():
            w = self.window(k)
            if w is not None:
                _persist(w)
        self._save()

    def detach(self, w):
        """Tira o widget do grupo; os outros continuam juntos, exatamente onde estão."""
        key = self._key(w)
        if key is None:
            return
        g = self.group_of(key)
        if len(g.keys()) < 2:
            return
        rects = self._rects_of(g)
        if rects is None:
            return
        rest = geo.prune(g.tree, key, rects)
        single = self._groups[key] = Group(key, glow=g.glow)    # o brilho (se havia) apaga suavemente
        if rest is not None:
            ng = Group(rest, glow=g.glow)
            for k in geo.members(rest):
                self._groups[k] = ng
        self._save()
        self._wake()

    # --- Arraste ---

    def drag_to(self, w, window_pos: QPoint):
        """No lugar do `self.move(...)` do arraste: move o grupo inteiro e aplica o ímã."""
        if self.window(getattr(w, "ANCHOR_KEY", "")) is not w:
            self.register(w)
        key = self._key(w)
        if key is None:
            w.move(window_pos)
            return
        d = self._drag
        if d is None or d.key != key:
            d = self._begin(key)
        r = _local_card(w)
        sx, sy = d.start[key]
        dx, dy = window_pos.x() + r.x() - sx, window_pos.y() + r.y() - sy
        d.base = {k: (x + dx, y + dy) for k, (x, y) in d.start.items()}
        self._evaluate()
        if not animations_enabled():
            d.cur = d.target
        self._apply_drag()
        # Com a rede ou o ímã em ação, ela é redesenhada AGORA, no mesmo passo que moveu as janelas.
        if (d.target != (0.0, 0.0) or d.cur != (0.0, 0.0)
                or any(g.prox or g.gain > 0 for g in self.groups())):
            self._wake()

    def _begin(self, key: str) -> _Drag:
        self._finish_arrange()      # pegar um widget no meio do deslize do alinhamento: ele assenta e o arraste segue
        g = self.group_of(key)
        start = {}
        for k in g.keys():
            w = self.window(k)
            if w is not None:
                r = card_rect(w)
                start[k] = (r.l, r.t)
        self._drag = _Drag(key=key, group=g, start=start)
        return self._drag

    @staticmethod
    def _group_gap(g: Group) -> Optional[float]:
        """Folga atual (px) de um grupo já formado, ou None se for um widget solto."""
        if isinstance(g.tree, geo.Join):
            return float(g.tree.gap)
        return None

    @classmethod
    def _inherited_gap(cls, dg: Group, og: Group) -> float:
        """Folga herdada ao encaixar `dg` em `og`: prevalece a do grupo alvo `og` (como a camada)."""
        g_gap = cls._group_gap(og)
        if g_gap is not None:
            return g_gap
        d_gap = cls._group_gap(dg)
        if d_gap is not None:
            return d_gap
        prefs = config_manager.get_anchor("align_prefs", None)
        if isinstance(prefs, dict) and isinstance(prefs.get("gap"), (int, float)):
            return float(prefs["gap"])
        return float(geo.GAP)

    def _evaluate(self):
        d = self._drag
        dg = d.group
        for g in self.groups():
            g.prox = None
        d.best, d.best_group, d.target = None, None, (0.0, 0.0)
        others = [g for g in self.groups() if g is not dg]
        if not dg.anchored and not any(g.anchored for g in others):
            return
        drects = []
        for k, (x, y) in d.base.items():
            w = self.window(k)
            if w is not None:
                r = card_rect(w)
                drects.append(Rect.of(x, y, r.w, r.h))
        if not drects:
            return
        D = geo.union(drects)
        for g in others:
            if not (g.anchored or dg.anchored):
                continue
            trs = [card_rect(self.window(k)) for k in g.keys()
                   if self.window(k) is not None and self.window(k).isVisible()]
            if not trs:
                continue
            T = geo.union(trs)
            c = geo.candidate(D, T, gap=self._inherited_gap(dg, g))
            if c.b <= 0.0 and not c.lock:
                continue
            if g.anchored:
                self._consider(g, c, T, D)
            if dg.anchored:
                self._consider(dg, c, D, T)
            if geo.better(c, d.best):
                d.best, d.best_group = c, g
        if d.best is not None and (d.best.sx or d.best.sy):
            d.target = (d.best.sx, d.best.sy)

    @staticmethod
    def _consider(owner: Group, c: geo.Candidate, A: Rect, O: Rect):
        cur = owner.prox
        if cur is None or c.b > cur["b"]:
            owner.prox = {"b": c.b, "lock": c.lock, "seam": c.seam, "focus": geo.focus_seg(A, O)}

    def _apply_drag(self):
        d = self._drag
        move_cards([(w, x + d.cur[0], y + d.cur[1]) for k, (x, y) in d.base.items()
                    if (w := self.window(k)) is not None])

    def drag_end(self, w):
        """Ao soltar: firma o ímã e, se estava travado, junta os grupos (com a onda)."""
        d = self._drag
        key = getattr(w, "ANCHOR_KEY", None)
        if d is None or d.key != key:
            return
        d.cur = d.target
        self._apply_drag()
        best, og = d.best, d.best_group
        if best is not None and best.lock and og is not None:
            self._join(d.group, og, best)
        self._drag = None
        for g in self.groups():
            g.prox = None
        for k in d.base:
            ow = self.window(k)
            if k != key and ow is not None:
                _persist(ow)
        self._wake()

    def _join(self, dg: Group, og: Group, c: geo.Candidate):
        owner = og if og.anchored else dg
        focus = owner.prox["focus"] if owner.prox else None
        rects = {}
        for g in (dg, og):
            gr = self._rects_of(g)
            if gr is None:
                return
            rects.update(gr)
        U = geo.union(rects[k] for k in owner.keys())
        first, second = (dg, og) if c.d_first else (og, dg)
        inherited_gap = self._inherited_gap(dg, og)
        joined_tree = geo.join_from_rects(first.tree, second.tree, c.ax, rects)

        def _apply_gap(node: geo.Tree) -> None:
            if isinstance(node, geo.Join):
                node.gap = inherited_gap
                _apply_gap(node.A)
                _apply_gap(node.B)

        _apply_gap(joined_tree)
        ng = Group(joined_tree)
        # A âncora cumpriu o papel: o grupo novo nasce sem âncora e o brilho que estava aceso apaga suavemente
        # (começa de onde estava; sem isso ele ficava parado na tela depois da junção).
        ng.glow = max(dg.glow, og.glow)
        for k in ng.keys():
            self._groups[k] = ng
        dg.gain = og.gain = 0.0
        # Garante a folga herdada exata nas posições da tela (inclusive sub-junções do grupo arrastado)
        sizes = {k: (rects[k].w, rects[k].h) for k in ng.keys()}
        anchor_k = next(iter(og.keys()))
        placed = geo.layout(ng.tree, sizes, anchor_k, (rects[anchor_k].l, rects[anchor_k].t))
        move_cards([(w, placed[k][0], placed[k][1]) for k in ng.keys() if (w := self.window(k)) is not None])
        pinned = self._adopt_layer(dg, og, ng)
        self._save()
        if animations_enabled() and c.origin is not None:
            self._boom = _Boom(time.perf_counter(), U, c.origin, c.ax, focus, boom_style(), pinned)

    # --- Camada (área de trabalho x por cima): o GRUPO tem uma só ---

    @staticmethod
    def _pinned_of(w) -> Optional[bool]:
        """Camada de uma janela: True = na área de trabalho, False = por cima; None = widget sem a opção."""
        fn = getattr(w, "desktop_mode_target", None)
        return bool(fn()) if fn is not None else None

    def is_pinned(self, g: Group) -> bool:
        """O grupo está na área de trabalho? Um membro sem a opção (música, timer) fica sempre por cima."""
        ws = [w for k in g.keys() if (w := self.window(k)) is not None]
        return bool(ws) and all(self._pinned_of(w) for w in ws)

    def _set_layer(self, w, pinned: bool):
        if self._pinned_of(w) in (None, pinned):
            return
        signal = getattr(w, "desktop_mode_changed", None)
        if signal is not None:
            signal.emit(pinned)        # pelo controller: aplica (com a onda de pontos), salva e avisa o Hub
        else:
            w.set_desktop_mode(pinned)

    def _set_group_layer(self, g: Group, pinned: bool, skip: Optional[str] = None):
        if self._layer_sync:
            return
        self._layer_sync = True
        try:
            for k in g.keys():
                w = self.window(k)
                if k != skip and w is not None:
                    self._set_layer(w, pinned)
        finally:
            self._layer_sync = False

    def member_layer_changed(self, w, pinned: bool):
        """Um membro mudou de camada ("Fixar na área de trabalho" no menu ou no Hub): o grupo inteiro vai junto."""
        key = self._key(w)
        if key is None or self._layer_sync:
            return
        g = self.group_of(key)
        if len(g.keys()) > 1:
            self._set_group_layer(g, bool(pinned), skip=key)

    def _adopt_layer(self, dragged: Group, target: Group, merged: Optional[Group] = None) -> bool:
        """
        Quem foi arrastado até o outro passa a ter o comportamento de camada DELE: arrastar o Desempenho até o Clima
        fixado na área de trabalho fixa o Desempenho também (com a onda de pontos de sempre), e o contrário solta.
        Widgets sem a opção (música, timer) ficam sempre por cima; como o grupo tem uma camada só, um grupo com um
        deles fica todo por cima (senão a música ficava acima de tudo e o resto do grupo atrás das janelas).
        Devolve a camada do grupo novo.
        """
        pinned = False
        for k in target.keys():
            w = self.window(k)
            if w is not None and self._pinned_of(w) is not None:
                pinned = self._pinned_of(w)
                break
        group = merged or dragged
        if pinned and not self._can_pin(group):
            pinned = False
        self._set_group_layer(group, pinned)
        return pinned

    def _can_pin(self, g: Group) -> bool:
        """Todos os membros (com janela) têm a opção "Fixar na área de trabalho"?"""
        return all(self._pinned_of(w) is not None for k in g.keys() if (w := self.window(k)) is not None)

    def _unify_layer(self, g: Group, ref_widget) -> bool:
        """Grupo montado pelo alinhador: todos na camada do widget de referência (por cima, se alguém não fixa)."""
        pinned = bool(self._pinned_of(ref_widget)) and self._can_pin(g)
        self._set_group_layer(g, pinned)
        return pinned

    # --- Relógio ---

    def _wake(self):
        """Algo mudou (arraste, menu, junção): redesenha e mantém o relógio rodando enquanto houver movimento."""
        self._dirty = True
        if not self._clock.isActive():
            self._last = time.perf_counter()
            self._clock.setInterval(refresh_interval_ms())
            self._clock.start()
        self._tick()

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        anim = animations_enabled()
        changed, moving, pulsing = self._dirty, False, False
        self._dirty = False
        d = self._drag
        if d is not None:
            k = 1.0 - math.exp(-dt * MAGNET_RATE) if anim else 1.0
            nx = d.cur[0] + (d.target[0] - d.cur[0]) * k
            ny = d.cur[1] + (d.target[1] - d.cur[1]) * k
            if abs(nx - d.target[0]) < 0.05 and abs(ny - d.target[1]) < 0.05:
                nx, ny = d.target
            if (nx, ny) != d.cur:
                d.cur = (nx, ny)
                self._apply_drag()
                changed = True
            moving = d.cur != d.target
        if self._arrange is not None and self._step_arrange(dt if anim else 1.0):
            moving = True
        for g in self.groups():
            target = clamp(g.prox["b"], 0.0, 1.0) ** 0.75 if g.prox else 0.0
            old_gain, old_focus = g.gain, g.focus
            if anim:
                g.gain += (target - g.gain) * (1.0 - math.exp(-dt * GAIN_RATE))
            else:
                g.gain = target
            if abs(g.gain - target) < 0.002:
                g.gain = target
            if g.prox:
                f = g.prox["focus"]
                if g.focus is None or old_gain < 0.03 or not anim:
                    g.focus = f
                else:
                    kf = 1.0 - math.exp(-dt * FOCUS_RATE)
                    g.focus = tuple(a + (b - a) * kf for a, b in zip(g.focus, f))
                    if max(abs(a - b) for a, b in zip(g.focus, f)) < 0.05:
                        g.focus = f
            # O brilho do modo ancorado é desenhado DENTRO da janela de cada widget (ver anchor_net.GlowLayer):
            # fica na mesma camada que ele (na área de trabalho ou por cima) e anda no mesmo quadro ao arrastar.
            old_glow, glow_to = g.glow, 1.0 if g.anchored else 0.0
            if anim:
                g.glow += (glow_to - g.glow) * (1.0 - math.exp(-dt * GLOW_RATE))
            else:
                g.glow = glow_to
            if abs(g.glow - glow_to) < 0.004:
                g.glow = glow_to
            if g.gain != old_gain or g.focus != old_focus:
                changed = True
            if g.glow != glow_to:
                moving = True
            if g.glow > 0.0 and anim:
                pulsing = True
            if g.glow > 0.0 or old_glow > 0.0:
                self._sync_glow(g, now, anim)
            if g.gain != target or (g.prox and g.focus != g.prox["focus"]):
                moving = True
        if self._boom is not None:
            changed = moving = True
            if now - self._boom.t0 >= BOOM_DUR:
                self._boom = None
        if changed:
            self._update_overlay(now)
        if not moving and not pulsing:
            self._clock.stop()
        else:
            interval = refresh_interval_ms() if moving else PULSE_FRAME_MS
            if self._clock.interval() != interval:
                self._clock.setInterval(interval)

    # --- Rede na tela ---

    def _scene_bounds(self, now: float) -> Optional[QRect]:
        rect = None

        def add(r: Rect):
            nonlocal rect
            q = QRect(int(math.floor(r.l)) - 8, int(math.floor(r.t)) - 8,
                      int(math.ceil(r.w)) + 16, int(math.ceil(r.h)) + 16)
            rect = q if rect is None else rect.united(q)

        for g in self.groups():
            rs = [card_rect(self.window(k)) for k in g.keys() if self.window(k) is not None]
            if not rs:
                continue
            if g.gain > 0.004:
                add(geo.union(rs).grown(NET_MARGIN))
        if self._boom is not None:
            ox, oy = self._boom.origin
            add(Rect(ox - REACH, oy - REACH, ox + REACH, oy + REACH))
        return rect

    def _update_overlay(self, now: float):
        bounds = self._scene_bounds(now)
        if bounds is None:
            if self._overlay is not None:
                self._overlay.cover(None)
            return
        if self._overlay is None:
            from app.ui_components.anchor_net import NetOverlay
            self._overlay = NetOverlay(self._paint_scene)
        self._overlay.set_desktop(self._overlay_pinned())
        self._overlay.cover(bounds)

    def _overlay_pinned(self) -> bool:
        """
        A rede e a onda ficam na camada do que estão desenhando: grupo na área de trabalho = rede na área de trabalho
        (qualquer app por cima a cobre, como cobre o widget). Se algo desenhado é de um grupo "por cima", ela fica
        por cima. Os cartões viram buracos na rede, então ela pode ficar abaixo deles sem aparecer por cima.
        """
        layers = [self.is_pinned(g) for g in self.groups() if g.gain > 0.004]
        if self._boom is not None:
            layers.append(self._boom.pinned)
        return bool(layers) and all(layers)

    def _paint_scene(self, p: QPainter):
        from app.ui_components.anchor_net import paint_lattice, paint_seam

        now = time.perf_counter()
        style = net_style()
        clip = QPainterPath()
        clip.addRect(QRectF(self._overlay.geometry()))
        for key in KNOWN_KEYS:     # a rede passa POR TRÁS dos cartões (a janela fica por cima deles)
            w = self.window(key)
            if w is not None and w.isVisible():
                r, rad = card_rect(w), card_radius(w)
                hole = QPainterPath()
                hole.addRoundedRect(QRectF(r.l, r.t, r.w, r.h), rad, rad)
                clip = clip.subtracted(hole)
        p.setClipPath(clip)

        for g in self.groups():
            rs = [card_rect(self.window(k)) for k in g.keys() if self.window(k) is not None]
            if not rs:
                continue
            U = geo.union(rs)
            if g.gain > 0.004 and g.focus is not None:
                paint_lattice(p, U, U.grown(NET_MARGIN), CELL, style, self._focus_alpha(g, U))
                if g.prox and g.prox["lock"] and g.prox["seam"]:
                    paint_seam(p, g.prox["seam"])
        if self._boom is not None:
            b = self._boom
            alpha, disp = self._boom_fns(b, now)
            ox, oy = b.origin
            paint_lattice(p, b.U, Rect(ox - REACH, oy - REACH, ox + REACH, oy + REACH), CELL, style, alpha, disp)

    @staticmethod
    def _edge_fall(du: float, m: float) -> float:
        return 1.0 - smooth((du - (m - CELL * 2.5)) / (CELL * 2.5))

    def _focus_alpha(self, g: Group, U: Rect):
        f, gain = g.focus, g.gain
        rf = CELL * 2.5 + CELL * 4.5 * gain     # a parte acesa cresce conforme os widgets se aproximam
        hot = 1.0 if (g.prox and g.prox["lock"]) else gain * 0.35
        edge = self._edge_fall

        def alpha(x, y):
            foc = 1.0 - smooth((dist_to_seg(x, y, f) - rf * 0.45) / (rf * 0.55))
            if foc <= 0.0:
                return 0.0, 0.0, 0.0
            return edge(dist_to_rect(x, y, U), NET_MARGIN) * foc * gain, hot, 0.0

        return alpha

    def _accent(self) -> QColor:
        """Cor de destaque do app (a mesma do Hub), relida no máximo uma vez por ACCENT_TTL."""
        now = time.perf_counter()
        cached = getattr(self, "_accent_cache", None)
        if cached is None or now - cached[0] > ACCENT_TTL:
            from app.hub.theme import resolve_theme
            try:
                color = QColor(resolve_theme(config_manager.get_hub_theme("system")).accent)
            except Exception:
                color = QColor(110, 193, 255)
            self._accent_cache = cached = (now, color)
        return QColor(cached[1])

    def _sync_glow(self, g: Group, now: float, anim: bool):
        """Passa o brilho (com o pulso) para a camada de cada membro e abre/fecha a folga da janela para ele."""
        from app.ui_components.anchor_net import GlowLayer

        pulse = 0.5 + 0.5 * math.sin(2.0 * math.pi * now / GLOW_PERIOD) if anim else 0.7
        level = g.glow * (0.45 + 0.55 * pulse)
        color = self._accent() if g.glow > 0.0 else None
        for key in g.keys():
            w = self.window(key)
            if w is None:
                continue
            layer = getattr(w, "_anchor_glow_layer", None)
            if layer is None or not _alive(layer):
                if g.glow <= 0.0:
                    continue
                layer = w._anchor_glow_layer = GlowLayer(w, lambda host=w: (card_rect(host), card_radius(host)))
            if g.glow > 0.0 and not layer.has_room:
                room = getattr(w, "anchor_glow_room", None)
                if room is not None:
                    room(True)          # a janela ganha a folga em volta do cartão (o cartão não se mexe)
                layer.has_room = True
            layer.set_level(level, 0.85 + 0.3 * pulse, color)
            if g.glow <= 0.0 and layer.has_room:
                room = getattr(w, "anchor_glow_room", None)
                if room is not None:
                    room(False)
                layer.has_room = False

    def _boom_fns(self, b: _Boom, now: float):
        """A onda: sobe a rede (altura) ao passar e a apaga atrás de si; sai do meio do ponto de encaixe."""
        G = CELL
        k = clamp((now - b.t0) / BOOM_DUR, 0.0, 1.0)
        lam, sig = G * 4.5, G * 2.2
        tail = max(lam * 0.5, geo.RIPPLES * lam * 0.45)
        trail = G * 5 if geo.RIPPLES == 0 else max(G * 5, tail * 1.8)
        total = REACH + trail + G * 3
        R = total * (1.0 - (1.0 - k) ** 1.5)
        A = geo.WAVE_HEIGHT * (1.0 - 0.45 * k)
        lock_fade = 1.0 - smooth(k / 0.3)
        ox, oy = b.origin
        ring = b.style == "ring"

        def direction(x, y):
            if ring:
                d = math.hypot(x - ox, y - oy) or 1e-6
                return d, (x - ox) / d, (y - oy) / d
            if b.ax == "x":
                return abs(y - oy), 0.0, (1.0 if y >= oy else -1.0)
            return abs(x - ox), (1.0 if x >= ox else -1.0), 0.0

        def shape(u):
            if geo.RIPPLES == 0:
                return math.exp(-(u / (sig * 0.9)) ** 2)
            env = math.exp(-(u / (sig * 0.55)) ** 2) if u > 0 else math.exp(-(u / tail) ** 2)
            return env * math.cos(2 * math.pi * u / lam)

        def alpha(x, y):
            ef = 1.0 - smooth((math.hypot(x - ox, y - oy) - (REACH - G * 2.5)) / (G * 2.5))
            if ef <= 0.0:
                return 0.0, 0.0, 0.0
            u = direction(x, y)[0] - R
            lead = math.exp(-(u / (G * 1.6)) ** 2) if u > 0 else 1.0
            tr = clamp(1.0 + u / trail, 0.0, 1.0) if u < 0 else 1.0
            band = math.exp(-(u / (sig * 0.8)) ** 2)
            a = lead * tr
            if b.focus is not None and lock_fade > 0:
                rf = G * 7
                foc = 1.0 - smooth((dist_to_seg(x, y, b.focus) - rf * 0.45) / (rf * 0.55))
                a = max(a, foc * lock_fade)
            return clamp(a * ef, 0.0, 1.0), 0.25 + 0.5 * band, band * 1.4

        def disp(x, y):
            d, ux, uy = direction(x, y)
            s = shape(d - R)
            h = A * s
            return ux * h * 0.45, -h + uy * h * 0.45, s

        return alpha, disp


_manager: Optional[AnchorManager] = None


def anchor_manager() -> AnchorManager:
    global _manager
    if _manager is None or not shiboken6.isValid(_manager):
        _manager = AnchorManager()
    return _manager


def anchor_bar_items(w) -> list:
    """Botões mínimos de Ancorar, Alinhar (HUD flutuante) e Soltar do grupo para a barra superior Fluent Rail."""
    from app.ui_components.menu_action_bar import ActionBarItem

    mgr = anchor_manager()
    if mgr.window(getattr(w, "ANCHOR_KEY", "")) is not w:
        mgr.register(w)
    if mgr._key(w) is None:
        return []

    def _open_aligner():
        from app.ui_components.align_hud import open_align_hud
        QTimer.singleShot(0, lambda: open_align_hud(w))

    items = [
        ActionBarItem(
            key="anchor",
            icon="anchor",
            tooltip=t("anchor_menu_anchor"),
            toggle=True,
            checked=mgr.is_anchored(w),
            on_trigger=lambda checked: mgr.set_anchored(w, checked),
        ),
        ActionBarItem(
            key="align",
            icon="align",
            tooltip=t("align_menu_open"),
            toggle=False,
            close_menu=True,
            on_trigger=_open_aligner,
        ),
    ]
    if mgr.is_grouped(w):
        items.append(
            ActionBarItem(
                key="detach",
                icon="detach",
                tooltip=t("anchor_menu_detach"),
                toggle=False,
                close_menu=True,
                on_trigger=lambda: mgr.detach(w),
            )
        )
    return items


def add_anchor_actions(menu, w, icon=None):
    """Itens "Ancorar" (com check) e, num grupo, "Soltar do grupo", para os menus de contexto dos widgets."""
    mgr = anchor_manager()
    if mgr.window(getattr(w, "ANCHOR_KEY", "")) is not w:
        mgr.register(w)
    if mgr._key(w) is None:
        return
    anchored = mgr.is_anchored(w)
    act = QAction(icon, t("anchor_menu_anchor"), w) if icon is not None else QAction(t("anchor_menu_anchor"), w)
    menu.set_trailing_check(act, anchored)
    act.triggered.connect(lambda: mgr.set_anchored(w, not anchored))
    menu.addAction(act)
    if mgr.is_grouped(w):
        act_detach = QAction(t("anchor_menu_detach"), w)
        act_detach.triggered.connect(lambda: mgr.detach(w))
        menu.addAction(act_detach)
