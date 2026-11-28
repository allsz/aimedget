"""
Indicador visual padronizado de redimensionamento (3 pontos diagonais) para todos os widgets.
Mantém o mesmo estilo do Music Widget / Timer Widget em toda a aplicação.
"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter


def paint_resize_dots(
    painter: QPainter,
    grip_x: float,
    grip_y: float,
    color: QColor,
    alpha: int = 145,
    scale: float = 1.0,
    radius: float = 1.4,
    spacing: float = 4.2,
) -> None:
    """
    Desenha os 3 pontos diagonais no canto inferior direito ancorados em (grip_x, grip_y):
    um ponto no vértice (grip_x, grip_y), um à esquerda e um acima.
    """
    col = QColor(color)
    col.setAlpha(max(0, min(255, int(alpha))))

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(col))

    r = radius * scale
    step = spacing * scale
    painter.drawEllipse(QPointF(grip_x, grip_y), r, r)
    painter.drawEllipse(QPointF(grip_x - step, grip_y), r, r)
    painter.drawEllipse(QPointF(grip_x, grip_y - step), r, r)
    painter.restore()
