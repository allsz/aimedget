"""
Módulo Timer Widget - Windows Redesign Suite.
Widget de temporizador e cronômetro com visual Fluent e integração ao Hub.
"""

from app.widgets.timer.timer_controller import TimerWidgetController
from app.widgets.timer.specs import init_timer_spec
from app.widgets.timer.skins.specs import init_timer_skin_specs

__all__ = ["TimerWidgetController", "init_timer_spec", "init_timer_skin_specs"]
