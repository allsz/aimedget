"""
PillSwitch (Toggle Switch no formato pílula estilo iOS/Fluent/Mockup Hub).
Componente tátil com animação suave (QVariantAnimation) do thumb deslizando de um lado para o outro.
"""

from PySide6.QtCore import Property, QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractButton

from app.hub.theme import HubTheme, THEME_LIGHT


class PillSwitch(QAbstractButton):
    toggled_value = Signal(bool)

    def __init__(
        self,
        checked: bool = False,
        theme: HubTheme = THEME_LIGHT,
        compact: bool = False,
        before_toggle=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._theme = theme
        self._compact = compact
        self._before_toggle = before_toggle

        if self._compact:
            self.setFixedSize(30, 18)
        else:
            self.setFixedSize(44, 26)

        # Posição do thumb de 0.0 (desligado/esquerda) a 1.0 (ligado/direita)
        self._thumb_position: float = 1.0 if checked else 0.0

        # Animação suave e fluida
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(130 if compact else 160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_val_changed)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self) -> QSize:
        return QSize(30, 18) if self._compact else QSize(44, 26)

    def minimumSizeHint(self) -> QSize:
        return QSize(30, 18) if self._compact else QSize(44, 26)

    def is_checked(self) -> bool:
        return self.isChecked()

    def set_checked(self, checked: bool, animated: bool = True):
        if not animated:
            self._anim.stop()
            self._thumb_position = 1.0 if checked else 0.0
            self.setChecked(checked)
            self.update()
        else:
            self.setChecked(checked)

    def set_before_toggle(self, callback):
        self._before_toggle = callback

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            target_checked = not self.isChecked()
            if self._before_toggle is not None:
                if not self._before_toggle(target_checked):
                    event.accept()
                    return
        super().mousePressEvent(event)

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    def _on_anim_val_changed(self, value):
        self._thumb_position = float(value)
        self.update()

    def _on_toggled(self, checked: bool):
        start_val = self._thumb_position
        end_val = 1.0 if checked else 0.0

        self._anim.stop()
        self._anim.setStartValue(start_val)
        self._anim.setEndValue(end_val)
        self._anim.start()

        self.toggled_value.emit(checked)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        radius = h / 2.0

        # Interpolação suave de cor de fundo entre a linha (inativo) e o accent (ativo)
        off_color = QColor(self._theme.line)
        on_color = QColor(self._theme.accent)

        r = off_color.red() + (on_color.red() - off_color.red()) * self._thumb_position
        g = off_color.green() + (on_color.green() - off_color.green()) * self._thumb_position
        b = off_color.blue() + (on_color.blue() - off_color.blue()) * self._thumb_position
        track_color = QColor(int(r), int(g), int(b))

        # Trilha em cápsula
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        # Thumb circular com sombra
        pad = 2.0 if self._compact else 3.0
        thumb_diameter = h - (pad * 2.0)
        min_x = pad
        max_x = w - pad - thumb_diameter
        current_x = min_x + (max_x - min_x) * self._thumb_position

        # Sombra sutil sob o thumb
        shadow_rect = QRectF(current_x, pad + 0.5, thumb_diameter, thumb_diameter)
        painter.setBrush(QBrush(QColor(0, 0, 0, 35)))
        painter.drawEllipse(shadow_rect)

        # Círculo branco puro
        thumb_rect = QRectF(current_x, pad, thumb_diameter, thumb_diameter)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(thumb_rect)
