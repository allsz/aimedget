"""
HueSlider - seletor de matiz para a cor de destaque do app.

A trilha mostra as cores que o tema realmente vai usar (derivadas por `derive_accent` para o modo claro/escuro
atual), então o que o usuário vê na trilha é o que ele recebe. O botão deslizante leva a cor escolhida.

- `hueChanged(int)`: a cada movimento (aplicar ao vivo)
- `hueCommitted(int)`: ao soltar o botão do mouse ou ao terminar um ajuste pelo teclado
- Teclado: setas ±1°, Shift+setas ±10°, Home/End; foco visível por anel.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.hub.theme import HubTheme, THEME_DARK, derive_accent

TRACK_H = 10.0
KNOB_R = 10.0
MARGIN = KNOB_R + 2.0   # folga lateral para o anel de foco não ser cortado
STEPS = 36   # paradas do gradiente (a cada 10°)


class HueSlider(QWidget):
    hueChanged = Signal(int)
    hueCommitted = Signal(int)

    def __init__(self, hue: int = 33, theme: HubTheme = THEME_DARK, parent: QWidget | None = None):
        super().__init__(parent)
        self._hue = int(hue) % 360
        self._theme = theme
        self._dragging = False
        self.setFixedHeight(int(KNOB_R * 2 + 8))
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- API ---

    def hue(self) -> int:
        return self._hue

    def set_hue(self, hue: int):
        """Move o botão sem emitir sinais (uso programático, ex.: restaurar o padrão)."""
        hue = max(0, min(359, int(hue)))
        if hue != self._hue:
            self._hue = hue
            self.update()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    # --- Geometria ---

    def _track_rect(self) -> QRectF:
        return QRectF(MARGIN, (self.height() - TRACK_H) / 2.0, self.width() - 2 * MARGIN, TRACK_H)

    def _hue_at(self, x: float) -> int:
        track = self._track_rect()
        ratio = (x - track.left()) / max(1.0, track.width())
        return max(0, min(359, int(round(ratio * 359))))

    def _knob_x(self) -> float:
        track = self._track_rect()
        return track.left() + track.width() * (self._hue / 359.0)

    # --- Entrada ---

    def _move_to(self, x: float):
        hue = self._hue_at(x)
        if hue != self._hue:
            self._hue = hue
            self.update()
            self.hueChanged.emit(hue)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._move_to(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._move_to(event.position().x())

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.hueCommitted.emit(self._hue)

    def keyPressEvent(self, event):
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            new = self._hue - step
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            new = self._hue + step
        elif key == Qt.Key.Key_Home:
            new = 0
        elif key == Qt.Key.Key_End:
            new = 359
        else:
            super().keyPressEvent(event)
            return
        new = max(0, min(359, new))
        if new != self._hue:
            self._hue = new
            self.update()
            self.hueChanged.emit(new)
            self.hueCommitted.emit(new)

    # --- Desenho ---

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing)
        track = self._track_rect()
        is_dark = self._theme.is_dark

        grad = QLinearGradient(track.left(), 0, track.right(), 0)
        for i in range(STEPS + 1):
            hue = min(359, round(i * 359 / STEPS))
            grad.setColorAt(i / STEPS, QColor(derive_accent(hue, is_dark)[0]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(track, TRACK_H / 2, TRACK_H / 2)

        # Botão: anel na cor do painel (separa da trilha) + miolo na cor escolhida
        center = QPointF(self._knob_x(), self.height() / 2.0)
        picked = QColor(derive_accent(self._hue, is_dark)[0])
        p.setBrush(QColor(self._theme.panel))
        p.setPen(QPen(QColor(self._theme.line), 1.0))
        p.drawEllipse(center, KNOB_R - 0.5, KNOB_R - 0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(picked)
        p.drawEllipse(center, KNOB_R - 4.0, KNOB_R - 4.0)

        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(self._theme.text), 1.5))
            p.drawEllipse(center, KNOB_R + 1.5, KNOB_R + 1.5)
        p.end()
