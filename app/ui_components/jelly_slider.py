"""
Jelly Slider (DesignBookmark: https://designbookmark.com/motion#db-jelly-slider), em PySide6 nativo.

- O polegar segue o ponteiro por mola (`FOLLOW = 900/50`) e estica conforme a velocidade preservando área.
- Ao arrastar, uma gota de valor sobe do polegar (`BUBBLE = 420/22`), inclina para trás acompanhando a
  inércia (`DX = 260/18`) e se funde ao polegar por uma ponte líquida (metaball) que se separa ao subir
  e volta a derreter no polegar ao soltar.
- Arrastar além das pontas encontra resistência elástica (rubber band) e volta com quique (`RELEASE = 300/14`).
- Escala graduada logo abaixo da trilha (0..32 px por padrão, marcas a cada 4 px, maiores a cada 8 px)
  que acende conforme o valor passa.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from app.core import widget_animator
from app.core.refresh_rate import FRAME_MS, refresh_interval_ms
from app.hub.theme import HubTheme, THEME_DARK
from app.core.frame_clock import FrameTimer

# Molas exatas do Jelly Slider (DesignBookmark)
FOLLOW = (900.0, 50.0)     # polegar seguindo o ponteiro
BUBBLE = (420.0, 22.0)     # gota subindo/descendo
RELEASE = (300.0, 14.0)    # retorno após over-drag elástico
GLIDE = (420.0, 34.0)      # deslize suave pelo teclado
DROP_LAG = (260.0, 18.0)   # atraso horizontal da gota (cria a inclinação)
POP = (520.0, 16.0)        # escala de hover / clique do polegar


SUBSTEPS = 4


class _Spring:
    __slots__ = ("x", "t", "v", "k", "c")

    def __init__(self, x: float = 0.0, params: tuple[float, float] = FOLLOW):
        self.x = float(x)
        self.t = float(x)
        self.v = 0.0
        self.k, self.c = params

    def tune(self, params: tuple[float, float]) -> None:
        self.k, self.c = params

    def step(self, dt: float) -> None:
        a = -self.k * (self.x - self.t) - self.c * self.v
        self.v += a * dt
        self.x += self.v * dt

    def settled(self, eps: float = 0.08) -> bool:
        return abs(self.x - self.t) < eps and abs(self.v) < eps * 10.0


def _clamp(v: float, a: float, b: float) -> float:
    return a if v < a else b if v > b else v


def _rubber(x: float, lo: float, hi: float, d: float = 16.0) -> float:
    if x < lo:
        return lo - (1.0 - 1.0 / ((lo - x) * 0.55 / d + 1.0)) * d
    if x > hi:
        return hi + (1.0 - 1.0 / ((x - hi) * 0.55 / d + 1.0)) * d
    return x


def _metaball_bridge(c1: QPointF, r1: float, c2: QPointF, r2: float, max_gap: float = 28.0) -> Optional[QPainterPath]:
    """Desenha a ponte líquida (efeito goo) entre o polegar e a gota de valor enquanto sobem/descem."""
    dx = c2.x() - c1.x()
    dy = c2.y() - c1.y()
    d = math.hypot(dx, dy)
    if d < 1e-3 or d > r1 + r2 + max_gap or d <= abs(r1 - r2):
        return None

    # Ângulo entre os centros e largura do pescoço afinando com a distância
    angle = math.atan2(dy, dx)
    u = _clamp((d - abs(r1 - r2)) / (r1 + r2 + max_gap - abs(r1 - r2)), 0.0, 1.0)
    spread1 = math.acos(_clamp((r1 - r2) / d, -1.0, 1.0)) * (0.65 - 0.35 * u)
    spread2 = math.acos(_clamp((r2 - r1) / d, -1.0, 1.0)) * (0.65 - 0.35 * u)

    # Pontos tangentes aproximados em cada círculo
    a1 = angle + math.pi * 0.48 - spread1 * 0.35
    a2 = angle - math.pi * 0.48 + spread1 * 0.35
    b1 = angle + math.pi - (math.pi * 0.48 - spread2 * 0.35)
    b2 = angle + math.pi + (math.pi * 0.48 - spread2 * 0.35)

    p1 = QPointF(c1.x() + math.cos(a1) * r1, c1.y() + math.sin(a1) * r1)
    p2 = QPointF(c1.x() + math.cos(a2) * r1, c1.y() + math.sin(a2) * r1)
    p3 = QPointF(c2.x() + math.cos(b2) * r2, c2.y() + math.sin(b2) * r2)
    p4 = QPointF(c2.x() + math.cos(b1) * r2, c2.y() + math.sin(b1) * r2)

    # Ponto de controle puxado para o eixo central cria o afunilamento viscoso ("goo")
    mid = QPointF((c1.x() + c2.x()) * 0.5, (c1.y() + c2.y()) * 0.5)
    pinch = 0.38 + 0.42 * u
    ctrl_l = QPointF(
        (p1.x() + p4.x()) * 0.5 * (1.0 - pinch) + mid.x() * pinch,
        (p1.y() + p4.y()) * 0.5 * (1.0 - pinch) + mid.y() * pinch,
    )
    ctrl_r = QPointF(
        (p2.x() + p3.x()) * 0.5 * (1.0 - pinch) + mid.x() * pinch,
        (p2.y() + p3.y()) * 0.5 * (1.0 - pinch) + mid.y() * pinch,
    )

    path = QPainterPath(p1)
    path.quadTo(ctrl_l, p4)
    path.lineTo(p3)
    path.quadTo(ctrl_r, p2)
    path.closeSubpath()
    return path


class JellySlider(QWidget):
    """Slider elástico com gota líquida de valor e escala graduada (0..32 px por padrão)."""

    value_changed = Signal(int)
    live_value_changed = Signal(float)   # valor contínuo (mola) emitido a cada quadro na taxa do monitor (até 240 Hz)
    interaction_finished = Signal()      # emitido ao soltar o arraste / assentar, para gravar em disco uma só vez

    # Métricas internas (deixam folga no topo para a gota subir sem ser cortada)
    TOP_HEADROOM = 42.0   # espaço acima da trilha para a gota subir
    RAIL_H = 26.0
    THUMB_R = 9.5
    DROP_R = 14.5
    RISE = -32.0
    REST_DROP = 0.46
    SIDE_PAD = 14.0

    def __init__(
        self,
        minimum: int = 0,
        maximum: int = 32,
        value: int = 10,
        step_minor: int = 4,
        step_major: int = 8,
        theme: HubTheme = THEME_DARK,
        parent: Optional[QWidget] = None,
        suffix: str = "",
        headroom: Optional[float] = None,   # espaço acima da trilha para a gota (menor = controle mais compacto)
        side_pad: Optional[float] = None,   # folga lateral da trilha
    ):
        super().__init__(parent)
        self._suffix = suffix
        if headroom is not None:
            self.TOP_HEADROOM = float(headroom)
            self.RISE = -(float(headroom) + self.RAIL_H * 0.5 - self.DROP_R - 1.0)   # a gota cabe sem cortar
        if side_pad is not None:
            self.SIDE_PAD = float(side_pad)
        self._min = int(minimum)
        self._max = max(self._min + 1, int(maximum))
        self._step_minor = max(1, int(step_minor))
        self._step_major = max(self._step_minor, int(step_major))
        self._theme = theme
        self._value = int(_clamp(value, self._min, self._max))
        self._ratio = (self._value - self._min) / float(self._max - self._min)

        self._dragging = False
        self._hovered = False
        self._lifted = False

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(int(self.TOP_HEADROOM + self.RAIL_H + 26))
        self.setMinimumWidth(210)

        cy = self._track_cy()
        init_x = self._to_x(self._value)
        self._x = _Spring(init_x, FOLLOW)
        self._dx = _Spring(init_x, DROP_LAG)
        self._dy = _Spring(cy, BUBBLE)
        self._ds = _Spring(self.REST_DROP, BUBBLE)
        self._ps = _Spring(1.0, POP)

        self._last = 0.0
        self._last_live = float(self._value)
        self._dirty_commit = False
        self._timer = FrameTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(refresh_interval_ms(self))
        self._timer.timeout.connect(self._tick)

    def sizeHint(self) -> QSize:
        return QSize(248, int(self.TOP_HEADROOM + self.RAIL_H + 26))

    def value(self) -> int:
        return self._value

    def is_dragging(self) -> bool:
        return self._dragging

    def is_busy(self) -> bool:
        """Arrastando ou ainda assentando o quique: quem sincroniza o valor por fora espera."""
        return self._dragging or self._dirty_commit

    def set_theme(self, theme: HubTheme) -> None:
        self._theme = theme
        self.update()

    def set_value(self, value: int, animated: bool = False) -> None:
        v = int(_clamp(value, self._min, self._max))
        self._value = v
        self._ratio = (v - self._min) / float(self._max - self._min)
        tx = self._to_x(v)
        if not animated or not widget_animator.animations_enabled():
            self._x.x = self._x.t = tx
            self._x.v = 0.0
            self._dx.x = self._dx.t = tx
            self._dx.v = 0.0
            self.update()
            return
        self._x.tune(GLIDE)
        self._x.t = tx
        self._start()

    # --- Geometria ---

    def _track_left(self) -> float:
        return self.SIDE_PAD

    def _track_right(self) -> float:
        return max(self.SIDE_PAD + 20.0, float(self.width()) - self.SIDE_PAD)

    def _travel_left(self) -> float:
        return self._track_left() + self.THUMB_R

    def _travel_right(self) -> float:
        return max(self._travel_left() + 1.0, self._track_right() - self.THUMB_R)

    def _track_cy(self) -> float:
        return self.TOP_HEADROOM + self.RAIL_H * 0.5

    def _to_x(self, val: float) -> float:
        lo, hi = self._travel_left(), self._travel_right()
        frac = (val - self._min) / float(self._max - self._min)
        return lo + _clamp(frac, 0.0, 1.0) * (hi - lo)

    def _to_val(self, x: float) -> float:
        lo, hi = self._travel_left(), self._travel_right()
        frac = _clamp((x - lo) / max(hi - lo, 1.0), 0.0, 1.0)
        return self._min + frac * (self._max - self._min)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        tx = self._to_x(self._min + self._ratio * (self._max - self._min))
        self._x.x = self._x.t = self._dx.x = self._dx.t = tx
        self._x.v = self._dx.v = 0.0
        self._dy.x = self._dy.t = self._track_cy()
        self.update()

    # --- Interação ---

    def _sync_targets(self) -> None:
        up = self._dragging or self._lifted
        cy = self._track_cy()
        self._dy.t = cy + self.RISE if up else cy
        self._ds.t = 1.0 if up else self.REST_DROP
        self._ps.t = 1.15 if self._dragging else (1.08 if self._hovered else 1.0)
        if not widget_animator.animations_enabled():
            for s in (self._x, self._dx, self._dy, self._ds, self._ps):
                s.x = s.t
                s.v = 0.0
            self.update()
        else:
            self._start()

    def _start(self) -> None:
        self._timer.setInterval(refresh_interval_ms(self))
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def _emit_live_value(self, x: float) -> None:
        live = self._to_val(x)
        if abs(live - self._last_live) >= 0.01:
            self._last_live = live
            self.live_value_changed.emit(live)
        new_val = int(round(live))
        if new_val != self._value:
            self._value = new_val
            self.value_changed.emit(new_val)

    def _update_value_from_x(self, x: float) -> None:
        self._emit_live_value(x)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Só inicia arraste na área da trilha/escala (evita clicar no headroom transparente acima)
            if event.position().y() >= self.TOP_HEADROOM - 6:
                self._dragging = True
                self._dirty_commit = True
                self._x.tune(FOLLOW)
                self._x.t = _rubber(event.position().x(), self._travel_left(), self._travel_right())
                self._ratio = (self._to_val(self._x.t) - self._min) / float(self._max - self._min)
                if not widget_animator.animations_enabled():
                    self._x.x = self._dx.x = self._dx.t = self._x.t
                    self._emit_live_value(self._x.x)
                self._sync_targets()
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        in_rail = event.position().y() >= self.TOP_HEADROOM - 6
        if self._dragging:
            self._x.t = _rubber(event.position().x(), self._travel_left(), self._travel_right())
            self._ratio = (self._to_val(self._x.t) - self._min) / float(self._max - self._min)
            if not widget_animator.animations_enabled():
                self._x.x = self._dx.x = self._dx.t = self._x.t
                self._emit_live_value(self._x.x)
                self.update()
            else:
                self._start()
            event.accept()
            return
        if in_rail != self._hovered:
            self._hovered = in_rail
            self._sync_targets()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._x.tune(RELEASE)
            self._x.t = _clamp(self._x.t, self._travel_left(), self._travel_right())
            if not widget_animator.animations_enabled():
                self._x.x = self._dx.x = self._dx.t = self._x.t
                self._emit_live_value(self._x.x)
                self._dirty_commit = False
                self.interaction_finished.emit()
            self._sync_targets()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._sync_targets()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        delta = {
            Qt.Key.Key_Right: 2,
            Qt.Key.Key_Up: 2,
            Qt.Key.Key_Left: -2,
            Qt.Key.Key_Down: -2,
            Qt.Key.Key_PageUp: self._step_major,
            Qt.Key.Key_PageDown: -self._step_major,
        }.get(key)
        abs_val = {Qt.Key.Key_Home: self._min, Qt.Key.Key_End: self._max}.get(key)
        if delta is not None or abs_val is not None:
            nxt = abs_val if abs_val is not None else int(_clamp(self._value + delta, self._min, self._max))
            self._lifted = True
            self.set_value(nxt, animated=True)
            self.value_changed.emit(nxt)
            self._sync_targets()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._lifted:
            self._lifted = False
            self._sync_targets()
        super().focusOutEvent(event)

    # --- Loop de física ---

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._last, 1.0 / 30.0) / SUBSTEPS
        self._last = now
        for _ in range(SUBSTEPS):
            self._dx.t = self._x.x
            self._x.step(dt)
            self._dx.step(dt)
            self._dy.step(dt)
            self._ds.step(dt)
            self._ps.step(dt)

        # Emite continuamente o valor da mola (inclusive durante o retorno elástico após soltar!)
        if self._dragging or self._dirty_commit:
            self._emit_live_value(self._x.x)

        if (
            not self._dragging
            and self._x.settled()
            and self._dx.settled()
            and self._dy.settled()
            and self._ds.settled(0.005)
            and self._ps.settled(0.005)
        ):
            for s in (self._x, self._dx, self._dy, self._ds, self._ps):
                s.x = s.t
                s.v = 0.0
            self._timer.stop()
            if self._dirty_commit:
                self._dirty_commit = False
                self._emit_live_value(self._x.x)
                self.interaction_finished.emit()
        self.update()

    # --- Desenho ---

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        t = self._theme
        is_dark = t.is_dark
        track_bg = QColor(255, 255, 255, 36) if is_dark else QColor(23, 24, 26, 30)
        inverse = QColor(t.text)
        on_inverse = QColor(t.menu_bg)
        tick_dim = QColor(255, 255, 255, 42) if is_dark else QColor(23, 24, 26, 38)
        tick_major_dim = QColor(255, 255, 255, 110) if is_dark else QColor(23, 24, 26, 95)
        tick_on = QColor(255, 255, 255, 200) if is_dark else QColor(23, 24, 26, 195)
        tick_major_on = QColor(t.text)
        num_dim = QColor(t.mute)
        num_on = QColor(t.text)

        cy = self._track_cy()
        tl = self._track_left()
        tr = self._track_right()
        tw = max(1.0, tr - tl)
        track_h = 5.5

        # 1. Trilha + preenchimento
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track_bg)
        p.drawRoundedRect(QRectF(tl, cy - track_h / 2.0, tw, track_h), track_h / 2.0, track_h / 2.0)

        x = self._x.x
        fill_ratio = _clamp((x - self._travel_left()) / max(self.THUMB_R, 1.0), 0.0, 1.0)
        fill_w = _clamp(x - tl, 0.0, tw) * fill_ratio
        if fill_w > 0.5:
            p.setBrush(inverse)
            p.drawRoundedRect(QRectF(tl, cy - track_h / 2.0, fill_w, track_h), track_h / 2.0, track_h / 2.0)

        # 2. Camada líquida: ponte metaball + polegar esticado pela velocidade + gota de valor
        st = 1.0 + min(abs(self._x.v) / 2400.0, 0.4)
        ps = max(0.5, self._ps.x)
        thumb_rx = self.THUMB_R * st * ps
        thumb_ry = self.THUMB_R * (ps / st)
        drop_r = self.DROP_R * max(0.0, self._ds.x)

        thumb_c = QPointF(x, cy)
        drop_c = QPointF(self._dx.x, self._dy.x)

        p.setBrush(inverse)
        if drop_r > 2.0:
            bridge = _metaball_bridge(thumb_c, min(thumb_rx, thumb_ry) * 0.96, drop_c, drop_r * 0.96)
            if bridge is not None:
                p.drawPath(bridge)
            p.drawEllipse(drop_c, drop_r, drop_r)

        p.drawEllipse(thumb_c, thumb_rx, thumb_ry)

        # 3. Número dentro da gota (inclina conforme o atraso DX)
        label_alpha = _clamp((self._ds.x - 0.68) / 0.26, 0.0, 1.0)
        if label_alpha > 0.02:
            tilt = _clamp((self._dx.x - x) * 0.9, -28.0, 28.0)
            p.save()
            p.translate(drop_c)
            p.rotate(tilt)
            font = QFont(self.font())
            font.setPixelSize(10 if self._suffix else 11)
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            txt_col = QColor(on_inverse)
            txt_col.setAlphaF(label_alpha)
            p.setPen(txt_col)
            box = QRectF(-self.DROP_R, -self.DROP_R, self.DROP_R * 2, self.DROP_R * 2)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, f"{self._value}{self._suffix}")
            p.restore()

        # 4. Escala graduada sob a trilha (marcas a cada step_minor, maiores + números a cada step_major)
        marks_y = cy + self.THUMB_R + 6.0
        font_num = QFont(self.font())
        font_num.setPixelSize(10)
        font_num.setWeight(QFont.Weight.Medium)
        font_num.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)   # sem franjas coloridas (ClearType) sobre fundo translúcido
        p.setFont(font_num)

        v = self._min
        while v <= self._max:
            mx = self._to_x(v)
            is_major = (v - self._min) % self._step_major == 0
            passed = v <= self._value and self._value > self._min
            h = 7.0 if is_major else 3.8
            col = (tick_major_on if is_major else tick_on) if passed else (tick_major_dim if is_major else tick_dim)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(mx - 0.75, marks_y, 1.5, h), 0.75, 0.75)

            if is_major:
                p.setPen(num_on if passed else num_dim)
                p.drawText(QRectF(mx - 14.0, marks_y + 9.0, 28.0, 13.0), Qt.AlignmentFlag.AlignCenter, str(v))
            v += self._step_minor

        p.end()
