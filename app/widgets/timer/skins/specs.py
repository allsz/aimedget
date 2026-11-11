"""
Especificações declarativas para as Skins do Timer & Focus Widget.
Permite renderizar miniaturas vetoriais reais e precisas no Hub,
com zero timers ativos e sem overhead de CPU.
"""

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from app.core.preview_registry import SkinSpec, get_skins_for_widget, register_skin
from app.hub.theme import HubTheme, THEME_DARK
from app.widgets.timer.skins.skin import TimerState, paint_windows_timer


def paint_tba_timer(
    p: QPainter,
    rect: QRectF,
    state: TimerState | None = None,
    theme: HubTheme | None = None,
):
    """Vaga de uma skin ainda não implementada: só um X desenhado, sem mockup do que virá."""
    if theme is None:
        theme = THEME_DARK

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(theme.mute)
    color.setAlphaF(0.75)
    arm = min(rect.width(), rect.height()) * 0.11
    c = rect.center()
    p.setPen(QPen(color, max(2.0, arm * 0.28), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(c.x() - arm, c.y() - arm), QPointF(c.x() + arm, c.y() + arm))
    p.drawLine(QPointF(c.x() - arm, c.y() + arm), QPointF(c.x() + arm, c.y() - arm))
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
            title="Aimedget",
            subtitle="PIP clássico",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_windows_timer),
            mock_state=lambda: TimerState(current_seconds=300.0, mode="timer"),
        ),
        SkinSpec(
            id="notion",
            widget_id="timer",
            title="TBA",
            subtitle="",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_tba_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
            available=False,
        ),
        SkinSpec(
            id="focus_wheel",
            widget_id="timer",
            title="TBA",
            subtitle="",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_tba_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
            available=False,
        ),
        SkinSpec(
            id="pomodoro_bars",
            widget_id="timer",
            title="TBA",
            subtitle="",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_tba_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
            available=False,
        ),
    ]

    for s in specs:
        register_skin(s)

    return specs
