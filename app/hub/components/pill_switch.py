"""
PillSwitch (Toggle Switch no formato pílula estilo iOS/Fluent/Mockup Hub).
Movimento do "Toggle switch" de https://designbookmark.com/motion#db-toggle-switch: cada chave tem uma mola de posição
(320/18) e uma de esticar (300/20). Ao virar, a de esticar leva um chute (v=60) e o botão cresce na direção do destino;
a posição chega com um quique pequeno e o botão volta a ficar redondo, enquanto a trilha enche com a cor de destaque.
Com os efeitos de animação do Windows desligados, a troca acontece na hora.
"""

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractButton
from app.core.refresh_rate import FRAME_MS, refresh_interval_ms

from app.core.widget_animator import animations_enabled
from app.hub.components.city_list import Spring
from app.hub.theme import HubTheme, THEME_LIGHT
from app.core.frame_clock import FrameTimer


POSITION = (320.0, 18.0)     # onde o botão está (0 desligado, 1 ligado; passa um pouco de 1 ao chegar)
STRETCH = (300.0, 20.0)      # quanto o botão está esticado (chutada ao virar)
STRETCH_KICK = 60.0
STRETCH_MAX = 10.0 / 32.0    # crescimento máximo, em fração da altura (10px numa chave de 32px)

SUBSTEPS = 4


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

        self._pos = Spring(self._thumb_position, POSITION)
        self._stretch = Spring(0.0, STRETCH)
        self._last = 0.0
        self._timer = FrameTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

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
            self._snap(checked)
            self.blockSignals(True)
            self.setChecked(checked)
            self.blockSignals(False)
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

    def _snap(self, checked: bool):
        self._timer.stop()
        self._thumb_position = 1.0 if checked else 0.0
        self._pos.x = self._pos.t = self._thumb_position
        self._pos.v = 0.0
        self._stretch.x = self._stretch.t = self._stretch.v = 0.0

    def _on_toggled(self, checked: bool):
        if animations_enabled():
            self._pos.t = 1.0 if checked else 0.0
            self._stretch.t = 0.0
            self._stretch.v = STRETCH_KICK
            self._last = time.monotonic()
            self._timer.setInterval(refresh_interval_ms(self))
            self._timer.start()
        else:
            self._snap(checked)
            self.update()
        self.toggled_value.emit(checked)

    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last, 1 / 30) / SUBSTEPS
        self._last = now
        for _ in range(SUBSTEPS):
            self._pos.step(dt)
            self._stretch.step(dt)
        self._thumb_position = self._pos.x
        if self._pos.settled() and self._stretch.settled():
            self._snap(self.isChecked())
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        radius = h / 2.0

        p = min(max(self._thumb_position, 0.0), 1.0)
        off_color = QColor(self._theme.line)
        on_color = QColor(self._theme.accent)
        track_color = QColor(
            int(off_color.red() + (on_color.red() - off_color.red()) * p),
            int(off_color.green() + (on_color.green() - off_color.green()) * p),
            int(off_color.blue() + (on_color.blue() - off_color.blue()) * p),
        )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        pad = 2.0 if self._compact else 3.0
        d = h - (pad * 2.0)
        travel = w - pad * 2.0 - d
        # o botão cresce enquanto viaja; a ponta da frente puxa (ao ligar, a direita; ao desligar, a esquerda)
        grow = min(max(self._stretch.x, 0.0), 1.0) * STRETCH_MAX * h
        x = pad + travel * self._thumb_position
        if self.isChecked():
            x -= grow * p
        width = d + grow

        painter.setBrush(QBrush(QColor(0, 0, 0, 35)))
        painter.drawRoundedRect(QRectF(x, pad + 0.5, width, d), d / 2.0, d / 2.0)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawRoundedRect(QRectF(x, pad, width, d), d / 2.0, d / 2.0)
