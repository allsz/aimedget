"""
Gera ícones nativos para a aplicação (Janela, Barra de Tarefas e System Tray)
utilizando o asset oficial sem fundo (transparente) aimedget_icon_clean.svg.
Suporta múltiplas resoluções nítidas para qualquer escala de DPI do Windows.
"""

import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.core.paths import APP_ICON_CLEAN_SVG, APP_ICON_ICO, APP_ICON_PNG

_cached_icon: QIcon | None = None


def create_aimedget_icon(size: int = 64) -> QIcon:
    """
    Retorna o QIcon oficial do Aimedget (sem fundo / transparente).
    Renderiza o SVG oficial em múltiplas resoluções (16, 20, 24, 32, 40, 48, 64, 128, 256)
    para nitidez perfeita em qualquer escala de DPI do Windows.
    """
    global _cached_icon
    if _cached_icon is not None and not _cached_icon.isNull():
        return _cached_icon

    icon = QIcon()

    if os.path.exists(APP_ICON_CLEAN_SVG):
        renderer = QSvgRenderer(APP_ICON_CLEAN_SVG)
        if renderer.isValid():
            for s in [16, 20, 24, 32, 40, 48, 64, 128, 256]:
                pm = QPixmap(s, s)
                pm.fill(Qt.GlobalColor.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                renderer.render(p)
                p.end()
                icon.addPixmap(pm)

            _cached_icon = icon
            return icon

    # Fallbacks caso o SVG não esteja disponível
    if os.path.exists(APP_ICON_ICO):
        _cached_icon = QIcon(APP_ICON_ICO)
        return _cached_icon

    if os.path.exists(APP_ICON_PNG):
        _cached_icon = QIcon(APP_ICON_PNG)
        return _cached_icon

    return icon


def create_aimedget_clean_icon(size: int = 64) -> QIcon:
    """Alias para o ícone padrão transparente."""
    return create_aimedget_icon(size)
