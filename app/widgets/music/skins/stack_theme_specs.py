"""
Miniatura de um TEMA da Capa Empilhada para a galeria do Hub.

Reaproveita a skin "headless" da galeria de skins (nunca mostrada, só desenhada): aplica o tema só durante o
desenho e SEMPRE devolve o visual original no fim (a miniatura da skin espera o original). A miniatura inclui a
margem transparente que o tema pede (figurinhas que passam da borda do cartão), como o widget de verdade.
"""

from contextlib import contextmanager

from PySide6.QtCore import QPoint, QRectF, QSizeF

from app.core.preview_registry import SkinSpec
from app.widgets.music.skins import stack_theme

WIDGET_ID = "music_theme"


def _headless():
    from app.widgets.music.skins.specs import _get_headless

    def load():
        from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
        return CapaEmpilhadaSkin

    return _get_headless("capa_empilhada", load)


@contextmanager
def _themed(theme: stack_theme.StackTheme):
    """A skin headless com `theme` aplicado (paleta, margem e hitboxes); devolve tudo ao original no fim."""
    skin = _headless()
    saved = (skin.skin_theme, skin.pastel_theme, skin.target_pastel_theme)
    try:
        skin.skin_theme = theme
        skin.pastel_theme = skin.target_pastel_theme = skin._palette_for(None)
        skin._apply_art_margin()
        yield skin
    finally:
        skin.skin_theme, skin.pastel_theme, skin.target_pastel_theme = saved
        skin._apply_art_margin()


def _paint(p, rect: QRectF, theme: stack_theme.StackTheme, _hub_theme=None):
    with _themed(theme) as skin:
        skin.render(p, QPoint(int(rect.x()), int(rect.y())))


def _natural(theme) -> QSizeF:
    with _themed(theme) as skin:
        return QSizeF(skin.width(), skin.height())


def make_theme_spec(theme_id: str, title: str, theme: stack_theme.StackTheme) -> SkinSpec:
    return SkinSpec(
        id=theme_id, widget_id=WIDGET_ID, title=title, subtitle="",
        natural_size=_natural, paint=_paint, mock_state=lambda: theme,
    )
