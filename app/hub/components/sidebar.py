"""
HubSidebar - Barra de navegação lateral com design Notion/Linear.
Tipografia Inter coesa, pesos moderados (Medium 500 / SemiBold 600) e badges sutis.
"""

from typing import List, Tuple
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.i18n import t
from app.hub.theme import HubTheme, THEME_LIGHT


class NavItemButton(QPushButton):
    """Botão de navegação lateral minimalista estilo Notion."""

    def __init__(self, key: str, label: str, count: int = 0, parent=None):
        super().__init__(parent)
        self.key = key
        self.label_text = label
        self.count = count

        self.setProperty("class", "NavButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(6)

        self.lbl_title = QLabel(label, self)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.lbl_title)

        layout.addStretch()

        self.badge = QLabel(str(count) if count > 0 else "", self)
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedSize(18, 16)
        self.badge.setVisible(count > 0)
        layout.addWidget(self.badge)

    def set_active(self, active: bool, theme: HubTheme):
        self.setProperty("active", "true" if active else "false")
        if active:
            self.lbl_title.setStyleSheet(f"color: {theme.text}; font-size: 13.5px; font-weight: 600;")
            self.badge.setStyleSheet(
                f"background-color: {theme.accent}; color: {theme.ink}; border-radius: 4px; font-size: 10.5px; font-weight: 600;"
            )
        else:
            self.lbl_title.setStyleSheet(f"color: {theme.mute}; font-size: 13.5px; font-weight: 400;")
            self.badge.setStyleSheet(
                f"background-color: {theme.panel2}; color: {theme.mute}; border-radius: 4px; font-size: 10.5px; font-weight: 500;"
            )
        self.style().unpolish(self)
        self.style().polish(self)

    def update_count(self, count: int):
        self.count = count
        self.badge.setText(str(count) if count > 0 else "")
        self.badge.setVisible(count > 0)


class HubSidebar(QWidget):
    page_changed = Signal(str)

    NAV_ITEMS: List[Tuple[str, str]] = [
        ("ov", "sidebar_overview"),
        ("music", "sidebar_music"),
        ("keys", "sidebar_keys"),
        ("vol", "sidebar_volume"),
        ("timer", "sidebar_timer"),
        ("gen", "sidebar_general"),
    ]

    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self.setObjectName("HubSidebar")
        self.setFixedWidth(200)
        self._theme = theme
        self._buttons: dict[str, NavItemButton] = {}
        self._current_page = "ov"

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 18, 10, 16)
        layout.setSpacing(2)

        # Brand Title limpo e refinado
        brand = QLabel("Aimedget", self)
        brand.setObjectName("HubBrand")
        layout.addWidget(brand)

        # Lista de itens
        for key, i18n_key in self.NAV_ITEMS:
            btn = NavItemButton(key, t(i18n_key), count=0, parent=self)
            btn.clicked.connect(lambda checked=False, k=key: self.select_page(k))
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch()

        self.select_page("ov", emit_signal=False)

    def retranslate_ui(self):
        for key, i18n_key in self.NAV_ITEMS:
            if key in self._buttons:
                self._buttons[key].lbl_title.setText(t(i18n_key))

    def select_page(self, key: str, emit_signal: bool = True):
        if key not in self._buttons:
            return
        self._current_page = key
        for k, btn in self._buttons.items():
            btn.set_active(k == key, self._theme)

        if emit_signal:
            self.page_changed.emit(key)

    def set_badge_count(self, key: str, count: int):
        if key in self._buttons:
            self._buttons[key].update_count(count)

    def update_theme(self, theme: HubTheme):
        self._theme = theme
        for k, btn in self._buttons.items():
            btn.set_active(k == self._current_page, self._theme)
