"""
Ícones de Aleatório e Repetir "nítidos" (skin Ecos da Capa).

Diferenças para `MediaIconsMixin`:
- Desenhados em PIXELS DE DISPOSITIVO: o centro é arredondado para o pixel e o espaçamento entre as duas linhas
  horizontais vira um número inteiro de pixels, então os traços nunca caem entre dois pixels (sem serrilhado).
- Espessura do traço em px de tela (mínimo 1,5, máximo 2,2), não múltiplo fixo do canvas.
- Pontas de seta são triângulos cheios com cantos arredondados (não ficam borradas em tamanho pequeno).
- Ligado = chip branco com glifo escuro (combina com o botão play/pause) (legível em qualquer capa); desligado = branco com sombra de 1 px;
  repetir uma faixa = selo escuro com o numeral 1 no canto do chip.

Grade do glifo: 24 x 24 unidades; o canvas da skin tem 960 px de largura (1 unidade do canvas = `scale` px lógicos).
"""


from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF

ACCENT = QColor(255, 255, 255, 240)   # chip do ligado: branco, como o botão play/pause
ON_ACCENT = QColor("#17151C")          # glifo sobre o chip branco
BADGE_BG = QColor("#17151C")

GLYPH_SCALE = 1.2                  # unidades do canvas por unidade da grade
CHIP_RADIUS = 26.0                 # em unidades do canvas
STROKE_UNITS = 2.3                 # espessura em unidades da grade (limitada em px de tela abaixo)
MIN_STROKE_PX, MAX_STROKE_PX = 1.5, 2.2
LINE_GAP_UNITS = 11.0              # distância entre as linhas horizontais (y = 6.5 e 17.5)

_SHUFFLE_LINES = (
    ((2.5, 6.5), ("L", 6.8, 6.5), ("C", 10.6, 6.5, 12.4, 17.5, 16.2, 17.5), ("L", 18.6, 17.5)),
    ((2.5, 17.5), ("L", 6.8, 17.5), ("C", 8.2, 17.5, 9.2, 16.7, 10.0, 15.5)),
    ((14.0, 8.5), ("C", 14.7, 7.3, 15.4, 6.5, 16.4, 6.5), ("L", 18.6, 6.5)),
)
_SHUFFLE_HEADS = (((18.2, 3.4), (22.2, 6.5), (18.2, 9.6)), ((18.2, 14.4), (22.2, 17.5), (18.2, 20.6)))

_K = 0.5523 * 4.2   # controle de um quarto de círculo de raio 4.2
_REPEAT_LINES = (
    ((3.5, 12.2), ("L", 3.5, 11.0), ("C", 3.5, 11.0 - _K, 7.7 - _K, 6.8, 7.7, 6.8), ("L", 18.4, 6.8)),
    ((20.5, 11.8), ("L", 20.5, 13.0), ("C", 20.5, 13.0 + _K, 16.3 + _K, 17.2, 16.3, 17.2), ("L", 5.6, 17.2)),
)
_REPEAT_HEADS = (((18.2, 3.6), (22.0, 6.8), (18.2, 10.0)), ((5.8, 14.0), (2.0, 17.2), (5.8, 20.4)))


class CrispIconsMixin:
    """`_draw_shuffle_icon` / `_draw_repeat_icon` com a mesma assinatura do `MediaIconsMixin`."""

    def _draw_shuffle_icon(self, painter: QPainter, center: QPointF, hovered: bool, active: bool):
        self._draw_crisp_icon(painter, center, _SHUFFLE_LINES, _SHUFFLE_HEADS, hovered, active, 0)

    def _draw_repeat_icon(self, painter: QPainter, center: QPointF, hovered: bool, mode: int):
        self._draw_crisp_icon(painter, center, _REPEAT_LINES, _REPEAT_HEADS, hovered, mode > 0, mode)

    # --- implementação ---

    @staticmethod
    def _glyph_metrics(painter: QPainter, center: QPointF):
        """(centro em px de dispositivo já alinhado ao pixel, px por unidade do glifo, espessura em px, px por unidade do canvas)."""
        dpr = painter.device().devicePixelRatioF() if painter.device() else 1.0
        tr = painter.worldTransform()
        canvas_px = tr.m11() * dpr
        phys = tr.map(center) * dpr
        u0 = GLYPH_SCALE * canvas_px
        gap = max(7, round(LINE_GAP_UNITS * u0))      # distância inteira em px entre as duas linhas horizontais
        u = gap / LINE_GAP_UNITS
        width = max(MIN_STROKE_PX, min(MAX_STROKE_PX, STROKE_UNITS * u))
        half = 0.5 if width < 1.75 else 0.0           # traço fino: centro no meio do pixel; grosso: na borda
        line_y = round(phys.y() - gap / 2.0 - half) + half
        cy = line_y + gap / 2.0
        cx = round(phys.x() - half) + half
        return QPointF(cx, cy), u, width, canvas_px, dpr

    def _draw_crisp_icon(self, painter, center, lines, heads, hovered, active, mode):
        c, u, width, canvas_px, dpr = self._glyph_metrics(painter, center)
        painter.save()
        painter.resetTransform()
        painter.scale(1.0 / dpr, 1.0 / dpr)           # daqui em diante 1 unidade = 1 pixel de dispositivo
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if active:
            chip, fg = QColor(ACCENT), QColor(ON_ACCENT)
        elif hovered:
            chip, fg = QColor(255, 255, 255, 44), QColor(255, 255, 255)
        else:
            chip, fg = None, QColor(255, 255, 255, 230)

        if chip is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(chip)
            painter.drawEllipse(c, CHIP_RADIUS * canvas_px, CHIP_RADIUS * canvas_px)

        def pt(x, y):
            return QPointF(c.x() + (x - 12.0) * u, c.y() + (y - 12.0) * u)

        paths = []
        for spec in lines:
            path = QPainterPath(pt(*spec[0]))
            for seg in spec[1:]:
                if seg[0] == "L":
                    path.lineTo(pt(seg[1], seg[2]))
                else:
                    path.cubicTo(pt(seg[1], seg[2]), pt(seg[3], seg[4]), pt(seg[5], seg[6]))
            paths.append(path)
        polys = [QPolygonF([pt(*p) for p in tri]) for tri in heads]

        def paint(color: QColor, dy: float):
            painter.save()
            painter.translate(0.0, dy)
            pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for path in paths:
                painter.drawPath(path)
            head_pen = QPen(color, max(1.0, 1.4 * u), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin)
            painter.setPen(head_pen)
            painter.setBrush(color)
            for poly in polys:
                painter.drawPolygon(poly)
            painter.restore()

        if chip is None:                               # desligado: sombra de 1 px para separar de capas claras
            paint(QColor(0, 0, 0, 80), max(1.0, canvas_px * 1.4))
        paint(fg, 0.0)

        if mode == 2:                                  # repetir uma faixa: selo com o numeral 1
            r = 9.5 * canvas_px
            bc = QPointF(c.x() + 19.0 * canvas_px, c.y() - 19.0 * canvas_px)
            painter.setPen(QPen(QColor(255, 255, 255, 235), max(1.0, 2.0 * canvas_px)))
            painter.setBrush(BADGE_BG)
            painter.drawEllipse(bc, r, r)
            font = QFont()
            font.setPixelSize(max(7, round(13.0 * canvas_px)))
            font.setWeight(QFont.Weight.ExtraBold)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRectF(bc.x() - r, bc.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, "1")

        painter.restore()
