"""
StorageCardPainter - Renderização QPainter do Storage Widget no estilo DesignBookmark.

Desenha em coordenadas de referência (300 x card_h, raio 27); o chamador aplica `scale`.
Suporta tema escuro e claro automaticamente seguindo o tema do Hub/sistema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from app.core.i18n import t
from app.core.typography import APP_FONT_FAMILY
from app.hub.theme import THEME_DARK as HUB_DARK, THEME_LIGHT as HUB_LIGHT, THEME_TRUE_DARK as HUB_TRUE_DARK
from app.widgets.storage.card_state import CARD_W, PAN_H, ROW_H, StorageState

RADIUS = 27.0

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_TRUE_DARK = "true_dark"

SEGMENT_COLORS = (
    QColor("#3ec9ff"),   # blue
    QColor("#c69bff"),   # purple
    QColor("#ff9f0a"),   # orange
    QColor("#34d17a"),   # green
    QColor("#ff6ad5"),   # pink
)


@dataclass(frozen=True)
class StoragePalette:
    surface: QColor
    fill1: QColor
    fill2: QColor
    fill3: QColor
    border: QColor
    text: QColor
    text2: QColor
    muted: QColor
    muted2: QColor
    cap: QColor
    size: QColor
    path: QColor
    detail: QColor


PALETTE_DARK = StoragePalette(
    surface=QColor(HUB_DARK.bg),
    fill1=QColor(255, 255, 255, 13),
    fill2=QColor(255, 255, 255, 23),
    fill3=QColor(255, 255, 255, 36),
    border=QColor(255, 255, 255, 26),
    text=QColor("#ffffff"),
    text2=QColor(255, 255, 255, 199),
    muted=QColor("#b0b0b6"),
    muted2=QColor("#a8a8b0"),
    cap=QColor("#b8b8be"),
    size=QColor("#c4c4ca"),
    path=QColor(255, 255, 255, 224),
    detail=QColor("#b0b0b6"),
)

PALETTE_TRUE_DARK = StoragePalette(
    surface=QColor(HUB_TRUE_DARK.bg),
    fill1=QColor(255, 255, 255, 16),
    fill2=QColor(255, 255, 255, 26),
    fill3=QColor(255, 255, 255, 42),
    border=QColor(255, 255, 255, 35),
    text=QColor("#ffffff"),
    text2=QColor(255, 255, 255, 199),
    muted=QColor("#b0b0b6"),
    muted2=QColor("#a8a8b0"),
    cap=QColor("#b8b8be"),
    size=QColor("#c4c4ca"),
    path=QColor(255, 255, 255, 224),
    detail=QColor("#b0b0b6"),
)

PALETTE_LIGHT = StoragePalette(
    surface=QColor(HUB_LIGHT.panel),
    fill1=QColor(23, 24, 26, 10),
    fill2=QColor(23, 24, 26, 18),
    fill3=QColor(23, 24, 26, 31),
    border=QColor(23, 24, 26, 30),
    text=QColor("#17181a"),
    text2=QColor("#3c3b37"),
    muted=QColor("#5a5a5e"),
    muted2=QColor("#5e5e64"),
    cap=QColor("#525257"),
    size=QColor("#45454a"),
    path=QColor("#262629"),
    detail=QColor("#525257"),
)

PALETTES = {
    THEME_LIGHT: PALETTE_LIGHT,
    THEME_DARK: PALETTE_DARK,
    THEME_TRUE_DARK: PALETTE_TRUE_DARK,
}


def resolve_storage_palette(light: bool = False, theme=None) -> StoragePalette:
    if theme is not None:
        mode = getattr(theme, "mode", theme) if not isinstance(theme, str) else theme
        if mode in ("true_dark", "black", "oled"):
            return PALETTE_TRUE_DARK
        if mode == "light":
            return PALETTE_LIGHT
        if mode == "dark":
            return PALETTE_DARK
        if hasattr(theme, "is_dark"):
            return PALETTE_DARK if theme.is_dark else PALETTE_LIGHT
    return PALETTE_LIGHT if light else PALETTE_DARK


def _font(px: float, weight: QFont.Weight = QFont.Weight.Normal, tabular: bool = False) -> QFont:
    f = QFont(APP_FONT_FAMILY)
    f.setPixelSize(max(8, int(round(px))))
    f.setWeight(weight)
    f.setStyleStrategy(
        QFont.StyleStrategy.PreferQuality
        | QFont.StyleStrategy.PreferAntialias
        | QFont.StyleStrategy.NoSubpixelAntialias
    )
    if tabular:
        f.setStyleHint(QFont.StyleHint.SansSerif)
    return f


def _baseline(top: float, h: float, fm: QFontMetricsF) -> float:
    return top + (h - (fm.ascent() + fm.descent())) / 2.0 + fm.ascent()


def _fmt_gb(gb: float) -> str:
    if gb >= 100.0:
        return f"{gb:.1f} GB"
    return f"{gb:.1f} GB"


# --- Geometria e hit-testing (coordenadas do cartão 300 x card_h) ---

EXPAND_BTN_RECT = QRectF(CARD_W - 18.0 - 24.0, 14.0, 24.0, 24.0)
BAR_RECT = QRectF(18.0, 104.0, CARD_W - 36.0, 12.0)
CATS_TOP = 126.0


def drive_tab_rects(count: int) -> list[QRectF]:
    """Retângulos dos botões de disco (C:, D:...) alinhados à esquerda do chevron."""
    if count <= 1:
        return []
    tab_w = 28.0
    gap = 2.0
    pad = 2.0
    total_w = count * tab_w + (count - 1) * gap + 2 * pad
    right = EXPAND_BTN_RECT.left() - 5.0
    x0 = right - total_w + pad
    return [QRectF(x0 + i * (tab_w + gap), 16.0, tab_w, 20.0) for i in range(count)]


def drive_container_rect(count: int) -> Optional[QRectF]:
    tabs = drive_tab_rects(count)
    if not tabs:
        return None
    return QRectF(tabs[0].left() - 2.0, 14.0, tabs[-1].right() - tabs[0].left() + 4.0, 24.0)


def row_rect(state: StorageState, index: int) -> QRectF:
    y = CATS_TOP
    for i in range(index):
        y += ROW_H + PAN_H * max(0.0, min(1.06, state.rows[i].p.x))
    return QRectF(8.0, y, CARD_W - 16.0, ROW_H)


def open_btn_rect(state: StorageState, index: int) -> Optional[QRectF]:
    if not state.expanded or index != state.selected_row or not 0 <= index < len(state.rows):
        return None
    p = max(0.0, min(1.0, state.rows[index].p.x))
    if p < 0.5:
        return None
    rr = row_rect(state, index)
    return QRectF(CARD_W - 16.0 - 62.0, rr.bottom() + 8.0, 62.0, 28.0)


def hit_test_drive(state: StorageState, pt: QPointF) -> int:
    for i, r in enumerate(drive_tab_rects(len(state.drives))):
        if r.contains(pt):
            return i
    return -1


def hit_test_row(state: StorageState, pt: QPointF) -> int:
    if pt.y() < CATS_TOP or pt.y() > state.card_h.x - 8.0:
        return -1
    for i in range(len(state.rows)):
        if row_rect(state, i).contains(pt):
            return i
    return -1


def paint_storage_card(
    p: QPainter,
    rect: QRectF,
    state: StorageState,
    light: bool = False,
    theme=None,
):
    pal = resolve_storage_palette(light=light, theme=theme)
    card_h = max(120.0, state.card_h.x)
    s = rect.width() / CARD_W
    dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    origin = p.transform().map(rect.topLeft())
    snapped = QPointF(round(origin.x() * dpr) / dpr, round(origin.y() * dpr) / dpr)
    rect = QRectF(rect.topLeft() + (snapped - origin), rect.size())

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.translate(rect.topLeft())
    p.scale(s, s)

    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0.0, 0.0, CARD_W, card_h), RADIUS, RADIUS)
    p.setClipPath(clip)

    # Fundo
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal.surface)
    p.drawRect(QRectF(0.0, 0.0, CARD_W, card_h))

    # 1. Cabeçalho: "Armazenamento" + discos (C:/D:) + chevron expandir/recolher
    f_head = _font(13.0, QFont.Weight.Medium)
    fm_head = QFontMetricsF(f_head)
    p.setFont(f_head)
    p.setPen(pal.muted)
    p.drawText(QPointF(18.0, _baseline(14.0, 24.0, fm_head)), t("storage_card_title"))

    # Abas de disco (só aparecem quando há 2+ discos)
    drv_box = drive_container_rect(len(state.drives))
    if drv_box is not None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pal.fill1)
        p.drawRoundedRect(drv_box, 12.0, 12.0)
        f_drv = _font(11.0, QFont.Weight.DemiBold)
        fm_drv = QFontMetricsF(f_drv)
        p.setFont(f_drv)
        for i, tr in enumerate(drive_tab_rects(len(state.drives))):
            active = i == state.active_drive_index
            hovered = i == state.hovered_drive
            if active:
                p.setBrush(pal.fill3)
                p.drawRoundedRect(tr, 10.0, 10.0)
            elif hovered:
                p.setBrush(pal.fill2)
                p.drawRoundedRect(tr, 10.0, 10.0)
            p.setPen(pal.text if (active or hovered) else pal.muted)
            lbl = state.drives[i].drive
            lw = fm_drv.horizontalAdvance(lbl)
            p.drawText(QPointF(tr.center().x() - lw / 2.0, _baseline(tr.top(), tr.height(), fm_drv)), lbl)
            p.setPen(Qt.PenStyle.NoPen)

    # Botão chevron expandir/recolher
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal.fill2 if state.hovered_expand else pal.fill1)
    p.drawEllipse(EXPAND_BTN_RECT)
    p.save()
    c = EXPAND_BTN_RECT.center()
    p.translate(c)
    if state.expanded:
        p.rotate(180.0)
    p.setPen(QPen(pal.text if state.hovered_expand else pal.muted, 1.8, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(-3.8, -1.6), QPointF(0.0, 2.2))
    p.drawLine(QPointF(0.0, 2.2), QPointF(3.8, -1.6))
    p.restore()

    drv = state.active_drive
    if drv is None:
        f_empty = _font(13.0, QFont.Weight.Medium)
        fm_e = QFontMetricsF(f_empty)
        p.setFont(f_empty)
        p.setPen(pal.muted)
        msg = t("storage_empty_hint")
        mw = fm_e.horizontalAdvance(msg)
        p.drawText(QPointF((CARD_W - mw) / 2.0, _baseline(105.0, 24.0, fm_e)), msg)
        _paint_border(p, card_h, pal, s)
        p.restore()
        return

    # 2. Hero: tambor rolante "ddd.d GB of XXX GB"
    x = _paint_roller(p, state, 18.0, 42.0, pal)
    f_gb = _font(15.0, QFont.Weight.DemiBold)
    fm_gb = QFontMetricsF(f_gb)
    p.setFont(f_gb)
    p.setPen(pal.text)
    p.drawText(QPointF(x + 3.0, _baseline(54.0, 20.0, fm_gb)), "GB")
    x += 3.0 + fm_gb.horizontalAdvance("GB") + 5.0

    f_unit = _font(12.5, QFont.Weight.Medium)
    fm_unit = QFontMetricsF(f_unit)
    p.setFont(f_unit)
    p.setPen(pal.cap)
    cap_txt = t("storage_of_total").format(total=f"{drv.total_gb:.0f}")
    p.drawText(QPointF(x, _baseline(56.0, 18.0, fm_unit)), cap_txt)

    # 3. Subtítulo do disco: "Secondary SSD (D:)" e "81% usado"
    f_sub = _font(12.0, QFont.Weight.Medium)
    fm_sub = QFontMetricsF(f_sub)
    p.setFont(f_sub)
    p.setPen(pal.muted2)
    elided_lbl = fm_sub.elidedText(drv.label, Qt.TextElideMode.ElideRight, 185.0)
    p.drawText(QPointF(18.0, _baseline(78.0, 16.0, fm_sub)), elided_lbl)

    pct = (drv.used_gb / drv.total_gb * 100.0) if drv.total_gb > 0 else 0.0
    pct_txt = t("storage_pct_used").format(pct=f"{pct:.0f}")
    pw = fm_sub.horizontalAdvance(pct_txt)
    p.drawText(QPointF(CARD_W - 18.0 - pw, _baseline(78.0, 16.0, fm_sub)), pct_txt)

    # 4. Barra segmentada com molas
    p.save()
    bar_clip = QPainterPath()
    bar_clip.addRoundedRect(BAR_RECT, 6.0, 6.0)
    p.setClipPath(bar_clip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal.fill2)
    p.drawRect(BAR_RECT)

    cap_gb = max(1.0, drv.total_gb)
    scale_x = BAR_RECT.width() / cap_gb
    gap = 2.0
    min_seg_w = 6.0

    # Calcula larguras com mínimo visível para pastas pequenas (ex.: 7.6 GB num SSD de 930 GB)
    seg_widths: list[float] = []
    for r in state.rows:
        if r.w.x > 0.005:
            seg_widths.append(max(min_seg_w, r.w.x * scale_x))
        else:
            seg_widths.append(0.0)
    other_w = max(0.0, state.other_w.x * scale_x)

    active_segs = sum(1 for w in seg_widths if w > 0.0) + (1 if other_w > 0.5 else 0)
    total_gaps = gap * max(0, active_segs - 1)
    total_fill = sum(seg_widths) + other_w
    max_fill = max(1.0, BAR_RECT.width() - total_gaps)
    if total_fill > max_fill:
        # Encolhe primeiro o segmento neutro ("Outros") antes de comprimir as pastas monitoradas
        overflow = total_fill - max_fill
        if other_w > overflow:
            other_w -= overflow
        else:
            other_w = 0.0
            rem = sum(seg_widths)
            if rem > max_fill:
                ratio = max_fill / rem
                seg_widths = [w * ratio for w in seg_widths]

    seg_x = BAR_RECT.left()
    for j, (r, draw_w) in enumerate(zip(state.rows, seg_widths)):
        if draw_w > 0.5:
            sy = max(0.5, min(1.1, 0.86 + 0.14 * r.h.x))
            sh = BAR_RECT.height() * sy
            cy = BAR_RECT.center().y()
            col = QColor(SEGMENT_COLORS[j % len(SEGMENT_COLORS)])
            col.setAlphaF(max(0.0, min(1.0, r.o.x)))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(seg_x, cy - sh / 2.0, draw_w, sh), sh / 2.0, sh / 2.0)
            seg_x += draw_w + gap

    # Segmento neutro ("Outros")
    if other_w > 0.5:
        sh = BAR_RECT.height() * 0.86
        cy = BAR_RECT.center().y()
        ocol = QColor(pal.fill3)
        ocol.setAlphaF(ocol.alphaF() * 0.75)
        p.setBrush(ocol)
        p.drawRoundedRect(QRectF(seg_x, cy - sh / 2.0, other_w, sh), sh / 2.0, sh / 2.0)
    p.restore()

    # 5. Lista de pastas (cortada no limite inferior do cartão)
    p.save()
    list_clip = QPainterPath()
    list_clip.addRect(QRectF(0.0, CATS_TOP, CARD_W, max(0.0, card_h - CATS_TOP - 8.0)))
    p.setClipPath(list_clip)

    # Pílula de destaque deslizante (.hl)
    if state.hl_o.x > 0.01 and state.rows:
        hl_col = QColor(pal.fill1)
        hl_col.setAlphaF(hl_col.alphaF() * max(0.0, min(1.0, state.hl_o.x)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(hl_col)
        p.drawRoundedRect(QRectF(8.0, CATS_TOP + state.hl_y.x, CARD_W - 16.0, max(0.0, state.hl_h.x)), 15.0, 15.0)

    f_nm = _font(13.5, QFont.Weight.Medium)
    fm_nm = QFontMetricsF(f_nm)
    f_sz = _font(13.0, QFont.Weight.Medium, tabular=True)
    fm_sz = QFontMetricsF(f_sz)
    f_path = _font(11.5, QFont.Weight.Medium)
    fm_path = QFontMetricsF(f_path)
    f_det = _font(11.5, QFont.Weight.Medium)
    fm_det = QFontMetricsF(f_det)

    y = CATS_TOP
    for i, r in enumerate(state.rows):
        rr = QRectF(8.0, y, CARD_W - 16.0, ROW_H)
        on = state.expanded and i == state.selected_row
        hovered = i == state.hovered_row

        # Ponto colorido com pop-spring
        dot_s = max(0.0, r.dot.x)
        dot_r = 4.5 * dot_s
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(SEGMENT_COLORS[i % len(SEGMENT_COLORS)])
        p.drawEllipse(QPointF(rr.left() + 14.5, rr.center().y()), dot_r, dot_r)

        # Nome da pasta (limpo, sem tag "Custom")
        p.setFont(f_nm)
        p.setPen(pal.text if (on or hovered) else pal.text2)
        name_x = rr.left() + 29.0
        max_name_w = rr.width() - 29.0 - 74.0
        elided_name = fm_nm.elidedText(r.folder.name, Qt.TextElideMode.ElideRight, max_name_w)
        p.drawText(QPointF(name_x, _baseline(rr.top(), rr.height(), fm_nm)), elided_name)

        # Tamanho em GB
        p.setFont(f_sz)
        p.setPen(pal.size)
        sz_txt = _fmt_gb(r.folder.size_gb)
        sw = fm_sz.horizontalAdvance(sz_txt)
        p.drawText(QPointF(rr.right() - 10.0 - sw, _baseline(rr.top(), rr.height(), fm_sz)), sz_txt)

        y += ROW_H

        # Painel de detalhes expandido (caminho + % do disco + arquivos + botão Abrir)
        pan_p = max(0.0, min(1.06, r.p.x))
        pan_h = PAN_H * pan_p
        if pan_h > 1.0:
            op = max(0.0, min(1.0, r.p.x * 1.8 - 0.8))
            if op > 0.01:
                p.save()
                p.setOpacity(op)
                dy = (1.0 - max(0.0, min(1.0, r.p.x))) * -6.0
                meta_x = rr.left() + 29.0
                meta_w = rr.width() - 29.0 - 76.0

                p.setFont(f_path)
                p.setPen(pal.path)
                elided_path = fm_path.elidedText(r.folder.path, Qt.TextElideMode.ElideMiddle, meta_w)
                p.drawText(QPointF(meta_x, _baseline(y + 4.0 + dy, 16.0, fm_path)), elided_path)

                share = (r.folder.size_gb / drv.total_gb * 100.0) if drv.total_gb > 0 else 0.0
                if r.folder.is_game_library:
                    det_txt = t("storage_row_detail_games").format(
                        pct=f"{share:.1f}", drive=drv.drive, count=r.folder.file_count,
                    )
                else:
                    det_txt = t("storage_row_detail").format(
                        pct=f"{share:.1f}", drive=drv.drive, files=f"{r.folder.file_count:,}",
                    )
                p.setFont(f_det)
                p.setPen(pal.detail)
                elided_det = fm_det.elidedText(det_txt, Qt.TextElideMode.ElideRight, meta_w)
                p.drawText(QPointF(meta_x, _baseline(y + 21.0 + dy, 16.0, fm_det)), elided_det)

                # Botão "Abrir" (Explorer)
                ob = QRectF(CARD_W - 16.0 - 62.0, y + 8.0 + dy, 62.0, 28.0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(pal.fill3 if state.hovered_open else pal.fill2)
                p.drawRoundedRect(ob, 14.0, 14.0)
                f_btn = _font(11.5, QFont.Weight.DemiBold)
                fm_btn = QFontMetricsF(f_btn)
                p.setFont(f_btn)
                p.setPen(pal.text)
                lbl_open = t("storage_open_btn")
                ow_b = fm_btn.horizontalAdvance(lbl_open)
                p.drawText(QPointF(ob.center().x() - ow_b / 2.0, _baseline(ob.top(), ob.height(), fm_btn)), lbl_open)
                p.restore()
            y += pan_h

    p.restore()
    _paint_border(p, card_h, pal, s)
    p.restore()


def _paint_roller(p: QPainter, state: StorageState, x0: float, y0: float, pal: StoragePalette) -> float:
    """Desenha os dígitos rolantes ('ddd.d') e retorna o x final."""
    f_num = _font(30.0, QFont.Weight.DemiBold, tabular=True)
    fm = QFontMetricsF(f_num)
    cell_h = 34.0
    col_w = 18.0
    x = x0

    p.setFont(f_num)
    p.setPen(pal.text)

    for idx, col in enumerate(state.total_roller.cols):
        if idx == 0 and not state.total_roller.show_hundreds:
            continue
        if idx == 3:
            dot_w = fm.horizontalAdvance(".")
            p.drawText(QPointF(x, _baseline(y0, cell_h, fm)), ".")
            x += dot_w + 1.0

        p.save()
        p.setClipRect(QRectF(x, y0, col_w, cell_h))
        val = col.x
        base_d = int(val)
        for d in range(max(0, base_d - 1), min(10, base_d + 2)):
            dy = (d - val) * cell_h
            ch = str(d)
            cw = fm.horizontalAdvance(ch)
            p.drawText(QPointF(x + (col_w - cw) / 2.0, _baseline(y0 + dy, cell_h, fm)), ch)
        p.restore()
        x += col_w

    return x


def _paint_border(p: QPainter, card_h: float, pal: StoragePalette, s: float):
    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(pal.border, 1.0 / s))
    inset = 0.5 / s
    p.drawRoundedRect(QRectF(inset, inset, CARD_W - 2.0 * inset, card_h - 2.0 * inset), RADIUS, RADIUS)
