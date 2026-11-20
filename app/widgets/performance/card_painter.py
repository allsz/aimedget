"""
Pintura do Performance Widget no mesmo cartão de referência (300 x 262, raio 27) do Weather Widget.

Compartilhada entre o widget vivo e a miniatura do Hub (sem timers, pura QPainter).
"""

import math

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
from app.ui_components.dot_matrix import NOTHING_BG, NOTHING_RED, draw_dot_text
from app.ui_components.floating_card import CARD_H, CARD_RADIUS, CARD_W, card_path
from app.widgets.performance.card_state import (
    HISTORY_LEN,
    METRIC_COLORS,
    METRIC_LABELS,
    SKIN_NOTHING_DOT,
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
DONE_RECT = QRectF(CARD_W - 38.0, HEADER_Y + 1.0, 22.0, 20.0)

# Geometria da skin Nothing Dot (mesmo canvas 300 x 262)
ND_TRIGGER_RECT = QRectF(14.0, 14.0, 114.0, 26.0)
ND_MATRIX_RECT = QRectF(18.0, 80.0, 264.0, 142.0)
ND_COLS = 32
ND_ROWS = 15
ND_DD_X = 14.0
ND_DD_Y = 44.0
ND_DD_W = 156.0
ND_DD_PAD = 5.0
ND_DD_ITEM_H = 26.0
ND_PAGER_Y = 237.0


def nd_dropdown_rect(count: int) -> QRectF:
    h = ND_DD_PAD * 2.0 + max(1, count) * ND_DD_ITEM_H
    return QRectF(ND_DD_X, ND_DD_Y, ND_DD_W, h)


def nd_dropdown_item_at(pos: QPointF, count: int) -> int:
    r = nd_dropdown_rect(count)
    if not r.contains(pos):
        return -1
    idx = int((pos.y() - r.y() - ND_DD_PAD) // ND_DD_ITEM_H)
    return idx if 0 <= idx < count else -1


def nd_pager_dot_at(pos: QPointF, count: int, active_idx: int) -> int:
    if count <= 1 or abs(pos.y() - ND_PAGER_Y) > 12.0:
        return -1
    gap = 6.0
    widths = [12.0 if i == active_idx else 4.0 for i in range(count)]
    total = sum(widths) + gap * (count - 1)
    x = (CARD_W - total) * 0.5
    for i, w in enumerate(widths):
        if x - 4.0 <= pos.x() <= x + w + 4.0:
            return i
        x += w + gap
    return -1


def _pill_metrics(count: int) -> tuple[float, float, float]:
    """(y0, height, gap) ajustados para 4 ou 5 pílulas dentro da altura do cartão."""
    if count >= 5:
        return 50.0, 35.0, 5.0
    return PILL_Y0, 44.0, 6.0


def pill_bounds(count: int) -> tuple[float, float, float, float]:
    """(y0, height, gap, y_max) para limitar o arraste de reordenação dentro da coluna de pílulas."""
    y0, h, gap = _pill_metrics(count)
    y_max = y0 + max(0, count - 1) * (h + gap)
    return y0, h, gap, y_max


def pill_rect(index: int, count: int = 4) -> QRectF:
    y0, h, gap = _pill_metrics(count)
    return QRectF(PILL_X, y0 + index * (h + gap), PILL_W, h)


def pill_at(pos: QPointF, count: int = 4) -> int:
    for i in range(count):
        if pill_rect(i, count).contains(pos):
            return i
    return -1


def done_hit(pos: QPointF) -> bool:
    return DONE_RECT.adjusted(-3.0, -3.0, 3.0, 3.0).contains(pos)


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
    nothing_theme=None,
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

    if state.skin_id == SKIN_NOTHING_DOT:
        from app.widgets.performance.theme import load_user_theme as _load_perf_theme
        nt = nothing_theme if nothing_theme is not None else _load_perf_theme()
        _paint_nothing_dot_performance(p, state, pinned, now, nt)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(nt.border, 1.0 / s))
        inset = 0.5 / s
        p.drawRoundedRect(
            QRectF(inset, inset, CARD_W - 2.0 * inset, CARD_H - 2.0 * inset),
            CARD_RADIUS,
            CARD_RADIUS,
        )
        p.restore()
        return

    _paint_backdrop(p, accent)
    _paint_header(p, accent, pinned, state)
    _paint_pills(p, state, now)
    _paint_right_panel(p, state, c_curr, now)

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


def _sampled_columns(state: PerformanceState, metric: str, cols: int, now: float) -> list[float]:
    """Amostra o histórico de `metric` em `cols` colunas normalizadas (0..1)."""
    samples = state.samples(metric, now=now)
    ceiling = max(1.0, state.chart_ceiling(metric))
    if not samples:
        cur = state.current_pct(metric)
        norm = max(0.0, min(1.0, (cur or 0.0) / ceiling))
        return [0.0] * (cols - 1) + [norm] if norm > 0.0 else [0.0] * cols
    # Alinha as amostras mais recentes à direita da matriz
    n = len(samples)
    out = [0.0] * cols
    if n <= cols:
        offset = cols - n
        for i, v in enumerate(samples):
            out[offset + i] = max(0.0, min(1.0, float(v) / ceiling))
    else:
        for c in range(cols):
            idx = int(round(c * (n - 1) / max(1, cols - 1)))
            out[c] = max(0.0, min(1.0, float(samples[idx]) / ceiling))
    return out


def _paint_nothing_dot_performance(p: QPainter, state: PerformanceState, pinned: bool, now: float, theme):
    from app.core.theme_art import paint_background, paint_stickers
    from app.ui_components.dot_matrix import measure_dot_text

    card_r = QRectF(0.0, 0.0, CARD_W, CARD_H)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.card_bg)
    p.drawRect(card_r)
    if theme.background is not None:
        paint_background(p, card_r, theme.background, CARD_RADIUS)
    if theme.stickers:
        paint_stickers(p, card_r, theme.stickers, "below")

    def _tone(base: QColor, alpha_mul: float = 1.0) -> QColor:
        c = QColor(base)
        c.setAlphaF(max(0.0, min(1.0, c.alphaF() * alpha_mul)))
        return c

    metric = state.selected
    prev_metric = state.prev_selected
    e = state.transition_progress(now)
    swapping = prev_metric != metric and e < 1.0

    # 1. Topo esquerdo: Gatilho de categoria (CPU ▾) com hover sutil abraçando o rótulo + crossfade na troca
    cat_rect = QRectF(18.0, 16.0, 88.0, 22.0)
    pill_w = measure_dot_text(METRIC_LABELS[metric], dot_r=1.25, gap=2.8)[0] + 28.0
    if state.trigger_hovered or state.dropdown_open:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_tone(theme.text, 0.09 if state.dropdown_open else 0.07))
        p.drawRoundedRect(QRectF(ND_TRIGGER_RECT.x(), ND_TRIGGER_RECT.y(), pill_w, ND_TRIGGER_RECT.height()), 9.0, 9.0)
    if swapping:
        draw_dot_text(p, METRIC_LABELS[prev_metric], cat_rect.translated(0.0, -4.0 * e),
                      dot_r=1.25, gap=2.8, color=_tone(theme.dot_on, 1.0 - e))
        cat_w = draw_dot_text(p, METRIC_LABELS[metric], cat_rect.translated(0.0, 4.0 * (1.0 - e)),
                              dot_r=1.25, gap=2.8, color=_tone(theme.dot_on, e))
    else:
        cat_w = draw_dot_text(p, METRIC_LABELS[metric], cat_rect, dot_r=1.25, gap=2.8, color=theme.dot_on)

    # Chevron giratório ao lado da categoria
    chev_cx = 18.0 + cat_w + 10.0
    chev_cy = 27.0
    p.save()
    p.translate(chev_cx, chev_cy)
    p.rotate(180.0 * state.dropdown_progress)
    p.setPen(QPen(_tone(theme.text, 0.62 if state.trigger_hovered or state.dropdown_open else 0.48), 1.6,
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    ch = QPainterPath()
    ch.moveTo(-3.2, -1.5)
    ch.lineTo(0.0, 1.8)
    ch.lineTo(3.2, -1.5)
    p.drawPath(ch)
    p.restore()

    # Subtítulo de hardware / detalhe abaixo da categoria
    detail = state.detail_text(metric)
    f_sub = _font(11.5, QFont.Weight.Normal, tabular=True)
    fm_sub = QFontMetricsF(f_sub)
    if detail:
        p.setFont(f_sub)
        p.setPen(_tone(theme.muted_text, e if swapping else 1.0))
        elided = fm_sub.elidedText(detail, Qt.TextElideMode.ElideRight, 162.0)
        p.drawText(QPointF(18.0, _baseline(45.0, 16.0, fm_sub)), elided)

    # 2. Topo direito: Valor atual em matriz de pontos circular + subtexto
    val_rect = QRectF(CARD_W - 18.0 - 96.0, 16.0, 96.0, 22.0)
    if swapping:
        draw_dot_text(p, state.pct_text(prev_metric), val_rect.translated(0.0, -4.0 * e),
                      dot_r=1.25, gap=2.8, color=_tone(theme.dot_on, 1.0 - e), align="right")
        draw_dot_text(p, state.pct_text(metric), val_rect.translated(0.0, 4.0 * (1.0 - e)),
                      dot_r=1.25, gap=2.8, color=_tone(theme.dot_on, e), align="right")
    else:
        draw_dot_text(p, state.pct_text(metric), val_rect, dot_r=1.25, gap=2.8, color=theme.dot_on, align="right")

    cap_txt = f"{int(round(state.chart_ceiling(metric)))}{' FPS' if metric == 'fps' else '%'}"
    p.setFont(f_sub)
    p.setPen(_tone(theme.muted_text, 0.80))
    cw_cap = fm_sub.horizontalAdvance(cap_txt)
    p.drawText(QPointF(CARD_W - 18.0 - cw_cap, _baseline(45.0, 16.0, fm_sub)), cap_txt)

    # 3. Matriz de pontos 32x15 (interpola altura de cada coluna na troca de métrica!)
    curr_cols = _sampled_columns(state, metric, ND_COLS, now)
    if swapping:
        prev_cols = _sampled_columns(state, prev_metric, ND_COLS, now)
        cols = [_lerp(a, b, e) for a, b in zip(prev_cols, curr_cols)]
    else:
        cols = curr_cols

    mr = ND_MATRIX_RECT
    step_x = mr.width() / ND_COLS
    step_y = mr.height() / ND_ROWS
    dot_r = 2.45

    p.setPen(Qt.PenStyle.NoPen)
    for c_idx, norm in enumerate(cols):
        lit_rows = max(1, int(round(norm * ND_ROWS))) if norm > 0.005 else 0
        is_latest = c_idx == ND_COLS - 1
        cx = mr.x() + c_idx * step_x + step_x * 0.5
        for r_idx in range(ND_ROWS):
            from_bottom = ND_ROWS - 1 - r_idx
            cy = mr.y() + r_idx * step_y + step_y * 0.5
            if from_bottom < lit_rows:
                p.setBrush(theme.accent if (is_latest and from_bottom == lit_rows - 1) else theme.dot_on)
            else:
                p.setBrush(theme.dot_off)
            p.drawEllipse(QPointF(cx, cy), dot_r, dot_r)

    # 4. Rodapé: "60s", pontos de paginação clicáveis
    f_foot = _font(10.5, QFont.Weight.Normal, tabular=True)
    fm_foot = QFontMetricsF(f_foot)
    p.setFont(f_foot)
    p.setPen(_tone(theme.muted_text, 0.75))
    foot_base = _baseline(229.0, 16.0, fm_foot)
    p.drawText(QPointF(18.0, foot_base), "60s")

    visible = state.visible_metrics()
    sel_idx = state.selected_index()
    if len(visible) > 1:
        gap = 6.0
        widths = [12.0 if i == sel_idx else 4.0 for i in range(len(visible))]
        total_w = sum(widths) + gap * (len(visible) - 1)
        px = (CARD_W - total_w) * 0.5
        p.setPen(Qt.PenStyle.NoPen)
        for i, w_dot in enumerate(widths):
            p.setBrush(theme.accent if i == sel_idx else _tone(theme.text, 0.24))
            p.drawRoundedRect(QRectF(px, ND_PAGER_Y - 2.0, w_dot, 4.0), 2.0, 2.0)
            px += w_dot + gap

    if pinned:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_tone(theme.text, 0.32))
        p.drawEllipse(QPointF(CARD_W - 22.0, ND_PAGER_Y), 2.8, 2.8)

    if theme.stickers:
        paint_stickers(p, card_r, theme.stickers, "above")

    # 5. Menu dropdown interno animado (quando aberto ou fechando)
    dd_p = max(0.0, min(1.0, state.dropdown_progress))
    if dd_p > 0.01:
        dd_r = nd_dropdown_rect(len(visible))
        p.save()
        p.setOpacity(dd_p)
        slide_y = -6.0 * (1.0 - dd_p)
        scale_dd = 0.96 + 0.04 * dd_p
        p.translate(dd_r.x(), dd_r.y() + slide_y)
        p.scale(scale_dd, scale_dd)
        p.translate(-dd_r.x(), -dd_r.y())

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawRoundedRect(dd_r.translated(0.0, 4.0), 13.0, 13.0)

        dd_bg = QColor(theme.card_bg)
        dd_bg.setAlpha(248)
        p.setBrush(dd_bg)
        p.setPen(QPen(_tone(theme.text, 0.16), 1.0))
        p.drawRoundedRect(dd_r, 13.0, 13.0)

        f_dd = _font(11.5, QFont.Weight.Medium)
        f_dd_val = _font(11.0, QFont.Weight.Normal, tabular=True)
        fm_dd = QFontMetricsF(f_dd)
        fm_dd_v = QFontMetricsF(f_dd_val)

        for i, m in enumerate(visible):
            ir = QRectF(dd_r.x() + ND_DD_PAD, dd_r.y() + ND_DD_PAD + i * ND_DD_ITEM_H,
                        dd_r.width() - ND_DD_PAD * 2.0, ND_DD_ITEM_H)
            is_cur = m == metric
            is_hov = i == state.dropdown_hovered
            if is_cur or is_hov:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_tone(theme.text, 0.12 if is_cur else 0.08))
                p.drawRoundedRect(ir, 8.0, 8.0)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.accent if is_cur else _tone(theme.text, 0.24))
            p.drawEllipse(QPointF(ir.x() + 10.0, ir.center().y()), 2.4, 2.4)

            p.setFont(f_dd)
            p.setPen(_tone(theme.text, 0.98 if (is_cur or is_hov) else 0.78))
            p.drawText(QPointF(ir.x() + 20.0, _baseline(ir.y(), ir.height(), fm_dd)), METRIC_LABELS[m])

            v_txt = state.pct_text(m)
            p.setFont(f_dd_val)
            p.setPen(theme.muted_text)
            vw = fm_dd_v.horizontalAdvance(v_txt)
            p.drawText(QPointF(ir.right() - 8.0 - vw, _baseline(ir.y(), ir.height(), fm_dd_v)), v_txt)
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


def _paint_header(p: QPainter, accent: QColor, pinned: bool, state: PerformanceState):
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

    if state.reorder_mode:
        p.save()
        if state.done_pressed:
            c = DONE_RECT.center()
            p.translate(c)
            p.scale(0.94, 0.94)
            p.translate(-c)
        bg_alpha = 0.22 if state.done_hovered else 0.13
        p.setBrush(_white(bg_alpha))
        p.setPen(QPen(_white(0.24 if state.done_hovered else 0.16), 1.0))
        p.drawRoundedRect(DONE_RECT, 7.0, 7.0)
        chk = QPainterPath()
        cx, cy = DONE_RECT.center().x(), DONE_RECT.center().y()
        chk.moveTo(cx - 4.2, cy + 0.3)
        chk.lineTo(cx - 1.1, cy + 3.4)
        chk.lineTo(cx + 4.4, cy - 3.0)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(accent, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(chk)
        p.restore()
    elif pinned:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_white(0.32))
        p.drawEllipse(QPointF(CARD_W - 22.0, HEADER_Y + HEADER_H / 2.0), 3.0, 3.0)


def _paint_reorder_pills(p: QPainter, state: PerformanceState, now: float):
    visible = state.visible_metrics()
    count = len(visible)
    compact = count >= 5
    f_label = _font(11.0 if compact else 11.5, QFont.Weight.Medium)
    f_val = _font(11.5 if compact else 12.5, QFont.Weight.DemiBold, tabular=True)
    fm_label = QFontMetricsF(f_label)
    fm_val = QFontMetricsF(f_val)
    rad = 10.0 if compact else PILL_RADIUS

    # Pinta primeiro as pílulas paradas e por último a pílula arrastada (sempre por cima)
    order = [(i, m) for i, m in enumerate(visible) if m != state.drag_metric]
    for i, m in enumerate(visible):
        if m == state.drag_metric:
            order.append((i, m))

    for i, metric in order:
        is_dragged = metric == state.drag_metric
        base = pill_rect(i, count)
        if is_dragged:
            r = QRectF(base.x(), state.drag_y, base.width(), base.height())
        else:
            off = state.pill_y_offsets.get(metric, 0.0)
            r = base.translated(0.0, off)

        m_color = QColor(METRIC_COLORS[metric])
        is_sel = metric == state.selected
        is_hov = (i == state.hovered_pill) and state.drag_metric is None

        p.save()
        c = r.center()
        if is_dragged:
            p.translate(c)
            p.scale(1.035, 1.035)
            p.translate(-c)
            # Sombra suave abaixo da pílula levantada
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 95))
            p.drawRoundedRect(r.translated(0.0, 3.0), rad, rad)
        elif state.animated:
            # Tremidinha sutil estilo tela inicial de celular (defasada entre pílulas)
            phase = (now - state.reorder_t0) * 11.5 + i * 1.35
            angle = 1.25 * math.sin(phase)
            p.translate(c)
            p.rotate(angle)
            p.translate(-c)

        if is_dragged:
            border = QColor(m_color)
            border.setAlphaF(0.75)
            p.setBrush(QColor(36, 40, 48, 244))
            p.setPen(QPen(border, 1.25))
        else:
            p.setBrush(_white(0.11 if is_sel else (0.085 if is_hov else 0.06)))
            p.setPen(QPen(_white(0.20 if is_hov else (0.15 if is_sel else 0.10)), 1.0))
        p.drawRoundedRect(r, rad, rad)

        # 6 pontinhos de arraste (2x3) à esquerda, na cor da métrica
        grip_color = QColor(m_color)
        grip_color.setAlphaF(0.95 if (is_dragged or is_sel) else 0.78)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grip_color)
        cy = r.center().y()
        dy_step = 3.6 if compact else 4.2
        for gx in (r.x() + 6.8, r.x() + 10.0):
            for dy in (-dy_step, 0.0, dy_step):
                p.drawEllipse(QPointF(gx, cy + dy), 1.05, 1.05)

        p.setFont(f_label)
        p.setPen(_white(0.96 if (is_dragged or is_sel) else 0.78))
        p.drawText(QPointF(r.x() + 16.5, _baseline(r.y(), r.height(), fm_label)), METRIC_LABELS[metric])

        val_txt = state.pct_text(metric)
        p.setFont(f_val)
        p.setPen(_white(0.98 if (is_dragged or is_sel) else 0.82))
        vw = fm_val.horizontalAdvance(val_txt)
        p.drawText(QPointF(r.right() - 9.0 - vw, _baseline(r.y(), r.height(), fm_val)), val_txt)
        p.restore()


def _paint_pills(p: QPainter, state: PerformanceState, now: float):
    if state.reorder_mode:
        _paint_reorder_pills(p, state, now)
        return
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


def _paint_right_panel(p: QPainter, state: PerformanceState, accent: QColor, now: float = 0.0):
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

    _paint_chart(p, state.samples(metric, now=now), accent, ceiling)

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
