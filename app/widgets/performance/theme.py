"""
Tema visual (tokens) da skin Nothing Dot do Performance Widget.

Pasta dos temas: %LOCALAPPDATA%/Aimedget/themes/performance/<tema>/theme.json
"""

from app.core.nothing_theme import DEFAULT_NOTHING_THEME, NothingDotTheme, nothing_theme_from_dict
from app.core.theme_loader import ThemeLoader

LABEL = "performance"
PerformanceTheme = NothingDotTheme
DEFAULT_THEME = DEFAULT_NOTHING_THEME


def theme_from_dict(data: dict, base_dir: str | None = None) -> PerformanceTheme:
    return nothing_theme_from_dict(data, base_dir, LABEL)


_loader = ThemeLoader("performance", DEFAULT_THEME, theme_from_dict, LABEL)

theme_path = _loader.path
load_user_theme = _loader.load
reset_cache = _loader.reset
loader = _loader
