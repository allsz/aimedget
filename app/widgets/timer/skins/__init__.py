"""
Skins do Timer Widget.
"""

from app.core.skin_packs import discover
from app.widgets.timer.skins.art_skin import make_art_skin_class
from app.widgets.timer.skins.base_skin import BaseTimerSkin
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
from app.widgets.timer.skins.specs import init_timer_skin_specs


def timer_skin_classes() -> dict[str, type[BaseTimerSkin]]:
    """As skins que o Timer pode usar agora: a Padrão e as dos pacotes de skin que estão em disco."""
    classes: dict[str, type[BaseTimerSkin]] = {"windows": WindowsTimerSkin}
    for pack in discover("timer"):
        classes[pack.id] = make_art_skin_class(pack)
    return classes


__all__ = ["BaseTimerSkin", "WindowsTimerSkin", "init_timer_skin_specs", "timer_skin_classes"]
