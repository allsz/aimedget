"""
Gera ícones nativos para a aplicação (Janela, Barra de Tarefas e System Tray)
utilizando o asset oficial sem fundo (transparente) aimedget_icon_clean.svg.
Suporta múltiplas resoluções nítidas para qualquer escala de DPI do Windows.
"""

import colorsys
import os
import sys
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.core.paths import APP_ICON_CLEAN_SVG, APP_ICON_ICO, APP_ICON_PNG

BRAND_FILL = "#FFA13D"   # única cor do SVG oficial; é ela que acompanha a cor de destaque escolhida
_DEV_BADGE_BG = QColor("#D92B2B")
_DEV_BADGE_BORDER = QColor("#1A1A1A")
_DEV_BADGE_FG = QColor("#FFFFFF")
_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

_cached_icon: QIcon | None = None
_cached_dev: bool | None = None
_hue_loaded = False
_accent = None   # None = âmbar oficial; int = matiz; str = '#RRGGBB'


def is_dev_build() -> bool:
    """True somente quando rodando direto pelo Python (nunca no .exe gerado pelo PyInstaller)."""
    return not getattr(sys, "frozen", False)


def _draw_dev_badge(painter: QPainter, size: int) -> None:
    """Pinta uma etiqueta vermelha 'DEV' no canto inferior direito (somente em desenvolvimento)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    if size < 24:
        # Em 16px/20px (bandeja/título pequeno), texto de 3 letras vira borrão: usa uma pílula vermelha nítida.
        d = max(5.0, size * 0.36)
        rect = QRectF(size - d - 0.5, size - d - 0.5, d, d)
        painter.setPen(QPen(_DEV_BADGE_BORDER, max(0.8, size * 0.05)))
        painter.setBrush(_DEV_BADGE_BG)
        painter.drawRoundedRect(rect, d * 0.45, d * 0.45)
        painter.restore()
        return

    badge_h = max(11.0, size * 0.36)
    badge_w = min(float(size), max(badge_h * 2.1, size * 0.78))
    margin = max(0.5, size * 0.02)
    rect = QRectF(size - badge_w - margin, size - badge_h - margin, badge_w, badge_h)
    radius = badge_h * 0.28

    painter.setPen(QPen(_DEV_BADGE_BORDER, max(1.0, size * 0.03)))
    painter.setBrush(_DEV_BADGE_BG)
    painter.drawRoundedRect(rect, radius, radius)

    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(max(7, round(badge_h * 0.66)))
    painter.setFont(font)
    painter.setPen(_DEV_BADGE_FG)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "DEV")
    painter.restore()


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
    global _cached_icon, _cached_dev, _hue_loaded, _accent
    _hue_loaded = True
    if accent == _accent and _cached_icon is not None and _cached_dev == is_dev_build():
        return
    _accent = accent
    _cached_icon = None
    _cached_dev = None


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


def _draws_something(renderer: QSvgRenderer) -> bool:
    """Um SVG "válido" pode estar vazio (já aconteceu: o arquivo foi regravado sem o desenho). Aí cai no .ico."""
    img = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    renderer.render(p)
    p.end()
    return any(img.pixelColor(x, y).alpha() > 0 for y in range(0, 32, 2) for x in range(0, 32, 2))


def create_aimedget_icon(size: int = 64) -> QIcon:
    """
    Retorna o QIcon oficial do Aimedget (sem fundo / transparente).
    Renderiza o SVG oficial em múltiplas resoluções (16, 20, 24, 32, 40, 48, 64, 128, 256)
    para nitidez perfeita em qualquer escala de DPI do Windows.
    Em desenvolvimento (não congelado pelo PyInstaller), adiciona um selo vermelho 'DEV'.
    """
    global _cached_icon, _cached_dev
    dev = is_dev_build()
    if _cached_icon is not None and not _cached_icon.isNull() and _cached_dev == dev:
        return _cached_icon

    icon = QIcon()

    if os.path.exists(APP_ICON_CLEAN_SVG):
        renderer = QSvgRenderer(_tinted_svg(_current_accent()))
        if renderer.isValid() and _draws_something(renderer):
            for s in _ICON_SIZES:
                pm = QPixmap(s, s)
                pm.fill(Qt.GlobalColor.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                renderer.render(p)
                if dev:
                    _draw_dev_badge(p, s)
                p.end()
                icon.addPixmap(pm)

            _cached_icon = icon
            _cached_dev = dev
            return icon

    # Fallbacks caso o SVG não esteja disponível
    if os.path.exists(APP_ICON_ICO):
        _cached_icon = QIcon(APP_ICON_ICO)
        _cached_dev = dev
        return _cached_icon

    if os.path.exists(APP_ICON_PNG):
        _cached_icon = QIcon(APP_ICON_PNG)
        _cached_dev = dev
        return _cached_icon

    return icon


def create_aimedget_clean_icon(size: int = 64) -> QIcon:
    """Alias para o ícone padrão transparente."""
    return create_aimedget_icon(size)
