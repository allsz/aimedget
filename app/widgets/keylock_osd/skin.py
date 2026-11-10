"""
Skin e função pura de pintura para o KeyLockFlyout.
Separa completamente o estado e o desenho da lógica de timers, SO e janelas,
permitindo reutilização idêntica tanto no flyout ao vivo quanto nos cards de preview do Hub.
"""

import math
from dataclasses import dataclass
from typing import Any
from PySide6.QtCore import Qt, QRectF, QSizeF, QPointF
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from app.core.theme_art import (
    paint_background,
    paint_card_shadow,
    paint_stickers,
    paint_stickers_behind,
)
from app.core.typography import get_ui_font
from app.widgets.keylock_osd.theme import DEFAULT_THEME, KeyLockTheme


@dataclass
class KeyLockState:
    """Estado visual puro do indicador de Caps / Num Lock."""
    label: str = "Caps Lock"
    is_on: bool = True
    anim_val: float = 1.0          # 0.0 = totalmente aberto (OFF), 1.0 = fechado (ON)
    shackle_x_shift: float = 0.0   # Deslocamento horizontal da haste do cadeado
    shackle_lift: float = 0.0      # Elevação vertical da haste
    left_leg_gap: float = 0.0      # Espaço aberto na perna esquerda
    body_recoil: float = 0.0       # Recuo mecânico suave do corpo
    draw_shadow: bool = False      # Se desenha a sombra externa (usado em previews)
    theme: KeyLockTheme = DEFAULT_THEME  # Tokens visuais (cores e raio)


def get_label_font(theme: KeyLockTheme | None = None):
    size = int(round(theme.label_size)) if theme else 14
    return get_ui_font(size)


def display_label(label: str, theme: KeyLockTheme) -> str:
    """O nome da tecla como o tema quer mostrar (minúsculas/MAIÚSCULAS ou como o app escreve)."""
    if theme.label_case == "lower":
        return label.lower()
    if theme.label_case == "upper":
        return label.upper()
    return label


def card_size(theme: KeyLockTheme, label: str) -> QSizeF:
    """Tamanho do cartão (antes de `scale`): o `size` do tema, ou largura pelo texto e altura 50."""
    if theme.size is not None:
        return QSizeF(theme.size[0], theme.size[1])
    fm = QFontMetricsF(get_label_font(theme))
    text_w = math.ceil(fm.horizontalAdvance(display_label(label, theme)))
    lead = 18.0 + 14.0 + 15.0 if theme.show_icon else 18.0
    return QSizeF(float(lead + text_w + 18.0), 50.0)


def natural_size(state: KeyLockState | None = None) -> QSizeF:
    """Retorna o tamanho natural do card baseado no texto do rótulo."""
    if state is None:
        return card_size(DEFAULT_THEME, "Caps Lock")
    return card_size(state.theme, state.label)


def paint_keylock(p: QPainter, rect: QRectF, s: KeyLockState, theme: Any = None):
    """
    Função pura de pintura do card OSD de Caps/Num Lock.
    Não depende de timers, janelas ou chamadas de SO.
    """
    p.save()
    p.setRenderHints(
        QPainter.RenderHint.Antialiasing
        | QPainter.RenderHint.TextAntialiasing
        | QPainter.RenderHint.SmoothPixmapTransform
    )

    x0 = rect.x()
    y0 = rect.y()
    card_w = rect.width()
    card_h = rect.height()
    th = s.theme
    card_radius = th.radius

    card_rect = QRectF(x0, y0, card_w, card_h)

    # 1. Sombra suave externa (se solicitada): a do tema, ou a original
    if s.draw_shadow and th.shadow is not None:
        paint_card_shadow(p, card_rect, card_radius, th.shadow)
    elif s.draw_shadow:
        for i in range(1, 5):
            sh_rect = card_rect.adjusted(-i * 1.5, -i * 1.0 + 1.5, i * 1.5, i * 1.8 + 1.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(28 / i)))
            p.drawRoundedRect(sh_rect, card_radius + i, card_radius + i)

    # Figurinhas com `state` acendem/apagam junto com a animação da tecla (0 = desligada, 1 = ligada)
    on_amount = max(0.0, min(1.0, s.anim_val))
    # O cadeado, o texto e a barrinha foram desenhados para 50 de altura: num cartão de outro tamanho ficam centralizados
    cy0 = y0 + (card_h - 50.0) / 2.0

    # 1.1 Figurinhas "behind": atrás do card (só a parte que sai pelas bordas aparece)
    if th.stickers:
        paint_stickers_behind(p, card_rect, th.stickers, on_amount)

    # 2. Fundo do Card e Borda 1px
    bg_rect = card_rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.setBrush(th.card_bg)
    p.setPen(QPen(th.border, 1.0))
    p.drawRoundedRect(bg_rect, card_radius, card_radius)

    # 2.1 Imagem de fundo (por cima do fundo liso, por baixo do conteúdo) e figurinhas "below"
    if th.background is not None:
        paint_background(p, card_rect, th.background, card_radius)
    if th.stickers:
        paint_stickers(p, card_rect, th.stickers, above=False, on_amount=on_amount)

    # 3. Cadeado Vetorial
    if th.show_icon:
        _draw_padlock(p, x0, cy0, s)

    # 4. Texto do Rótulo ("Caps Lock" / "Num Lock"): cor interpolada entre text_off e text se o tema definir text_off
    t = max(0.0, min(1.0, s.anim_val))
    text_color = th.text
    if th.text_off is not None:
        off, on = th.text_off, th.text
        text_color = QColor(
            int(round(off.red() + (on.red() - off.red()) * t)),
            int(round(off.green() + (on.green() - off.green()) * t)),
            int(round(off.blue() + (on.blue() - off.blue()) * t)),
            int(round(off.alpha() + (on.alpha() - off.alpha()) * t)),
        )
    p.setPen(text_color)
    p.setFont(get_label_font(th))
    label = display_label(s.label, th)
    if th.label_align == "center":
        text_rect = QRectF(x0 + 8.0, y0, max(10.0, card_w - 16.0), card_h)
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    else:
        lead = 18.0 + 14.0 + 15.0 if th.show_icon else 18.0
        text_w = card_w - (lead + 18.0)
        if th.indicator == "none":     # sem a barrinha embaixo, o texto fica no meio da altura
            text_rect = QRectF(x0 + lead, y0, max(10.0, text_w), card_h)
        else:
            text_rect = QRectF(x0 + lead, cy0 + 12.0, max(10.0, text_w), 20.0)
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    p.drawText(text_rect, flags, label)

    # 5. Barra Indicadora Inferior (LED Pill)
    # OFF: largura 36px, cor th.off_color (padrão #29414d)
    # ON:  largura 60px, cor th.on_color  (padrão #4cc2ff)
    if th.indicator == "bar":
        pill_w = 36.0 + (60.0 - 36.0) * t
        pill_h = 3.0
        pill_x = x0 + (card_w - pill_w) * 0.5
        pill_y = cy0 + 41.0

        off, on = th.off_color, th.on_color
        pill_color = QColor(
            int(round(off.red() + (on.red() - off.red()) * t)),
            int(round(off.green() + (on.green() - off.green()) * t)),
            int(round(off.blue() + (on.blue() - off.blue()) * t)),
            int(round(off.alpha() + (on.alpha() - off.alpha()) * t)),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pill_color)
        p.drawRoundedRect(QRectF(pill_x, pill_y, pill_w, pill_h), 1.5, 1.5)

    # 6. Figurinhas "above" (por cima de tudo)
    if th.stickers:
        paint_stickers(p, card_rect, th.stickers, above=True, on_amount=on_amount)

    p.restore()


def _draw_padlock(p: QPainter, x0: float, y0: float, s: KeyLockState):
    """Desenha a geometria do cadeado mecânico com base nas propriedades de haste e corpo."""
    pen = QPen(s.theme.icon, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Corpo do cadeado: 13x11px centrado em x = x0 + 25.0
    body_top = y0 + 18.5 + s.body_recoil
    body_rect = QRectF(x0 + 18.5, body_top, 13.0, 11.0)
    p.drawRoundedRect(body_rect, 2.3, 2.3)

    # Ponto da fechadura no centro do corpo
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(s.theme.icon)
    p.drawEllipse(QPointF(x0 + 25.0, body_top + 5.7), 1.3, 1.3)

    # Haste superior (Shackle)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    arch_cx = x0 + 25.0 + s.shackle_x_shift
    arch_r = 3.2
    arch_top = y0 + 13.5 + s.shackle_lift + s.body_recoil
    arch_cy = arch_top + arch_r

    left_x = arch_cx - arch_r
    right_x = arch_cx + arch_r
    right_bottom_y = body_top
    left_bottom_y = body_top - s.left_leg_gap

    shackle_path = QPainterPath()
    if left_bottom_y > arch_cy:
        shackle_path.moveTo(left_x, left_bottom_y)
        shackle_path.lineTo(left_x, arch_cy)
    else:
        shackle_path.moveTo(left_x, arch_cy)

    arc_rect = QRectF(left_x, arch_top, arch_r * 2.0, arch_r * 2.0)
    shackle_path.arcTo(arc_rect, 180.0, -180.0)
    shackle_path.lineTo(right_x, right_bottom_y)

    p.drawPath(shackle_path)
