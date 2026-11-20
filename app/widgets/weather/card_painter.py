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
from app.widgets.weather import conditions as cond
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
    f = QFont(family or typography.APP_FONT_FAMILY)
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferQuality | QFont.StyleStrategy.PreferAntialias)
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)   # algarismos de mesma largura (font-variant-numeric: tabular-nums)
        except Exception:
            pass
    return f


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


def paint_card(p: QPainter, rect: QRectF, state: CardState, now: float, cache: dict | None = None):
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
