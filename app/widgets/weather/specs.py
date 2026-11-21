"""
Miniaturas do Weather Widget para o Hub (cartão da Personalização e galeria de skins).

Usa o mesmo `paint_card` do widget vivo, com um estado de exemplo e o tempo parado: nenhum timer, nenhuma rede.
"""

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QPainter

from app.core.i18n import t
from app.core.preview_registry import SkinSpec, WidgetSpec, get_widget_spec, register_skin, register_widget
from app.widgets.weather import conditions as cond
from app.widgets.weather import font_skins
from app.widgets.weather.card_painter import paint_card
from app.widgets.weather.card_state import PAST, CardState, DayView
from app.widgets.weather.sky_painter import CARD_H, CARD_W

PREVIEW_NOW = 3.2   # instante fixo da miniatura (a deriva e as gotas param num ponto bonito)


def mock_state(font_family: str = "", skin_id: str = font_skins.DEFAULT_SKIN) -> CardState:
    if skin_id == font_skins.MIDNIGHT_SKIN:
        now_lbl = t("weather_now")
        sample = (
            (now_lbl, now_lbl, cond.SUNNY, 26, 28, 18),
            ("16h", "16:00", cond.SUNNY, 28, 28, 18),
            ("19h", "19:00", cond.CLOUDY, 22, 28, 18),
            ("22h", "22:00", cond.CLEAR_NIGHT, 19, 28, 18),
            ("01h", "01:00", cond.CLEAR_NIGHT, 18, 28, 18),
        )
        days = [DayView(sh, fl, c, tp, hi, lo) for sh, fl, c, tp, hi, lo in sample]
    else:
        short = [t(f"weather_wd_short_{i}") for i in range(7)]
        full = [t(f"weather_wd_{i}") for i in range(7)]
        sample = ((cond.SUNNY, 24, 26, 17), (cond.CLOUDY, 19, 21, 14), (cond.LIGHT_RAIN, 16, 18, 12),
                  (cond.THUNDERSTORM, 15, 17, 11), (cond.SUNNY, 22, 25, 15))
        days = [DayView(short[i], full[i], c, tp, hi, lo) for i, (c, tp, hi, lo) in enumerate(sample)]
    state = CardState(font_family=font_family, skin_id=skin_id, animated=False)
    names = {key: t(f"weather_cond_{key}") for key in cond.ALL_CONDITIONS}
    state.set_days("San Francisco", days, names, PAST, animate=False)
    return state


def paint_weather(p: QPainter, rect: QRectF, state, theme=None):
    """Encaixa o cartão (300:262) no retângulo, centralizado."""
    state = state or mock_state()
    scale = min(rect.width() / CARD_W, rect.height() / CARD_H)
    w, h = CARD_W * scale, CARD_H * scale
    target = QRectF(rect.x() + (rect.width() - w) / 2, rect.y() + (rect.height() - h) / 2, w, h)
    paint_card(p, target, state, PREVIEW_NOW)


def init_weather_spec() -> WidgetSpec:
    spec = get_widget_spec("weather")
    if spec:
        return spec
    spec = WidgetSpec(
        id="weather",
        title="Weather",
        subtitle="Aimedget",
        natural_size=QSizeF(CARD_W, CARD_H),
        paint=paint_weather,
        mock_state=mock_state,
        category="widget",
    )
    register_widget(spec)
    return spec


def init_weather_skin_specs() -> list:
    """Uma skin por fonte (relê a pasta de fontes a cada chamada) + uma vaga TBA enquanto só houver a padrão."""
    skins = font_skins.discover()
    specs = []
    for skin in skins:
        family = skin.family
        sid = skin.id
        specs.append(SkinSpec(
            id=skin.id,
            widget_id="weather",
            title=t("weather_skin_glass") if skin.id == font_skins.DEFAULT_SKIN else skin.title,
            subtitle="",
            natural_size=QSizeF(CARD_W, CARD_H),
            paint=paint_weather,
            mock_state=lambda f=family, s=sid: mock_state(f, s),
        ))
    if len(skins) == 1:
        from app.widgets.timer.skins.specs import paint_tba_timer
        specs.append(SkinSpec(
            id="weather_font_tba",
            widget_id="weather",
            title="TBA",
            subtitle="",
            natural_size=QSizeF(CARD_W, CARD_H),
            paint=lambda p, rect, state, theme: paint_tba_timer(p, rect, None, theme),
            mock_state=lambda: None,
            available=False,
        ))
    for s in specs:
        register_skin(s)
    return specs
