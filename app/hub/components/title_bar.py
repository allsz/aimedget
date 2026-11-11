"""
WindowControlBar - Barra de título integrada estilo 1Password / macOS / Windows 11 Modern.
- Se funde perfeitamente com a cor de fundo da janela (sem a barra preta grossa padrão do Windows).
- Botões de fechar, maximizar/restaurar e minimizar minimalistas com ícones discretos e proporcionais.
- Permite arrastar a janela livremente e maximizar com duplo-clique.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from app.hub.theme import HubTheme, THEME_LIGHT


class TitleBarButton(QAbstractButton):
    """Botão minimalista de controle de janela (Minimizar, Maximizar, Fechar)."""

    def __init__(self, action_type: str, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self.action_type = action_type  # 'min', 'max', 'close'
        self._theme = theme
        self._hovered = False
        self.setFixedSize(38, 30)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0

        # Background no hover
        if self._hovered:
            if self.action_type == "close":
                painter.setBrush(QBrush(QColor("#E81123")))
            else:
                hover_bg = QColor(255, 255, 255, 25) if self._theme.is_dark else QColor(0, 0, 0, 15)
                painter.setBrush(QBrush(hover_bg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(0, 0, w, h)

        # Cor do traço do ícone (ícones pequenos e delicados estilo 1Password)
        if self._hovered and self.action_type == "close":
            icon_color = QColor("#FFFFFF")
        else:
            icon_color = QColor(self._theme.mute)

        painter.setPen(icon_color)

        if self.action_type == "min":
            # Traço horizontal fino (8px)
            painter.drawLine(int(cx - 4.5), int(cy), int(cx + 4.5), int(cy))

        elif self.action_type == "max":
            # Quadrado vazado pequeno (8x8px)
            rect = QRectF(cx - 4, cy - 4, 8, 8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

        elif self.action_type == "close":
            # 'X' fino e elegante (8x8px)
            r = 4.0
            painter.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            painter.drawLine(QPointF(cx + r, cy - r), QPointF(cx - r, cy + r))


class IntegratedTitleBar(QWidget):
    """Barra superior que se integra e mescla com a janela."""

    def __init__(self, target_window: QWidget, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self.target_window = target_window
        self._theme = theme
        self._drag_pos = None

        self.setFixedHeight(34)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(0)

        # Espaço reservado para o título/menu caso queira, ou stretch limpo
        self.lbl_title = QLabel("Aimedget Hub", self)
        self.lbl_title.setStyleSheet(f"color: {self._theme.mute}; font-size: 11.5px; font-weight: 500;")
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.lbl_title)

        layout.addStretch()

        # Botões de controle de janela
        self.btn_min = TitleBarButton("min", theme=self._theme, parent=self)
        self.btn_min.clicked.connect(self.target_window.showMinimized)
        layout.addWidget(self.btn_min)

        self.btn_max = TitleBarButton("max", theme=self._theme, parent=self)
        self.btn_max.clicked.connect(self._toggle_maximize)
        layout.addWidget(self.btn_max)

        self.btn_close = TitleBarButton("close", theme=self._theme, parent=self)
        self.btn_close.clicked.connect(self.target_window.close)
        layout.addWidget(self.btn_close)

    def _toggle_maximize(self):
        if self.target_window.isMaximized():
            self.target_window.showNormal()
        else:
            self.target_window.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.target_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            if not self.target_window.isMaximized():
                self.target_window.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.lbl_title.setStyleSheet(f"color: {self._theme.mute}; font-size: 11.5px; font-weight: 500;")
        self.btn_min.set_theme(theme)
        self.btn_max.set_theme(theme)
        self.btn_close.set_theme(theme)
