"""
PositionPicker - Seletor visual de ancoragem na tela, desenhado como um mini monitor 16:9.

- A moldura é a tela e a faixa de baixo é a barra de tarefas: "embaixo" e "em cima" ficam óbvios.
- Cada posição é uma pequena pílula no formato de um flyout, encostada na borda: apagada quando livre, realçada
  no hover e no acento quando escolhida. O espaço sem posição é só tela (nada de "tecla faltando").
- O clique vale para a posição MAIS PRÓXIMA do ponteiro: o monitor inteiro é área de clique.

Posições: tl, tc, tr, bl, bc, br (widgets). Com `with_middle_row=True` ganha ml e mr (8 âncoras dos flyouts).
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.hub.theme import HubTheme, THEME_LIGHT


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

        self.setFixedSize(int(self.SCREEN_W) + 2, int(self.SCREEN_H) + 2)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- API ---

    def positions(self) -> tuple[str, ...]:
        return self._positions

    def set_position(self, pos_key: str):
        if pos_key not in self._positions:
            return
        self._current_pos = pos_key
        self.update()
        self.position_changed.emit(pos_key)

    def select(self, pos_key: str):
        """Marca a posição sem emitir o sinal (sincronização vinda de fora)."""
        if pos_key in self._positions and pos_key != self._current_pos:
            self._current_pos = pos_key
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

        # Pílulas de posição
        p.setPen(Qt.PenStyle.NoPen)
        for key in self._positions:
            rect = self._pill_rect(key)
            if key == self._current_pos:
                glow = QColor(th.accent)
                glow.setAlphaF(0.22)
                p.setBrush(glow)
                p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 6.0, 6.0)
                p.setBrush(QColor(th.accent))
            elif key == self._hover:
                p.setBrush(QColor(th.mute))
            else:
                idle = QColor(th.mute)
                idle.setAlphaF(0.35)
                p.setBrush(idle)
            p.drawRoundedRect(rect, self.PILL_H / 2.0, self.PILL_H / 2.0)
