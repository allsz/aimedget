"""
Miniatura de um TEMA do Timer (skin Aimedget) para a galeria do Hub.

Usa a função pura `paint_windows_timer`: não cria janela nem mexe no Timer vivo. As cores do tema são aplicadas
por cima das do Hub em uso (como no widget), então um tema parcial aparece claro ou escuro conforme o app.
A miniatura inclui a margem transparente que o tema pede (figurinhas que passam da borda), como o widget de verdade.
"""

from PySide6.QtCore import QRectF, QSizeF

from app.core.preview_registry import SkinSpec
from app.core.widget_theme import art_margin_px
from app.hub.theme import THEME_DARK
from app.widgets.timer.skins.skin import DEFAULT_SIZE, SHADOW_PAD, TimerState, paint_windows_timer
from app.widgets.timer.theme import TimerTheme

WIDGET_ID = "timer_theme"


def _margin(theme: TimerTheme) -> int:
    card = DEFAULT_SIZE - 2 * SHADOW_PAD
    return art_margin_px(theme.stickers, card, card, k=1.0, free=SHADOW_PAD)


def _natural(theme: TimerTheme) -> QSizeF:
    side = DEFAULT_SIZE + 2 * _margin(theme)
    return QSizeF(side, side)


def _paint(p, rect: QRectF, theme: TimerTheme, hub_theme=None):
    hub = hub_theme or THEME_DARK
    m = float(_margin(theme))
    paint_windows_timer(p, rect.adjusted(m, m, -m, -m), TimerState(current_seconds=300.0), theme.apply_to(hub),
                        art=theme)


def make_theme_spec(theme_id: str, title: str, theme: TimerTheme) -> SkinSpec:
    return SkinSpec(
        id=theme_id, widget_id=WIDGET_ID, title=title, subtitle="",
        natural_size=_natural, paint=_paint, mock_state=lambda: theme,
    )
