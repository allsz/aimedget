"""
Tema visual (tokens) da skin Nothing Dot do Weather Widget.

Pasta dos temas: %LOCALAPPDATA%/Aimedget/themes/weather/<tema>/theme.json
"""

from app.core.nothing_theme import APP_NOTHING_THEME, DEFAULT_NOTHING_THEME, NothingDotTheme, nothing_theme_from_dict
from app.core.theme_loader import ThemeLoader

LABEL = "weather"
WeatherTheme = NothingDotTheme
DEFAULT_THEME = DEFAULT_NOTHING_THEME


def theme_from_dict(data: dict, base_dir: str | None = None) -> WeatherTheme:
    return nothing_theme_from_dict(data, base_dir, LABEL)


# "Aimedget" fica na galeria, mas o visual de uma instalação nova continua o Nothing escuro com vermelho
_loader = ThemeLoader("weather", DEFAULT_THEME, theme_from_dict, LABEL,
                      app_theme=lambda: APP_NOTHING_THEME, app_is_default=False)

theme_path = _loader.path
load_user_theme = _loader.load
reset_cache = _loader.reset
loader = _loader
