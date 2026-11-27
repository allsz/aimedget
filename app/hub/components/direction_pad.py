"""
DirectionPad - Controle D-Pad estilo Console Cross para escolher as direções de expansão do Battery Widget.

- 4 braços independentes (l, r, u, d) com cantos arredondados externos e chevrons vetoriais; pelo menos 1 fica ativo.
- Ponto central alterna Automático (todas as 4 direções) em um clique.
- Braços ativos acendem com a cor de destaque do Hub e um halo suave.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.core.frame_clock import FrameTimer
from app.core.refresh_rate import FRAME_MS, refresh_interval_ms
from app.core.widget_animator import animations_enabled
from app.hub.theme import HubTheme, THEME_LIGHT
from app.widgets.battery import layout as lay


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(round(a.red() + (b.red() - a.red()) * t)),
        int(round(a.green() + (b.green() - a.green()) * t)),
        int(round(a.blue() + (b.blue() - a.blue()) * t)),
        int(round(a.alpha() + (b.alpha() - a.alpha()) * t)),
    )


def _rounded_rect_path(rect: QRectF, tl: float, tr: float, br: float, bl: float) -> QPainterPath:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    r, b = x + w, y + h
    p = QPainterPath()
    p.moveTo(x + tl, y)
    p.lineTo(r - tr, y)
    if tr > 0:
        p.quadTo(r, y, r, y + tr)
    p.lineTo(r, b - br)
    if br > 0:
        p.quadTo(r, b, r - br, b)
    p.lineTo(x + bl, b)
    if bl > 0:
        p.quadTo(x, b, x, b - bl)
    p.lineTo(x, y + tl)
    if tl > 0:
        p.quadTo(x, y, x + tl, y)
    p.closeSubpath()
    return p


class DirectionPad(QWidget):
    """D-Pad Console Cross interativo; emite a string normalizada de direções ativas (ex.: 'l', 'lr', 'lrud')."""

    directions_changed = Signal(str)

    PAD = 8.0        # folga externa para o halo do braço ativo não cortar
    CROSS = 84.0     # tamanho da cruz (84 x 84)
    ARM_W = 28.0     # largura de cada braço
    ARM_L = 30.0     # comprimento de cada braço
    HUB = 28.0       # quadrado central

    def __init__(self, directions: str = lay.DEFAULT_EXPAND, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self._dirs: str = lay.normalize_expand(directions)
        self._theme: HubTheme = theme
        self._hover: str | None = None
        self._pressed: str | None = None
        self._glow: dict[str, float] = {k: (1.0 if k in self._dirs else 0.0) for k in ("u", "d", "l", "r")}
        self._dot_glow: float = 1.0 if self._dirs == "lrud" else 0.0
        self._last: float = 0.0
        self._timer = FrameTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

        side = int(self.CROSS + self.PAD * 2)
        self.setFixedSize(side, side)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- API ---

    def directions(self) -> str:
        return self._dirs

    def set_directions(self, directions: str, emit: bool = False):
        norm = lay.normalize_expand(directions)
        if norm == self._dirs:
            return
        self._dirs = norm
        if animations_enabled() and self.isVisible():
            self._last = time.monotonic()
            self._timer.setInterval(refresh_interval_ms(self))
            self._timer.start()
        else:
            for k in ("u", "d", "l", "r"):
                self._glow[k] = 1.0 if k in self._dirs else 0.0
            self._dot_glow = 1.0 if self._dirs == "lrud" else 0.0
            self._timer.stop()
        self.update()
        if emit:
            self.directions_changed.emit(self._dirs)

    def _tick(self):
        now = time.monotonic()
        dt = max(0.0, min(0.05, now - self._last)) if self._last > 0.0 else 0.016
        self._last = now
        alpha = 1.0 - math.exp(-18.0 * dt)
        settled = True
        for k in ("u", "d", "l", "r"):
            target = 1.0 if k in self._dirs else 0.0
            val = self._glow[k] + (target - self._glow[k]) * alpha
            if abs(val - target) < 0.01:
                val = target
            else:
                settled = False
            self._glow[k] = val
        dot_t = 1.0 if self._dirs == "lrud" else 0.0
        self._dot_glow += (dot_t - self._dot_glow) * alpha
        if abs(self._dot_glow - dot_t) < 0.01:
            self._dot_glow = dot_t
        else:
            settled = False
        if settled:
            self._timer.stop()
        self.update()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    def sizeHint(self) -> QSize:
        side = int(self.CROSS + self.PAD * 2)
        return QSize(side, side)

    # --- Geometria ---

    def _rects(self) -> dict[str, QRectF]:
        ox = self.PAD
        oy = self.PAD
        cx = ox + (self.CROSS - self.HUB) / 2.0
        cy = oy + (self.CROSS - self.HUB) / 2.0
        return {
            "u": QRectF(cx, oy, self.ARM_W, self.ARM_L),
            "d": QRectF(cx, oy + self.CROSS - self.ARM_L, self.ARM_W, self.ARM_L),
            "l": QRectF(ox, cy, self.ARM_L, self.ARM_W),
            "r": QRectF(ox + self.CROSS - self.ARM_L, cy, self.ARM_L, self.ARM_W),
            "all": QRectF(cx, cy, self.HUB, self.HUB),
        }

    def _hit(self, pos: QPointF) -> str | None:
        rects = self._rects()
        # Centro primeiro (fica por cima das emendas dos braços)
        if rects["all"].contains(pos):
            return "all"
        for k in ("u", "d", "l", "r"):
            if rects[k].contains(pos):
                return k
        return None

    # --- Interação ---

    def mouseMoveEvent(self, event):
        h = self._hit(event.position())
        if h != self._hover:
            self._hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h is not None else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        if self._hover is not None or self._pressed is not None:
            self._hover = None
            self._pressed = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            h = self._hit(event.position())
            if h is not None:
                self._pressed = h
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed is not None:
            hit = self._hit(event.position())
            clicked = self._pressed
            self._pressed = None
            if hit == clicked:
                self._toggle(clicked)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _toggle(self, key: str):
        if key == "all":
            new_val = "l" if self._dirs == "lrud" else "lrud"
            self.set_directions(new_val, emit=True)
            return
        active = set(self._dirs)
        if key in active:
            if len(active) <= 1:
                return   # mantém sempre pelo menos 1 direção ligada
            active.remove(key)
        else:
            active.add(key)
        self.set_directions("".join(active), emit=True)

    # --- Pintura ---

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        t = self._theme
        accent = QColor(t.accent)
        ink = QColor(t.ink)
        panel = QColor(t.panel)
        panel2 = QColor(t.panel2)
        hover_bg = QColor(t.hover)
        line = QColor(t.line)
        mute = QColor(t.mute)
        text = QColor(t.text)

        rects = self._rects()
        radii = {
            "u": (8.0, 8.0, 3.0, 3.0),
            "d": (3.0, 3.0, 8.0, 8.0),
            "l": (8.0, 3.0, 3.0, 8.0),
            "r": (3.0, 8.0, 8.0, 3.0),
        }

        # 1. Halo suave por trás dos braços ativos (fade fluido)
        for k in ("u", "d", "l", "r"):
            g = self._glow[k]
            if g <= 0.01:
                continue
            r = rects[k]
            c = r.center()
            grad = QRadialGradient(c, 24.0)
            g0 = QColor(accent)
            g0.setAlpha(int(round((90 if t.is_dark else 72) * g)))
            g1 = QColor(accent)
            g1.setAlpha(0)
            grad.setColorAt(0.0, g0)
            grad.setColorAt(1.0, g1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(c, 24.0, 24.0)

        # 2. Braços (inativos primeiro, ativos por cima, com transição suave de cor)
        for pass_active in (False, True):
            for k in ("u", "d", "l", "r"):
                on = k in self._dirs
                if on != pass_active:
                    continue
                r = rects[k]
                if self._pressed == k:
                    r = r.adjusted(0.8, 0.8, -0.8, -0.8)
                path = _rounded_rect_path(r, *radii[k])
                g = self._glow[k]
                base_fill = hover_bg if self._hover == k else panel2
                base_fg = text if self._hover == k else mute
                fill = _lerp_color(base_fill, accent, g)
                border = _lerp_color(line, accent, g)
                fg = _lerp_color(base_fg, ink, g)
                p.setBrush(fill)
                p.setPen(QPen(border, 1.0))
                p.drawPath(path)
                self._paint_chevron(p, r.center(), k, fg)

        # 3. Centro (alterna Automático)
        hr = rects["all"]
        if self._pressed == "all":
            hr = hr.adjusted(0.8, 0.8, -0.8, -0.8)
        hub_border = accent if self._hover == "all" else line
        p.setBrush(panel)
        p.setPen(QPen(hub_border, 1.0))
        p.drawRoundedRect(hr, 6.0, 6.0)

        idle_dot = QColor(mute)
        idle_dot.setAlpha(140)
        dot_color = _lerp_color(idle_dot, accent, self._dot_glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot_color)
        p.drawEllipse(hr.center(), 3.4, 3.4)

    @staticmethod
    def _paint_chevron(p: QPainter, c: QPointF, direction: str, color: QColor):
        pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        s = 3.4
        cx, cy = c.x(), c.y()
        if direction == "u":
            pts = (QPointF(cx - s, cy + s * 0.45), QPointF(cx, cy - s * 0.55), QPointF(cx + s, cy + s * 0.45))
        elif direction == "d":
            pts = (QPointF(cx - s, cy - s * 0.45), QPointF(cx, cy + s * 0.55), QPointF(cx + s, cy - s * 0.45))
        elif direction == "l":
            pts = (QPointF(cx + s * 0.45, cy - s), QPointF(cx - s * 0.55, cy), QPointF(cx + s * 0.45, cy + s))
        else:
            pts = (QPointF(cx - s * 0.45, cy - s), QPointF(cx + s * 0.55, cy), QPointF(cx - s * 0.45, cy + s))
        p.drawPolyline(pts)
