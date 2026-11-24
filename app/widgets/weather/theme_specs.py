"""Miniatura de um TEMA do Weather (skin Nothing Dot) para a galeria do Hub."""

from PySide6.QtCore import QRectF, QSizeF

from app.core.preview_registry import SkinSpec
from app.widgets.weather import font_skins
from app.widgets.weather.card_painter import paint_card
from app.widgets.weather.sky_painter import CARD_H, CARD_W
from app.widgets.weather.specs import PREVIEW_NOW, mock_state
from app.widgets.weather.theme import WeatherTheme

WIDGET_ID = "weather_theme"


def _paint(p, rect: QRectF, theme: WeatherTheme, hub_theme=None):
    state = mock_state(skin_id=font_skins.NOTHING_DOT_SKIN)
    scale = min(rect.width() / CARD_W, rect.height() / CARD_H)
    w, h = CARD_W * scale, CARD_H * scale
    target = QRectF(rect.x() + (rect.width() - w) / 2.0, rect.y() + (rect.height() - h) / 2.0, w, h)
    paint_card(p, target, state, PREVIEW_NOW, nothing_theme=theme, hub_theme=hub_theme)


def make_theme_spec(theme_id: str, title: str, theme: WeatherTheme) -> SkinSpec:
    return SkinSpec(
        id=theme_id,
        widget_id=WIDGET_ID,
        title=title,
        subtitle="",
        natural_size=QSizeF(CARD_W, CARD_H),
        paint=_paint,
        mock_state=lambda: theme,
    )
