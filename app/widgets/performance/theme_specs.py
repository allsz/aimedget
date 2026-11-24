"""Miniatura de um TEMA do Performance (skin Nothing Dot) para a galeria do Hub."""

from PySide6.QtCore import QRectF, QSizeF

from app.core.preview_registry import SkinSpec
from app.ui_components.floating_card import CARD_H, CARD_W
from app.widgets.performance.card_painter import paint_performance_card
from app.widgets.performance.card_state import SKIN_NOTHING_DOT
from app.widgets.performance.specs import mock_state
from app.widgets.performance.theme import PerformanceTheme

WIDGET_ID = "performance_theme"


def _paint(p, rect: QRectF, theme: PerformanceTheme, hub_theme=None):
    state = mock_state(skin_id=SKIN_NOTHING_DOT)
    scale = min(rect.width() / CARD_W, rect.height() / CARD_H)
    w, h = CARD_W * scale, CARD_H * scale
    target = QRectF(rect.x() + (rect.width() - w) / 2.0, rect.y() + (rect.height() - h) / 2.0, w, h)
    paint_performance_card(p, target, state, nothing_theme=theme, hub_theme=hub_theme)


def make_theme_spec(theme_id: str, title: str, theme: PerformanceTheme) -> SkinSpec:
    return SkinSpec(
        id=theme_id,
        widget_id=WIDGET_ID,
        title=title,
        subtitle="",
        natural_size=QSizeF(CARD_W, CARD_H),
        paint=_paint,
        mock_state=lambda: theme,
    )
