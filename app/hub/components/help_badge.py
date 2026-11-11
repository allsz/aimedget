"""
HelpBadge: um "?" pequeno e discreto que guarda uma explicação longa sem ocupar espaço na página.
A mensagem aparece ao passar o mouse (tooltip) e também ao clicar (para quem não espera o hover ou usa toque).
O visual do balão vem do QToolTip do tema do Hub (ver app/hub/theme.py).
"""

import html

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QToolTip

from app.hub.theme import HubTheme, THEME_LIGHT


class HelpBadge(QAbstractButton):
    SIZE = 16

    def __init__(self, text: str = "", theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._text = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.clicked.connect(self.show_message)
        self.set_text(text)

    def set_text(self, text: str):
        self._text = text
        # Texto rico: o Qt quebra as linhas do balão em vez de abrir uma faixa larga na tela
        self.setToolTip(f"<p>{html.escape(text)}</p>" if text else "")
        self.setAccessibleName("?")
        self.setAccessibleDescription(text)

    def text_message(self) -> str:
        return self._text

    def show_message(self):
        if self._text:
            QToolTip.showText(self.mapToGlobal(QPoint(0, self.height() + 4)), self.toolTip(), self)

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.underMouse() or self.hasFocus()
        color = QColor(self._theme.accent if active else self._theme.mute)
        p.setPen(QPen(color, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(0.6, 0.6, self.SIZE - 1.2, self.SIZE - 1.2))
        f = QFont(self.font())
        f.setPixelSize(10)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "?")
