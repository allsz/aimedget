"""
Pintura do Performance Widget no mesmo cartão de referência (300 x 262, raio 27) do Weather Widget.

Compartilhada entre o widget vivo e a miniatura do Hub (sem timers, pura QPainter).
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

from app.core import typography
from app.core.i18n import t
from app.ui_components.floating_card import CARD_H, CARD_RADIUS, CARD_W, card_path
from app.widgets.performance.card_state import (
    HISTORY_LEN,
    METRIC_COLORS,
    METRIC_LABELS,
    PerformanceState,
)

# Geometria no canvas de referência 300 x 262
HEADER_Y = 18.0
HEADER_H = 22.0

PILL_X = 14.0
PILL_Y0 = 52.0
PILL_W = 108.0
PILL_RADIUS = 12.0

RIGHT_X = 134.0
RIGHT_W = 150.0
HERO_Y = 50.0
HERO_H = 44.0
DETAIL_Y = 98.0
DETAIL_H = 18.0

CHART_RECT = QRectF(RIGHT_X, 126.0, RIGHT_W, 96.0)
FOOTER_Y = 226.0
FOOTER_H = 16.0


def _pill_metrics(count: int) -> tuple[float, float, float]:
    """(y0, height, gap) ajustados para 4 ou 5 pílulas dentro da altura do cartão."""
    if count >= 5:
        return 50.0, 35.0, 5.0
    return PILL_Y0, 44.0, 6.0


def pill_rect(index: int, count: int = 4) -> QRectF:
    y0, h, gap = _pill_metrics(count)
    return QRectF(PILL_X, y0 + index * (h + gap), PILL_W, h)


def pill_at(pos: QPointF, count: int = 4) -> int:
    for i in range(count):
        if pill_rect(i, count).contains(pos):
            return i
    return -1


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _lerp_color(c0: QColor, c1: QColor, k: float) -> QColor:
    return QColor(
        int(round(_lerp(c0.red(), c1.red(), k))),
        int(round(_lerp(c0.green(), c1.green(), k))),
        int(round(_lerp(c0.blue(), c1.blue(), k))),
        int(round(_lerp(c0.alpha(), c1.alpha(), k))),
    )


def _font(px: float, weight: QFont.Weight = QFont.Weight.Normal, tabular: bool = False) -> QFont:
    f = QFont(typography.APP_FONT_FAMILY)
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferQuality | QFont.StyleStrategy.PreferAntialias)
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except Exception:
            pass
    return f


def _white(alpha: float) -> QColor:
    c = QColor(255, 255, 255)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _baseline(top: float, line_h: float, fm: QFontMetricsF) -> float:
    return top + (line_h - (fm.ascent() + fm.descent())) / 2.0 + fm.ascent()


def paint_performance_card(
    p: QPainter,
    rect: QRectF,
    state: PerformanceState,
    pinned: bool = False,
    now: float = 0.0,
):
    """Desenha o cartão de desempenho inteiro escalado para `rect` (proporção 300:262)."""
    s = rect.width() / CARD_W
    dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    origin = p.transform().map(rect.topLeft())
    snapped = QPointF(round(origin.x() * dpr) / dpr, round(origin.y() * dpr) / dpr)
    rect = QRectF(rect.topLeft() + (snapped - origin), rect.size())

    e = state.transition_progress(now)
    c_prev = QColor(METRIC_COLORS.get(state.prev_selected, "#38bdf8"))
    c_curr = QColor(METRIC_COLORS.get(state.selected, "#38bdf8"))
    accent = _lerp_color(c_prev, c_curr, e)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.translate(rect.topLeft())
    p.scale(s, s)
    p.setClipPath(card_path(CARD_W, CARD_H, CARD_RADIUS))

    _paint_backdrop(p, accent)
    _paint_header(p, accent, pinned)
    _paint_pills(p, state, now)
    _paint_right_panel(p, state, c_curr)

    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_white(0.11), 1.0 / s))
    inset = 0.5 / s
    p.drawRoundedRect(
        QRectF(inset, inset, CARD_W - 2.0 * inset, CARD_H - 2.0 * inset),
        CARD_RADIUS,
        CARD_RADIUS,
    )
    p.restore()


def _paint_backdrop(p: QPainter, accent: QColor):
    bg = QLinearGradient(0.0, 0.0, 0.0, CARD_H)
    bg.setColorAt(0.0, QColor(24, 26, 32, 238))
    bg.setColorAt(1.0, QColor(15, 17, 22, 244))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRect(QRectF(0.0, 0.0, CARD_W, CARD_H))

    glow = QLinearGradient(CARD_W, 0.0, RIGHT_X - 20.0, CARD_H * 0.7)
    c_top = QColor(accent)
    c_top.setAlpha(26)
    c_end = QColor(accent)
    c_end.setAlpha(0)
    glow.setColorAt(0.0, c_top)
    glow.setColorAt(1.0, c_end)
    p.setBrush(glow)
    p.drawRect(QRectF(0.0, 0.0, CARD_W, CARD_H))


def _paint_header(p: QPainter, accent: QColor, pinned: bool):
    ix, iy = 18.0, HEADER_Y + 4.0
    p.save()
    p.setPen(QPen(accent, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    wave = QPainterPath()
    wave.moveTo(ix, iy + 7.5)
    wave.lineTo(ix + 3.5, iy + 7.5)
    wave.lineTo(ix + 6.0, iy + 2.0)
    wave.lineTo(ix + 9.0, iy + 12.0)
    wave.lineTo(ix + 11.5, iy + 5.0)
    wave.lineTo(ix + 14.0, iy + 7.5)
    wave.lineTo(ix + 16.5, iy + 7.5)
    p.drawPath(wave)
    p.restore()

    f_title = _font(13.5, QFont.Weight.DemiBold)
    p.setFont(f_title)
    fm = QFontMetricsF(f_title)
    p.setPen(_white(0.92))
    p.drawText(QPointF(42.0, _baseline(HEADER_Y, HEADER_H, fm)), t("perf_card_title"))

    if pinned:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_white(0.32))
        p.drawEllipse(QPointF(CARD_W - 22.0, HEADER_Y + HEADER_H / 2.0), 3.0, 3.0)


def _paint_pills(p: QPainter, state: PerformanceState, now: float):
    visible = state.visible_metrics()
    count = len(visible)
    compact = count >= 5
    f_label = _font(11.0 if compact else 11.5, QFont.Weight.Medium)
    f_val = _font(11.5 if compact else 12.5, QFont.Weight.DemiBold, tabular=True)
    fm_label = QFontMetricsF(f_label)
    fm_val = QFontMetricsF(f_val)
    rad = 10.0 if compact else PILL_RADIUS

    # 1. Fundo de hover (para pílulas não selecionadas)
    if 0 <= state.hovered_pill < count and visible[state.hovered_pill] != state.selected:
        p.setBrush(_white(0.055))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill_rect(state.hovered_pill, count), rad, rad)

    # 2. Pílula ativa deslizante (glides de prev_selected até selected quando animações do Windows estão ligadas)
    sel_idx = state.selected_index()
    prev_idx = visible.index(state.prev_selected) if state.prev_selected in visible else sel_idx
    e = state.transition_progress(now)
    r_prev = pill_rect(prev_idx, count)
    r_curr = pill_rect(sel_idx, count)
    active_rect = QRectF(
        r_curr.x(),
        _lerp(r_prev.y(), r_curr.y(), e),
        r_curr.width(),
        r_curr.height(),
    )
    p.save()
    if state.pressed_pill == sel_idx:
        c = active_rect.center()
        p.translate(c)
        p.scale(0.98, 0.98)
        p.translate(-c)
    p.setBrush(_white(0.11))
    p.setPen(QPen(_white(0.14), 1.0))
    p.drawRoundedRect(active_rect, rad, rad)
    p.restore()

    # 3. Indicador (morph ponto <-> barra vertical) + rótulo + valor de cada pílula
    pad_y = 8.0 if compact else 11.0
    for i, metric in enumerate(visible):
        r = pill_rect(i, count)
        w_active = state.pill_active_weight(metric, now)
        is_press = i == state.pressed_pill
        m_color = QColor(METRIC_COLORS[metric])

        p.save()
        if is_press:
            c = r.center()
            p.translate(c)
            p.scale(0.98, 0.98)
            p.translate(-c)

        # Morph suave: ponto (4.4x4.4, raio 2.2) <-> barra vertical (3.0x(h - 2*pad_y), raio 1.5)
        bar_h = max(6.0, r.height() - 2.0 * pad_y)
        ind_w = _lerp(4.4, 3.0, w_active)
        ind_h = _lerp(4.4, bar_h, w_active)
        ind_rad = _lerp(2.2, 1.5, w_active)
        ind_cx = r.x() + _lerp(7.5, 6.5, w_active)
        ind_cy = r.center().y()

        ind_color = QColor(m_color)
        ind_color.setAlphaF(_lerp(0.45, 1.0, w_active))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ind_color)
        p.drawRoundedRect(
            QRectF(ind_cx - ind_w / 2.0, ind_cy - ind_h / 2.0, ind_w, ind_h),
            ind_rad,
            ind_rad,
        )

        p.setFont(f_label)
        p.setPen(_white(_lerp(0.68, 0.95, w_active)))
        p.drawText(QPointF(r.x() + 15.0, _baseline(r.y(), r.height(), fm_label)), METRIC_LABELS[metric])

        val_txt = state.pct_text(metric)
        p.setFont(f_val)
        p.setPen(_white(_lerp(0.78, 0.98, w_active)))
        vw = fm_val.horizontalAdvance(val_txt)
        p.drawText(QPointF(r.right() - 9.0 - vw, _baseline(r.y(), r.height(), fm_val)), val_txt)
        p.restore()


def _paint_right_panel(p: QPainter, state: PerformanceState, accent: QColor):
    metric = state.selected
    ceiling = state.chart_ceiling(metric)

    f_hero = _font(36.0, QFont.Weight.Bold, tabular=True)
    fm_hero = QFontMetricsF(f_hero)
    p.setFont(f_hero)
    p.setPen(_white(0.98))
    p.drawText(QPointF(RIGHT_X, _baseline(HERO_Y, HERO_H, fm_hero)), state.hero_text(metric))

    f_cap = _font(10.5, QFont.Weight.Medium, tabular=True)
    fm_cap = QFontMetricsF(f_cap)
    p.setFont(f_cap)
    p.setPen(_white(0.42))
    cap_txt = str(int(round(ceiling)))
    p.drawText(
        QPointF(RIGHT_X + RIGHT_W - fm_cap.horizontalAdvance(cap_txt), _baseline(HERO_Y + 6.0, 16.0, fm_cap)),
        cap_txt,
    )

    detail = state.detail_text(metric)
    if detail:
        f_det = _font(12.0, QFont.Weight.Normal, tabular=True)
        fm_det = QFontMetricsF(f_det)
        elided = fm_det.elidedText(detail, Qt.TextElideMode.ElideRight, RIGHT_W)
        p.setFont(f_det)
        p.setPen(_white(0.62))
        p.drawText(QPointF(RIGHT_X, _baseline(DETAIL_Y, DETAIL_H, fm_det)), elided)

    _paint_chart(p, state.samples(metric), accent, ceiling)

    f_foot = _font(10.5, QFont.Weight.Normal, tabular=True)
    fm_foot = QFontMetricsF(f_foot)
    p.setFont(f_foot)
    p.setPen(_white(0.48))
    foot_y = _baseline(FOOTER_Y, FOOTER_H, fm_foot)
    p.drawText(QPointF(RIGHT_X, foot_y), t("perf_chart_window"))
    zero_w = fm_foot.horizontalAdvance("0")
    p.drawText(QPointF(RIGHT_X + RIGHT_W - zero_w, foot_y), "0")


def _paint_chart(p: QPainter, samples: list[float], accent: QColor, ceiling: float = 100.0):
    r = CHART_RECT
    max_val = max(1.0, float(ceiling))
    p.save()

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white(0.03))
    p.drawRoundedRect(r, 8.0, 8.0)

    clip = QPainterPath()
    clip.addRoundedRect(r, 8.0, 8.0)
    p.setClipPath(clip)

    p.setPen(QPen(_white(0.06), 1.0))
    for frac in (0.25, 0.5, 0.75):
        y = r.top() + r.height() * frac
        p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))

    if samples:
        pad_top = 4.0
        usable_h = r.height() - pad_top - 1.0
        n = len(samples)
        step = r.width() / max(1, HISTORY_LEN - 1)
        start_x = r.right() - (n - 1) * step

        pts = [
            QPointF(start_x + i * step, r.bottom() - (min(max_val, max(0.0, v)) / max_val) * usable_h - 1.0)
            for i, v in enumerate(samples)
        ]

        line = QPainterPath()
        line.moveTo(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)

        area = QPainterPath(line)
        area.lineTo(pts[-1].x(), r.bottom())
        area.lineTo(pts[0].x(), r.bottom())
        area.closeSubpath()

        fill = QLinearGradient(0.0, r.top(), 0.0, r.bottom())
        c_hi = QColor(accent)
        c_hi.setAlpha(95)
        c_lo = QColor(accent)
        c_lo.setAlpha(4)
        fill.setColorAt(0.0, c_hi)
        fill.setColorAt(1.0, c_lo)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPath(area)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(accent, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(line)

        last = pts[-1]
        halo = QColor(accent)
        halo.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(last, 4.0, 4.0)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(last, 1.8, 1.8)

    p.restore()
