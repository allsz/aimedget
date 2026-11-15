"""
Forma própria do Volume e mixer, só com dados do tema (nada de código por tema):

- `tilt`: o card inteiro inclinado (graus). O mouse é convertido de volta, então tudo continua clicável.
- `plates`: placas coloridas ATRÁS do card. Cada placa é um quadrilátero preso aos 4 cantos do card
  (deslocamento em px por canto), então acompanha o card quando a gaveta abre.
- `digits`: o número do volume principal desenhado com uma imagem (folha com 0-9), com "pulo" ao mudar.
- `slider_style: "bar"`: sliders como faixa lisa (sem botão), com altura e pontas inclinadas.

Formato no theme.json:

    "tilt": -6,
    "plates": [{"color": "#e5001c", "corners": [[-7, -16], [31, -20], [4, 23], [-30, 12]]}],
    "digits": {"image": "digitos.png", "height": 40, "x": 2, "y": 5, "spacing": -3, "tilt": [5, -6, 4], "pop": true},
    "slider_style": "bar", "slider_height": 14, "slider_slant": 0.35
"""

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QPolygonF, QTransform

from app.core.theme_art import (
    _is_number, _num, issue_scope, load_pixmap, overflow_margins, parse_color, presample, report_issue,
)

TILT_RANGE = (-12.0, 12.0)
SLIDER_STYLES = ("fluent", "bar")
SLIDER_HEIGHT_RANGE = (2.0, 24.0)
SLIDER_SLANT_RANGE = (-1.0, 1.0)
MAX_PLATES = 6
MAX_PLATE_OFFSET = 80.0
DIGITS_HEIGHT_RANGE = (10.0, 64.0)
DIGITS_OFFSET = 60.0
DIGITS_SPACING_RANGE = (-20.0, 20.0)
DIGITS_TILT = 20.0
POP_DURATION_S = 0.16
SLIDER_TAPER_RANGE = (0.3, 3.0)
HEADER_X_RANGE = (-60.0, 320.0)       # onde a faixa e o botão da seta podem ficar (px do card, passando da borda)
HEADER_MIN_SLIDER = 40.0

# Onde o número do volume principal fica no cabeçalho (px do card): borda direita e centro vertical
NUMBER_RIGHT_X = 198.0
NUMBER_CY = 24.5


@dataclass(frozen=True)
class Header:
    """Onde ficam, no cabeçalho do card (x em px do card), a faixa do volume principal e o botão da seta."""
    slider: tuple[float, float] = (45.0, 162.0)
    chevron_x: float = 203.0


DEFAULT_HEADER = Header()


@dataclass(frozen=True, eq=False)
class Plate:
    color: QColor
    corners: tuple[tuple[float, float], ...]   # deslocamento (x, y) de cada canto: sup-esq, sup-dir, inf-dir, inf-esq


@dataclass(frozen=True, eq=False)
class Digits:
    glyphs: tuple[QPixmap, ...]      # 0..9, já recortados na largura
    ratios: tuple[float, ...]        # largura / altura de cada algarismo
    height: float = 28.0
    x: float = 0.0
    y: float = 0.0
    spacing: float = 0.0
    tilt: tuple[float, ...] = ()     # inclinação de cada casa, da direita para a esquerda
    pop: bool = True
    muted_opacity: float = 0.5


# --- Leitura ---------------------------------------------------------------------------------

def parse_slider_style(value) -> str | None:
    if value in SLIDER_STYLES:
        return value
    report_issue("'slider_style' inválido: %r (use %s; usando fluent)", value, " ou ".join(SLIDER_STYLES))
    return None


def parse_header(data) -> Header | None:
    if data is None:
        return None
    with issue_scope("cabeçalho"):
        if not isinstance(data, dict):
            report_issue("'header' precisa ser um objeto, como {\"slider\": [40, 235], \"chevron_x\": 243}")
            return None
        for key in data:
            if key not in ("slider", "chevron_x"):
                report_issue("chave desconhecida '%s' (ignorada); as válidas são: slider, chevron_x", key)
        slider = DEFAULT_HEADER.slider
        if "slider" in data:
            pair = _pair(data["slider"])
            if pair is None:
                report_issue("'slider' precisa ser [x_inicial, x_final] (veio %r; usando %s)", data["slider"], slider)
            else:
                a, b = (max(HEADER_X_RANGE[0], min(HEADER_X_RANGE[1], v)) for v in pair)
                if b - a < HEADER_MIN_SLIDER:
                    report_issue("'slider' precisa ter pelo menos %d px de comprimento (usando %s)",
                                 HEADER_MIN_SLIDER, slider)
                else:
                    slider = (a, b)
        chevron_x = _num(data, "chevron_x", DEFAULT_HEADER.chevron_x, *HEADER_X_RANGE)
        return Header(slider=slider, chevron_x=chevron_x)


def _pair(value) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(_is_number(v) for v in value):
        return float(value[0]), float(value[1])
    return None


def parse_plates(data) -> tuple[Plate, ...]:
    if data is None:
        return ()
    if not isinstance(data, list):
        report_issue("'plates' precisa ser uma lista [ {...}, {...} ]; nenhuma placa foi usada")
        return ()
    if len(data) > MAX_PLATES:
        report_issue("no máximo %d placas; as %d últimas foram ignoradas", MAX_PLATES, len(data) - MAX_PLATES)
    out: list[Plate] = []
    for i, item in enumerate(data[:MAX_PLATES]):
        with issue_scope(f"placa {i + 1}"):
            plate = _parse_plate(item)
        if plate is not None:
            out.append(plate)
    return tuple(out)


def _parse_plate(item) -> Plate | None:
    if not isinstance(item, dict):
        report_issue("precisa ser um objeto, como {\"color\": \"#ff0000\", \"corners\": [[0,0],[0,0],[0,0],[0,0]]}")
        return None
    for key in item:
        if key not in ("color", "corners"):
            report_issue("chave desconhecida '%s' (ignorada); as válidas são: color, corners", key)
    color = parse_color(item.get("color"))
    if color is None:
        report_issue("cor inválida em 'color': %r (use #rrggbb ou #aarrggbb); a placa foi ignorada", item.get("color"))
        return None
    raw = item.get("corners")
    pairs = [_pair(v) for v in raw] if isinstance(raw, list) and len(raw) == 4 else None
    if not pairs or any(p is None for p in pairs):
        report_issue("'corners' precisa ter 4 pares [x, y] (sup-esq, sup-dir, inf-dir, inf-esq); a placa foi ignorada")
        return None
    clamped = tuple((max(-MAX_PLATE_OFFSET, min(MAX_PLATE_OFFSET, x)), max(-MAX_PLATE_OFFSET, min(MAX_PLATE_OFFSET, y)))
                    for x, y in pairs)
    if clamped != tuple(pairs):
        report_issue("'corners' fora do limite (de %s a %s px); os valores foram ajustados",
                     -MAX_PLATE_OFFSET, MAX_PLATE_OFFSET)
    return Plate(color=color, corners=clamped)


def _trim_columns(img: QImage) -> tuple[int, int]:
    """(primeira, última) coluna com algum pixel visível; (0, largura-1) se a célula está vazia."""
    w, h = img.width(), img.height()
    step = max(1, h // 48)
    used = [x for x in range(w) if any(img.pixelColor(x, y).alpha() > 8 for y in range(0, h, step))]
    return (used[0], used[-1]) if used else (0, w - 1)


_DIGIT_KEYS = ("image", "height", "x", "y", "spacing", "tilt", "pop", "muted_opacity")


def parse_digits(data, base_dir: str) -> Digits | None:
    if data is None:
        return None
    with issue_scope("algarismos"):
        if not isinstance(data, dict):
            report_issue("'digits' precisa ser um objeto, como {\"image\": \"digitos.png\", \"height\": 32}")
            return None
        for key in data:
            if key not in _DIGIT_KEYS:
                report_issue("chave desconhecida '%s' (ignorada); as válidas são: %s", key, ", ".join(_DIGIT_KEYS))
        sheet = load_pixmap(base_dir, data.get("image"), what="algarismos")
        if sheet is None:
            return None
        cell_w = sheet.width() // 10
        if cell_w < 2 or sheet.height() < 2:
            report_issue("a imagem dos algarismos precisa ter os 10 algarismos (0 a 9) lado a lado, em células iguais")
            return None
        img = sheet.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        glyphs, ratios = [], []
        for d in range(10):
            cell = img.copy(d * cell_w, 0, cell_w, img.height())
            first, last = _trim_columns(cell)
            glyph = cell.copy(first, 0, last - first + 1, cell.height())
            glyphs.append(QPixmap.fromImage(glyph))
            ratios.append(glyph.width() / glyph.height())

        tilt: tuple[float, ...] = ()
        if "tilt" in data:
            raw = data["tilt"]
            if isinstance(raw, list) and len(raw) <= 3 and all(_is_number(v) for v in raw):
                tilt = tuple(max(-DIGITS_TILT, min(DIGITS_TILT, float(v))) for v in raw)
            else:
                report_issue("'tilt' precisa ser uma lista de até 3 números (graus de cada casa, da direita para a esquerda)")
        pop = data.get("pop", True)
        if not isinstance(pop, bool):
            report_issue("'pop' precisa ser true ou false (veio %r; usando true)", pop)
            pop = True
        height = _num(data, "height", 28.0, *DIGITS_HEIGHT_RANGE)
        # pré-reduz uma vez (filtro suave) para 3x o tamanho final: sobra folga para o pulo e telas de DPI alto
        glyphs = [presample(g, r * height, height, 3.0) for g, r in zip(glyphs, ratios)]
        return Digits(
            glyphs=tuple(glyphs), ratios=tuple(ratios),
            height=height,
            x=_num(data, "x", 0.0, -DIGITS_OFFSET, DIGITS_OFFSET),
            y=_num(data, "y", 0.0, -DIGITS_OFFSET, DIGITS_OFFSET),
            spacing=_num(data, "spacing", 0.0, *DIGITS_SPACING_RANGE),
            tilt=tilt, pop=pop,
            muted_opacity=_num(data, "muted_opacity", 0.5, 0.0, 1.0),
        )


# --- Geometria -------------------------------------------------------------------------------

def tilt_transform(card: QRectF, tilt: float, vertical: str) -> QTransform | None:
    """Rotação do card em volta do meio da borda ANCORADA (ela fica parada quando a gaveta abre)."""
    if not tilt:
        return None
    fy = {"top": 0.0, "middle": 0.5}.get(vertical, 1.0)
    px, py = card.center().x(), card.top() + card.height() * fy
    return QTransform().translate(px, py).rotate(tilt).translate(-px, -py)


def _plate_polygon(card: QRectF, plate: Plate) -> QPolygonF:
    base = (card.topLeft(), card.topRight(), card.bottomRight(), card.bottomLeft())
    return QPolygonF([QPointF(pt.x() + dx, pt.y() + dy) for pt, (dx, dy) in zip(base, plate.corners)])


def _digits_extent(d: Digits) -> tuple[float, float, float, float]:
    """Caixa (x1, y1, x2, y2), em px do card, que cobre "100" com folga para inclinação e pulo."""
    widest = max(d.ratios) * d.height
    width = 3.0 * widest + 2.0 * max(0.0, d.spacing)
    grow = d.height * 0.28
    right = NUMBER_RIGHT_X + d.x + grow
    cy = NUMBER_CY + d.y
    return right - width - 2.0 * grow, cy - d.height / 2.0 - grow, right, cy + d.height / 2.0 + grow


def _extent(theme, w: float, h: float) -> tuple[float, float, float, float]:
    left, top, right, bottom = overflow_margins(theme.stickers, theme.shadow, w, h)
    x1, y1, x2, y2 = -left, -top, w + right, h + bottom
    corners = ((0.0, 0.0), (w, 0.0), (w, h), (0.0, h))
    for plate in theme.plates:
        for (bx, by), (dx, dy) in zip(corners, plate.corners):
            x1, y1, x2, y2 = min(x1, bx + dx), min(y1, by + dy), max(x2, bx + dx), max(y2, by + dy)
    if theme.digits is not None:
        dx1, dy1, dx2, dy2 = _digits_extent(theme.digits)
        x1, y1, x2, y2 = min(x1, dx1), min(y1, dy1), max(x2, dx2), max(y2, dy2)
    if theme.header is not None:
        # botão do slider (raio 10) à esquerda; botão da seta (26 px) à direita
        x1 = min(x1, theme.header.slider[0] - 12.0)
        x2 = max(x2, theme.header.slider[1] + 12.0, theme.header.chevron_x + 29.0)
    return x1, y1, x2, y2


def art_overflow(theme, w: float, heights: tuple[float, ...], vertical: str | None = None) -> tuple[float, float, float, float]:
    """
    Quanto o tema desenha para fora do card, em px: (esquerda, topo, direita, base). `heights` são as alturas
    que o card pode ter; `vertical` é a âncora (None = o pior caso das três).
    """
    if not theme.tilt and not theme.plates and theme.digits is None and theme.header is None:
        return overflow_margins(theme.stickers, theme.shadow, w, heights[-1])   # temas antigos: conta de sempre
    out = [0.0, 0.0, 0.0, 0.0]
    pivots = {"top": (0.0,), "middle": (0.5,), "bottom": (1.0,)}.get(vertical, (0.0, 0.5, 1.0))
    for h in heights:
        x1, y1, x2, y2 = _extent(theme, w, h)
        boxes = [(x1, y1, x2, y2)]
        if theme.tilt:
            boxes = []
            for fy in pivots:
                tf = tilt_transform(QRectF(0.0, 0.0, w, h), theme.tilt, {0.0: "top", 0.5: "middle"}.get(fy, "bottom"))
                pts = [tf.map(QPointF(x, y)) for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
                boxes.append((min(p.x() for p in pts), min(p.y() for p in pts),
                              max(p.x() for p in pts), max(p.y() for p in pts)))
        for bx1, by1, bx2, by2 in boxes:
            out = [max(out[0], -bx1), max(out[1], -by1), max(out[2], bx2 - w), max(out[3], by2 - h)]
    return out[0], out[1], out[2], out[3]


# --- Pintura ---------------------------------------------------------------------------------

def paint_plates(p: QPainter, card: QRectF, plates) -> None:
    from PySide6.QtCore import Qt
    p.setPen(Qt.PenStyle.NoPen)
    for plate in plates:
        p.setBrush(plate.color)
        p.drawPolygon(_plate_polygon(card, plate))


def pop_amount(elapsed: float) -> float:
    """1 no instante da troca do número, 0 quando o pulo termina."""
    if elapsed < 0.0 or elapsed >= POP_DURATION_S:
        return 0.0
    k = 1.0 - elapsed / POP_DURATION_S
    return k * k


def paint_digits(p: QPainter, card: QRectF, d: Digits, value: int, muted: bool, pop: float = 0.0) -> None:
    """Desenha `value` alinhado à direita no lugar do número do cabeçalho. `pop` (0..1) é o pulo da troca."""
    text = str(max(0, min(100, int(value))))
    right = card.left() + NUMBER_RIGHT_X + d.x
    cy = card.top() + NUMBER_CY + d.y
    widths = [d.ratios[int(ch)] * d.height for ch in text]
    total = sum(widths) + d.spacing * (len(text) - 1)

    p.save()
    if muted:
        p.setOpacity(p.opacity() * d.muted_opacity)
    if pop > 0.0:
        cx = right - total / 2.0
        p.translate(cx, cy)
        p.scale(1.0 + 0.22 * pop, 1.0 + 0.22 * pop)
        p.rotate(-4.0 * pop)
        p.translate(-cx, -cy)
    x = right
    for slot, ch in enumerate(reversed(text)):
        glyph = d.glyphs[int(ch)]
        w = d.ratios[int(ch)] * d.height
        x -= w
        p.save()
        p.translate(x + w / 2.0, cy)
        if slot < len(d.tilt) and d.tilt[slot]:
            p.rotate(d.tilt[slot])
        p.drawPixmap(QRectF(-w / 2.0, -d.height / 2.0, w, d.height), glyph,
                     QRectF(0.0, 0.0, float(glyph.width()), float(glyph.height())))
        p.restore()
        x -= d.spacing
    p.restore()
