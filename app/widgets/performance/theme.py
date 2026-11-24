"""
Tema visual (tokens) da skin Nothing Dot do Performance Widget.

Pasta dos temas: %LOCALAPPDATA%/Aimedget/themes/performance/<tema>/theme.json
"""

from app.core.nothing_theme import (
    APP_NOTHING_THEME,
    DEFAULT_NOTHING_THEME,
    NothingDotTheme,
    nothing_theme_from_dict,
)
from app.core.theme_loader import ThemeLoader
from app.hub.theme import HubTheme

LABEL = "performance"
PerformanceTheme = NothingDotTheme
DEFAULT_THEME = DEFAULT_NOTHING_THEME


def theme_from_dict(data: dict, base_dir: str | None = None) -> PerformanceTheme:
    return nothing_theme_from_dict(data, base_dir, LABEL)


# "Aimedget" fica na galeria, mas o visual de uma instalação nova continua o Nothing escuro com vermelho
_loader = ThemeLoader("performance", DEFAULT_THEME, theme_from_dict, LABEL,
                      app_theme=lambda: APP_NOTHING_THEME, app_is_default=False)

_live_hub: HubTheme | None = None


def live_hub_theme() -> HubTheme:
    """Aparência do app para o widget vivo, guardada entre quadros (ler a do sistema a cada quadro sairia caro)."""
    global _live_hub
    if _live_hub is None:
        from app.core.app_theme import current_hub_theme
        _live_hub = current_hub_theme()
    return _live_hub


def invalidate_live_hub_theme() -> HubTheme | None:
    """O app trocou de modo ou de destaque: o próximo quadro relê. Devolve a aparência que estava guardada."""
    global _live_hub
    old, _live_hub = _live_hub, None
    return old


theme_path = _loader.path
load_user_theme = _loader.load
reset_cache = _loader.reset
loader = _loader
