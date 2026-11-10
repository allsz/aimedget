"""
Especificações declarativas para as Skins do Timer & Focus Widget.
Permite renderizar miniaturas vetoriais reais e precisas no Hub,
com zero timers ativos e sem overhead de CPU.
"""

import math
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen

from app.core.preview_registry import SkinSpec, get_skins_for_widget, register_skin
from app.core.typography import get_ui_font
from app.hub.theme import HubTheme, THEME_DARK
from app.widgets.timer.skins.skin import TimerState, paint_windows_timer, natural_size


def paint_notion_timer(
    p: QPainter,
    rect: QRectF,
    state: TimerState | None = None,
    theme: HubTheme | None = None,
):
    """Pintura vetorial para a skin Notion Minimal."""
    if theme is None:
        theme = THEME_DARK

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    pad = 8.0
    card = QRectF(rect.x() + pad, rect.y() + pad, rect.width() - 2 * pad, rect.height() - 2 * pad)

    # 1. Superfície do card Notion
    p.setPen(QPen(QColor(theme.line), 1.0))
    p.setBrush(QBrush(QColor(theme.panel)))
    p.drawRoundedRect(card, 12.0, 12.0)

    # 2. Rótulo superior minimalista
    p.setFont(get_ui_font(9, QFont.Weight.Medium))
    p.setPen(QColor(theme.mute))
    p.drawText(
        QRectF(card.left(), card.top() + 14, card.width(), 16),
        Qt.AlignmentFlag.AlignCenter,
        "NOTION FOCUS",
    )

    # 3. Dígitos digitais mono/clean
    p.setFont(get_ui_font(23, QFont.Weight.Medium))
    p.setPen(QColor(theme.text))
    p.drawText(
        QRectF(card.left(), card.top() + 38, card.width(), 36),
        Qt.AlignmentFlag.AlignCenter,
        "25:00",
    )

    # 4. Botão Pill Minimalista
    btn_w = 78.0
    btn_h = 26.0
    btn_rect = QRectF(
        card.center().x() - btn_w / 2.0,
        card.bottom() - btn_h - 14.0,
        btn_w,
        btn_h,
    )
    p.setPen(QPen(QColor(theme.line), 1.0))
    p.setBrush(QBrush(QColor(theme.panel2)))
    p.drawRoundedRect(btn_rect, 6.0, 6.0)

    p.setFont(get_ui_font(10.5, QFont.Weight.Medium))
    p.setPen(QColor(theme.text))
    p.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "▶ Iniciar")

    p.restore()


def paint_focus_ring_timer(
    p: QPainter,
    rect: QRectF,
    state: TimerState | None = None,
    theme: HubTheme | None = None,
):
    """Pintura vetorial para a skin Focus Ring (Círculo de progresso fluído)."""
    if theme is None:
        theme = THEME_DARK

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    pad = 8.0
    card = QRectF(rect.x() + pad, rect.y() + pad, rect.width() - 2 * pad, rect.height() - 2 * pad)

    # 1. Superfície do card
    p.setPen(QPen(QColor(theme.line), 1.0))
    p.setBrush(QBrush(QColor(theme.panel)))
    p.drawRoundedRect(card, 16.0, 16.0)

    # 2. Anel radial de foco
    ring_center = QPointF(card.center().x(), card.top() + 58.0)
    ring_radius = 34.0
    ring_box = QRectF(
        ring_center.x() - ring_radius,
        ring_center.y() - ring_radius,
        ring_radius * 2.0,
        ring_radius * 2.0,
    )

    # Pista de fundo do anel
    track_pen = QPen(QColor(theme.panel2), 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(track_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(ring_box)

    # Arco ativo de progresso (75% decorrido)
    prog_pen = QPen(QColor(theme.accent), 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(prog_pen)
    p.drawArc(ring_box, 90 * 16, -260 * 16)

    # Dígitos internos
    p.setFont(get_ui_font(14, QFont.Weight.DemiBold))
    p.setPen(QColor(theme.text))
    p.drawText(ring_box, Qt.AlignmentFlag.AlignCenter, "25:00")

    # 3. Botão circular Play centralizado abaixo do anel
    btn_r = 14.0
    btn_center = QPointF(card.center().x(), card.bottom() - 24.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(theme.accent)))
    p.drawEllipse(btn_center, btn_r, btn_r)

    # Ícone Play
    tri = QPainterPath()
    tx = btn_center.x() - 2.5
    ty = btn_center.y() - 5.0
    tri.moveTo(tx, ty)
    tri.lineTo(tx + 7.5, ty + 5.0)
    tri.lineTo(tx, ty + 10.0)
    tri.closeSubpath()
    p.setBrush(QBrush(QColor(theme.ink)))
    p.drawPath(tri)

    p.restore()


def paint_pomodoro_timer(
    p: QPainter,
    rect: QRectF,
    state: TimerState | None = None,
    theme: HubTheme | None = None,
):
    """Pintura vetorial para a skin Pomodoro Bars (4 blocos de foco)."""
    if theme is None:
        theme = THEME_DARK

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    pad = 8.0
    card = QRectF(rect.x() + pad, rect.y() + pad, rect.width() - 2 * pad, rect.height() - 2 * pad)

    # 1. Superfície do card
    p.setPen(QPen(QColor(theme.line), 1.0))
    p.setBrush(QBrush(QColor(theme.panel)))
    p.drawRoundedRect(card, 16.0, 16.0)

    # 2. Barras indicadoras das 4 sessões Pomodoro
    bar_w = 24.0
    bar_h = 4.0
    bar_gap = 5.0
    total_bars_w = 4 * bar_w + 3 * bar_gap
    start_bar_x = card.center().x() - total_bars_w / 2.0
    bar_y = card.top() + 16.0

    p.setPen(Qt.PenStyle.NoPen)
    for i in range(4):
        bx = start_bar_x + i * (bar_w + bar_gap)
        is_done = (i < 2)  # 2 sessões concluídas no mock
        p.setBrush(QBrush(QColor(theme.accent if is_done else theme.panel2)))
        p.drawRoundedRect(QRectF(bx, bar_y, bar_w, bar_h), 2.0, 2.0)

    # Rótulo de status
    p.setFont(get_ui_font(9, QFont.Weight.DemiBold))
    p.setPen(QColor(theme.accent))
    p.drawText(
        QRectF(card.left(), bar_y + 8.0, card.width(), 16),
        Qt.AlignmentFlag.AlignCenter,
        "SESSÃO 2 DE 4",
    )

    # 3. Dígitos centrais
    p.setFont(get_ui_font(23, QFont.Weight.DemiBold))
    p.setPen(QColor(theme.text))
    p.drawText(
        QRectF(card.left(), card.top() + 44, card.width(), 36),
        Qt.AlignmentFlag.AlignCenter,
        "25:00",
    )

    # 4. Botão circular Play
    btn_r = 14.0
    btn_center = QPointF(card.center().x(), card.bottom() - 22.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(theme.accent)))
    p.drawEllipse(btn_center, btn_r, btn_r)

    tri = QPainterPath()
    tx = btn_center.x() - 2.5
    ty = btn_center.y() - 5.0
    tri.moveTo(tx, ty)
    tri.lineTo(tx + 7.5, ty + 5.0)
    tri.lineTo(tx, ty + 10.0)
    tri.closeSubpath()
    p.setBrush(QBrush(QColor(theme.ink)))
    p.drawPath(tri)

    p.restore()


def init_timer_skin_specs() -> list[SkinSpec]:
    """Inicializa e registra as especificações visuais das skins do Timer Widget."""
    existing = get_skins_for_widget("timer")
    if existing:
        return existing

    def _make_paint(paint_func):
        def _fn(p, rect, state, theme):
            paint_func(p, rect, state or TimerState(current_seconds=300.0), theme)
        return _fn

    specs = [
        SkinSpec(
            id="windows",
            widget_id="timer",
            title="Aimedget Style",
            subtitle="PIP clássico",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_windows_timer),
            mock_state=lambda: TimerState(current_seconds=300.0, mode="timer"),
        ),
        SkinSpec(
            id="notion",
            widget_id="timer",
            title="Notion Minimal",
            subtitle="Em breve",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_notion_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
        ),
        SkinSpec(
            id="focus_wheel",
            widget_id="timer",
            title="Focus Ring",
            subtitle="Em breve",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_focus_ring_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
        ),
        SkinSpec(
            id="pomodoro_bars",
            widget_id="timer",
            title="Pomodoro Bars",
            subtitle="Em breve",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_pomodoro_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
        ),
    ]

    for s in specs:
        register_skin(s)

    return specs
