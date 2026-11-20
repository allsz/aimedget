import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from app.core.widget_animator import animations_enabled
from app.widgets.weather.motion import EASE_OUT


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

    # Mudança de volume vinda de fora (troca de dispositivo, teclas de volume): o botão desliza até o valor novo e o
    # número conta junto. Escolhido no protótipo mockups/volume-device-glide.html: 180 ms, ease-out, duração fixa.
    GLIDE_DURATION_S = 0.180
    GLIDE_CURVE = staticmethod(EASE_OUT)

    def __init__(self, x_start: float = 45.0, x_end: float = 162.0, cy: float = 24.5):
        self.x_start = x_start
        self.x_end = x_end
        self.cy = cy
        self._value = 50          # 0 a 100: o valor de verdade (alvo)
        self._shown = 50.0        # o que está desenhado: igual a _value, ou a caminho dele durante o deslize
        self._glide_from = 50.0
        self._glide_elapsed = 0.0
        self._gliding = False
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
        # Estilo (um tema pode trocar): "fluent" = trilho fino + botão; "bar" = faixa lisa sem botão
        self.style = "fluent"
        self.track_h = self.TRACK_H
        self.slant = 0.0          # só no estilo "bar": pontas inclinadas (fração da altura)
        self.taper = 1.0          # só no estilo "bar": altura da ponta direita / altura da ponta esquerda (cunha)

    def apply_style(self, style: str = "fluent", track_h: float | None = None, slant: float = 0.0,
                    taper: float = 1.0):
        self.style = style
        self.track_h = self.TRACK_H if track_h is None else float(track_h)
        self.slant = float(slant)
        self.taper = float(taper)

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

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, v: int):
        """Valor posto pelo usuário (arrastar, roda) ou sem animação: vai na hora, sem deslize."""
        self._value = int(v)
        self._shown = float(self._value)
        self._gliding = False

    def glide_to(self, v: int):
        """Valor vindo de fora: desliza do que está desenhado até `v` (na hora, sem as animações do Windows)."""
        v = int(v)
        if v == self._value and not self._gliding:
            return
        if not animations_enabled():
            self.value = v
            return
        self._value = v
        self._glide_from = self._shown
        self._glide_elapsed = 0.0
        self._gliding = abs(self._shown - v) > 1e-6

    def is_gliding(self) -> bool:
        return self._gliding

    def display_value(self) -> int:
        """O número a mostrar: conta junto com o botão durante o deslize."""
        return int(round(self._shown))

    def set_geometry(self, x_start: float, x_end: float, cy: float):
        self.x_start = x_start
        self.x_end = x_end
        self.cy = cy

    def step_animation(self, dt: float = 0.016) -> bool:
        """Interpola suavemente o raio do círculo interno do thumb e o deslize do valor, independente da taxa de Hz."""
        gliding = self._step_glide(dt)
        return self._step_thumb(dt) or gliding

    def _step_glide(self, dt: float) -> bool:
        if not self._gliding:
            return False
        self._glide_elapsed += max(0.001, min(0.05, dt))
        t = min(1.0, self._glide_elapsed / self.GLIDE_DURATION_S)
        self._shown = self._glide_from + (self._value - self._glide_from) * self.GLIDE_CURVE(t)
        if t >= 1.0:
            self._shown = float(self._value)
            self._gliding = False
        return True

    def _step_thumb(self, dt: float) -> bool:
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
        t = max(0.0, min(1.0, self._shown / 100.0))
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

    def _draw_bar(self, p: QPainter):
        """Faixa lisa: vazio atrás, preenchido por cima; as pontas (e o corte do preenchido) seguem `slant`."""
        h = self.track_h
        lean = h * self.slant * 0.5      # o topo vai para a direita e a base para a esquerda
        span = max(1.0, self.x_end - self.x_start)

        def half(x: float) -> float:
            """Meia altura da faixa em `x`: cresce (ou encolhe) em linha reta da ponta esquerda para a direita."""
            u = max(0.0, min(1.0, (x - self.x_start) / span))
            return h * 0.5 * (1.0 + (self.taper - 1.0) * u)

        def quad(x1: float, x2: float) -> QPolygonF:
            h1, h2 = half(x1), half(x2)
            return QPolygonF([QPointF(x1 + lean, self.cy - h1), QPointF(x2 + lean, self.cy - h2),
                              QPointF(x2 - lean, self.cy + h2), QPointF(x1 - lean, self.cy + h1)])

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.track_inactive)
        p.drawPolygon(quad(self.x_start, self.x_end))
        tx = self.thumb_x()
        if tx > self.x_start:
            p.setBrush(self.COLOR_TRACK_MUTED if self.is_muted else self.track_active)
            p.drawPolygon(quad(self.x_start, tx))

    def draw(self, p: QPainter):
        if self.style == "bar":
            self._draw_bar(p)
            return
        tx = self.thumb_x()
        track_top = self.cy - self.track_h * 0.5

        # 1. Trilho inativo (direita)
        if tx < self.x_end:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.track_inactive)
            p.drawRoundedRect(
                QRectF(tx, track_top, self.x_end - tx, self.track_h),
                self.TRACK_RADIUS,
                self.TRACK_RADIUS,
            )

        # 2. Trilho ativo (esquerda)
        if tx > self.x_start:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.COLOR_TRACK_MUTED if self.is_muted else self.track_active)
            p.drawRoundedRect(
                QRectF(self.x_start, track_top, tx - self.x_start, self.track_h),
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
