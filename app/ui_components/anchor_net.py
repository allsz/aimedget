"""
Rede de ancoragem: o desenho (pontos, linhas ou os dois) e a janela transparente onde ele aparece.

Protótipo e valores escolhidos: `mockups/anchor-net-snap.html`.

- `paint_lattice` desenha a grade de quadrados iguais (fase presa ao canto superior esquerdo do grupo, para os
  quadrados ficarem alinhados aos widgets). Quem chama diz a opacidade de cada ponto (`alpha_fn`) e, na onda, o
  deslocamento de altura (`disp_fn`). Os traços são agrupados por nível de opacidade e desenhados em lote
  (`drawLines`), porque um traço por chamada pesaria demais em Python.
- `NetOverlay` é uma janela sem moldura, transparente e que deixa os cliques passarem. Só existe na tela enquanto há
  rede para mostrar (aproximação, onda ou o aviso de ancorar) e ocupa só a área da rede, não a tela inteira.
"""

from __future__ import annotations

import math
from typing import Callable, Optional, Tuple

from PySide6.QtCore import QEvent, QLineF, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

from app.core.anchor_geometry import Rect

NET_RGB = (110, 193, 255)
HOT_RGB = (220, 243, 255)
DOT_R = 2.2            # raio dos pontos (o mesmo em toda a rede; só o brilho muda)
ALPHA_LEVELS = 20
HOT_LEVELS = 4
WIDTH_LEVELS = 4
MIN_ALPHA = 0.012

AlphaFn = Callable[[float, float], Tuple[float, float, float]]   # (x, y) -> (opacidade, "quente" 0..1, largura extra)
DispFn = Callable[[float, float], Tuple[float, float, float]]    # (x, y) -> (dx, dy, crista -1..1)


def lattice(phase: float, lo: float, hi: float, cell: float) -> list:
    """Linhas da grade dentro de [lo, hi], todas a um múltiplo de `cell` de `phase`."""
    k0, k1 = math.ceil((lo - phase) / cell), math.floor((hi - phase) / cell)
    return [phase + k * cell for k in range(k0, k1 + 1)]


def net_color(alpha: float, hot: float) -> QColor:
    r = NET_RGB[0] + (HOT_RGB[0] - NET_RGB[0]) * hot
    g = NET_RGB[1] + (HOT_RGB[1] - NET_RGB[1]) * hot
    b = NET_RGB[2] + (HOT_RGB[2] - NET_RGB[2]) * hot
    return QColor(round(r), round(g), round(b), round(255 * max(0.0, min(1.0, alpha))))


def _q(v: float, levels: int) -> int:
    return max(0, min(levels, int(round(v * levels))))


def paint_lattice(p: QPainter, U: Rect, B: Rect, cell: float, style: str, alpha_fn: AlphaFn,
                  disp_fn: Optional[DispFn] = None) -> int:
    """Desenha a rede em `B` com a fase de `U`. Devolve quantos elementos foram desenhados (para os testes)."""
    xs = lattice(U.l, B.l, B.r, cell)
    ys = lattice(U.t, B.t, B.b, cell)
    if not xs or not ys:
        return 0
    drawn = 0
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    if style in ("lines", "both"):
        step = cell / 3.0 if disp_fn else cell / 2.0
        buckets: dict = {}
        glow: dict = {}

        def samples(arr):
            out = []
            for i in range(len(arr) - 1):
                n = max(1, int(round((arr[i + 1] - arr[i]) / step)))
                for s in range(n):
                    out.append(arr[i] + (arr[i + 1] - arr[i]) * s / n)
            out.append(arr[-1])
            return out

        def run(points):
            prev = None
            for ox, oy in points:
                if disp_fn:
                    dx, dy, k = disp_fn(ox, oy)
                    cur = (ox + dx, oy + dy, k, ox, oy)
                else:
                    cur = (ox, oy, 0.0, ox, oy)
                if prev is not None:
                    a, hot, wx = alpha_fn((prev[3] + cur[3]) / 2.0, (prev[4] + cur[4]) / 2.0)
                    if a >= MIN_ALPHA:
                        k = max(0.0, (prev[2] + cur[2]) / 2.0)
                        al = min(1.0, a * (1.0 + 0.9 * k))
                        hot = min(1.0, hot + 0.5 * k)
                        wq = _q(min(1.0, (wx * 0.5 + k * 1.1) / 2.0), WIDTH_LEVELS)
                        line = QLineF(prev[0], prev[1], cur[0], cur[1])
                        buckets.setdefault((_q(al, ALPHA_LEVELS), _q(hot, HOT_LEVELS), wq), []).append(line)
                        if al > 0.45:
                            glow.setdefault((_q(al * 0.18, ALPHA_LEVELS * 4), _q(hot, HOT_LEVELS), wq), []).append(line)
                prev = cur

        ys_s, xs_s = samples(ys), samples(xs)
        for x in xs:
            run([(x, y) for y in ys_s])
        for y in ys:
            run([(x, y) for x in xs_s])

        p.setBrush(Qt.BrushStyle.NoBrush)
        for (aq, hq, wq), lines in glow.items():
            pen = QPen(net_color(aq / (ALPHA_LEVELS * 4), hq / HOT_LEVELS), 3.6 + wq * 2.0 / WIDTH_LEVELS * 2.0)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawLines(lines)
        for (aq, hq, wq), lines in buckets.items():
            pen = QPen(net_color(aq / ALPHA_LEVELS, hq / HOT_LEVELS), 1.0 + wq * 2.0 / WIDTH_LEVELS)
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
            p.setPen(pen)
            p.drawLines(lines)
            drawn += len(lines)

    if style in ("dots", "both"):
        dots: dict = {}
        for x in xs:
            for y in ys:
                a, hot, _wx = alpha_fn(x, y)
                if a < MIN_ALPHA:
                    continue
                k = 0.0
                px, py = x, y
                if disp_fn:
                    dx, dy, k = disp_fn(x, y)
                    px, py, k = x + dx, y + dy, max(0.0, k)
                al = min(1.0, a * (1.0 + 0.9 * k) * 1.15)
                hot = min(1.0, hot + 0.5 * k)
                dots.setdefault((_q(al, ALPHA_LEVELS), _q(hot, HOT_LEVELS), _q(k, WIDTH_LEVELS)), []).append((px, py))
        p.setPen(Qt.PenStyle.NoPen)
        for (aq, hq, kq), pts in dots.items():
            p.setBrush(net_color(aq / ALPHA_LEVELS, hq / HOT_LEVELS))
            r = DOT_R + 0.9 * kq / WIDTH_LEVELS
            for px, py in pts:
                p.drawEllipse(QPointF(px, py), r, r)
            drawn += len(pts)
    return drawn


def paint_seam(p: QPainter, seam) -> None:
    """A emenda acesa entre dois widgets travados."""
    x1, y1, x2, y2 = seam
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for width, color in ((7.0, QColor(190, 235, 255, 90)), (2.0, QColor(235, 248, 255, 242))):
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


GLOW_EXTENT = 7.0    # px: o quanto o brilho do modo ancorado passa da borda do cartão (sutil, contorna o canto)
GLOW_EDGE_GAP = 4.0  # px livres até a borda da janela: o halo nunca encosta nela (senão vira uma caixa quadrada)
GLOW_LAYERS = ((1.00, 0.05), (0.72, 0.09), (0.48, 0.15), (0.28, 0.26), (0.14, 0.62))   # (fração da largura total, opacidade): do halo largo ao fio junto da borda


class GlowLayer(QWidget):
    """
    Brilho do modo ancorado desenhado DENTRO da janela do widget (um filho transparente que cobre a janela toda e
    só pinta fora do cartão). Por estar na janela dele, fica na mesma camada (área de trabalho ou por cima) e anda
    junto no arraste, no mesmo quadro. `geometry()` devolve o contorno do cartão (QPainterPath em coordenadas da
    janela, ver anchor_manager.card_shape): o halo é um traço desse contorno, então segue qualquer forma
    (retângulo arredondado, cantos retos, estrela com pontas para fora).
    """

    def __init__(self, host: QWidget, geometry):
        super().__init__(host)
        self._host = host
        self._geometry = geometry
        self._level = 0.0
        self._breathe = 1.0
        self._color = QColor(110, 193, 255)
        self.has_room = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setGeometry(0, 0, host.width(), host.height())
        host.installEventFilter(self)
        self.show()
        self.raise_()

    def eventFilter(self, obj, event):
        if obj is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(0, 0, self._host.width(), self._host.height())
        return False

    def level(self) -> float:
        return self._level

    def set_level(self, level: float, breathe: float, color: Optional[QColor]):
        if color is not None:
            self._color = color
        # Ignora variações mínimas, mas nunca o apagar: sem isso um resto < 0.002 ficava aceso para sempre.
        if (abs(level - self._level) < 0.002 and abs(breathe - self._breathe) < 0.002
                and (level > 0.0) == (self._level > 0.0)):
            return
        self._level, self._breathe = level, breathe
        self.update(self._band())

    def shape(self) -> QPainterPath:
        return QPainterPath(self._geometry())

    def extent(self, shape: Optional[QPainterPath] = None) -> float:
        """Alcance do halo fora do cartão: GLOW_EXTENT, ou menos se a janela não tem folga (nunca encosta nela)."""
        box = (shape or self.shape()).boundingRect()     # inclui pontas que saem do retângulo do cartão
        room = min(box.left(), box.top(), self.width() - box.right(), self.height() - box.bottom())
        return max(0.0, min(GLOW_EXTENT, room - GLOW_EDGE_GAP))

    def _band(self) -> QRegion:
        """Só a faixa em volta do cartão precisa ser redesenhada: o halo nunca pinta dentro do contorno."""
        inner = QRegion(self.shape().toFillPolygon().toPolygon())
        # Encolhe 2 px (interseção com cópias deslocadas) para a borda suavizada também ser redesenhada.
        for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2)):
            inner = inner.intersected(inner.translated(dx, dy))
        return QRegion(self.rect()).subtracted(inner)

    def paintEvent(self, event):
        if self._level <= 0.0:
            return
        shape = self.shape()
        if shape.isEmpty():
            return
        extent = self.extent(shape)
        if extent <= 0.5:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        p.setClipPath(outside.subtracted(shape))     # só por fora do cartão
        p.setBrush(Qt.BrushStyle.NoBrush)
        for frac, alpha in GLOW_LAYERS:
            reach = min(2.0 * extent * frac * (self._breathe if frac > 0.2 else 1.0), 2.0 * extent)
            c = QColor(self._color)
            c.setAlpha(round(255 * max(0.0, min(1.0, alpha * self._level * 1.25))))
            # Traço centrado no contorno: metade cai dentro (cortada pelo clip), metade sai `reach - 0.5` px.
            # Junta redonda: nas pontas (estrela, cantos retos) o halo contorna em vez de virar um espinho.
            pen = QPen(c, max(0.0, 2.0 * (reach - 0.5)))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(shape)
        p.end()


class NetOverlay(QWidget):
    """Janela transparente, sem foco e sem cliques, onde a rede é desenhada (coordenadas globais de tela)."""

    def __init__(self, paint_scene: Callable[[QPainter], None]):
        super().__init__(None)
        self._paint_scene = paint_scene
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._desktop = False
        self._layer_dirty = True

    def set_desktop(self, desktop: bool):
        """Camada da rede: logo acima da área de trabalho (os apps a cobrem) ou por cima de tudo."""
        if bool(desktop) != self._desktop:
            self._desktop = bool(desktop)
            self._layer_dirty = True

    def is_desktop(self) -> bool:
        return self._desktop

    SLACK = 96   # px de folga em volta: num arraste a janela da rede quase nunca precisa se mover

    def cover(self, rect: Optional[QRect]):
        """
        Ocupa (pelo menos) `rect` da tela e redesenha NA HORA; `None` some com a janela.

        O redesenho é síncrono (`repaint`, não `update`): quem chama acabou de mover os widgets, e a rede/brilho tem
        de ir junto no mesmo passo. Com `update` o desenho saía no próximo ciclo e, por um quadro, o brilho ficava
        onde o widget estava (fantasma). A janela também só muda de lugar quando a área pedida sai da folga atual:
        mover a janela mostra o desenho velho no lugar novo até o repaint.
        """
        if rect is None or rect.isEmpty():
            if self.isVisible():
                self.hide()
            return
        cur = self.geometry()
        too_big = cur.width() * cur.height() > 4 * max(1, rect.width() * rect.height())
        if not self.isVisible() or not cur.contains(rect) or too_big:
            s = self.SLACK
            self.setGeometry(rect.adjusted(-s, -s, s, s))
        if not self.isVisible():
            self.show()
            self._layer_dirty = True       # mostrar a janela a põe por cima de novo
        if self._layer_dirty:
            from app.core import desktop_layer
            desktop_layer.apply_layer(int(self.winId()), self._desktop)
            self._layer_dirty = False
        self.repaint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.translate(-self.x(), -self.y())
        self._paint_scene(p)
        p.end()
