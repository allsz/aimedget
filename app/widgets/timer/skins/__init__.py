"""
Skins do Timer Widget.
"""

from app.widgets.timer.skins.base_skin import BaseTimerSkin
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
from app.widgets.timer.skins.shinra_skin import ShinraTimerSkin
from app.widgets.timer.skins.specs import init_timer_skin_specs

__all__ = ["BaseTimerSkin", "WindowsTimerSkin", "ShinraTimerSkin", "init_timer_skin_specs"]
