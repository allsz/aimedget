"""
PositionPicker - Seletor visual de ancoragem na tela, desenhado como um mini monitor 16:9.

- A moldura é a tela e a faixa de baixo é a barra de tarefas: "embaixo" e "em cima" ficam óbvios.
- Cada posição é uma pequena pílula no formato de um flyout, encostada na borda: apagada quando livre, realçada
  no hover e no acento quando escolhida. O espaço sem posição é só tela (nada de "tecla faltando").
- O clique vale para a posição MAIS PRÓXIMA do ponteiro: o monitor inteiro é área de clique.

Posições: tl, tc, tr, bl, bc, br (widgets). Com `with_middle_row=True` ganha ml e mr (8 âncoras dos flyouts).
"""

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget
from app.core.refresh_rate import refresh_interval_ms

from app.hub.components import tab_pill
from app.hub.components.city_list import Spring
from app.hub.theme import HubTheme, THEME_LIGHT
from app.core.frame_clock import FrameTimer

FRAME_MS = 16
SUBSTEPS = 4


class PositionPicker(QWidget):
    position_changed = Signal(str)  # ex: 'br', 'tl', 'bc'

    POSITIONS = ("tl", "tc", "tr", "bl", "bc", "br")
    POSITIONS_WITH_MIDDLE = ("tl", "tc", "tr", "ml", "mr", "bl", "bc", "br")

    SCREEN_W = 132.0
    SCREEN_H = 76.0          # ~16:9 com a barra de tarefas
    RADIUS = 8.0
    TASKBAR_H = 7.0
    PAD = 8.0                # distância das pílulas às bordas da tela
    PILL_W = 22.0
    PILL_H = 8.0

    def __init__(self, current_pos: str = "br", theme: HubTheme = THEME_LIGHT, parent=None,
                 with_middle_row: bool = False):
        super().__init__(parent)
        self._positions = self.POSITIONS_WITH_MIDDLE if with_middle_row else self.POSITIONS
        self._current_pos = current_pos if current_pos in self._positions else self._positions[-2]
        self._theme = theme
        self._hover: str | None = None

        # O destaque (pílula + brilho) desliza entre as posições: uma mola por borda do retângulo, a que vai na
        # frente é dura e a de trás é mole (o mesmo esticar da Tab pill, nos dois eixos).
        r = self._pill_rect(self._current_pos)
        self._edges = {"l": Spring(r.left(), tab_pill.TRAIL), "r": Spring(r.right(), tab_pill.TRAIL),
                       "t": Spring(r.top(), tab_pill.TRAIL), "b": Spring(r.bottom(), tab_pill.TRAIL)}
        self._last = 0.0
        self._timer = FrameTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

        self.setFixedSize(int(self.SCREEN_W) + 2, int(self.SCREEN_H) + 2)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- API ---

    def positions(self) -> tuple[str, ...]:
        return self._positions

    def set_position(self, pos_key: str):
        if pos_key not in self._positions:
            return
        self._move_highlight(pos_key)
        self.position_changed.emit(pos_key)

    def select(self, pos_key: str):
        """Marca a posição sem emitir o sinal (sincronização vinda de fora)."""
        if pos_key in self._positions and pos_key != self._current_pos:
            self._move_highlight(pos_key)

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def highlight_rect(self) -> QRectF:
        e = self._edges
        return QRectF(QPointF(e["l"].x, e["t"].x), QPointF(max(e["l"].x, e["r"].x), max(e["t"].x, e["b"].x)))

    def _move_highlight(self, pos_key: str):
        old = self._pill_rect(self._current_pos)
        new = self._pill_rect(pos_key)
        self._current_pos = pos_key
        targets = {"l": new.left(), "r": new.right(), "t": new.top(), "b": new.bottom()}
        if not (tab_pill.animations_enabled() and self.isVisible()):
            for k, v in targets.items():
                self._edges[k].x = self._edges[k].t = v
                self._edges[k].v = 0.0
            self._timer.stop()
            self.update()
            return
        # eixo X: indo para a direita a borda direita lidera; eixo Y: indo para baixo a borda de baixo lidera
        for (lo, hi), forward in ((("l", "r"), new.left() >= old.left()), (("t", "b"), new.top() >= old.top())):
            lead, trail = (hi, lo) if forward else (lo, hi)
            self._edges[lead].k, self._edges[lead].c = tab_pill.LEAD
            self._edges[trail].k, self._edges[trail].c = tab_pill.TRAIL
        for k, v in targets.items():
            self._edges[k].t = v
        self._last = time.monotonic()
        self._timer.setInterval(refresh_interval_ms(self))
        self._timer.start()
        self.update()

    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last, 1 / 30) / SUBSTEPS
        self._last = now
        for _ in range(SUBSTEPS):
            for spring in self._edges.values():
                spring.step(dt)
        if all(s.settled() for s in self._edges.values()):
            for s in self._edges.values():
                s.x, s.v = s.t, 0.0
            self._timer.stop()
        self.update()

    def get_position(self) -> str:
        return self._current_pos

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    # --- Geometria ---

    def _screen_rect(self) -> QRectF:
        return QRectF(1.0, 1.0, self.SCREEN_W, self.SCREEN_H)

    def _pill_rect(self, pos_key: str) -> QRectF:
        s = self._screen_rect()
        usable_bottom = s.bottom() - self.TASKBAR_H
        xs = {
            "l": s.left() + self.PAD,
            "c": s.center().x() - self.PILL_W / 2.0,
            "r": s.right() - self.PAD - self.PILL_W,
        }
        ys = {
            "t": s.top() + self.PAD,
            "m": (s.top() + usable_bottom) / 2.0 - self.PILL_H / 2.0,
            "b": usable_bottom - self.PAD - self.PILL_H,
        }
        return QRectF(xs[pos_key[1]], ys[pos_key[0]], self.PILL_W, self.PILL_H)

    def _nearest(self, pt: QPointF) -> str:
        def dist(k):
            c = self._pill_rect(k).center()
            return math.hypot(c.x() - pt.x(), c.y() - pt.y())
        return min(self._positions, key=dist)

    # --- Eventos ---

    def mouseMoveEvent(self, event):
        hover = self._nearest(event.position())
        if hover != self._hover:
            self._hover = hover
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_position(self._nearest(event.position()))

    # --- Pintura ---

    def paintEvent(self, event):
        th = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Tela
        screen = self._screen_rect()
        frame = QPainterPath()
        frame.addRoundedRect(screen, self.RADIUS, self.RADIUS)
        p.fillPath(frame, QColor(th.panel2))

        # Barra de tarefas (recortada pelos cantos arredondados da tela)
        p.save()
        p.setClipPath(frame)
        bar = QColor(th.mute)
        bar.setAlphaF(0.22)
        p.fillRect(QRectF(screen.left(), screen.bottom() - self.TASKBAR_H, screen.width(), self.TASKBAR_H), bar)
        p.restore()

        border = QColor(th.mute)
        border.setAlphaF(0.30)
        p.setPen(QPen(border, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(frame)

        # Pílulas de posição (a escolhida é o destaque abaixo, que desliza)
        p.setPen(Qt.PenStyle.NoPen)
        for key in self._positions:
            if key == self._current_pos and not self._timer.isActive():
                continue
            rect = self._pill_rect(key)
            if key == self._hover and key != self._current_pos:
                p.setBrush(QColor(th.mute))
            else:
                idle = QColor(th.mute)
                idle.setAlphaF(0.35)
                p.setBrush(idle)
            p.drawRoundedRect(rect, self.PILL_H / 2.0, self.PILL_H / 2.0)
        rect = self.highlight_rect()
        glow = QColor(th.accent)
        glow.setAlphaF(0.22)
        p.setBrush(glow)
        p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 6.0, 6.0)
        p.setBrush(QColor(th.accent))
        p.drawRoundedRect(rect, self.PILL_H / 2.0, self.PILL_H / 2.0)
