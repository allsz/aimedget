"""
Miniatura de um TEMA do Caps/Num Lock para a galeria do Hub.

Usa a função pura `paint_keylock` com um `KeyLockState` que carrega o tema: não cria janela, não toca no
flyout vivo nem no tema ativo. O tamanho acompanha o flyout real: escala efetiva do tema (com `auto_scale`,
a da tela) e a arte que passa da borda do card (figurinhas e sombra), para nada sair cortado.
"""

import math

from PySide6.QtCore import QRectF, QSizeF

from app.core.preview_registry import SkinSpec
from app.core.theme_art import overflow_margins
from app.widgets.keylock_osd.skin import KeyLockState, natural_size, paint_keylock
from app.widgets.keylock_osd.theme import KeyLockTheme, effective_scale

WIDGET_ID = "keylock_theme"
MIN_PAD = 8.0   # respiro mínimo em volta do card (cabe a sombra original, que não é uma sombra de tema)


def _layout(state: KeyLockState) -> tuple[float, QSizeF, tuple[float, float, float, float]]:
    """(escala, tamanho do card sem escala, margens em px da miniatura: esquerda, topo, direita, base)."""
    th = state.theme
    s = effective_scale(th)
    card = natural_size(state)
    ov = overflow_margins(th.stickers, th.shadow, card.width(), card.height())
    margins = tuple(max(MIN_PAD, math.ceil(v * s)) for v in ov)
    return s, card, margins


def _natural(state: KeyLockState) -> QSizeF:
    s, card, (ml, mt, mr, mb) = _layout(state)
    return QSizeF(card.width() * s + ml + mr, card.height() * s + mt + mb)


def _paint(p, rect: QRectF, state: KeyLockState, _hub_theme=None):
    s, card, (ml, mt, _mr, _mb) = _layout(state)
    p.save()
    p.translate(rect.x() + ml, rect.y() + mt)
    p.scale(s, s)
    paint_keylock(p, QRectF(0.0, 0.0, card.width(), card.height()), state)
    p.restore()


def make_theme_spec(theme_id: str, title: str, theme: KeyLockTheme) -> SkinSpec:
    state = KeyLockState(label="Caps Lock", is_on=True, anim_val=1.0, draw_shadow=True, theme=theme)
    return SkinSpec(
        id=theme_id, widget_id=WIDGET_ID, title=title, subtitle="",
        natural_size=_natural, paint=_paint, mock_state=lambda: state,
    )
