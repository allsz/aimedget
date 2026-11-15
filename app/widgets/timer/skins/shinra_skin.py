"""
Skin Shinra do Timer: a arte do logo ocupa o cartão inteiro (o quadrado base) e as quatro pontas do losango passam
da borda. O nome do modo é montado com as letras da identidade (PNG), os números usam uma fonte manuscrita grossa com
contorno e sombra como o kanji, e os botões ficam centrados no losango.

Pintura pura (QPainter) em `paint_shinra_timer`, compartilhada pelo widget e pela miniatura do Hub.
O comportamento (arrastar, redimensionar, editar o tempo, menu) vem do WindowsTimerSkin.
"""

import json
import math
import os
import unicodedata

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPaintEvent, QPen, QPixmap, QTransform,
)

from app.core.config_manager import config_manager
from app.core.paths import ASSETS_DIR
from app.core.theme_art import presample
from app.widgets.timer.skins.skin import TimerState, _paint_select_sweep, mode_label
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin

SKIN_DIR = os.path.join(ASSETS_DIR, "skins", "shinra")
ART_FILE = os.path.join(SKIN_DIR, "arte.png")
LETTERS_DIR = os.path.join(SKIN_DIR, "letters")
LETTERS_META = os.path.join(SKIN_DIR, "letters.json")

# --- Medidas, em px do cartão no tamanho padrão (148 x 148) ---------------------------------------------------------
# A arte original tem 1932 x 1927,6 unidades; o quadrado base vai de 154 a 1778 e é o cartão. K converte unidades em px.
SIDE = 148.0
K = SIDE / 1624.0
ART_SIZE = QSizeF(1932.0 * K, 1927.6 * K)
ART_ORIGIN = QPointF(-154.0 * K, -154.0 * K)
TIP_OVERSHOOT = 154.0 * K          # quanto cada ponta do losango passa da borda do cartão (~14 px)

CENTER_X = SIDE / 2.0
LABEL_CY = (0.212 * 1927.6 - 154.0) * K     # centro do nome do modo
DIGITS_CY = (0.500 * 1927.6 - 154.0) * K    # centro dos números: o centro do losango
BUTTONS_CY = (0.639 * 1927.6 - 154.0) * K + 4.0
BUTTON_DIAM = 234.0 * K
BUTTON_SPACING = 381.0 * K                  # entre os centros do Play e do Reset
DIGITS_FONT_PX = 0.108 * ART_SIZE.width()
LABEL_UNIT = 0.000235 * ART_SIZE.width()    # px do cartão por px do PNG das letras
LABEL_MAX_W = 66.0                          # nomes mais longos que isso encolhem

INK = QColor("#3a0e10")
PINK = QColor("#c08080")
DIGIT_FILL = QColor("#ffeaea")
ORANGE = QColor("#f58a1f")
YELLOW = QColor("#f6ee3a")
RESET_FILL = QColor("#6b0a0c")
RESET_ICON = QColor("#e8b4b4")
PLAY_ICON = QColor("#3a0306")

DIGIT_FAMILIES = ["Ink Free", "Segoe Print", "Kristen ITC", "Segoe UI"]
FALLBACK_FAMILIES = ["Garamond", "Palatino Linotype", "Georgia", "Times New Roman"]

_pixmaps: dict[str, QPixmap | None] = {}
_art_scaled: dict[tuple[int, int], QPixmap] = {}
_meta: dict | None = None


def _letters_meta() -> dict:
    global _meta
    if _meta is None:
        try:
            with open(LETTERS_META, encoding="utf-8") as fh:
                _meta = json.load(fh)
        except (OSError, ValueError):
            _meta = {}
    return _meta


def _pixmap(path: str) -> QPixmap | None:
    if path not in _pixmaps:
        pm = QPixmap(path)
        _pixmaps[path] = None if pm.isNull() else pm
    return _pixmaps[path]


_silhouettes: dict[int, QPixmap] = {}


def _silhouette(pm: QPixmap) -> QPixmap:
    """A mesma letra toda em tinta escura: desenhada deslocada em volta, vira um contorno que lê bem sobre a gravata."""
    key = pm.cacheKey()
    out = _silhouettes.get(key)
    if out is None:
        out = QPixmap(pm)
        q = QPainter(out)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        q.fillRect(out.rect(), INK)
        q.end()
        _silhouettes[key] = out
    return out


def _art_for(w: float, h: float) -> QPixmap | None:
    pm = _pixmap(ART_FILE)
    if pm is None:
        return None
    key = (int(round(w)), int(round(h)))
    cached = _art_scaled.get(key)
    if cached is None:
        if len(_art_scaled) > 8:
            _art_scaled.clear()
        cached = presample(pm, w, h)
        _art_scaled[key] = cached
    return cached


# --- Nome do modo, montado com as letras da identidade -----------------------------------------------------------------

_ACCENTS = {"̂": "circumflex", "́": "acute", "̀": "grave", "̈": "diaeresis"}
_OUTLINE_R = 11.0   # espessura do contorno escuro das letras, em px do PNG
_OUTLINE = [(_OUTLINE_R * math.cos(a * math.pi / 4.0), _OUTLINE_R * math.sin(a * math.pi / 4.0)) for a in range(8)]


def _split_accents(text: str) -> list[tuple[str, str | None]]:
    """[(letra-base, acento|None)]: 'Ô' vira ('O', 'circumflex'). Acentos que não sabemos desenhar são descartados."""
    out: list[tuple[str, str | None]] = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.combining(ch):
            if out:
                out[-1] = (out[-1][0], _ACCENTS.get(ch))
            continue
        out.append((ch, None))
    return out


def _fallback_font(px: float) -> QFont:
    font = QFont()
    font.setFamilies(FALLBACK_FAMILIES)
    font.setPixelSize(max(1, int(px)))
    return font


def _accent_path(kind: str) -> QPainterPath:
    """Acento em uma caixa de 100 x 50 (mesmo desenho da mockup)."""
    pts = {
        "circumflex": [(8, 46), (50, 4), (92, 46), (84, 49), (50, 20), (16, 49)],
        "acute": [(34, 50), (62, 4), (80, 12), (50, 52)],
        "grave": [(66, 50), (38, 4), (20, 12), (50, 52)],
    }.get(kind)
    path = QPainterPath()
    if pts:
        path.moveTo(*pts[0])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
    elif kind == "diaeresis":
        path.addEllipse(QPointF(30, 30), 11, 11)
        path.addEllipse(QPointF(70, 30), 11, 11)
    return path


def _layout_label(text: str) -> tuple[list[dict], float]:
    """Posiciona as letras em unidades do PNG (a linha de base fica em y = 0). Devolve (itens, largura)."""
    meta = _letters_meta()
    items: list[dict] = []
    x = 0.0
    start_of_word = True
    for base, accent in _split_accents(text):
        if base.isspace():
            x += 48.0
            start_of_word = True
            continue
        low = base.lower()
        if "a" <= low <= "z" and meta:
            name = f"upper_initial_{low.upper()}" if start_of_word else f"lower_{low}"
            info = meta.get(name)
            pm = _pixmap(os.path.join(LETTERS_DIR, name + ".png")) if info else None
            if pm is not None:
                items.append({"kind": "img", "pm": pm, "x": x, "base": info["base"], "w": info["w"], "h": info["h"],
                              "accent": accent})
                x += info["w"] + (-14.0 if (start_of_word and base.upper() == "C") else
                                  -4.0 if start_of_word else 3.0)
                start_of_word = False
                continue
        # Dígitos, pontuação e o que não tem letra: fonte serifada, na cor do logo
        font = _fallback_font(290.0)
        w = QFontMetricsF(font).horizontalAdvance(base)
        items.append({"kind": "glyph", "ch": base, "font": font, "x": x, "w": w})
        x += w + 4.0
        start_of_word = False
    width = max(0.0, x - 3.0)
    return items, width


def paint_label(p: QPainter, cx: float, cy: float, text: str, scale: float):
    items, width = _layout_label(text)
    if not items or width <= 0:
        return
    unit = min(LABEL_UNIT * scale, LABEL_MAX_W * scale / width)
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(cx - width * unit / 2.0, cy + 109.0 * unit)   # linha de base: a caixa das letras fica centrada em cy
    p.scale(unit, unit)
    for it in items:
        if it["kind"] == "img":
            box, src = QRectF(it["x"], -it["base"], it["w"], it["h"]), QRectF(it["pm"].rect())
            dark = _silhouette(it["pm"])
            for ox, oy in _OUTLINE:
                p.drawPixmap(box.translated(ox, oy), dark, src)
            p.drawPixmap(box, it["pm"], src)
            if it["accent"]:
                path = _accent_path(it["accent"])
                if not path.isEmpty():
                    top = -it["base"] - 62.0 * 0.92 + (46.0 * 0.92 if it["accent"] == "diaeresis" else 0.0)
                    tr = QTransform()
                    tr.translate(it["x"] + it["w"] / 2.0 - 46.0, top)
                    tr.scale(0.92, 0.92)
                    shaded = tr.map(path)
                    p.fillPath(shaded.translated(5.0, 5.0), QColor(0, 0, 0))
                    p.fillPath(shaded, ORANGE)
        else:
            path = QPainterPath()
            path.addText(it["x"], 0.0, it["font"], it["ch"])
            p.strokePath(path, QPen(INK, 2 * _OUTLINE_R, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
            p.fillPath(path.translated(4.0, 4.0), QColor(0, 0, 0))
            p.fillPath(path, ORANGE)
    p.restore()


# --- Números --------------------------------------------------------------------------------------------------------------

def digits_font(scale: float) -> QFont:
    font = QFont()
    font.setFamilies(DIGIT_FAMILIES)
    font.setPixelSize(max(12, int(round(DIGITS_FONT_PX * scale))))
    font.setWeight(QFont.Weight.Bold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferQuality | QFont.StyleStrategy.PreferAntialias)
    return font


def digits_layout(card: QRectF, scale: float, seconds: float):
    """
    Geometria dos segmentos (horas, dois-pontos, minutos, segundos) centrada no centro do losango, nos dois eixos.
    Cada dígito ocupa uma célula de largura fixa, então o texto não balança quando os números mudam.
    Devolve (rects, textos, fonte, linha-de-base-y, largura-da-célula).
    """
    font = digits_font(scale)
    fm = QFontMetricsF(font)
    cell = max(fm.horizontalAdvance(str(d)) for d in range(10))
    colon_w = fm.horizontalAdvance(":")
    total = max(0, int(round(seconds)))
    texts = {
        "hours": f"{total // 3600:02d}", "colon1": ":",
        "minutes": f"{(total % 3600) // 60:02d}", "colon2": ":",
        "seconds": f"{total % 60:02d}",
    }
    widths = {"hours": 2 * cell, "colon1": colon_w, "minutes": 2 * cell, "colon2": colon_w, "seconds": 2 * cell}
    total_w = sum(widths.values())
    cy = card.top() + DIGITS_CY * scale
    height = fm.height()
    x = card.center().x() - total_w / 2.0
    rects = {}
    for key in ("hours", "colon1", "minutes", "colon2", "seconds"):
        rects[key] = QRectF(x, cy - height / 2.0, widths[key], height)
        x += widths[key]
    baseline = cy + fm.capHeight() / 2.0
    return rects, texts, font, baseline, cell


def _paint_text_path(p: QPainter, path: QPainterPath, fill: QColor, scale: float):
    p.fillPath(path.translated(0.5 * scale * 1.7, 0.6 * scale * 1.7), INK)       # sombra deslocada
    p.strokePath(path, QPen(INK, 1.3 * scale * 1.7 + 1.0 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))                           # contorno por baixo do preenchimento
    p.strokePath(path, QPen(fill, 1.0 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))                           # engrossa o traço (a fonte só tem um peso)
    p.fillPath(path, fill)


def paint_digits(p: QPainter, card: QRectF, scale: float, state: TimerState):
    rects, texts, font, baseline, cell = digits_layout(card, scale, state.current_seconds)
    fm = QFontMetricsF(font)
    for key in ("hours", "colon1", "minutes", "colon2", "seconds"):
        r = rects[key]
        hovered = (state.is_smart_hover_enabled and not state.is_running and state.hovered_time_segment == key)
        fill = DIGIT_FILL
        if hovered:
            pill = QColor(YELLOW)
            pill.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(pill))
            p.drawRoundedRect(r.adjusted(-2.5 * scale, 1.5 * scale, 2.5 * scale, -1.5 * scale), 5 * scale, 5 * scale)
            fill = YELLOW
        elif state.is_alarm_pulsing:
            fill = YELLOW
        text = texts[key]
        if key.startswith("colon"):
            path = QPainterPath()
            path.addText(r.left() + (r.width() - fm.horizontalAdvance(":")) / 2.0, baseline, font, ":")
            _paint_text_path(p, path, fill, scale)
        else:
            for i, ch in enumerate(text):
                path = QPainterPath()
                path.addText(r.left() + i * cell + (cell - fm.horizontalAdvance(ch)) / 2.0, baseline, font, ch)
                _paint_text_path(p, path, fill, scale)
        if state.select_segment == key and 0.0 < state.select_progress < 1.0:
            _paint_select_sweep(p, r.adjusted(-3.0 * scale, 2.0 * scale, 3.0 * scale, -2.0 * scale), 4.0 * scale,
                                scale, state, _SweepTheme)


class _SweepTheme:
    """O volta-de-luz só lê `is_dark` quando o estado não traz cor; aqui o fundo é sempre escuro."""
    is_dark = True


# --- Botões ---------------------------------------------------------------------------------------------------------------

def buttons_geometry(card: QRectF, scale: float) -> tuple[QRectF, QRectF]:
    """Play e Reset, centrados juntos no eixo X do cartão (a distância entre eles vem da mockup)."""
    d = BUTTON_DIAM * scale
    cy = card.top() + BUTTONS_CY * scale
    half = BUTTON_SPACING * scale / 2.0
    cx = card.center().x()
    return (QRectF(cx - half - d / 2.0, cy - d / 2.0, d, d),
            QRectF(cx + half - d / 2.0, cy - d / 2.0, d, d))


def _paint_button_disc(p: QPainter, rect: QRectF, fill: QColor, edge: QColor, scale: float, alpha: float = 1.0):
    ring = 0.55 * ART_SIZE.width() / 100.0 * scale
    off = QPointF(0.5 * ART_SIZE.width() / 100.0 * scale, 0.6 * ART_SIZE.width() / 100.0 * scale)
    p.save()
    p.setOpacity(p.opacity() * alpha)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(edge))
    p.drawEllipse(rect.translated(off).adjusted(-ring, -ring, ring, ring))
    p.setBrush(QBrush(INK))
    p.drawEllipse(rect.adjusted(-ring, -ring, ring, ring))
    p.setBrush(QBrush(fill))
    p.drawEllipse(rect)
    p.restore()


def paint_buttons(p: QPainter, card: QRectF, scale: float, state: TimerState):
    play, reset = buttons_geometry(card, scale)

    fill = QColor(PINK)
    if state.hovered_btn == "play_pause" and state.is_play_enabled:
        fill = fill.lighter(112)
    if state.pressed_btn == "play_pause" and state.is_play_enabled:
        fill = fill.darker(112)
    _paint_button_disc(p, play, fill, QColor("#ffffff"), scale, 1.0 if state.is_play_enabled else 0.4)
    c, icon = play.center(), 0.56 * play.width()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(PLAY_ICON))
    if state.is_play_enabled:
        if state.is_running:
            bar_w, gap = icon * 0.21, icon * 0.2
            for dx in (-bar_w - gap / 2.0, gap / 2.0):
                p.drawRoundedRect(QRectF(c.x() + dx, c.y() - icon / 2.0, bar_w, icon), bar_w * 0.3, bar_w * 0.3)
        else:
            tri = QPainterPath()
            tri.moveTo(c.x() - icon * 0.36 + icon * 0.07, c.y() - icon / 2.0)
            tri.lineTo(c.x() + icon * 0.46 + icon * 0.07, c.y())
            tri.lineTo(c.x() - icon * 0.36 + icon * 0.07, c.y() + icon / 2.0)
            tri.closeSubpath()
            p.drawPath(tri)

    rfill = QColor(RESET_FILL)
    if state.hovered_btn == "reset":
        rfill = rfill.lighter(125)
    if state.pressed_btn == "reset":
        rfill = rfill.darker(115)
    _paint_button_disc(p, reset, rfill, PINK, scale)
    c = reset.center()
    r = 0.56 * reset.width() * 0.36
    pen = QPen(RESET_ICON, 0.56 * reset.width() * 0.125, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), int(35 * 16), int(290 * 16))
    tip = QPointF(c.x() + r * math.cos(math.radians(35)), c.y() - r * math.sin(math.radians(35)))
    head = QPainterPath()
    head.moveTo(tip.x() + r * 0.55, tip.y() - r * 0.05)
    head.lineTo(tip.x() + r * 0.02, tip.y() + r * 0.02)
    head.lineTo(tip.x() + r * 0.02, tip.y() - r * 0.6)
    p.drawPath(head)


# --- Cartão ---------------------------------------------------------------------------------------------------------------

def paint_shinra_timer(p: QPainter, rect: QRectF, state: TimerState | None = None, theme=None, art=None):
    """`rect` é o quadrado do widget (cartão + 8 px de folga). `theme` e `art` existem só para ter a mesma assinatura
    da skin Padrão: esta skin tem arte própria e não usa os temas do Timer."""
    if state is None:
        state = TimerState()
    pad = 8.0
    card = QRectF(rect.x() + pad, rect.y() + pad, rect.width() - 2 * pad, rect.height() - 2 * pad)
    scale = max(0.8, min(card.width(), card.height()) / SIDE)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    target = QRectF(card.left() + ART_ORIGIN.x() * scale, card.top() + ART_ORIGIN.y() * scale,
                    ART_SIZE.width() * scale, ART_SIZE.height() * scale)
    pm = _art_for(target.width(), target.height())
    if pm is not None:
        p.drawPixmap(target, pm, QRectF(pm.rect()))
    else:   # arte ausente (instalação incompleta): fundo liso na cor do logo
        p.fillRect(card, QColor("#8a0a12"))

    paint_label(p, card.center().x(), card.top() + LABEL_CY * scale, mode_label(state), scale)
    paint_digits(p, card, scale, state)
    paint_buttons(p, card, scale, state)

    if state.close_opacity > 0.01:
        close = QRectF(card.left() + 9.0 * scale, card.top() + 9.0 * scale, 22.0 * scale, 22.0 * scale)
        color = QColor(YELLOW)
        color.setAlpha(int(state.close_opacity * 255))
        p.setPen(QPen(color, 1.5 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c, arm = close.center(), 3.6 * scale
        p.drawLine(QPointF(c.x() - arm, c.y() - arm), QPointF(c.x() + arm, c.y() + arm))
        p.drawLine(QPointF(c.x() - arm, c.y() + arm), QPointF(c.x() + arm, c.y() - arm))
    p.restore()


class ShinraTimerSkin(WindowsTimerSkin):
    """Skin Shinra: mesma interação da Padrão, com arte, letras e botões próprios."""

    def _wanted_art_margin(self, side: int) -> int:
        """As pontas do losango passam do cartão (~14 px no tamanho padrão): a janela ganha essa margem."""
        scale = max(0.8, (side - 2 * self.ART_FREE_PAD) / (self.DEFAULT_SIZE - 2 * self.ART_FREE_PAD))
        return max(0, int(math.ceil(TIP_OVERSHOOT * scale + 1.0 - self.ART_FREE_PAD)))

    def reload_skin_theme(self):
        """Os temas do Timer valem só para a skin Padrão; esta tem arte própria."""

    def get_buttons_geometry(self) -> tuple[QRectF, QRectF]:
        play, reset = buttons_geometry(self.get_card_rect(), self.get_scale())
        grow = 3.0 * self.get_scale()   # botões pequenos: a área de clique é um pouco maior que o desenho
        return play.adjusted(-grow, -grow, grow, grow), reset.adjusted(-grow, -grow, grow, grow)

    def get_digits_geometry(self):
        rects, texts, font, _baseline, _cell = digits_layout(self.get_card_rect(), self.get_scale(), self.current_seconds)
        return rects, texts, font

    def get_time_segment_at(self, pos: QPointF) -> str | None:
        rects, _, _ = self.get_digits_geometry()
        scale = self.get_scale()
        top, bottom = rects["hours"].top() - 2 * scale, rects["hours"].bottom() + 2 * scale
        if not (top <= pos.y() <= bottom):
            return None
        px = pos.x()
        c1, c2 = rects["colon1"].center().x(), rects["colon2"].center().x()
        if rects["hours"].left() - 6 * scale <= px <= c1:
            return "hours"
        if c1 < px <= c2:
            return "minutes"
        if c2 < px <= rects["seconds"].right() + 6 * scale:
            return "seconds"
        return None

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        state = TimerState(
            current_seconds=self.current_seconds,
            target_duration=self.target_duration,
            mode=self.mode,
            is_running=self.is_running,
            is_alarm_pulsing=self.is_alarm_pulsing,
            pressed_btn=self.pressed_btn,
            hovered_btn=self.hovered_btn,
            hovered_time_segment=self.hovered_time_segment,
            close_opacity=self._close_opacity,
            is_hovered=self._hovered,
            is_smart_hover_enabled=config_manager.is_timer_smart_hover_enabled(),
            is_play_enabled=self.is_play_enabled(),
            select_segment=self._sweep_segment,
            select_progress=self._sweep_progress,
            select_color=QColor("#ffffff"),
            alarm_time=self.alarm_time,
            alarm_finished=self.alarm_finished,
        )
        m = float(self.art_margin)
        paint_shinra_timer(p, QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m), state)
        if self._hovered or self._is_resizing:
            self._paint_resize_grip(p, self.get_scale())
        p.end()
