"""
Pintura do Battery Widget (QPainter), no estilo do protótipo do Figma: anéis grossos (9,5% do diâmetro), ícone ou
porcentagem centralizados, nome abaixo. Desenha em coordenadas do cartão (W x H do layout); o chamador dá o retângulo
já em pixels de tela.

Tipografia (passe do Impeccable, fonte do app): título 16 px Medium no topo 24 / linha 22, igual ao nome do lugar no
Clima, para os dois cartões alinharem lado a lado; contador 12 px Regular, cor fraca, alinhado à direita na mesma
linha de base; nomes 11-13 px acompanhando o anel; porcentagem 24% do anel, Medium, algarismos tabulares. Contraste
dos textos >= 4,5:1 nos três temas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtSvg import QSvgRenderer

from app.core.i18n import t
from app.core.typography import card_font
from app.services.battery.models import (
    KIND_CONTROLLER,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_PHONE,
)
from app.widgets.battery import layout as lay
from app.widgets.battery.card_state import LABEL_TYPE, BatteryState

RADIUS = 27.0
PAD = 24.0
HEAD_TOP, HEAD_LH = 24.0, 22.0
STROKE = 0.095            # espessura do anel em fração do diâmetro
LOW_PCT = 20.0
PULSE_S = 1.8             # período da bolinha de carregando

THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_BLACK = "black"


@dataclass(frozen=True)
class Palette:
    surface: QColor
    text: QColor
    label: QColor
    muted: QColor
    track: QColor
    ok: QColor
    low: QColor


PALETTES = {
    THEME_DARK: Palette(QColor("#1b1b1b"), QColor("#ffffff"), QColor(255, 255, 255, 199), QColor("#8f8f8f"),
                        QColor("#3c3d3c"), QColor("#14c414"), QColor("#d9922a")),
    THEME_LIGHT: Palette(QColor("#f7f6f2"), QColor("#161616"), QColor("#55544f"), QColor("#66655f"),
                         QColor("#dcddd6"), QColor("#10b010"), QColor("#a8620f")),
    THEME_BLACK: Palette(QColor("#000000"), QColor("#ffffff"), QColor(255, 255, 255, 199), QColor("#8f8f8f"),
                         QColor("#2c2d2c"), QColor("#14c414"), QColor("#d9922a")),
}

_ICON_PATHS = {
    KIND_MOUSE: '<rect x="4.5" y="1.5" width="7" height="13" rx="3.5"/><path d="M8 4.5v2.5"/>',
    KIND_KEYBOARD: '<rect x="1.5" y="3.5" width="13" height="9" rx="2"/>'
                   '<path d="M4.5 7h1M7.5 7h1M10.5 7h1M5 10h6"/>',
    KIND_CONTROLLER: '<path d="M4.5 4.5h7a3.5 3.5 0 0 1 3.4 4.3l-.6 2.4a1.8 1.8 0 0 1-3 .8L9.6 10.5H6.4L4.7 12a1.8 '
                     '1.8 0 0 1-3-.8l-.6-2.4a3.5 3.5 0 0 1 3.4-4.3Z"/><path d="M5 6.8v2M4 7.8h2"/>',
    KIND_HEADSET: '<path d="M2.5 10V8a5.5 5.5 0 0 1 11 0v2"/><rect x="2" y="9.5" width="3" height="4.5" rx="1.2"/>'
                  '<rect x="11" y="9.5" width="3" height="4.5" rx="1.2"/>',
    KIND_PHONE: '<rect x="4.5" y="1.5" width="7" height="13" rx="1.8"/><path d="M7 12.5h2"/>',
}
_ICON_OTHER = '<rect x="1.5" y="5" width="11.5" height="6" rx="1.5"/><path d="M14.5 7v2"/>'
_renderers: dict = {}


def _icon(kind: str, color: QColor) -> QSvgRenderer:
    key = (kind, color.name(QColor.NameFormat.HexArgb))
    r = _renderers.get(key)
    if r is None:
        body = _ICON_PATHS.get(kind, _ICON_OTHER)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="{color.name()}" '
               f'stroke-opacity="{color.alphaF():.3f}" stroke-width="1.5" stroke-linecap="round" '
               f'stroke-linejoin="round">{body}</svg>')
        r = _renderers[key] = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    return r


def _font(px: float, weight: QFont.Weight = QFont.Weight.Normal, tabular: bool = False) -> QFont:
    return card_font(px, weight, tabular, min_px=6)


def _baseline(top: float, h: float, fm: QFontMetricsF) -> float:
    return top + (h - (fm.ascent() + fm.descent())) / 2.0 + fm.ascent()


def kind_label(kind: str) -> str:
    return t(f"battery_kind_{kind}") if kind else t("battery_kind_other")


def count_label(n: int) -> str:
    return t("battery_count_one") if n == 1 else t("battery_count").format(n=n)


def paint_battery_card(p: QPainter, rect: QRectF, state: BatteryState, theme: str = THEME_DARK, now: float = 0.0):
    pal = PALETTES.get(theme, PALETTES[THEME_DARK])
    W, H = max(1.0, state.W.x), max(1.0, state.H.x)
    s = rect.width() / W

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.translate(rect.topLeft())
    p.scale(s, s)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0.0, 0.0, W, H), RADIUS, RADIUS)
    p.setClipPath(clip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal.surface)
    p.drawRect(QRectF(0.0, 0.0, W, H))

    opts = state.options
    if opts.header:
        _paint_header(p, pal, W, len(state.order), max(0.0, min(1.0, state.count_alpha.x)))

    if not state.order and not any(c.leaving for c in state.cells.values()):
        _paint_empty(p, pal, W, H, opts.header, state.scanned)
    else:
        d = max(8.0, state.D.x)
        ty = lay.typo(d, opts.names)
        lw = d + min((state.layout.gap_x if state.layout else 20.0) * 0.8, 56.0)
        pulse = 0.5 - 0.5 * math.cos(2.0 * math.pi * ((now % PULSE_S) / PULSE_S)) if state.animated else 0.0
        for cell in state.visible_cells():
            _paint_cell(p, pal, state, cell, d, ty, lw, pulse)
    p.restore()


def _paint_header(p: QPainter, pal: Palette, W: float, n: int, count_alpha: float = 1.0):
    f_title = _font(16.0, QFont.Weight.Medium)
    fm_t = QFontMetricsF(f_title)
    base = _baseline(HEAD_TOP, HEAD_LH, fm_t)
    title = t("battery_title")
    count = count_label(n) if (n and count_alpha > 0.003) else ""
    f_count = _font(12.0, QFont.Weight.Normal, tabular=True)
    fm_c = QFontMetricsF(f_count)
    count_w = fm_c.horizontalAdvance(count) if count else 0.0
    room = W - 2 * PAD
    show_count = bool(count) and fm_t.horizontalAdvance(title) + 12.0 + count_w <= room
    p.setFont(f_title)
    p.setPen(pal.text)
    title_room = room - ((count_w + 12.0) if show_count else 0.0)
    p.drawText(QPointF(PAD, base), fm_t.elidedText(title, Qt.TextElideMode.ElideRight, max(10.0, title_room)))
    if show_count:
        p.save()
        p.setOpacity(p.opacity() * count_alpha)     # aparece/some com movimento (opção "nº de dispositivos")
        p.setFont(f_count)
        p.setPen(pal.muted)
        p.drawText(QPointF(W - PAD - count_w, base), count)
        p.restore()


def _paint_empty(p: QPainter, pal: Palette, W: float, H: float, header: bool, scanned: bool):
    top = lay.HEAD_H if header else 0.0
    f = _font(12.5)
    fm = QFontMetricsF(f)
    text = t("battery_empty") if scanned else t("battery_scanning")
    text = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(20.0, W - 2 * PAD))
    p.setFont(f)
    p.setPen(pal.muted)
    y = _baseline(top, H - top - (PAD if header else 0.0), fm)
    p.drawText(QPointF((W - fm.horizontalAdvance(text)) / 2.0, y), text)


def _paint_cell(p: QPainter, pal: Palette, state: BatteryState, cell, d: float, ty: lay.Typo, lw: float, pulse: float):
    dev = cell.device
    alpha = max(0.0, min(1.0, cell.alpha.x))
    if alpha <= 0.003:
        return
    sc = cell.scale.x
    cx, cy = cell.x.x + d / 2.0, cell.y.x + d / 2.0
    p.save()
    p.setOpacity(alpha)
    p.translate(cx, cy)
    p.scale(sc, sc)

    # Anel: trilho + arco (de cima, sentido horário, pontas redondas)
    sw = d * STROKE
    r = (d - sw) / 2.0
    ring = QRectF(-r, -r, 2 * r, 2 * r)
    known = dev.percent is not None
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(pal.track, sw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    p.drawEllipse(ring)
    fill = max(0.0, min(100.0, cell.fill.x)) if known else 0.0
    if fill > 0.4:
        low = known and dev.percent <= LOW_PCT and not dev.charging
        p.setPen(QPen(pal.low if low else pal.ok, sw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring, 90 * 16, -int(round(fill / 100.0 * 360.0 * 16)))

    # Face: ícone <-> porcentagem (ou os dois), centralizados no anel
    f_pct, both = state.face_pct.x, state.face_both.x
    icon_a = max(both, 1.0 - f_pct)
    pct_a = max(both, f_pct)
    if icon_a > 0.01:
        isz = d * 0.30 * (1.0 - 0.1 * f_pct * (1.0 - both)) * (1.0 - 0.22 * both)
        iy = -0.14 * d * both
        p.save()
        p.setOpacity(alpha * icon_a * (1.0 if known else 0.55))
        _icon(dev.kind, pal.text).render(p, QRectF(-isz / 2.0, iy - isz / 2.0, isz, isz))
        p.restore()
    if pct_a > 0.01:
        px = d * (0.24 * (1.0 - both) + 0.20 * both)
        f = _font(px, QFont.Weight.Medium, tabular=True)
        fm = QFontMetricsF(f)
        text = (f"~{int(round(dev.percent))}%" if dev.approximate else f"{int(round(dev.percent))}%") if known else "–"
        k = 0.9 + 0.1 * pct_a
        p.save()
        p.setOpacity(alpha * pct_a)
        p.translate(0.0, 0.15 * d * both)
        p.scale(k, k)
        p.setFont(f)
        p.setPen(pal.text)
        tw = fm.horizontalAdvance(text)
        p.drawText(QPointF(-tw / 2.0, (fm.ascent() - fm.descent()) / 2.0), text)
        p.restore()
    p.restore()

    # Nome (fora da escala do anel para o texto não "respirar" ao entrar)
    if state.options.names and ty.lh > 0:
        text = kind_label(dev.kind) if state.options.label == LABEL_TYPE else dev.name
        f = _font(ty.fs)
        fm = QFontMetricsF(f)
        charge = max(0.0, min(1.0, cell.charge.x))
        dot = ty.dot
        slot = dot * 1.8 * charge                 # bolinha + vão: abre/fecha com a mola, o nome desliza junto
        # Corta o nome pelo espaço FINAL (o texto não troca de reticências no meio do movimento)
        final_slot = dot * 1.8 if dev.charging else 0.0
        text = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(10.0, lw - final_slot))
        tw = fm.horizontalAdvance(text)
        x0 = cx - (slot + tw) / 2.0
        top = cell.y.x + d + ty.gap
        base = _baseline(top, ty.lh, fm)
        p.save()
        p.setOpacity(alpha)
        if charge > 0.003:
            # Bolinha à esquerda do nome, apoiada na linha de base, menor que a altura da maiúscula; entra crescendo
            # e acendendo a partir do centro do próprio espaço
            k = (1.0 - 0.3 * pulse) * (0.35 + 0.65 * charge)
            rr = dot / 2.0 * k
            p.setPen(Qt.PenStyle.NoPen)
            c = QColor(pal.ok)
            c.setAlphaF((1.0 - 0.6 * pulse) * charge)
            p.setBrush(c)
            p.drawEllipse(QPointF(x0 + dot / 2.0 * charge, base - dot / 2.0), rr, rr)
        p.setFont(f)
        p.setPen(pal.label if dev.percent is not None else pal.muted)
        p.drawText(QPointF(x0 + slot, base), text)
        p.restore()
