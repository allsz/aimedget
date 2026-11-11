"""
Especificação declarativa para o Timer Widget.
Renderização vetorial pura com 0% overhead de CPU e sem instâncias QWidget em memória.
"""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter
from app.core.preview_registry import WidgetSpec, register_widget, get_widget_spec
from app.widgets.timer.skins.skin import TimerState, paint_windows_timer, natural_size


def paint_timer(p: QPainter, rect: QRectF, state, theme):
    paint_windows_timer(p, rect, state or TimerState(current_seconds=300.0), theme)


def init_timer_spec() -> WidgetSpec:
    spec = get_widget_spec("timer")
    if spec:
        return spec
    spec = WidgetSpec(
        id="timer",
        title="Timer & Focus",
        subtitle="Aimedget",
        natural_size=natural_size,
        paint=paint_timer,
        mock_state=lambda: TimerState(current_seconds=300.0),
        category="widget",
    )
    register_widget(spec)
    return spec
