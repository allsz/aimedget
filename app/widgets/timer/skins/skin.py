"""
Pure painting and state for WindowsTimerSkin.
Zero timers, zero QWidget overhead, 100% pure QPainter rendering.
Shared by live WindowsTimerSkin and Hub preview cards.
"""

from dataclasses import dataclass
import math
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)

from app.core.theme_art import paint_background, paint_stickers
from app.core.typography import get_ui_font
from app.hub.theme import HubTheme, THEME_DARK


@dataclass
class TimerState:
    current_seconds: float = 300.0
    target_duration: float = 300.0
    mode: str = "timer"  # 'timer' ou 'stopwatch'
    is_running: bool = False
    is_alarm_pulsing: bool = False
    pressed_btn: str | None = None
    hovered_btn: str | None = None
    hovered_time_segment: str | None = None
    close_opacity: float = 0.0
    is_hovered: bool = False
    is_smart_hover_enabled: bool = True
    is_play_enabled: bool = True   # False: duração zerada (00:00:00), nada para contar
    select_segment: str | None = None   # segmento clicado, com a volta de luz na borda da pílula
    select_progress: float = 0.0        # 0..1 da volta (1 = completa)
    select_color: QColor | None = None  # None: branco no tema escuro, escuro no claro


SHADOW_PAD = 8.0
CORNER_RADIUS = 16.0
DEFAULT_SIZE = 164.0


def natural_size(state: TimerState | None = None) -> QSizeF:
    return QSizeF(DEFAULT_SIZE, DEFAULT_SIZE)


def _paint_select_sweep(p: QPainter, rect: QRectF, radius: float, scale: float, state: TimerState, theme: HubTheme):
    """Uma volta de luz ANTI-HORÁRIA só na borda da pílula do segmento clicado (dica visual de que o clique valeu)."""
    color = QColor(state.select_color) if state.select_color is not None else (
        QColor(255, 255, 255) if theme.is_dark else QColor(24, 24, 27))
    t = state.select_progress
    eased = 1.0 - (1.0 - t) ** 3
    fade = min(1.0, (1.0 - t) * 4.0)                  # some no final da volta
    head = 90.0 + 360.0 * eased                       # parte do topo; o ângulo do Qt cresce no sentido anti-horário
    grad = QConicalGradient(rect.center(), head)
    clear, solid = QColor(color), QColor(color)
    clear.setAlpha(0)
    solid.setAlpha(int(255 * fade))
    grad.setColorAt(0.0, clear)
    grad.setColorAt(0.55, clear)
    grad.setColorAt(1.0, solid)                       # cabeça do cometa; a cauda fica atrás (sentido horário)
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QBrush(grad), max(1.2, 1.6 * scale)))
    p.drawRoundedRect(rect, radius, radius)
    p.restore()


def paint_windows_timer(
    p: QPainter,
    rect: QRectF,
    state: TimerState | None = None,
    theme: HubTheme | None = None,
    art=None,
):
    """`art` (TimerTheme, opcional): fundo e figurinhas do tema. As cores do tema já vêm aplicadas em `theme`."""
    if state is None:
        state = TimerState()
    if theme is None:
        theme = THEME_DARK

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    w = rect.width()
    h = rect.height()
    pad = SHADOW_PAD
    card = QRectF(rect.x() + pad, rect.y() + pad, w - 2 * pad, h - 2 * pad)
    scale = max(0.8, min(card.width(), card.height()) / (DEFAULT_SIZE - 2 * pad))

    # 1. Sombra suave externa
    shadow_color = QColor(0, 0, 0, 65 if theme.is_dark else 35)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(shadow_color))
    p.drawRoundedRect(
        card.adjusted(0, 2.5 * scale, 0, 3.5 * scale),
        CORNER_RADIUS,
        CORNER_RADIUS,
    )

    # 2. Superfície do Card Fluent (Tons do Hub)
    bg_color = QColor(theme.panel)
    p.setBrush(QBrush(bg_color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(card, CORNER_RADIUS, CORNER_RADIUS)

    # 2b. Fundo e figurinhas de baixo do tema (dentro do cartão), antes da borda e do conteúdo
    if art is not None and (art.background is not None or art.stickers):
        _paint_art(p, card, scale, art, above=False)

    border_pen = QPen(QColor(theme.line), 1.0)
    if state.is_alarm_pulsing:
        border_pen = QPen(QColor(theme.accent), 2.0)
    p.setPen(border_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(card, CORNER_RADIUS, CORNER_RADIUS)

    # 3. Rótulo de Modo / Status no topo
    mode_text = "TEMPORIZADOR" if state.mode == "timer" else "CRONÔMETRO"
    # "Concluído" só quando a contagem terminou; um timer zerado pelo usuário segue sendo "temporizador"
    if state.mode == "timer" and state.current_seconds <= 0 and not state.is_running and state.target_duration > 0:
        mode_text = "CONCLUÍDO"

    lbl_font = get_ui_font(max(8, int(9.5 * scale)), QFont.Weight.DemiBold)
    p.setFont(lbl_font)
    p.setPen(QColor(theme.accent if state.is_alarm_pulsing else theme.mute))
    p.drawText(
        QRectF(card.left(), card.top() + 14 * scale, card.width(), 16 * scale),
        Qt.AlignmentFlag.AlignCenter,
        mode_text,
    )

    # 4. Display Digital do Tempo
    total_sec = max(0, int(round(state.current_seconds)))
    hh, rem = divmod(total_sec, 3600)
    mm, ss = divmod(rem, 60)
    hh_str, mm_str, ss_str = f"{hh:02d}", f"{mm:02d}", f"{ss:02d}"
    colon = ":"

    font_size = max(16, int(25 * scale))
    digits_font = get_ui_font(font_size, QFont.Weight.DemiBold)
    p.setFont(digits_font)

    fm = QFontMetricsF(digits_font)
    w_hh = fm.horizontalAdvance(hh_str)
    w_c1 = fm.horizontalAdvance(colon)
    w_mm = fm.horizontalAdvance(mm_str)
    w_c2 = fm.horizontalAdvance(colon)
    w_ss = fm.horizontalAdvance(ss_str)

    total_w = w_hh + w_c1 + w_mm + w_c2 + w_ss
    start_x = card.left() + (card.width() - total_w) / 2.0
    digits_y = card.top() + 32 * scale
    digits_h = 40 * scale

    rects = {
        "hours": QRectF(start_x, digits_y, w_hh, digits_h),
        "colon1": QRectF(start_x + w_hh, digits_y, w_c1, digits_h),
        "minutes": QRectF(start_x + w_hh + w_c1, digits_y, w_mm, digits_h),
        "colon2": QRectF(start_x + w_hh + w_c1 + w_mm, digits_y, w_c2, digits_h),
        "seconds": QRectF(start_x + w_hh + w_c1 + w_mm + w_c2, digits_y, w_ss, digits_h),
    }
    texts = {
        "hours": hh_str,
        "colon1": colon,
        "minutes": mm_str,
        "colon2": colon,
        "seconds": ss_str,
    }

    for seg_key in ("hours", "colon1", "minutes", "colon2", "seconds"):
        r = rects[seg_key]
        txt = texts[seg_key]
        is_seg_hovered = (
            state.is_smart_hover_enabled
            and not state.is_running
            and state.hovered_time_segment == seg_key
        )
        if is_seg_hovered:
            p.setPen(Qt.PenStyle.NoPen)
            pill_bg = QColor(theme.accent)
            pill_bg.setAlpha(42 if theme.is_dark else 35)
            p.setBrush(QBrush(pill_bg))
            pad_x = 3.0 * scale
            pad_y = 2.0 * scale
            p.drawRoundedRect(r.adjusted(-pad_x, pad_y, pad_x, -pad_y), 4.0 * scale, 4.0 * scale)
            p.setPen(QColor(theme.accent))
        elif state.is_alarm_pulsing:
            p.setPen(QColor(theme.accent))
        elif seg_key.startswith("colon"):
            p.setPen(QColor(theme.mute))
        else:
            p.setPen(QColor(theme.text))

        p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)
        if state.select_segment == seg_key and 0.0 < state.select_progress < 1.0:
            _paint_select_sweep(p, r.adjusted(-3.0 * scale, 2.0 * scale, 3.0 * scale, -2.0 * scale), 4.0 * scale,
                                scale, state, theme)

    # 5. Botões de Ação
    play_diam = 40.0 * scale
    reset_diam = 32.0 * scale
    gap = 12.0 * scale
    btns_total_w = play_diam + gap + reset_diam
    btns_start_x = card.left() + (card.width() - btns_total_w) / 2.0
    btns_cy = card.top() + 104.0 * scale

    play_rect = QRectF(btns_start_x, btns_cy - play_diam / 2.0, play_diam, play_diam)
    reset_rect = QRectF(btns_start_x + play_diam + gap, btns_cy - reset_diam / 2.0, reset_diam, reset_diam)

    # Botão Play
    is_play_pressed = state.pressed_btn == "play_pause"
    is_play_hover = state.hovered_btn == "play_pause"
    play_enabled = state.is_play_enabled
    btn_color = QColor(theme.accent_hover if (is_play_hover and play_enabled) else theme.accent)
    if is_play_pressed and play_enabled:
        btn_color = btn_color.darker(115)
    if not play_enabled:
        btn_color.setAlphaF(0.32)   # apagado: com 00:00:00 não há o que contar
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(btn_color))
    p.drawEllipse(play_rect)

    # Ícone interno do botão Play/Pause
    icon_color = QColor(theme.ink)
    if not play_enabled:
        icon_color = QColor(theme.mute)
        icon_color.setAlphaF(0.75)
    p.setBrush(QBrush(icon_color))
    center = play_rect.center()
    icon_size = 13.0 * scale

    if state.is_running:
        bar_w = 3.2 * scale
        bar_h = icon_size
        bar_gap = 3.4 * scale
        left_bar = QRectF(center.x() - bar_w - bar_gap / 2.0, center.y() - bar_h / 2.0, bar_w, bar_h)
        right_bar = QRectF(center.x() + bar_gap / 2.0, center.y() - bar_h / 2.0, bar_w, bar_h)
        p.drawRoundedRect(left_bar, 1.2 * scale, 1.2 * scale)
        p.drawRoundedRect(right_bar, 1.2 * scale, 1.2 * scale)
    else:
        tri = QPainterPath()
        offset_x = 1.0 * scale
        half_w = (icon_size * 0.9) / 2.0
        half_h = icon_size / 2.0
        tri.moveTo(center.x() - half_w + offset_x, center.y() - half_h)
        tri.lineTo(center.x() + half_w + offset_x, center.y())
        tri.lineTo(center.x() - half_w + offset_x, center.y() + half_h)
        tri.closeSubpath()
        p.drawPath(tri)

    # Botão Reset
    is_reset_pressed = state.pressed_btn == "reset"
    is_reset_hover = state.hovered_btn == "reset"
    reset_color = QColor(theme.panel2)
    if is_reset_hover:
        reset_color = reset_color.lighter(120) if theme.is_dark else reset_color.darker(108)
    if is_reset_pressed:
        reset_color = reset_color.darker(115)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(reset_color))
    p.drawEllipse(reset_rect)

    # Ícone interno de Reset
    r_center = reset_rect.center()
    r = 5.2 * scale
    arc_rect = QRectF(r_center.x() - r, r_center.y() - r, 2 * r, 2 * r)
    pen = QPen(QColor(theme.body), 1.6 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(arc_rect, int(35 * 16), int(290 * 16))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(theme.body)))
    arrow_head = QPainterPath()
    tip_x = r_center.x() + r * math.cos(math.radians(35))
    tip_y = r_center.y() - r * math.sin(math.radians(35))
    arrow_head.moveTo(tip_x, tip_y - 3.2 * scale)
    arrow_head.lineTo(tip_x + 3.0 * scale, tip_y + 1.5 * scale)
    arrow_head.lineTo(tip_x - 3.0 * scale, tip_y + 1.5 * scale)
    arrow_head.closeSubpath()
    p.drawPath(arrow_head)

    # 6. Botão Fechar oculto (se hovered)
    if state.close_opacity > 0.01:
        close_size = 22.0 * scale
        close_pad = 9.0 * scale
        close_rect = QRectF(card.left() + close_pad, card.top() + close_pad, close_size, close_size)
        alpha = int(state.close_opacity * 255)
        cross_color = QColor(theme.mute)
        cross_color.setAlpha(alpha)
        p.setPen(QPen(cross_color, 1.4 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c_ctr = close_rect.center()
        arm = 3.6 * scale
        p.drawLine(QPointF(c_ctr.x() - arm, c_ctr.y() - arm), QPointF(c_ctr.x() + arm, c_ctr.y() + arm))
        p.drawLine(QPointF(c_ctr.x() - arm, c_ctr.y() + arm), QPointF(c_ctr.x() + arm, c_ctr.y() - arm))

    # 7. Figurinhas de cima do tema (podem passar um pouco da borda, dentro da margem da sombra)
    if art is not None and art.stickers:
        _paint_art(p, card, scale, art, above=True)

    p.restore()


def _paint_art(p: QPainter, card: QRectF, scale: float, art, above: bool):
    """Fundo/figurinhas em px do cartão no tamanho padrão (148 x 148), escalados com o cartão."""
    p.save()
    if not above:
        clip = QPainterPath()
        clip.addRoundedRect(card, CORNER_RADIUS, CORNER_RADIUS)
        p.setClipPath(clip)
    p.translate(card.topLeft())
    p.scale(scale, scale)
    rect = QRectF(0.0, 0.0, card.width() / scale, card.height() / scale)
    if not above and art.background is not None:
        paint_background(p, rect, art.background, CORNER_RADIUS / scale)
    paint_stickers(p, rect, art.stickers, above=above)
    p.restore()
