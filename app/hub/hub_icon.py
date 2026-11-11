"""
Gera ícones nativos para a aplicação (Janela, Barra de Tarefas e System Tray)
utilizando o asset oficial sem fundo (transparente) aimedget_icon_clean.svg.
Suporta múltiplas resoluções nítidas para qualquer escala de DPI do Windows.
"""

import colorsys
import os
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.core.paths import APP_ICON_CLEAN_SVG, APP_ICON_ICO, APP_ICON_PNG

BRAND_FILL = "#FFA13D"   # única cor do SVG oficial; é ela que acompanha a cor de destaque escolhida
_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

_cached_icon: QIcon | None = None
_hue_loaded = False
_accent = None   # None = âmbar oficial; int = matiz; str = '#RRGGBB'


def _current_accent():
    global _hue_loaded, _accent
    if not _hue_loaded:
        from app.core.config_manager import config_manager
        _accent = config_manager.get_hub_accent()
        _hue_loaded = True
    return _accent


def set_icon_accent(accent) -> None:
    """Define a cor do ícone (None = âmbar oficial, int = matiz, str = '#RRGGBB') e descarta o cache;
    quem usa o ícone deve pedi-lo de novo."""
    global _cached_icon, _hue_loaded, _accent
    _hue_loaded = True
    if accent == _accent and _cached_icon is not None:
        return
    _accent = accent
    _cached_icon = None


def _tinted_svg(accent) -> QByteArray | None:
    """SVG oficial com a cor trocada: matiz escolhido (mesma saturação e brilho do âmbar) ou a cor exata."""
    with open(APP_ICON_CLEAN_SVG, "r", encoding="utf-8") as fh:
        svg = fh.read()
    if isinstance(accent, str):
        svg = svg.replace(BRAND_FILL, accent)
    elif accent is not None:
        r, g, b = colorsys.hsv_to_rgb((accent % 360) / 360.0, 0.76, 1.0)
        svg = svg.replace(BRAND_FILL, "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255)))
    return QByteArray(svg.encode("utf-8"))


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
        renderer = QSvgRenderer(_tinted_svg(_current_accent()))
        if renderer.isValid():
            for s in _ICON_SIZES:
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
