from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QLinearGradient
from PySide6.QtSvg import QSvgRenderer


def draw_pill_button(
    painter: QPainter,
    renderer: QSvgRenderer,
    rect: QRectF,
    is_hovered: bool = False,
    is_pressed: bool = False,
    icon_size: float = 26.0,
):
    """
    Reproduz fielmente o estilo CSS .pill do widget.html:
    - border-radius: 999px (30px para altura 60px)
    - background: linear-gradient(180deg, rgba(255,255,255,.18), rgba(255,255,255,.07))
    - box-shadow externa + brilho superior inset + borda fina translúcida
    - ícone SVG centralizado (26x26)
    """
    painter.save()

    dy = 0.0
    if is_pressed:
        dy = 2.0
    elif is_hovered:
        dy = -2.0

    r = rect.translated(0, dy)
    radius = r.height() / 2.0

    # 1. Sombra projetada inferior (0 10px 20px -6px rgba(0,10,30,.55))
    if not is_pressed:
        shadow_rect = r.adjusted(2, 6, -2, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 10, 30, 115))
        painter.drawRoundedRect(shadow_rect, radius, radius)

    # 2. Corpo da pílula com gradiente vertical translúcido
    grad = QLinearGradient(r.left(), r.top(), r.left(), r.bottom())
    if is_pressed:
        grad.setColorAt(0.0, QColor(255, 255, 255, 28))
        grad.setColorAt(1.0, QColor(255, 255, 255, 14))
    elif is_hovered:
        grad.setColorAt(0.0, QColor(255, 255, 255, 56))
        grad.setColorAt(1.0, QColor(255, 255, 255, 22))
    else:
        grad.setColorAt(0.0, QColor(255, 255, 255, 46))  # 0.18
        grad.setColorAt(1.0, QColor(255, 255, 255, 18))  # 0.07

    painter.setBrush(grad)
    painter.setPen(QPen(QColor(255, 255, 255, 32), 1.5))
    painter.drawRoundedRect(r, radius, radius)

    # 3. Brilho superior interno (inset 0 1px 0 rgba(255,255,255,.28))
    if not is_pressed:
        highlight_path = QPainterPath()
        highlight_path.addRoundedRect(r.adjusted(1.5, 1.5, -1.5, -r.height() * 0.5), radius - 1, radius - 1)
        painter.setPen(QPen(QColor(255, 255, 255, 65), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), radius - 1.5, radius - 1.5)

    # 4. Ícone SVG centralizado
    icon_rect = QRectF(
        r.center().x() - icon_size / 2.0,
        r.center().y() - icon_size / 2.0,
        icon_size,
        icon_size,
    )
    renderer.render(painter, icon_rect)

    painter.restore()

