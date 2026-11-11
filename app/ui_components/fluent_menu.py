"""
Menu de contexto com design system unificado (Fluent / Notion / Linear):
- Herda as cores globais de tema do Hub (Claro, Escuro, True Dark ou Sistema).
- Trailing check (indicador de seleção com checkmark vetorial à direita) idêntico ao menu do Timer.
- Tipografia Inter refinada com métricas de toque confortáveis.
"""

import os
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu

from app.core.config_manager import config_manager
from app.core.paths import ASSETS_DIR
from app.core.typography import get_ui_font
from app.hub.theme import HubTheme, resolve_theme


def get_fluent_menu_stylesheet(theme: HubTheme) -> str:
    """
    Gera a folha de estilo QSS para menus de contexto baseado no tema ativo do Hub.
    Compatível com Claro, Escuro, True Dark e Sistema, padronizado com o menu de contexto do Timer.
    """
    t = theme
    bg = t.menu_bg            # Claro #FFFFFF · Escuro #202020 · True Dark #000000
    text_color = t.text
    border_color = t.line     # Borda fina do Hub (True Dark: #232323)
    selected_bg = t.hover
    sub_text = t.mute
    sep_color = t.line
    suffix = "" if t.is_dark else "-dark"
    arrow_icon_path = os.path.join(ASSETS_DIR, "icons", f"menu-arrow-right{suffix}.svg").replace("\\", "/")
    check_icon_path = os.path.join(ASSETS_DIR, "icons", f"menu-check{suffix}.svg").replace("\\", "/")

    return f"""
        QMenu {{
            background-color: {bg};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 10px;
            padding: 8px 10px;
        }}
        QMenu::item {{
            padding: 7px 34px 7px 14px;
            border-radius: 6px;
            color: {text_color};
        }}
        QMenu::item:selected {{
            background-color: {selected_bg};
        }}
        QMenu::item:disabled {{
            color: {sub_text};
        }}
        QMenu::icon {{
            padding-left: 6px;
            margin-right: 12px;
        }}
        QMenu::separator {{
            height: 1px;
            background: {sep_color};
            margin: 6px 8px;
        }}
        QMenu::right-arrow {{
            image: url("{arrow_icon_path}");
            width: 9px;
            height: 9px;
            padding-right: 8px;
        }}
        QMenu::indicator {{
            width: 12px;
            height: 12px;
            padding-left: 4px;
        }}
        QMenu::indicator:checked {{
            image: url("{check_icon_path}");
        }}
    """


class FluentMusicMenu(QMenu):
    """
    Menu de contexto unificado que herda automaticamente o tema ativo do Hub.
    Padronizado com o menu de contexto do Timer Widget, suportando
    marcação trailing check (checkmark vetorial idêntico ao Timer) e ícones ricos.
    """

    def __init__(self, title_or_parent=None, parent=None, theme: Optional[HubTheme] = None):
        if isinstance(title_or_parent, str):
            super().__init__(title_or_parent, parent)
        else:
            super().__init__(title_or_parent)

        self._trailing_checked_actions = set()

        if theme is not None:
            self._theme = theme
        elif parent is not None and hasattr(parent, "_theme"):
            self._theme = parent._theme
        else:
            pref = config_manager.get_hub_theme("system")
            self._theme = resolve_theme(pref)

        self._apply_style()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._apply_style()

    def _apply_style(self):
        self.setFont(get_ui_font(13))
        self.setStyleSheet(get_fluent_menu_stylesheet(self._theme))

    def set_trailing_check(self, action: QAction, is_checked: bool):
        if is_checked:
            self._trailing_checked_actions.add(action)
        else:
            self._trailing_checked_actions.discard(action)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._trailing_checked_actions:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_dark = not self._theme or self._theme.is_dark
        check_color = QColor(255, 255, 255, 240) if is_dark else QColor(31, 30, 29, 230)

        for action in self._trailing_checked_actions:
            if not action.isVisible():
                continue
            rect = self.actionGeometry(action)
            if rect.isEmpty():
                continue

            check_size = 16
            chk_x = rect.right() - 24
            chk_y = rect.top() + (rect.height() - check_size) // 2

            path = QPainterPath()
            path.moveTo(chk_x + 3.5, chk_y + 8.5)
            path.lineTo(chk_x + 6.5, chk_y + 11.5)
            path.lineTo(chk_x + 12.5, chk_y + 4.5)

            pen = QPen(
                check_color,
                1.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        p.end()

