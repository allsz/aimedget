import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen


class FluentSlider:
    """
    Componente visual reutilizável de Slider Horizontal no estilo Windows 11 / Fluent Design:
    - Trilho de 4px de espessura: azul (#54aff4) à esquerda e cinza (#999999) à direita
    - Thumb circular duplo de 20px (#454545 externo + círculo interno #4db2ff reativo a hover/drag)
    """

    TRACK_H = 4.0
    TRACK_RADIUS = 2.0
    THUMB_OUTER_R = 10.0
    THUMB_INNER_R_IDLE = 5.0
    THUMB_INNER_R_HOVER = 6.2
    THUMB_INNER_R_PRESSED = 4.3

    COLOR_TRACK_ACTIVE = QColor(84, 175, 244)
    COLOR_TRACK_MUTED = QColor(115, 115, 115)
    COLOR_TRACK_INACTIVE = QColor(153, 153, 153)
    COLOR_THUMB_OUTER = QColor(69, 69, 69)
    COLOR_THUMB_BORDER = QColor(54, 54, 54)
    COLOR_THUMB_INNER = QColor(77, 178, 255)

    def __init__(self, x_start: float = 45.0, x_end: float = 162.0, cy: float = 24.5):
        self.x_start = x_start
        self.x_end = x_end
        self.cy = cy
        self.value = 50       # 0 a 100
        self.is_muted = False
        self.is_hovered = False
        self.is_dragging = False
        self._inner_r = self.THUMB_INNER_R_IDLE
        # Cores por instância (um tema pode trocá-las); o padrão são as constantes da classe
        self.track_active = QColor(self.COLOR_TRACK_ACTIVE)
        self.thumb_inner = QColor(self.COLOR_THUMB_INNER)
        self.thumb_outer = QColor(self.COLOR_THUMB_OUTER)
        self.thumb_border = QColor(self.COLOR_THUMB_BORDER)
        self.track_inactive = QColor(self.COLOR_TRACK_INACTIVE)

    def apply_colors(self, track_active: QColor, thumb_inner: QColor, thumb_outer: QColor | None = None,
                     thumb_border: QColor | None = None, track_inactive: QColor | None = None):
        """Cores do slider: preenchido e miolo do botão (ativação) e, opcionalmente, o resto."""
        self.track_active = QColor(track_active)
        self.thumb_inner = QColor(thumb_inner)
        if thumb_outer is not None:
            self.thumb_outer = QColor(thumb_outer)
        if thumb_border is not None:
            self.thumb_border = QColor(thumb_border)
        if track_inactive is not None:
            self.track_inactive = QColor(track_inactive)

    def set_geometry(self, x_start: float, x_end: float, cy: float):
        self.x_start = x_start
        self.x_end = x_end
        self.cy = cy

    def step_animation(self, dt: float = 0.016) -> bool:
        """Interpola suavemente o raio do círculo interno do thumb independente da taxa de Hz."""
        target = (
            self.THUMB_INNER_R_PRESSED
            if self.is_dragging
            else (self.THUMB_INNER_R_HOVER if self.is_hovered else self.THUMB_INNER_R_IDLE)
        )
        diff = target - self._inner_r
        if abs(diff) > 0.03:
            alpha = 1.0 - math.exp(-24.0 * max(0.001, min(0.05, dt)))
            self._inner_r += diff * alpha
            return True
        self._inner_r = target
        return False

    def thumb_x(self) -> float:
        t = max(0.0, min(1.0, self.value / 100.0))
        return self.x_start + (self.x_end - self.x_start) * t

    def hit_rect(self) -> QRectF:
        """Retorna a área clicável do slider (incluindo margem do thumb)."""
        return QRectF(
            self.x_start - self.THUMB_OUTER_R,
            self.cy - 13.0,
            (self.x_end - self.x_start) + self.THUMB_OUTER_R * 2.0,
            26.0,
        )

    def contains(self, pt: QPointF) -> bool:
        return self.hit_rect().contains(pt)

    def value_from_x(self, x: float) -> int:
        width = max(1.0, self.x_end - self.x_start)
        t = max(0.0, min(1.0, (x - self.x_start) / width))
        return int(round(t * 100.0))

    def draw(self, p: QPainter):
        tx = self.thumb_x()
        track_top = self.cy - self.TRACK_H * 0.5

        # 1. Trilho inativo (direita)
        if tx < self.x_end:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.track_inactive)
            p.drawRoundedRect(
                QRectF(tx, track_top, self.x_end - tx, self.TRACK_H),
                self.TRACK_RADIUS,
                self.TRACK_RADIUS,
            )

        # 2. Trilho ativo (esquerda)
        if tx > self.x_start:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.COLOR_TRACK_MUTED if self.is_muted else self.track_active)
            p.drawRoundedRect(
                QRectF(self.x_start, track_top, tx - self.x_start, self.TRACK_H),
                self.TRACK_RADIUS,
                self.TRACK_RADIUS,
            )

        # 3. Thumb externo (#454545, raio 10px)
        center = QPointF(tx, self.cy)
        p.setPen(QPen(self.thumb_border, 1.0))
        p.setBrush(self.thumb_outer)
        p.drawEllipse(center, self.THUMB_OUTER_R, self.THUMB_OUTER_R)

        # 4. Thumb interno (#4db2ff, raio animado ~5px)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.COLOR_TRACK_MUTED if self.is_muted else self.thumb_inner)
        p.drawEllipse(center, self._inner_r, self._inner_r)
