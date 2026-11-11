from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QPen,
    QLinearGradient,
    QFont,
)
from app.core.colorimetry import ThemePalette
from app.core.typography import get_ui_font


def draw_tactile_physical_button(
    painter: QPainter,
    rect: QRectF,
    palette: ThemePalette,
    kind: str,  # 'play', 'pause', 'prev', 'next'
    is_hovered: bool = False,
    is_pressed: bool = False,
):
    """
    Renderiza os botões físicos estilizados com base nos SVGs de fisical_buttons:
    - Pílula superior lisa com acabamento 3D 'saltado' (sombra profunda + relevo inferior).
    - Incorpora dinamicamente as cores de fundo extraídas da capa do álbum (palette.stop0 e stop1).
    - Legenda/ícone posicionados abaixo do pill (PLAY/PAUSE em texto, |< e >| em vetores nítidos).
    - Micro-feedback de afundamento físico (press = dy de 2.5px).
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    pill_h = 48.0
    pill_w = w
    pill_rx = pill_h / 2.0
    dy = 2.5 if is_pressed else 0.0

    # 1. SOMBRA SUAVE 'SALTADA' (feDropShadow simulada com blur gradual)
    if not is_pressed:
        for s_dy, s_blur, s_alpha in [(8, 14, 110), (4, 7, 90), (2, 3, 130)]:
            s_rect = QRectF(x + 2, y + s_dy, pill_w - 4, pill_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, s_alpha))
            painter.drawRoundedRect(s_rect, pill_rx, pill_rx)
    else:
        s_rect = QRectF(x + 2, y + 2, pill_w - 4, pill_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 130))
        painter.drawRoundedRect(s_rect, pill_rx, pill_rx)

    # 2. BORDA DE RELEVO FÍSICO / EXTRUSÃO INFERIOR (Chanfro de profundidade do botão)
    if not is_pressed:
        ext_rect = QRectF(x, y + 3.0, pill_w, pill_h)
        ext_grad = QLinearGradient(x, y + pill_h, x, y + pill_h + 3.0)
        c_rim_bot = QColor(palette.stop0).darker(170)
        c_rim_deep = QColor(0, 0, 0, 240)
        ext_grad.setColorAt(0.0, c_rim_bot)
        ext_grad.setColorAt(1.0, c_rim_deep)
        painter.setBrush(ext_grad)
        painter.setPen(QPen(QColor(0, 0, 0, 150), 1.0))
        painter.drawRoundedRect(ext_rect, pill_rx, pill_rx)

    # 3. CORPO DO PILL COM A COR DO FUNDO DETECTADA DA CAPA (btnFill adaptativo)
    pill_rect = QRectF(x, y + dy, pill_w, pill_h)
    c_base = QColor(palette.stop1)
    c_top = c_base.lighter(135 if is_hovered else 122)
    c_mid = c_base.darker(105)
    c_bot = QColor(palette.stop0).darker(115)

    fill_grad = QLinearGradient(x, y + dy, x, y + dy + pill_h)
    fill_grad.setColorAt(0.0, c_top)
    fill_grad.setColorAt(0.45, c_mid)
    fill_grad.setColorAt(1.0, c_bot)
    painter.setBrush(fill_grad)

    rim_alpha = 55 if is_hovered else 35
    painter.setPen(QPen(QColor(255, 255, 255, rim_alpha), 1.8))
    painter.drawRoundedRect(pill_rect, pill_rx, pill_rx)

    # 4. BRILHO ESPECULAR INTERNO
    inner_rect = pill_rect.adjusted(1.5, 1.5, -1.5, -1.5)
    inner_grad = QLinearGradient(x, y + dy, x, y + dy + pill_h * 0.45)
    inner_alpha = 50 if is_hovered else 30
    inner_grad.setColorAt(0.0, QColor(255, 255, 255, inner_alpha))
    inner_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(inner_grad, 1.0))
    painter.drawRoundedRect(inner_rect, pill_rx - 1.5, pill_rx - 1.5)

    # 5. LEGENDA / ÍCONE ABAIXO DO BOTÃO (Exatamente como nos SVGs de fisical_buttons)
    cx = x + pill_w / 2.0
    bot_cy = y + pill_h + 16.0
    label_alpha = 255 if is_hovered else 205
    label_color = QColor(255, 255, 255, label_alpha)

    if kind in ("play", "pause"):
        text = "PAUSE" if kind == "pause" else "PLAY"
        lbl_font = get_ui_font(15, QFont.Weight.Bold)
        lbl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
        painter.setFont(lbl_font)
        painter.setPen(label_color)
        painter.drawText(QRectF(x, y + pill_h + 3, pill_w, 26), Qt.AlignmentFlag.AlignCenter, text)

    elif kind == "prev":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(label_color)
        painter.drawRect(QRectF(cx - 10.0, bot_cy - 8.0, 3.5, 16.0))
        tri = QPainterPath()
        tri.moveTo(cx + 9.0, bot_cy - 8.0)
        tri.lineTo(cx - 4.5, bot_cy)
        tri.lineTo(cx + 9.0, bot_cy + 8.0)
        tri.closeSubpath()
        painter.drawPath(tri)

    elif kind == "next":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(label_color)
        tri = QPainterPath()
        tri.moveTo(cx - 9.0, bot_cy - 8.0)
        tri.lineTo(cx + 4.5, bot_cy)
        tri.lineTo(cx - 9.0, bot_cy + 8.0)
        tri.closeSubpath()
        painter.drawPath(tri)
        painter.drawRect(QRectF(cx + 6.5, bot_cy - 8.0, 3.5, 16.0))

    painter.restore()
