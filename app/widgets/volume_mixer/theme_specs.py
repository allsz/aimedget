"""
Miniatura de um TEMA do Volume e mixer para a galeria do Hub.

Reaproveita o mixer "headless" (um VolumeMixerFlyout que nunca é mostrado, só desenhado), que é DIFERENTE do
flyout vivo. Aplica o tema nele só durante o desenho e SEMPRE devolve o visual padrão no fim (as outras
miniaturas, como a da Visão geral, esperam o padrão). Só a região do card + a arte que passa da borda é
desenhada, então figurinhas e sombra aparecem sem sobras.
"""

import math

from PySide6.QtCore import QPoint, QRect, QRectF, QSizeF
from PySide6.QtGui import QRegion

from app.core.preview_registry import SkinSpec
from app.core.theme_art import overflow_margins
from app.widgets.volume_mixer.theme import DEFAULT_THEME, MixerTheme

WIDGET_ID = "mixer_theme"
MIN_PAD = 14.0   # mesmo respiro da miniatura do mixer na Visão geral


def _pads(theme: MixerTheme, card: QRectF) -> tuple[float, float, float, float]:
    ov = overflow_margins(theme.stickers, theme.shadow, card.width(), card.height())
    return tuple(max(MIN_PAD, math.ceil(v)) for v in ov)


def _card_size() -> QRectF:
    from app.widgets.volume_mixer.specs import _get_headless_volume_mixer
    return _get_headless_volume_mixer()._card_rect()


def _paint(p, rect: QRectF, theme: MixerTheme, _hub_theme=None):
    from app.widgets.volume_mixer.specs import _get_headless_volume_mixer
    flyout = _get_headless_volume_mixer()
    flyout._apply_theme(theme)
    try:
        card = flyout._card_rect()
        pl, pt, pr, pb = _pads(theme, card)
        source = QRect(int(card.left() - pl), int(card.top() - pt),
                       int(card.width() + pl + pr), int(card.height() + pt + pb))
        p.save()
        flyout.render(p, QPoint(int(rect.x()), int(rect.y())), QRegion(source))
        p.restore()
    finally:
        flyout._apply_theme(DEFAULT_THEME)


def _natural(theme: MixerTheme) -> QSizeF:
    card = _card_size()
    pl, pt, pr, pb = _pads(theme, card)
    return QSizeF(card.width() + pl + pr, card.height() + pt + pb)


def make_theme_spec(theme_id: str, title: str, theme: MixerTheme) -> SkinSpec:
    return SkinSpec(
        id=theme_id, widget_id=WIDGET_ID, title=title, subtitle="",
        natural_size=_natural, paint=_paint, mock_state=lambda: theme,
    )
