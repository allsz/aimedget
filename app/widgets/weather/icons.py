"""
Ícones de traço do Weather Widget.

Sol, nuvem, raio e lua são os Heroicons (outline) da referência: Copyright (c) Tailwind Labs, Inc., licença MIT
(https://github.com/tailwindlabs/heroicons/blob/master/LICENSE). Parcialmente nublado e neblina são composições
deles. Cada ícone vira um QPixmap pintado na cor pedida e guardado em cache (por tamanho, cor, traço e DPR), então
girar o sol ou mover a nuvem quadro a quadro só desenha um pixmap pronto.
"""

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

SUN = ("M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 18.75V21m-4.773-4.227-1.591 "
       "1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0Z")
CLOUD = ("M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 "
         "0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z")
BOLT = "m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z"
MOON = ("M21.752 15.002A9.718 9.718 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 "
        "9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z")
FOG_LINES = "M4.5 18.25h15M7.5 21.5h9"


@dataclass(frozen=True)
class Layer:
    path: str
    warm: bool = False        # usa a cor quente (sol/raio) em vez da cor do texto
    transform: str = ""       # transform SVG dentro da grade 24x24
    scale: float = 1.0        # escala do transform (o traço é compensado para ficar com a mesma espessura)
    knockout: bool = False    # apaga o que está embaixo no formato desta camada (a nuvem "na frente" do sol)


ICONS: dict[str, tuple] = {
    "sun": (Layer(SUN, warm=True),),
    "moon": (Layer(MOON),),
    "cloud": (Layer(CLOUD),),
    "rain": (Layer(CLOUD),),     # as gotas são animadas à parte (card_painter)
    "snow": (Layer(CLOUD),),     # os flocos também
    "bolt": (Layer(BOLT, warm=True),),
    "partly": (
        Layer(SUN, warm=True, transform="translate(10.2 -0.6) scale(0.6)", scale=0.6),
        Layer(CLOUD, transform="translate(0 4.2) scale(0.82)", scale=0.82, knockout=True),
    ),
    "fog": (
        Layer(CLOUD, transform="translate(2.4 -1.6) scale(0.8)", scale=0.8),
        Layer(FOG_LINES),
    ),
}

# Onde as gotas/flocos animados saem, na grade 24x24 do ícone (logo abaixo da nuvem)
DROPS_TOP_UNITS = 19.0
DROPS_WIDTH_UNITS = 12.0

_cache: dict = {}
_CACHE_MAX = 96


def _svg(layer: Layer, color: str, stroke: float, fill: bool) -> bytes:
    width = stroke / layer.scale
    paint = f'fill="{color}" stroke="{color}"' if fill else f'fill="none" stroke="{color}"'
    body = f'<path d="{layer.path}"/>'
    if layer.transform:
        body = f'<g transform="{layer.transform}">{body}</g>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" {paint} '
            f'stroke-width="{width:.3f}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def icon_pixmap(key: str, size_px: float, color: QColor, warm: QColor, stroke: float, dpr: float = 1.0) -> QPixmap:
    """Pixmap transparente (size_px lógicos) com o ícone `key` desenhado nas cores dadas."""
    cache_key = (key, round(size_px, 1), color.rgba(), warm.rgba(), round(stroke, 2), round(dpr, 2))
    pm = _cache.get(cache_key)
    if pm is not None:
        return pm

    side = max(1, int(round(size_px * dpr)))
    pm = QPixmap(side, side)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    target = QRectF(0, 0, side, side)
    for layer in ICONS.get(key, ICONS["cloud"]):
        if layer.knockout:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            QSvgRenderer(QByteArray(_svg(layer, "#000000", stroke * 1.9, fill=True))).render(p, target)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        tint = warm if layer.warm else color
        # Só a cor (sem alfa): a opacidade é aplicada por quem desenha (setOpacity)
        QSvgRenderer(QByteArray(_svg(layer, tint.name(), stroke, fill=False))).render(p, target)
    p.end()
    pm.setDevicePixelRatio(dpr)

    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[cache_key] = pm
    return pm
