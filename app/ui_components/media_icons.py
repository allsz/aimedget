from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen

ACCENT = QColor("#5CD6FF")
ICON_SCALE = 1.1  # grade 24 -> ~26 px no canvas 960x540 (~13 px na tela)
ICON_PEN = 2.8


class MediaIconsMixin:
    """
    Ícones vetoriais dinâmicos (Shuffle e Repeat) compartilhados entre as skins do Music Widget.
    - Estilo Fluent Windows 11 Pro: traço 2.8px consistente, flechas em 45° harmônicas com o Forward button
      e numeral '1' lapidado para repetição de uma faixa.
    - Estados: normal (branco translúcido), hover (pílula branca sutil) e ativo (pílula + traço em ACCENT).
    """

    def _begin_icon(self, painter: QPainter, center: QPointF, hovered: bool, active: bool):
        """Desenha a pílula de fundo e prepara a grade 24x24 centrada em `center`."""
        painter.save()
        if active:
            bg, fg = QColor(92, 214, 255, 38), QColor(ACCENT)
        elif hovered:
            bg, fg = QColor(255, 255, 255, 28), QColor(255, 255, 255, 255)
        else:
            bg, fg = None, QColor(255, 255, 255, 200)

        if bg is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawEllipse(center, 24.0, 24.0)

        painter.translate(center)
        painter.scale(ICON_SCALE, ICON_SCALE)
        painter.translate(-12.0, -12.0)
        painter.setPen(QPen(fg, ICON_PEN, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        return fg

    def _draw_shuffle_icon(self, painter: QPainter, center: QPointF, hovered: bool, active: bool):
        fg = self._begin_icon(painter, center, hovered, active)
        # Linha superior para inferior com curvatura Fluent contínua
        p1 = QPainterPath()
        p1.moveTo(2.0, 6.0)
        p1.lineTo(7.5, 6.0)
        p1.cubicTo(11.0, 6.0, 13.0, 18.0, 16.5, 18.0)
        p1.lineTo(22.0, 18.0)
        painter.drawPath(p1)

        # Linha inferior para superior com vão óptico no cruzamento
        p2 = QPainterPath()
        p2.moveTo(2.0, 18.0)
        p2.lineTo(7.5, 18.0)
        p2.cubicTo(9.5, 18.0, 10.8, 15.8, 11.8, 13.8)
        painter.drawPath(p2)

        p3 = QPainterPath()
        p3.moveTo(12.2, 10.2)
        p3.cubicTo(13.2, 8.2, 14.5, 6.0, 16.5, 6.0)
        p3.lineTo(22.0, 6.0)
        painter.drawPath(p3)

        # Flechas de precisão (45° idênticas ao chanfro do Forward)
        a1 = QPainterPath()
        a1.moveTo(18.2, 2.2)
        a1.lineTo(22.2, 6.0)
        a1.lineTo(18.2, 9.8)
        painter.drawPath(a1)

        a2 = QPainterPath()
        a2.moveTo(18.2, 14.2)
        a2.lineTo(22.2, 18.0)
        a2.lineTo(18.2, 21.8)
        painter.drawPath(a2)

        if active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fg)
            painter.drawEllipse(QPointF(12.0, 27.0), 2.2, 2.2)

        painter.restore()

    def _draw_repeat_icon(self, painter: QPainter, center: QPointF, hovered: bool, mode: int):
        active = mode > 0
        fg = self._begin_icon(painter, center, hovered, active)

        # Alça superior (indo para a direita)
        p_top = QPainterPath()
        p_top.moveTo(7.0, 18.0)
        p_top.lineTo(6.0, 18.0)
        p_top.cubicTo(2.0, 18.0, 2.0, 6.0, 6.0, 6.0)
        p_top.lineTo(21.5, 6.0)
        painter.drawPath(p_top)

        # Flecha superior direita
        a_top = QPainterPath()
        a_top.moveTo(17.7, 2.2)
        a_top.lineTo(21.7, 6.0)
        a_top.lineTo(17.7, 9.8)
        painter.drawPath(a_top)

        # Alça inferior (indo para a esquerda)
        p_bot = QPainterPath()
        p_bot.moveTo(17.0, 6.0)
        p_bot.lineTo(18.0, 6.0)
        p_bot.cubicTo(22.0, 6.0, 22.0, 18.0, 18.0, 18.0)
        p_bot.lineTo(2.5, 18.0)
        painter.drawPath(p_bot)

        # Flecha inferior esquerda
        a_bot = QPainterPath()
        a_bot.moveTo(6.3, 21.8)
        a_bot.lineTo(2.3, 18.0)
        a_bot.lineTo(6.3, 14.2)
        painter.drawPath(a_bot)

        # Numeral "1" lapidado para repetir uma faixa
        if mode == 2:
            painter.setPen(QPen(fg, 2.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            one = QPainterPath()
            one.moveTo(10.4, 10.8)
            one.lineTo(12.2, 8.8)
            one.lineTo(12.2, 15.4)
            painter.drawPath(one)

        if active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fg)
            painter.drawEllipse(QPointF(12.0, 27.0), 2.2, 2.2)

        painter.restore()
