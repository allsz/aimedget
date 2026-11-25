"""
Renderizador vetorial compartilhado de matriz de pontos circular (estilo Nothing OS / NDot).

Usado pelas skins "Nothing Dot" dos widgets de Clima e Desempenho:
- Fonte 5x7 em círculos antisserrilhados (nítida em qualquer DPI/escala, sem depender de arquivos de fonte).
- Ícones climáticos 9x9 em matriz de pontos para todas as condições suportadas pelo Weather Widget.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter

NOTHING_BG = QColor("#161616")
NOTHING_RED = QColor("#D71921")
NOTHING_RAIN_BLUE = QColor("#60A5FA")
NOTHING_BOLT_AMBER = QColor("#FBBF24")

GLYPHS: dict[str, tuple[str, ...]] = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    "3": ("01110", "10001", "00001", "00110", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("01110", "10000", "11110", "10001", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "%": ("11001", "11010", "00100", "00100", "01011", "10011", "00000"),
    "°": ("01100", "10010", "01100", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "11110", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    ".": ("000", "000", "000", "000", "000", "010", "010"),
    ":": ("000", "010", "010", "000", "010", "010", "000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10001", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01110", "10001", "10000", "01110", "00001", "10001", "01110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10001", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    " ": ("000", "000", "000", "000", "000", "000", "000"),
}


def measure_dot_text(text: str, dot_r: float = 1.3, gap: float = 3.0) -> tuple[float, float]:
    """Largura e altura em px lógicos de `text` na fonte de matriz de pontos."""
    chars = (text or "").upper()
    if not chars:
        return 0.0, 0.0
    char_gap = gap * 1.45
    total_w = 0.0
    for idx, ch in enumerate(chars):
        g = GLYPHS.get(ch, GLYPHS[" "])
        total_w += (len(g[0]) - 1) * gap + 2.0 * dot_r
        if idx < len(chars) - 1:
            total_w += char_gap
    total_h = 6.0 * gap + 2.0 * dot_r
    return total_w, total_h


def draw_dot_text(
    p: QPainter,
    text: str,
    rect: QRectF,
    dot_r: float = 1.3,
    gap: float = 3.0,
    color: QColor | None = None,
    align: str = "left",
    red_degree: bool = False,
) -> float:
    """Desenha `text` centralizado verticalmente em `rect`. Retorna a largura desenhada."""
    chars = (text or "").upper()
    if not chars:
        return 0.0
    base_color = QColor(color) if color is not None else QColor(255, 255, 255)
    total_w, total_h = measure_dot_text(chars, dot_r, gap)
    if align == "right":
        x = rect.right() - total_w
    elif align == "center":
        x = rect.x() + (rect.width() - total_w) * 0.5
    else:
        x = rect.x()
    y0 = rect.y() + (rect.height() - total_h) * 0.5

    char_gap = gap * 1.45
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for ch in chars:
        g = GLYPHS.get(ch, GLYPHS[" "])
        if red_degree and ch == "°":
            c = QColor(NOTHING_RED)
            c.setAlpha(base_color.alpha())
        else:
            c = base_color
        p.setBrush(c)
        for r_idx, row in enumerate(g):
            cy = y0 + r_idx * gap + dot_r
            for c_idx, cell in enumerate(row):
                if cell == "1":
                    cx = x + c_idx * gap + dot_r
                    p.drawEllipse(QPointF(cx, cy), dot_r, dot_r)
        x += (len(g[0]) - 1) * gap + 2.0 * dot_r + char_gap
    p.restore()
    return total_w


# Ícones climáticos 9x9 em matriz de pontos circular
_DOT_ICONS: dict[str, tuple[str, ...]] = {
    "sunny": (
        "000010000",
        "010000010",
        "000111000",
        "001111100",
        "101111101",
        "001111100",
        "000111000",
        "010000010",
        "000010000",
    ),
    "clear_night": (
        "000111000",
        "001110000",
        "011100000",
        "011100000",
        "011100000",
        "011110010",
        "001111100",
        "000111000",
        "000000000",
    ),
    "partly_cloudy": (
        "000001000",
        "000100010",
        "000011100",
        "001111110",
        "011111100",
        "111111110",
        "111111110",
        "011111100",
        "000000000",
    ),
    "cloudy": (
        "000000000",
        "000111000",
        "001111100",
        "011111110",
        "111111111",
        "111111111",
        "011111110",
        "000000000",
        "000000000",
    ),
    "fog": (
        "000000000",
        "011111100",
        "000000000",
        "111111110",
        "000000000",
        "001111111",
        "000000000",
        "011111100",
        "000000000",
    ),
    "rain": (
        "000111000",
        "001111100",
        "011111110",
        "111111111",
        "011111110",
        "000000000",
        "010010010",
        "001001000",
        "010010010",
    ),
    "thunderstorm": (
        "000111000",
        "001111100",
        "011111110",
        "111111111",
        "011111110",
        "000011000",
        "000110000",
        "000011000",
        "000100000",
    ),
    "snow": (
        "000111000",
        "001111100",
        "011111110",
        "111111111",
        "011111110",
        "000000000",
        "010001010",
        "000100000",
        "001000100",
    ),
}


def _icon_key(condition: str) -> str:
    c = (condition or "").lower()
    if "thunder" in c:
        return "thunderstorm"
    if "snow" in c:
        return "snow"
    if "rain" in c:
        return "rain"
    if "fog" in c:
        return "fog"
    if "partly" in c:
        return "partly_cloudy"
    if "cloud" in c:
        return "cloudy"
    if "night" in c:
        return "clear_night"
    return "sunny"


def draw_dot_weather_icon(
    p: QPainter,
    condition: str,
    rect: QRectF,
    opacity: float = 1.0,
    color: QColor | None = None,
) -> None:
    """Desenha ícone climático 9x9 em pontos circulares dentro de `rect`. `color`: pontos neutros (padrão branco; no
    tema "Aimedget" claro, o texto escuro do app). Chuva e raio mantêm o azul e o âmbar."""
    key = _icon_key(condition)
    grid = _DOT_ICONS[key]
    size = min(rect.width(), rect.height())
    ox = rect.x() + (rect.width() - size) * 0.5
    oy = rect.y() + (rect.height() - size) * 0.5
    step = size / 9.0
    r = step * 0.34
    alpha = max(0.0, min(1.0, opacity))

    white = QColor(color) if color is not None else QColor(255, 255, 255)
    white.setAlphaF(alpha)
    rain_blue = QColor(NOTHING_RAIN_BLUE)
    rain_blue.setAlphaF(alpha)
    bolt = QColor(NOTHING_BOLT_AMBER)
    bolt.setAlphaF(alpha)

    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for row_i, row in enumerate(grid):
        cy = oy + row_i * step + step * 0.5
        for col_i, cell in enumerate(row):
            if cell != "1":
                continue
            if key == "rain" and row_i >= 6:
                p.setBrush(rain_blue)
            elif key == "thunderstorm" and row_i >= 5:
                p.setBrush(bolt)
            else:
                p.setBrush(white)
            cx = ox + col_i * step + step * 0.5
            p.drawEllipse(QPointF(cx, cy), r, r)
    p.restore()
