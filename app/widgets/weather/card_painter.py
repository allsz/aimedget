"""
Pintura do cartão de clima inteiro (fundo, textos, ícone, abas dos dias), compartilhada pelo widget vivo e pela
miniatura do Hub. Medidas em px do cartão de referência (300 x 262, `.wx` do CSS); `paint_card` escala para o
retângulo pedido.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap

from app.core.i18n import t
from app.core import typography
from app.ui_components.dot_matrix import NOTHING_BG, NOTHING_RED, draw_dot_text, draw_dot_weather_icon, measure_dot_text
from app.widgets.weather import conditions as cond
from app.widgets.weather import font_skins
from app.widgets.weather import motion as mo
from app.widgets.weather.card_state import CardState
from app.widgets.weather.icons import DROPS_TOP_UNITS, DROPS_WIDTH_UNITS, icon_pixmap
from app.widgets.weather.sky_painter import CARD_H, CARD_W, paint_sky, paint_sky_particles, paint_sky_soft

RADIUS = 27.0
PAD = 24.0
WHITE = QColor(255, 255, 255)
SUN_COLOR = QColor("#ffd75e")
MUTED_ALPHA = 0.8          # --wx-muted
TAB_MUTED_ALPHA = 0.78     # --tabs-text-muted

# Geometria (topo de cada linha, como no CSS)
PLACE_TOP, PLACE_LH = 24.0, 22.0
DAY_TOP, DAY_LH = 46.0, 16.0
HERO_TOP, HERO_LH = 70.0, 70.0
ICON_BOX = 64.0
ICON_SIZE = 48.0
COND_TOP, COND_LH = 144.0, 20.0
HL_TOP, HL_LH = 164.0, 16.0
BAR = QRectF(12.0, 196.0, 276.0, 54.0)
BAR_PAD, TAB_GAP, TAB_H = 3.0, 3.0, 48.0
TAB_ICON = 16.0


def tab_width(count: int = 5) -> float:
    n = max(1, count)
    return (BAR.width() - 2 * BAR_PAD - (n - 1) * TAB_GAP) / n


def tab_rect(i: int, count: int = 5) -> QRectF:
    w = tab_width(count)
    return QRectF(BAR.x() + BAR_PAD + i * (w + TAB_GAP), BAR.y() + BAR_PAD, w, TAB_H)


def _font(family: str, px: float, weight: QFont.Weight = QFont.Weight.Normal, tabular: bool = False) -> QFont:
    return typography.card_font(px, weight, tabular, family=family)


def _baseline(top: float, line_h: float, fm: QFontMetricsF) -> float:
    return top + (line_h - (fm.ascent() + fm.descent())) / 2.0 + fm.ascent()


def _white(alpha: float) -> QColor:
    c = QColor(WHITE)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def card_path(w: float = CARD_W, h: float = CARD_H) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), RADIUS, RADIUS)
    return path


SOFT_LAYER_SCALE = 0.5   # px da camada suave do céu por px lógico do cartão (é só gradiente: ampliar não perde nada)


def paint_card(
    p: QPainter,
    rect: QRectF,
    state: CardState,
    now: float,
    cache: dict | None = None,
    nothing_theme=None,
):
    """
    Desenha o cartão em `rect` (proporção 300:262).

    `cache` (o widget vivo passa um dict seu): o céu suave é desenhado numa imagem pequena reaproveitada e ampliado, e
    textos + abas ficam num pixmap enquanto nenhuma troca está em curso. Sem `cache` (miniatura do Hub), tudo é
    desenhado direto, em resolução cheia.
    """
    s = rect.width() / CARD_W
    dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    # Canto do cartão num pixel inteiro da tela: o pixmap de textos é colado sem reamostrar (nítido e sem deslocar)
    origin = p.transform().map(rect.topLeft())
    snapped = QPointF(round(origin.x() * dpr) / dpr, round(origin.y() * dpr) / dpr)
    rect = QRectF(rect.topLeft() + (snapped - origin), rect.size())
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.translate(rect.topLeft())
    p.scale(s, s)
    p.setClipPath(card_path())

    if font_skins.is_nothing_skin(state.skin_id):
        from app.widgets.weather.theme import load_user_theme as _load_weather_theme
        nt = nothing_theme if nothing_theme is not None else _load_weather_theme()
        _paint_nothing_dot_card(p, state, now, nt)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(nt.border, 1.0 / s))
        inset = 0.5 / s
        p.drawRoundedRect(QRectF(inset, inset, CARD_W - 2 * inset, CARD_H - 2 * inset), RADIUS, RADIUS)
        p.restore()
        return

    if state.skin_id == font_skins.MIDNIGHT_SKIN:
        _paint_midnight_card(p, state, now, s, dpr)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_white(0.10), 1.0 / s))
        inset = 0.5 / s
        p.drawRoundedRect(QRectF(inset, inset, CARD_W - 2 * inset, CARD_H - 2 * inset), RADIUS, RADIUS)
        p.restore()
        return

    _paint_backdrop(p, state, now, cache)
    if cache is not None:
        # Sempre pelo mesmo caminho (pixmap): trocar entre pixmap parado e desenho direto durante as animações
        # mudava a renderização das letras por um instante e o texto parecia "pular" a cada clique.
        _paint_cached_foreground(p, state, now, s, dpr, cache, force=state.transitions_busy(now))
    else:
        _paint_texts(p, state, now)
        _paint_tabs(p, state, now, s, dpr)
    _paint_big_icon(p, state, now, s, dpr)

    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_white(0.10), 1.0 / s))   # anel de 1 px (separa o cartão de fundos da mesma cor)
    inset = 0.5 / s
    p.drawRoundedRect(QRectF(inset, inset, CARD_W - 2 * inset, CARD_H - 2 * inset), RADIUS, RADIUS)
    p.restore()


# --- Skin Midnight (gradiente atmosférico dinâmico por condição + barra fosca com animações) ---

_MIDNIGHT_SKIES = {
    cond.SUNNY:         ("#244c80", "#2f6199", "#1d3352"),
    cond.PARTLY_CLOUDY: ("#2a476b", "#385980", "#213146"),
    cond.CLOUDY:        ("#323d4c", "#404c5c", "#262d39"),
    cond.FOG:           ("#3c4650", "#4b5661", "#2d343d"),
    cond.LIGHT_RAIN:    ("#22364d", "#2d4662", "#192636"),
    cond.HEAVY_RAIN:    ("#1a273a", "#24354c", "#121b28"),
    cond.THUNDERSTORM:  ("#1c1e36", "#282b4a", "#121424"),
    cond.SNOW:          ("#37506a", "#4a6886", "#293c50"),
    cond.CLEAR_NIGHT:   ("#1d2e4a", "#263d5e", "#1a2234"),
}


def _paint_midnight_sky_layer(p: QPainter, condition: str, now: float, animated: bool, opacity: float):
    from PySide6.QtGui import QLinearGradient

    if opacity <= 0.005:
        return
    c0, c1, c2 = _MIDNIGHT_SKIES.get(condition, _MIDNIGHT_SKIES[cond.CLEAR_NIGHT])
    card_r = QRectF(0.0, 0.0, CARD_W, CARD_H)
    p.save()
    p.setOpacity(p.opacity() * opacity)
    grad = QLinearGradient(0.0, 0.0, CARD_W * 0.35, CARD_H)
    grad.setColorAt(0.0, QColor(c0))
    grad.setColorAt(0.45, QColor(c1))
    grad.setColorAt(1.0, QColor(c2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRect(card_r)
    scene = cond.SCENES.get(condition)
    if scene is not None:
        paint_sky_particles(p, scene, now, animated, opacity=0.45)
    p.restore()


def _draw_midnight_icon(p: QPainter, icon_key: str, icon_rect: QRectF, s: float, dpr: float, opacity: float, scale: float):
    from PySide6.QtGui import QRadialGradient

    if opacity <= 0.01:
        return
    p.save()
    p.setOpacity(p.opacity() * opacity)
    c = icon_rect.center()
    p.translate(c)
    p.scale(scale, scale)
    p.translate(-c)
    if icon_key == "sun":
        glow = QRadialGradient(icon_rect.center(), 30.0)
        glow.setColorAt(0.0, QColor(255, 190, 70, 115))
        glow.setColorAt(1.0, QColor(255, 190, 70, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(icon_rect.center(), 30.0, 30.0)
        sun = QRadialGradient(icon_rect.left() + 14.0, icon_rect.top() + 14.0, 26.0)
        sun.setColorAt(0.0, QColor("#ffe58f"))
        sun.setColorAt(1.0, QColor("#ffae34"))
        p.setBrush(sun)
        p.drawEllipse(icon_rect.adjusted(2.0, 2.0, -2.0, -2.0))
    else:
        pm = icon_pixmap(icon_key, max(1, int(round(44.0 * s * dpr))), WHITE, SUN_COLOR, 1.8)
        p.drawPixmap(icon_rect, pm, QRectF(pm.rect()))
    p.restore()


def _paint_midnight_card(p: QPainter, state: CardState, now: float, s: float, dpr: float):
    # Fundo dinâmico com crossfade suave por condição (sol, chuva, tempestade, neve, noite)
    sky_p = mo.EASE_IN_OUT(state.sky.progress(now))
    if state.sky.previous is not None and sky_p < 1.0:
        _paint_midnight_sky_layer(p, state.sky.previous, now, state.animated, 1.0 - sky_p)
        _paint_midnight_sky_layer(p, state.sky.current, now, state.animated, sky_p)
    else:
        _paint_midnight_sky_layer(p, state.sky.current, now, state.animated, 1.0)

    if state.message:
        f_msg = _font("", 14.0, QFont.Weight.DemiBold)
        fm_m = QFontMetricsF(f_msg)
        p.setFont(f_msg)
        p.setPen(_white(0.92))
        p.drawText(QPointF(20.0, _baseline(92.0, 22.0, fm_m)), t(state.message))
        if state.message_detail:
            f_det = _font("", 11.5, QFont.Weight.Normal)
            fm_d = QFontMetricsF(f_det)
            p.setFont(f_det)
            p.setPen(_white(0.68))
            p.drawText(QPointF(20.0, _baseline(118.0, 18.0, fm_d)), state.message_detail)
        return

    # 1. Topo esquerdo: Cidade + Dia/Hora
    place_txt, place_dy, place_op = state.place_text.state(now)
    f_city = _font("", 15.0, QFont.Weight.DemiBold)
    fm_city = QFontMetricsF(f_city)
    if place_op > 0.01:
        p.save()
        p.setFont(f_city)
        p.setPen(_white(0.96 * place_op))
        elided_city = fm_city.elidedText(place_txt or "", Qt.TextElideMode.ElideRight, 200.0)
        p.drawText(QPointF(20.0, _baseline(20.0 + place_dy, 19.0, fm_city)), elided_city)
        p.restore()

    day_str = state.day_text.next if hasattr(state.day_text, "next") else (
        state.days[state.selected].full if state.days else ""
    )
    f_day = _font("", 12.0, QFont.Weight.Normal)
    fm_day = QFontMetricsF(f_day)
    if day_str:
        p.setFont(f_day)
        p.setPen(_white(0.75))
        elided_day = fm_day.elidedText(day_str, Qt.TextElideMode.ElideRight, 200.0)
        p.drawText(QPointF(20.0, _baseline(41.0, 16.0, fm_day)), elided_day)

    # 2. Topo direito: Ícone climático com crossfade + escala suave
    icon_rect = QRectF(CARD_W - 20.0 - 44.0, 18.0, 44.0, 44.0)
    ic_p = mo.EASE_IN_OUT(state.icon.progress(now))
    if state.icon.previous is not None and ic_p < 1.0:
        _draw_midnight_icon(p, state.icon.previous, icon_rect, s, dpr, 1.0 - ic_p, 1.0 - 0.14 * ic_p)
        _draw_midnight_icon(p, state.icon.current, icon_rect, s, dpr, ic_p, 0.86 + 0.14 * ic_p)
    else:
        _draw_midnight_icon(p, state.icon.current, icon_rect, s, dpr, 1.0, 1.0)

    # 3. Temperatura hero (52 px)
    temp_str = state.temp.text or ""
    if temp_str:
        f_hero = _font("", 52.0, QFont.Weight.DemiBold, tabular=True)
        fm_hero = QFontMetricsF(f_hero)
        p.setFont(f_hero)
        x_cur = 20.0
        for idx, ch in enumerate(temp_str):
            dy, op = state.temp.char_state(idx, now)
            if op > 0.01:
                p.setPen(_white(op))
                p.drawText(QPointF(x_cur, _baseline(92.0 + dy * 0.6, 56.0, fm_hero)), ch)
            x_cur += fm_hero.horizontalAdvance(ch)
        if not temp_str.endswith("°"):
            p.setPen(_white(1.0))
            p.drawText(QPointF(x_cur, _baseline(92.0, 56.0, fm_hero)), "°")

    # 4. Condição à esquerda + Máx/Mín à direita
    cond_txt, cond_dy, cond_op = state.cond_text.state(now)
    f_meta = _font("", 12.0, QFont.Weight.Medium)
    fm_meta = QFontMetricsF(f_meta)
    p.setFont(f_meta)
    if cond_op > 0.01 and cond_txt:
        p.setPen(_white(0.85 * cond_op))
        p.drawText(QPointF(20.0, _baseline(158.0 + cond_dy * 0.5, 16.0, fm_meta)),
                   fm_meta.elidedText(cond_txt, Qt.TextElideMode.ElideRight, 165.0))

    hi_s = f"{state.hi.text}°" if state.hi.text and not state.hi.text.endswith("°") else state.hi.text
    lo_s = f"{state.lo.text}°" if state.lo.text and not state.lo.text.endswith("°") else state.lo.text
    hl_txt = f"{t('weather_high')}{hi_s}  {t('weather_low')}{lo_s}".strip()
    p.setPen(_white(0.85))
    hl_w = fm_meta.horizontalAdvance(hl_txt)
    p.drawText(QPointF(CARD_W - 20.0 - hl_w, _baseline(158.0, 16.0, fm_meta)), hl_txt)

    # 5. Barra fosca inferior com pílula deslizante e troca em onda de dias/horas
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white(0.10))
    p.drawRoundedRect(BAR, 16.0, 16.0)

    count = len(state.days)
    if count <= 0:
        return

    pill_i = state.pill_position(now)
    tw = tab_width(count)
    pill_x = BAR.x() + BAR_PAD + pill_i * (tw + TAB_GAP)
    pill_r = QRectF(pill_x + 3.0, BAR.y() + 8.0, tw - 6.0, BAR.height() - 16.0)
    p.setBrush(_white(0.18))
    p.drawRoundedRect(pill_r, 12.0, 12.0)

    if 0 <= state.hovered_tab < count and state.hovered_tab != state.selected:
        hr = tab_rect(state.hovered_tab, count)
        p.setBrush(_white(0.07))
        p.drawRoundedRect(QRectF(hr.x() + 3.0, BAR.y() + 8.0, hr.width() - 6.0, BAR.height() - 16.0), 12.0, 12.0)

    tab_e = mo.EASE_SMOOTH_OUT(mo.progress(now, state.pill_t0, mo.TABS_DUR))
    prev_sel = int(round(state.pill_from))
    f_tab = _font("", 11.5, QFont.Weight.Medium, tabular=True)
    f_tab_on = _font("", 11.5, QFont.Weight.DemiBold, tabular=True)
    for i, d in enumerate(state.days):
        tr = tab_rect(i, count)
        active = i == state.selected
        if active:
            alpha = mo.lerp(0.75, 1.0, tab_e)
        elif i == prev_sel and tab_e < 1.0:
            alpha = mo.lerp(1.0, 0.75, tab_e)
        else:
            alpha = 0.75
        if i == state.hovered_tab:
            alpha = 1.0

        f_cur = f_tab_on if active else f_tab
        fm_cur = QFontMetricsF(f_cur)
        p.save()
        if i == state.pressed_tab:
            c = tr.center()
            p.translate(c)
            p.scale(mo.PRESS_SCALE, mo.PRESS_SCALE)
            p.translate(-c)
        swap = state.tab_swap(i, now) if state.animated else None
        text, dy, text_alpha = d.short, 0.0, 1.0
        if swap is not None:
            text, dy, text_alpha = _tab_text_swap(swap[0][0], d.short, swap[1], state.tab_dir)
        p.setFont(f_cur)
        p.setPen(_white(alpha * text_alpha))
        lw = fm_cur.horizontalAdvance(text)
        p.drawText(QPointF(tr.center().x() - lw / 2.0, _baseline(BAR.y(), BAR.height(), fm_cur) + dy), text)
        p.restore()


# --- Skin Nothing Dot (matriz de pontos circular + animações nativas do CardState) ---

def _paint_nothing_dot_card(p: QPainter, state: CardState, now: float, theme):
    from app.core.theme_art import paint_background, paint_stickers

    card_r = QRectF(0.0, 0.0, CARD_W, CARD_H)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.card_bg)
    p.drawRect(card_r)
    if theme.background is not None:
        paint_background(p, card_r, theme.background, RADIUS)
    if theme.stickers:
        paint_stickers(p, card_r, theme.stickers, "below")

    def _tone(base: QColor, alpha_mul: float = 1.0) -> QColor:
        c = QColor(base)
        c.setAlphaF(max(0.0, min(1.0, c.alphaF() * alpha_mul)))
        return c

    if state.message:
        f_msg = _font("", 14.0, QFont.Weight.DemiBold)
        fm_m = QFontMetricsF(f_msg)
        p.setFont(f_msg)
        p.setPen(_tone(theme.text, 0.90))
        msg_txt = t(state.message)
        p.drawText(QPointF(20.0, _baseline(92.0, 22.0, fm_m)), msg_txt)
        if state.message_detail:
            f_det = _font("", 11.5, QFont.Weight.Normal)
            fm_d = QFontMetricsF(f_det)
            p.setFont(f_det)
            p.setPen(theme.muted_text)
            p.drawText(QPointF(20.0, _baseline(118.0, 18.0, fm_d)), state.message_detail)
        return

    # 1. Topo esquerdo: Cidade (sem ponto vermelho à esquerda) + Dia · Condição
    place_txt, place_dy, place_op = state.place_text.state(now)
    f_city = _font("", 12.5, QFont.Weight.DemiBold)
    fm_city = QFontMetricsF(f_city)
    if place_op > 0.01:
        p.save()
        p.setFont(f_city)
        p.setPen(_tone(theme.text, 0.88 * place_op))
        elided_city = fm_city.elidedText((place_txt or "").upper(), Qt.TextElideMode.ElideRight, 198.0)
        p.drawText(QPointF(20.0, _baseline(18.0 + place_dy, 18.0, fm_city)), elided_city)
        p.restore()

    day_str = state.day_text.current if hasattr(state.day_text, "current") else (
        state.days[state.selected].full if state.days else ""
    )
    cond_txt, cond_dy, cond_op = state.cond_text.state(now)
    sub_line = f"{day_str} · {cond_txt}" if (day_str and cond_txt) else (day_str or cond_txt)
    f_sub = _font("", 11.0, QFont.Weight.Normal)
    fm_sub = QFontMetricsF(f_sub)
    if cond_op > 0.01 and sub_line:
        p.save()
        p.setFont(f_sub)
        p.setPen(_tone(theme.muted_text, cond_op))
        elided_sub = fm_sub.elidedText(sub_line, Qt.TextElideMode.ElideRight, 200.0)
        p.drawText(QPointF(20.0, _baseline(37.0 + cond_dy * 0.5, 16.0, fm_sub)), elided_sub)
        p.restore()

    # 2. Topo direito: Ícone climático 9x9 em matriz de pontos com crossfade + escala suave
    icon_rect = QRectF(CARD_W - 20.0 - 46.0, 16.0, 46.0, 46.0)
    ic_p = mo.EASE_IN_OUT(state.icon.progress(now))
    if state.icon.previous is not None and ic_p < 1.0:
        p.save()
        c = icon_rect.center()
        s_out = 1.0 - 0.12 * ic_p
        p.translate(c)
        p.scale(s_out, s_out)
        p.translate(-c)
        draw_dot_weather_icon(p, state.icon.previous, icon_rect, opacity=1.0 - ic_p)
        p.restore()
    p.save()
    c = icon_rect.center()
    s_in = 0.88 + 0.12 * ic_p
    p.translate(c)
    p.scale(s_in, s_in)
    p.translate(-c)
    draw_dot_weather_icon(p, state.icon.current, icon_rect, opacity=ic_p if state.icon.previous else 1.0)
    p.restore()

    # 3. Centro: Temperatura em matriz de pontos circular (dígitos escalonados como no Glass + ° em accent)
    temp_str = state.temp.text or ""
    if temp_str:
        dot_r, gap = 3.0, 7.2
        char_gap = gap * 1.45
        x_cur = 20.0
        last_op = 1.0
        for idx, ch in enumerate(temp_str):
            dy, op = state.temp.char_state(idx, now)
            last_op = op
            cw, _ch = measure_dot_text(ch, dot_r, gap)
            if op > 0.01:
                draw_dot_text(
                    p,
                    ch,
                    QRectF(x_cur, 86.0 + dy * 0.65, cw + 4.0, 62.0),
                    dot_r=dot_r,
                    gap=gap,
                    color=_tone(theme.accent if ch == "°" else theme.dot_on, op),
                    align="left",
                )
            x_cur += cw + char_gap
        if not temp_str.endswith("°") and last_op > 0.01:
            draw_dot_text(
                p,
                "°",
                QRectF(x_cur, 86.0, 28.0, 62.0),
                dot_r=dot_r,
                gap=gap,
                color=_tone(theme.accent, last_op),
                align="left",
            )

    # 4. Direita do centro: Máx/Mín + pontos de paginação de cidades (quando há 2+ cidades)
    hi_s = f"{state.hi.text}°" if state.hi.text and not state.hi.text.endswith("°") else state.hi.text
    lo_s = f"{state.lo.text}°" if state.lo.text and not state.lo.text.endswith("°") else state.lo.text
    hl_txt = f"{t('weather_high')}{hi_s}  {t('weather_low')}{lo_s}".strip()
    f_hl = _font("", 11.5, QFont.Weight.Normal, tabular=True)
    fm_hl = QFontMetricsF(f_hl)
    p.setFont(f_hl)
    p.setPen(_tone(theme.text, 0.72))
    hl_w = fm_hl.horizontalAdvance(hl_txt)
    p.drawText(QPointF(CARD_W - 20.0 - hl_w, _baseline(122.0, 16.0, fm_hl)), hl_txt)

    if state.city_count > 1:
        dot_pos = state.city_dot_pos(now) if hasattr(state, "city_dot_pos") else float(state.city_index)
        dot_gap = 5.0
        widths = [10.0 if abs(i - dot_pos) < 0.5 else 4.0 for i in range(state.city_count)]
        total_dw = sum(widths) + dot_gap * (state.city_count - 1)
        dx = CARD_W - 20.0 - total_dw
        dy = 144.0
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(state.city_count):
            dist = max(0.0, 1.0 - abs(i - dot_pos))
            w_i = 4.0 + 6.0 * dist
            p.setBrush(theme.accent if dist > 0.5 else _tone(theme.text, 0.24))
            p.drawRoundedRect(QRectF(dx, dy, w_i, 4.0), 2.0, 2.0)
            dx += w_i + dot_gap

    # 5. Divisória sutil + faixa de 5 dias (mesmo tab_rect do Glass -> hit-test 100% compatível)
    p.setPen(QPen(_tone(theme.text, 0.10), 1.0))
    p.drawLine(QPointF(18.0, BAR.y() - 6.0), QPointF(CARD_W - 18.0, BAR.y() - 6.0))

    count = len(state.days)
    if count <= 0:
        if theme.stickers:
            paint_stickers(p, card_r, theme.stickers, "above")
        return

    pill_i = state.pill_position(now)
    tw = tab_width(count)
    pill_x = BAR.x() + BAR_PAD + pill_i * (tw + TAB_GAP)
    pill_r = QRectF(pill_x, BAR.y() + BAR_PAD, tw, TAB_H)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_tone(theme.text, 0.12))
    p.drawRoundedRect(pill_r, 11.0, 11.0)

    if 0 <= state.hovered_tab < count and state.hovered_tab != state.selected:
        p.setBrush(_tone(theme.text, 0.06))
        p.drawRoundedRect(tab_rect(state.hovered_tab, count), 11.0, 11.0)

    f_wd = _font("", 9.5, QFont.Weight.DemiBold)
    f_tp = _font("", 10.5, QFont.Weight.Medium, tabular=True)
    fm_wd = QFontMetricsF(f_wd)
    fm_tp = QFontMetricsF(f_tp)

    for i, day in enumerate(state.days):
        tr = tab_rect(i, count)
        is_sel = i == state.selected
        p.save()
        if i == state.pressed_tab:
            c = tr.center()
            p.translate(c)
            p.scale(0.95, 0.95)
            p.translate(-c)

        swap = state.tab_swap(i, now) if state.animated else None
        wd_txt, wd_dy, wd_alpha = (day.short or "").upper(), 0.0, 1.0
        if swap is not None:
            raw_t, wd_dy, wd_alpha = _tab_text_swap((swap[0][0] or "").upper(), wd_txt, swap[1], state.tab_dir)
            wd_txt = raw_t
        p.setFont(f_wd)
        base_wd = _tone(theme.text, 0.96) if is_sel else theme.muted_text
        p.setPen(_tone(base_wd, wd_alpha))
        ww = fm_wd.horizontalAdvance(wd_txt)
        p.drawText(QPointF(tr.center().x() - ww * 0.5, _baseline(tr.y() + 3.0, 12.0, fm_wd) + wd_dy), wd_txt)

        draw_dot_weather_icon(
            p,
            day.condition,
            QRectF(tr.center().x() - 8.5, tr.y() + 16.0, 17.0, 17.0),
            opacity=(0.95 if is_sel else 0.65) * wd_alpha,
        )

        tp_txt = f"{int(round(day.temp))}°"
        p.setFont(f_tp)
        p.setPen(_tone(theme.text, (0.96 if is_sel else 0.72) * wd_alpha))
        tp_w = fm_tp.horizontalAdvance(tp_txt)
        p.drawText(QPointF(tr.center().x() - tp_w * 0.5, _baseline(tr.y() + 34.0, 12.0, fm_tp) + wd_dy * 0.5), tp_txt)
        p.restore()

    if theme.stickers:
        paint_stickers(p, card_r, theme.stickers, "above")


# --- Fundo ---

def _sky_layers(state: CardState, now: float) -> list:
    """[(cena, opacidade)] de baixo para cima: durante a troca, a cena antiga cheia e a nova surgindo por cima."""
    if state.message:
        return [(cond.UNAVAILABLE_SCENE, 1.0)]
    sky = state.sky
    fade = mo.EASE_IN_OUT(sky.progress(now))
    if sky.previous is not None and fade < 1.0:
        return [(cond.scene_for(sky.previous), 1.0), (cond.scene_for(sky.current), fade)]
    return [(cond.scene_for(sky.current), 1.0)]


def _paint_backdrop(p: QPainter, state: CardState, now: float, cache: dict | None):
    layers = _sky_layers(state, now)
    if cache is None:
        for scene, opacity in layers:
            paint_sky(p, scene, now, state.animated, opacity)
        return

    w = max(2, int(math.ceil(CARD_W * SOFT_LAYER_SCALE)))
    h = max(2, int(math.ceil(CARD_H * SOFT_LAYER_SCALE)))
    img = cache.get("soft")
    if img is None or img.width() != w or img.height() != h:
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        cache["soft"] = img
    sp = QPainter(img)
    sp.setRenderHint(QPainter.RenderHint.Antialiasing)
    sp.scale(SOFT_LAYER_SCALE, SOFT_LAYER_SCALE)
    for scene, opacity in layers:
        paint_sky_soft(sp, scene, now, state.animated, opacity)
    sp.end()
    p.drawImage(QRectF(0, 0, CARD_W, CARD_H), img)
    for scene, opacity in layers:
        paint_sky_particles(p, scene, now, state.animated, opacity)


def _foreground_key(state: CardState, s: float, dpr: float) -> tuple:
    days = tuple((d.short, d.full, d.condition, d.temp, d.hi, d.lo) for d in state.days)
    return (state.place_text.new, state.city_index, state.city_count, days, state.selected, state.hovered_tab,
            state.pressed_tab, state.message,
            state.message_detail, state.font_family, round(s, 3), round(dpr, 2), t("weather_high"), t("weather_title"))


def _paint_cached_foreground(p: QPainter, state: CardState, now: float, s: float, dpr: float, cache: dict,
                             force: bool = False):
    """
    Textos + abas num pixmap (transparente) no tamanho de tela. Parado, é reaproveitado até algo visível mudar; com
    `force` (alguma troca em curso) é redesenhado a cada quadro, mas pelo mesmo caminho, para as letras não mudarem.
    """
    key = None if force else _foreground_key(state, s, dpr)
    pm = cache.get("fg")
    size = (int(math.ceil(CARD_W * s * dpr)), int(math.ceil(CARD_H * s * dpr)))
    if force or pm is None or cache.get("fg_key") != key:
        if pm is None or (pm.width(), pm.height()) != size or abs(pm.devicePixelRatio() - dpr) > 0.001:
            pm = QPixmap(*size)
            pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        fp = QPainter(pm)
        fp.setRenderHint(QPainter.RenderHint.Antialiasing)
        fp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        fp.scale(s, s)
        _paint_texts(fp, state, now)
        _paint_tabs(fp, state, now, s, dpr)
        fp.end()
        cache["fg"], cache["fg_key"] = pm, key
    p.save()
    p.scale(1.0 / s, 1.0 / s)
    p.drawPixmap(QPointF(0, 0), pm)
    p.restore()


# --- Pontos da lista de cidades ---

DOT = 5.0
DOT_GAP = 5.0
DOT_NAME_GAP = 9.0


def dots_width(count: int) -> float:
    """Largura da fileira de pontos (0 com uma cidade só: o cartão fica igual ao de sempre)."""
    return 0.0 if count < 2 else count * DOT + (count - 1) * DOT_GAP


def _paint_city_dots(p: QPainter, state: CardState, now: float, x: float, cy: float):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white(0.38))
    for i in range(state.city_count):
        p.drawEllipse(QPointF(x + DOT / 2 + i * (DOT + DOT_GAP), cy), DOT / 2, DOT / 2)
    pos = state.dot_position(now)   # o ponto ativo desliza como a pílula dos dias
    p.setBrush(WHITE)
    p.drawEllipse(QPointF(x + DOT / 2 + pos * (DOT + DOT_GAP), cy), DOT / 2, DOT / 2)
    p.restore()


# --- Textos ---

def _paint_texts(p: QPainter, state: CardState, now: float):
    family = state.font_family
    right = CARD_W - PAD

    # Local (troca com direção ao mudar de cidade) + pontos da lista de cidades
    f_place = _font(family, 16, QFont.Weight.Medium)
    fm = QFontMetricsF(f_place)
    p.setFont(f_place)
    dots_w = dots_width(state.city_count)
    max_w = right - PAD - (dots_w + DOT_NAME_GAP if dots_w else 0)
    y_place = _baseline(PLACE_TOP, PLACE_LH, fm)
    swap = state.place_text
    text, dy, alpha = swap.state(now)
    p.setPen(_white(alpha))
    p.drawText(QPointF(PAD, y_place + dy), fm.elidedText(text or t("weather_title"), Qt.TextElideMode.ElideRight, max_w))
    if dots_w:
        def width(s):
            return fm.horizontalAdvance(fm.elidedText(s or t("weather_title"), Qt.TextElideMode.ElideRight, max_w))
        name_w = mo.lerp(width(swap.old), width(swap.new), mo.EASE_SMOOTH_OUT(swap.progress(now)))
        _paint_city_dots(p, state, now, PAD + name_w + DOT_NAME_GAP, PLACE_TOP + PLACE_LH / 2)

    # Dia (morph)
    f_day = _font(family, 12)
    fm = QFontMetricsF(f_day)
    p.setFont(f_day)
    y_day = _baseline(DAY_TOP, DAY_LH, fm)
    if not state.message:
        _paint_day_morph(p, state, now, fm, y_day)

    # Temperatura
    f_temp = _font(family, 60, QFont.Weight.Medium, tabular=True)
    fm = QFontMetricsF(f_temp)
    p.setFont(f_temp)
    y_temp = _baseline(HERO_TOP, HERO_LH, fm)
    if state.message:
        p.setPen(_white(0.85))
        p.drawText(QPointF(PAD, y_temp), "--°")
    else:
        x = _paint_digits(p, state.temp, now, fm, PAD, y_temp)
        p.setPen(WHITE)
        p.drawText(QPointF(x, y_temp), "°")

    # Condição (troca de texto)
    f_cond = _font(family, 13)
    fm = QFontMetricsF(f_cond)
    p.setFont(f_cond)
    y_cond = _baseline(COND_TOP, COND_LH, fm)
    if state.message:
        p.setPen(WHITE)
        p.drawText(QPointF(PAD, y_cond), fm.elidedText(t(state.message), Qt.TextElideMode.ElideRight, right - PAD))
    else:
        text, dy, alpha = state.cond_text.state(now if state.animated else 1e12)
        p.setPen(_white(alpha))
        p.drawText(QPointF(PAD, y_cond + dy), text)

    # Máxima / mínima
    f_hl = _font(family, 12, tabular=True)
    fm = QFontMetricsF(f_hl)
    p.setFont(f_hl)
    y_hl = _baseline(HL_TOP, HL_LH, fm)
    if state.message:
        if state.message_detail:
            p.setPen(_white(MUTED_ALPHA))
            p.drawText(QPointF(PAD, y_hl),
                       fm.elidedText(state.message_detail, Qt.TextElideMode.ElideRight, right - PAD))
        return
    x = PAD
    for piece in (t("weather_high"), state.hi, "° " + t("weather_low"), state.lo, "°"):
        if isinstance(piece, str):
            p.setPen(_white(MUTED_ALPHA))
            p.drawText(QPointF(x, y_hl), piece)
            x += fm.horizontalAdvance(piece)
        else:
            x = _paint_digits(p, piece, now, fm, x, y_hl, base_alpha=MUTED_ALPHA)


def _paint_digits(p: QPainter, group, now: float, fm: QFontMetricsF, x: float, y: float,
                  base_alpha: float = 1.0) -> float:
    for i, ch in enumerate(group.text):
        dy, alpha = group.char_state(i, now)
        p.setPen(_white(alpha * base_alpha))
        p.drawText(QPointF(x, y + dy), ch)
        x += fm.horizontalAdvance(ch)
    return x


def _paint_day_morph(p: QPainter, state: CardState, now: float, fm: QFontMetricsF, y: float):
    morph = state.day_text
    prefix, old_mid, new_mid, suffix = morph.parts()
    fade = morph.fade(now)
    width = mo.lerp(fm.horizontalAdvance(old_mid), fm.horizontalAdvance(new_mid), morph.resize(now))
    x = PAD
    p.setPen(_white(MUTED_ALPHA))
    p.drawText(QPointF(x, y), prefix)
    x += fm.horizontalAdvance(prefix)
    if fade < 1.0 and old_mid:
        p.setPen(_white(MUTED_ALPHA * (1.0 - fade)))
        p.drawText(QPointF(x, y), old_mid)
    p.setPen(_white(MUTED_ALPHA * fade))
    p.drawText(QPointF(x, y), new_mid)
    p.setPen(_white(MUTED_ALPHA))
    p.drawText(QPointF(x + width, y), suffix)


# --- Ícone grande ---

def _icon_center() -> QPointF:
    return QPointF(CARD_W - PAD - ICON_BOX / 2, HERO_TOP + HERO_LH / 2)


def _paint_big_icon(p: QPainter, state: CardState, now: float, s: float, dpr: float):
    center = _icon_center()
    if state.message:
        _draw_icon(p, "cloud", center, ICON_SIZE, 2.1, 0.85, 1.0, 0.0, s, dpr)
        return
    swap = state.icon
    e = mo.EASE_IN_OUT(swap.progress(now))
    if swap.previous is not None and e < 1.0:
        prev_scene = cond.scene_for(state.sky.previous) if state.sky.previous else None
        _paint_icon_state(p, swap.previous, prev_scene, now, 1.0 - e, mo.lerp(1.0, mo.ICON_SWAP_START_SCALE, e),
                          center, s, dpr, state.animated)
        _paint_icon_state(p, swap.current, cond.scene_for(state.sky.current), now, e,
                          mo.lerp(mo.ICON_SWAP_START_SCALE, 1.0, e), center, s, dpr, state.animated)
    else:
        _paint_icon_state(p, swap.current, cond.scene_for(state.sky.current), now, 1.0, 1.0, center, s, dpr,
                          state.animated)


def _paint_icon_state(p: QPainter, key: str, scene, now: float, opacity: float, scale: float, center: QPointF,
                      s: float, dpr: float, animated: bool):
    if opacity <= 0.0:
        return
    clock = now if animated else 0.0
    rotation = 0.0
    dy = 0.0
    if key == "sun":
        rotation = (clock / mo.SPIN_DUR) * 360.0 % 360.0
    elif key == "bolt":
        x = (clock % (mo.FLOAT_DUR * 1.5)) / (mo.FLOAT_DUR * 1.5)
        opacity *= mo.keyframes(x, mo.FLICKER_OPACITY, mo.EASE_IN_OUT)
        scale *= mo.keyframes(x, mo.FLICKER_SCALE, mo.EASE_IN_OUT)
    else:
        dy = mo.lerp(-mo.FLOAT_DISTANCE, mo.FLOAT_DISTANCE, mo.alternate(clock, mo.FLOAT_DUR))
    _draw_icon(p, key, QPointF(center.x(), center.y() + dy * scale), ICON_SIZE * scale, 2.1, opacity, 1.0,
               rotation, s, dpr)

    drops = scene.drops if scene is not None and scene.icon == key else (3 if key in ("rain", "snow") else 0)
    if drops and key in ("rain", "snow"):
        _paint_icon_drops(p, drops, scene.drop_kind if scene is not None else "rain", clock, center, opacity,
                          scale, animated)


def _paint_icon_drops(p: QPainter, n: int, kind: str, now: float, center: QPointF, opacity: float, scale: float,
                      animated: bool):
    unit = ICON_SIZE / 24.0
    top = center.y() + (DROPS_TOP_UNITS - 12.0) * unit * scale
    width = DROPS_WIDTH_UNITS * unit * scale
    dur = mo.DROP_DUR * (1.5 if kind == "snow" else 1.0)
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(n):
        x = center.x() - width / 2 + (width * i / (n - 1) if n > 1 else width / 2)
        if animated:
            phase = (now / dur - i / n) % 1.0
            y = top + mo.keyframes(phase, mo.DROP_Y, mo.EASE_IN) * scale
            alpha = mo.keyframes(phase, mo.DROP_OPACITY, mo.EASE_IN)
        else:
            y, alpha = top + 3.0 * scale, 1.0
        p.setBrush(_white(alpha * opacity))
        if kind == "snow":
            r = 1.7 * scale
            p.drawEllipse(QPointF(x + math.sin(now * 3 + i) * 1.2, y + r), r, r)
        else:
            p.drawRoundedRect(QRectF(x - 1.25 * scale, y, 2.5 * scale, 7.0 * scale), 1.25 * scale, 1.25 * scale)
    p.restore()


def _draw_icon(p: QPainter, key: str, center: QPointF, size: float, stroke: float, opacity: float, alpha_color: float,
               rotation: float, s: float, dpr: float, color: QColor = WHITE, warm: QColor | None = None):
    """Desenha o pixmap do ícone em resolução de tela (o pixmap é gerado já no tamanho final, sem reamostrar)."""
    if size <= 0.5 or opacity <= 0.0:
        return
    px = size * s
    pm = icon_pixmap(key, px, color, warm or SUN_COLOR, stroke, dpr)
    p.save()
    p.setOpacity(p.opacity() * opacity * alpha_color)
    p.translate(center)
    if rotation:
        p.rotate(rotation)
    p.scale(1.0 / s, 1.0 / s)
    p.drawPixmap(QPointF(-px / 2, -px / 2), pm)
    p.restore()


# --- Abas dos dias ---

def _paint_tabs(p: QPainter, state: CardState, now: float, s: float, dpr: float):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, int(0.16 * 255)))
    p.drawRoundedRect(BAR, 15.0, 15.0)

    count = 5
    days = state.days
    if not state.message and days:
        pos = state.pill_position(now)
        pill = tab_rect(0, count)
        pill.moveLeft(BAR.x() + BAR_PAD + pos * (tab_width(count) + TAB_GAP))
        p.setBrush(_white(0.2))
        p.drawRoundedRect(pill, 12.0, 12.0)

    f_tab = _font(state.font_family, 12, QFont.Weight.Medium)
    fm = QFontMetricsF(f_tab)
    p.setFont(f_tab)
    tab_e = mo.EASE_SMOOTH_OUT(mo.progress(now, state.pill_t0, mo.TABS_DUR))
    prev_sel = int(round(state.pill_from))
    for i in range(count):
        r = tab_rect(i, count)
        if i < len(days):
            day = days[i]
            label, icon = day.short, cond.TAB_ICON.get(day.condition, "cloud")
        else:
            label, icon = "", None
        if state.message:
            alpha = 0.45
            icon = None
        elif i == state.selected:
            alpha = mo.lerp(TAB_MUTED_ALPHA, 1.0, tab_e)
        elif i == prev_sel and tab_e < 1.0:
            alpha = mo.lerp(1.0, TAB_MUTED_ALPHA, tab_e)
        else:
            alpha = TAB_MUTED_ALPHA
        if i == state.hovered_tab and not state.message:
            alpha = 1.0

        p.save()
        if i == state.pressed_tab:
            c = r.center()
            p.translate(c)
            p.scale(mo.PRESS_SCALE, mo.PRESS_SCALE)
            p.translate(-c)
        content_top = r.y() + (TAB_H - (TAB_ICON + 2 + 16)) / 2
        swap = state.tab_swap(i, now) if (icon and state.animated) else None
        if icon:
            # Nas abas o ícone é da cor do texto (currentColor), sem o amarelo do ícone grande
            _paint_tab_icon(p, icon, swap, QPointF(r.center().x(), content_top + TAB_ICON / 2), alpha, s, dpr)
        label_top = content_top + TAB_ICON + 2 if icon else r.y() + (TAB_H - 16) / 2   # sem ícone: centralizado
        y = _baseline(label_top, 16.0, fm)
        text, dy, text_alpha = label, 0.0, 1.0
        if swap is not None:   # o nome sai para cima e entra de baixo, como a condição
            text, dy, text_alpha = _tab_text_swap(swap[0][0], label, swap[1], state.tab_dir)
        p.setPen(_white(alpha * text_alpha))
        p.drawText(QPointF(r.center().x() - fm.horizontalAdvance(text) / 2, y + dy), text)
        p.restore()
    p.restore()


def _paint_tab_icon(p: QPainter, icon: str, swap, center: QPointF, alpha: float, s: float, dpr: float):
    """Ícone da aba. Trocando: o antigo some encolhendo e o novo cresce (como o ícone grande); se o ícone é o
    mesmo (outra cidade, mesmo tempo), ele só dá um pulinho."""
    if swap is None:
        _draw_icon(p, icon, center, TAB_ICON, 2.25, alpha, 1.0, 0.0, s, dpr, warm=WHITE)
        return
    (_prev_label, prev_icon), f = swap
    fi = min(1.0, f * (2 * mo.TEXT_SWAP_DUR) / mo.ICON_SWAP_DUR)
    e = mo.EASE_IN_OUT(fi)
    if prev_icon != icon:
        _draw_icon(p, prev_icon, center, TAB_ICON * mo.lerp(1.0, mo.ICON_SWAP_START_SCALE, e), 2.25,
                   alpha * (1.0 - e), 1.0, 0.0, s, dpr, warm=WHITE)
        _draw_icon(p, icon, center, TAB_ICON * mo.lerp(mo.ICON_SWAP_START_SCALE, 1.0, e), 2.25, alpha * e, 1.0,
                   0.0, s, dpr, warm=WHITE)
    else:
        dip = math.sin(math.pi * e)   # 0 -> 1 -> 0: encolhe um pouco e volta, sem salto no começo nem no fim
        size = TAB_ICON * mo.lerp(1.0, mo.TAB_SAME_ICON_SCALE, dip)
        _draw_icon(p, icon, center, size, 2.25, alpha * mo.lerp(1.0, 0.45, dip), 1.0, 0.0, s, dpr, warm=WHITE)


def _tab_text_swap(old: str, new: str, f: float, direction: int) -> tuple:
    """(texto, deslocamento y, opacidade) da troca do nome da aba; f = 0..1 da troca inteira (sai + entra)."""
    if f < 0.5:
        q = mo.EASE_IN_OUT(f * 2)
        return old, -mo.TEXT_SWAP_Y * q * direction, 1.0 - q
    q = mo.EASE_IN_OUT(f * 2 - 1)
    return new, mo.TEXT_SWAP_Y * (1.0 - q) * direction, q


WAVE_LEVELS = 12   # a intensidade de cada ponto é arredondada em níveis: um pincel por nível em vez de um por ponto


def paint_dot_wave(p: QPainter, rect: QRectF, progress: float, gap: float = mo.WAVE_GAP, band: float = mo.WAVE_BAND):
    """
    Faixa diagonal de pontos brancos que atravessa o cartão do canto superior esquerdo ao inferior direito
    (o "Passing wave" do protótipo). Cada ponto cresce e some conforme a frente da onda passa por ele.
    """
    if not 0.0 < progress < 1.0:
        return
    s = rect.width() / CARD_W
    front = -band + mo.ease_in_out_cubic(progress) * (1.0 + 2.0 * band)
    r_max = gap * 0.42
    levels = [[] for _ in range(WAVE_LEVELS + 1)]
    diag = CARD_W + CARD_H
    y = gap / 2
    while y < CARD_H + gap:
        # Só a parte da linha que a faixa cobre: |front - d| < band, com d = (x + y) / diag
        x_lo = max(gap / 2, (front - band) * diag - y)
        x_hi = min(CARD_W + gap, (front + band) * diag - y)
        if x_lo < x_hi:
            x = gap / 2 + math.ceil((x_lo - gap / 2) / gap) * gap
            while x < x_hi:
                u = (front - (x + y) / diag) / band
                if abs(u) < 1.0:
                    k = math.cos(u * math.pi / 2)
                    level = int(round(k * WAVE_LEVELS))
                    if level > 0:
                        levels[level].append((x, y))
                x += gap
        y += gap

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.topLeft())
    p.scale(s, s)
    p.setClipPath(card_path())
    p.setPen(Qt.PenStyle.NoPen)
    for level, points in enumerate(levels):
        if not points:
            continue
        k = level / WAVE_LEVELS
        p.setBrush(_white(0.9 * k))
        radius = r_max * k
        for x, y in points:
            p.drawEllipse(QPointF(x, y), radius, radius)
    p.restore()


def tab_at(pos: QPointF) -> int:
    """Índice da aba sob o ponto (em px do cartão de referência), ou -1."""
    for i in range(5):
        if tab_rect(i).contains(pos):
            return i
    return -1
