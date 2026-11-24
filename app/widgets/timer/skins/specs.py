"""
Especificações declarativas para as Skins do Timer & Focus Widget.
Permite renderizar miniaturas vetoriais reais e precisas no Hub,
com zero timers ativos e sem overhead de CPU.
"""

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from functools import partial

from app.core.i18n import i18n, t
from app.core.preview_registry import SkinSpec, get_skins_for_widget, register_skin
from app.hub.theme import HubTheme, THEME_DARK
from app.core.skin_packs import discover
from app.widgets.timer.skins.art_skin import paint_art_timer
from app.widgets.timer.skins.nothing_dot_skin import paint_nothing_dot_timer
from app.widgets.timer.skins.skin import TimerState, paint_windows_timer


def paint_tba_timer(
    p: QPainter,
    rect: QRectF,
    state: TimerState | None = None,
    theme: HubTheme | None = None,
):
    """Vaga de uma skin ainda não implementada: só um X desenhado, sem mockup do que virá."""
    if theme is None:
        theme = THEME_DARK

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(theme.mute)
    color.setAlphaF(0.75)
    arm = min(rect.width(), rect.height()) * 0.11
    c = rect.center()
    p.setPen(QPen(color, max(2.0, arm * 0.28), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(c.x() - arm, c.y() - arm), QPointF(c.x() + arm, c.y() + arm))
    p.drawLine(QPointF(c.x() - arm, c.y() + arm), QPointF(c.x() + arm, c.y() - arm))
    p.restore()


def init_timer_skin_specs() -> list[SkinSpec]:
    """Inicializa e registra as especificações visuais das skins do Timer Widget."""
    existing = get_skins_for_widget("timer")
    if existing:
        return existing

    def _make_paint(paint_func):
        def _fn(p, rect, state, theme):
            paint_func(p, rect, state or TimerState(current_seconds=300.0), theme)
        return _fn

    def _pack_spec(pack) -> SkinSpec:
        title, subtitle = pack.texts(i18n.current_language)
        return SkinSpec(
            id=pack.id,
            widget_id="timer",
            title=title,
            subtitle=subtitle,
            natural_size=QSizeF(164, 164),
            paint=_make_paint(partial(paint_art_timer, pack=pack)),
            mock_state=lambda: TimerState(current_seconds=300.0, mode="timer"),
            supports_themes=False,   # a arte é do pacote: os temas do Timer não se aplicam
        )

    specs = [
        SkinSpec(
            id="windows",
            widget_id="timer",
            title=t("theme_default_timer"),
            subtitle="PIP clássico",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_windows_timer),
            mock_state=lambda: TimerState(current_seconds=300.0, mode="timer"),
        ),
        SkinSpec(
            id="nothing_dot",
            widget_id="timer",
            title="Nothing Dot",
            subtitle=t("skin_nothing_dot_timer_sub"),
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_nothing_dot_timer),
            mock_state=lambda: TimerState(current_seconds=300.0, mode="timer"),
            supports_themes=True,
        ),
        *[_pack_spec(pack) for pack in discover("timer")],   # skins com arte própria: só as que estão em disco
        SkinSpec(
            id="notion",
            widget_id="timer",
            title="TBA",
            subtitle="",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_tba_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
            available=False,
        ),
        SkinSpec(
            id="focus_wheel",
            widget_id="timer",
            title="TBA",
            subtitle="",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_tba_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
            available=False,
        ),
        SkinSpec(
            id="pomodoro_bars",
            widget_id="timer",
            title="TBA",
            subtitle="",
            natural_size=QSizeF(164, 164),
            paint=_make_paint(paint_tba_timer),
            mock_state=lambda: TimerState(current_seconds=1500.0, mode="timer"),
            available=False,
        ),
    ]

    for s in specs:
        register_skin(s)

    return specs
