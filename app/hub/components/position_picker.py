"""
PositionPicker - Seletor visual de ancoragem de widgets na tela.
Permite posicionar nos cantos e centros: Top-Left (tl), Top-Center (tc), Top-Right (tr),
Bottom-Left (bl), Bottom-Center (bc), Bottom-Right (br).
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QPushButton, QWidget

from app.hub.theme import HubTheme, THEME_LIGHT


class PositionPicker(QWidget):
    position_changed = Signal(str)  # ex: 'br', 'tl', 'bc'

    POSITIONS = [
        ("tl", 0, 0),
        ("tc", 0, 1),
        ("tr", 0, 2),
        ("bl", 1, 0),
        ("bc", 1, 1),
        ("br", 1, 2),
    ]

    def __init__(self, current_pos: str = "br", theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self._current_pos = current_pos
        self._theme = theme
        self._buttons: dict[str, QPushButton] = {}

        self._build_ui()

    def _build_ui(self):
        self.setFixedSize(110, 68)

        # Container com borda simulando uma mini tela de monitor
        layout = QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        for pos_key, row, col in self.POSITIONS:
            btn = QPushButton(self)
            btn.setFixedSize(26, 20)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=pos_key: self.set_position(k))
            self._buttons[pos_key] = btn
            layout.addWidget(btn, row, col)

        self._update_styles()

    def set_position(self, pos_key: str):
        if pos_key not in self._buttons:
            return
        self._current_pos = pos_key
        self._update_styles()
        self.position_changed.emit(pos_key)

    def get_position(self) -> str:
        return self._current_pos

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._update_styles()

    def _update_styles(self):
        # Borda externa do monitor
        self.setStyleSheet(
            f"""
            PositionPicker {{
                background-color: {self._theme.panel2};
                border: 1.5px solid {self._theme.line};
                border-radius: 10px;
            }}
            """
        )

        for k, btn in self._buttons.items():
            is_active = (k == self._current_pos)
            bg = self._theme.accent if is_active else self._theme.line
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {bg};
                    border: none;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    background-color: {self._theme.accent if is_active else self._theme.mute};
                }}
                """
            )
