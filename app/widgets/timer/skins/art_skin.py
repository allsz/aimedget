"""
Skin do Timer com arte própria, vinda de um PACOTE (ver app/core/skin_packs.py): a arte ocupa o cartão inteiro (o quadrado
base) e pode passar da borda; o nome do modo é montado com letras em PNG do pacote, os números usam uma fonte grossa com
contorno e sombra, e os botões ficam centrados na arte. Nada aqui é de uma skin específica: tamanhos, posições, cores e
fontes vêm do `skin.json` do pacote, em "unidades da arte".

Pintura pura (QPainter) em `paint_art_timer`, compartilhada pelo widget e pela miniatura do Hub. O comportamento
(arrastar, redimensionar, editar o tempo, menu) vem do WindowsTimerSkin.

`skin.json` (todas as chaves de medida são em unidades da arte; `art.units` é o lado do cartão nessas unidades):

    {
      "widget": "timer", "name": "Nome", "subtitle": {"pt": "...", "en": "..."},
      "art":     {"file": "arte.png", "units": 1624, "origin": [-154, -154], "size": [1932, 1927.6], "tip_overshoot": 154},
      "label":   {"letters_dir": "letters", "letters_meta": "letters.json", "cy": 254.6, "unit": 0.454, "max_width": 724},
      "digits":  {"cy": 809.8, "font_px": 208.7, "fonts": ["Ink Free", "Segoe UI"]},
      "buttons": {"cy": 1121.6, "diameter": 234, "spacing": 381, "ring": 10.6, "shadow": [9.7, 11.6]},
      "colors":  {"ink": "#3a0e10", "button": "#c08080", "digits": "#ffeaea", "label_accent": "#f58a1f",
                  "highlight": "#f6ee3a", "reset_fill": "#6b0a0c", "reset_icon": "#e8b4b4", "play_icon": "#3a0306",
                  "fallback": "#8a0a12"},
      "fallback_fonts": ["Georgia"]
    }
"""

import json
import math
import os
import unicodedata

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QBitmap, QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPaintEvent, QPen, QPixmap, QRegion,
    QTransform,
)

from app.core.config_manager import config_manager
from app.core.skin_packs import SkinPack
from app.core.theme_art import presample
from app.widgets.timer.skins.skin import TimerState, _paint_select_sweep, mode_label
from app.widgets.timer.time_layout import SLOT_KEYS, cell_advance, layout_slots, morph_target, slot_texts, slot_visibility
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin

SIDE = 148.0   # lado do cartão no tamanho padrão, em px


def _num(value, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float(default)


def _pair(value, default: tuple[float, float]) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
        return float(value[0]), float(value[1])
    return default


def _color(value, default: str) -> QColor:
    c = QColor(value) if isinstance(value, str) else QColor()
    return c if c.isValid() else QColor(default)


def _fonts(value, default: list[str]) -> list[str]:
    return [f for f in value if isinstance(f, str)] if isinstance(value, list) and value else list(default)


class ArtLook:
    """O `skin.json` de um pacote já convertido para px do cartão (tamanho padrão) e com as imagens em cache."""

    def __init__(self, pack: SkinPack):
        data = pack.data
        sub = lambda key: data.get(key) if isinstance(data.get(key), dict) else {}   # noqa: E731
        art, label, digits, buttons, colors = sub("art"), sub("label"), sub("digits"), sub("buttons"), sub("colors")

        units = max(1.0, _num(art.get("units"), 1000.0))
        k = self.k = SIDE / units                                        # px do cartão por unidade da arte
        ox, oy = _pair(art.get("origin"), (0.0, 0.0))
        aw, ah = _pair(art.get("size"), (units, units))
        self.art_file = pack.path(art["file"])
        self.art_origin = QPointF(ox * k, oy * k)
        self.art_size = QSizeF(aw * k, ah * k)
        self.tip_overshoot = max(0.0, _num(art.get("tip_overshoot"), 0.0)) * k   # quanto a arte passa da borda do cartão

        self.letters_dir = pack.path(str(label.get("letters_dir", "letters")))
        self.letters_meta_file = pack.path(str(label.get("letters_meta", "letters.json")))
        self.label_cy = _num(label.get("cy"), units * 0.15) * k
        self.label_unit = _num(label.get("unit"), 0.4) * k               # px do cartão por px do PNG das letras
        self.label_max_w = _num(label.get("max_width"), units * 0.4) * k   # nomes mais longos que isso encolhem

        self.digits_cy = _num(digits.get("cy"), units * 0.5) * k
        self.digits_font_px = _num(digits.get("font_px"), units * 0.12) * k
        self.digit_families = _fonts(digits.get("fonts"), ["Segoe UI"])
        self.fallback_families = _fonts(data.get("fallback_fonts"), ["Georgia"])

        self.buttons_cy = _num(buttons.get("cy"), units * 0.65) * k
        self.button_diam = _num(buttons.get("diameter"), units * 0.14) * k
        self.button_spacing = _num(buttons.get("spacing"), units * 0.23) * k
        self.ring = _num(buttons.get("ring"), 0.0) * k
        sx, sy = _pair(buttons.get("shadow"), (0.0, 0.0))
        self.ring_shadow = QPointF(sx * k, sy * k)

        self.ink = _color(colors.get("ink"), "#222222")
        self.button = _color(colors.get("button"), "#bbbbbb")
        self.digits = _color(colors.get("digits"), "#ffffff")
        self.label_accent = _color(colors.get("label_accent"), "#f58a1f")
        self.highlight = _color(colors.get("highlight"), "#f6ee3a")
        self.reset_fill = _color(colors.get("reset_fill"), "#555555")
        self.reset_icon = _color(colors.get("reset_icon"), "#dddddd")
        self.play_icon = _color(colors.get("play_icon"), "#111111")
        self.fallback = _color(colors.get("fallback"), "#444444")

        self._pixmaps: dict[str, QPixmap | None] = {}
        self._art_scaled: dict[tuple[int, int], QPixmap] = {}
        self._silhouettes: dict[int, QPixmap] = {}
        self._meta: dict | None = None

    # --- Imagens ---

    def pixmap(self, path: str) -> QPixmap | None:
        if path not in self._pixmaps:
            pm = QPixmap(path)
            self._pixmaps[path] = None if pm.isNull() else pm
        return self._pixmaps[path]

    def letters_meta(self) -> dict:
        if self._meta is None:
            try:
                with open(self.letters_meta_file, encoding="utf-8") as fh:
                    self._meta = json.load(fh)
            except (OSError, ValueError):
                self._meta = {}
        return self._meta

    def silhouette(self, pm: QPixmap) -> QPixmap:
        """A mesma letra toda em tinta escura: desenhada deslocada em volta, vira um contorno que lê bem sobre a arte."""
        out = self._silhouettes.get(pm.cacheKey())
        if out is None:
            out = QPixmap(pm)
            q = QPainter(out)
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            q.fillRect(out.rect(), self.ink)
            q.end()
            self._silhouettes[pm.cacheKey()] = out
        return out

    OUTLINE_RES = 256   # px do lado maior da máscara de onde sai o contorno (degraus somem sob o halo)

    def outline(self) -> QPainterPath | None:
        """
        Contorno da arte (onde o PNG não é transparente), em coordenadas 0..1 do retângulo da arte. É a borda
        real do cartão de um pacote: pontas, cantos retos ou qualquer forma. None sem arte.
        """
        if not hasattr(self, "_outline"):
            self._outline = None
            pm = self.pixmap(self.art_file)
            if pm is not None:
                img = pm.toImage().scaled(self.OUTLINE_RES, self.OUTLINE_RES, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
                mask = QBitmap.fromImage(img.createAlphaMask(Qt.ImageConversionFlag.ThresholdAlphaDither))
                path = QPainterPath()
                path.addRegion(QRegion(mask))
                path = path.simplified()
                if not path.isEmpty():
                    self._outline = QTransform.fromScale(1.0 / img.width(), 1.0 / img.height()).map(path)
        return self._outline

    def art_for(self, w: float, h: float) -> QPixmap | None:
        pm = self.pixmap(self.art_file)
        if pm is None:
            return None
        key = (int(round(w)), int(round(h)))
        cached = self._art_scaled.get(key)
        if cached is None:
            if len(self._art_scaled) > 8:
                self._art_scaled.clear()
            cached = self._art_scaled[key] = presample(pm, w, h)
        return cached


_looks: dict[str, tuple[float, ArtLook]] = {}


def look_for(pack: SkinPack) -> ArtLook:
    """O `ArtLook` do pacote (com as imagens em cache), refeito se o `skin.json` mudou em disco."""
    try:
        stamp = os.path.getmtime(pack.path("skin.json"))
    except OSError:
        stamp = 0.0
    hit = _looks.get(pack.folder)
    if hit is None or hit[0] != stamp:
        hit = _looks[pack.folder] = (stamp, ArtLook(pack))
    return hit[1]


# --- Nome do modo, montado com as letras do pacote --------------------------------------------------------------------

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


def _accent_path(kind: str) -> QPainterPath:
    """Acento em uma caixa de 100 x 50."""
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


def _fallback_font(look: ArtLook, px: float) -> QFont:
    font = QFont()
    font.setFamilies(look.fallback_families)
    font.setPixelSize(max(1, int(px)))
    return font


def _layout_label(text: str, look: ArtLook) -> tuple[list[dict], float]:
    """Posiciona as letras em unidades do PNG (a linha de base fica em y = 0). Devolve (itens, largura).
    O pacote tem uma letra por arquivo: `upper_initial_X.png` (inicial de palavra) e `lower_x.png` (as demais)."""
    meta = look.letters_meta()
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
            pm = look.pixmap(os.path.join(look.letters_dir, name + ".png")) if info else None
            if pm is not None:
                items.append({"kind": "img", "pm": pm, "x": x, "base": info["base"], "w": info["w"], "h": info["h"],
                              "accent": accent})
                x += info["w"] + (-14.0 if (start_of_word and base.upper() == "C") else
                                  -4.0 if start_of_word else 3.0)
                start_of_word = False
                continue
        # Dígitos, pontuação e o que não tem letra no pacote: fonte do pacote, na cor de destaque das letras
        font = _fallback_font(look, 290.0)
        w = QFontMetricsF(font).horizontalAdvance(base)
        items.append({"kind": "glyph", "ch": base, "font": font, "x": x, "w": w})
        x += w + 4.0
        start_of_word = False
    width = max(0.0, x - 3.0)
    return items, width


def paint_label(p: QPainter, cx: float, cy: float, text: str, scale: float, look: ArtLook):
    items, width = _layout_label(text, look)
    if not items or width <= 0:
        return
    unit = min(look.label_unit * scale, look.label_max_w * scale / width)
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(cx - width * unit / 2.0, cy + 109.0 * unit)   # linha de base: a caixa das letras fica centrada em cy
    p.scale(unit, unit)
    for it in items:
        if it["kind"] == "img":
            box, src = QRectF(it["x"], -it["base"], it["w"], it["h"]), QRectF(it["pm"].rect())
            dark = look.silhouette(it["pm"])
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
                    p.fillPath(shaded, look.label_accent)
        else:
            path = QPainterPath()
            path.addText(it["x"], 0.0, it["font"], it["ch"])
            p.strokePath(path, QPen(look.ink, 2 * _OUTLINE_R, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
            p.fillPath(path.translated(4.0, 4.0), QColor(0, 0, 0))
            p.fillPath(path, look.label_accent)
    p.restore()


# --- Números --------------------------------------------------------------------------------------------------------------

def digits_font(scale: float, look: ArtLook) -> QFont:
    font = QFont()
    font.setFamilies(look.digit_families)
    font.setPixelSize(max(12, int(round(look.digits_font_px * scale))))
    font.setWeight(QFont.Weight.Bold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferQuality | QFont.StyleStrategy.PreferAntialias)
    return font


def digits_layout(card: QRectF, scale: float, seconds: float, look: ArtLook, mode: str = "timer",
                  morph: float | None = None):
    """
    Geometria dos segmentos (horas, minutos, segundos, centésimos e os dois-pontos) centrada no centro da arte, nos
    dois eixos. Cada dígito ocupa uma célula de largura fixa, então o texto não balança quando os números mudam.
    `morph` (0 = MM:SS:cc, 1 = HH:MM:SS; None: o formato do modo) abre/fecha os campos que entram/saem.
    Devolve (rects, textos, fonte, linha-de-base-y, largura-da-célula).
    """
    font = digits_font(scale, look)
    fm = QFontMetricsF(font)
    cell = max(fm.horizontalAdvance(str(d)) for d in range(10))
    texts = slot_texts(mode, seconds)
    vis = slot_visibility(morph_target(mode, seconds) if morph is None else morph)
    cy = card.top() + look.digits_cy * scale
    height = fm.height()
    rects = layout_slots(card.center().x(), cy - height / 2.0, height, cell_advance(cell), fm.horizontalAdvance(":"),
                         texts, vis)
    baseline = cy + fm.capHeight() / 2.0
    return rects, texts, font, baseline, cell


def _paint_text_path(p: QPainter, path: QPainterPath, fill: QColor, scale: float, look: ArtLook):
    p.fillPath(path.translated(0.5 * scale * 1.7, 0.6 * scale * 1.7), look.ink)       # sombra deslocada
    p.strokePath(path, QPen(look.ink, 1.3 * scale * 1.7 + 1.0 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))                               # contorno por baixo do preenchimento
    p.strokePath(path, QPen(fill, 1.0 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))                               # engrossa o traço (a fonte só tem um peso)
    p.fillPath(path, fill)


class _SweepTheme:
    """O volta-de-luz só lê `is_dark` quando o estado não traz cor; aqui o fundo é sempre escuro."""
    is_dark = True


def paint_digits(p: QPainter, card: QRectF, scale: float, state: TimerState, look: ArtLook):
    morph = state.time_morph if state.time_morph is not None else morph_target(state.mode, state.current_seconds)
    rects, texts, font, baseline, cell = digits_layout(card, scale, state.current_seconds, look, state.mode, morph)
    vis = slot_visibility(morph)
    fm = QFontMetricsF(font)
    for key in SLOT_KEYS:
        r = rects[key]
        key_vis = vis[key]
        if key_vis <= 0.004:
            continue   # campo recolhido (horas ou milissegundos que não estão no formato de agora)
        hovered = (state.is_smart_hover_enabled and not state.is_running and state.mode != "stopwatch"
                   and state.hovered_time_segment == key)
        p.save()
        if key_vis < 0.999:   # entrando/saindo: aparece junto com a largura, sem vazar para o vizinho
            p.setClipRect(r.adjusted(-4.0 * scale, -r.height(), 4.0 * scale, r.height()))
            p.setOpacity(p.opacity() * key_vis)
        fill = look.digits
        if hovered:
            pill = QColor(look.highlight)
            pill.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(pill))
            p.drawRoundedRect(r.adjusted(-2.5 * scale, 1.5 * scale, 2.5 * scale, -1.5 * scale), 5 * scale, 5 * scale)
            fill = look.highlight
        elif state.is_alarm_pulsing:
            fill = look.highlight
        text = texts[key]
        if key.startswith("colon"):
            path = QPainterPath()
            path.addText(r.left() + (r.width() - fm.horizontalAdvance(":")) / 2.0, baseline, font, ":")
            _paint_text_path(p, path, fill, scale, look)
        else:
            x0 = r.left() + (r.width() - len(text) * cell) / 2.0
            for i, ch in enumerate(text):
                path = QPainterPath()
                path.addText(x0 + i * cell + (cell - fm.horizontalAdvance(ch)) / 2.0, baseline, font, ch)
                _paint_text_path(p, path, fill, scale, look)
        if state.select_segment == key and 0.0 < state.select_progress < 1.0:
            _paint_select_sweep(p, r.adjusted(-3.0 * scale, 2.0 * scale, 3.0 * scale, -2.0 * scale), 4.0 * scale,
                                scale, state, _SweepTheme)
        p.restore()


# --- Botões ---------------------------------------------------------------------------------------------------------------

def buttons_geometry(card: QRectF, scale: float, look: ArtLook) -> tuple[QRectF, QRectF]:
    """Play e Reset, centrados juntos no eixo X do cartão."""
    d = look.button_diam * scale
    cy = card.top() + look.buttons_cy * scale
    half = look.button_spacing * scale / 2.0
    cx = card.center().x()
    return (QRectF(cx - half - d / 2.0, cy - d / 2.0, d, d),
            QRectF(cx + half - d / 2.0, cy - d / 2.0, d, d))


def _paint_button_disc(p: QPainter, rect: QRectF, fill: QColor, edge: QColor, scale: float, look: ArtLook,
                       alpha: float = 1.0):
    ring = look.ring * scale
    off = QPointF(look.ring_shadow.x() * scale, look.ring_shadow.y() * scale)
    p.save()
    p.setOpacity(p.opacity() * alpha)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(edge))
    p.drawEllipse(rect.translated(off).adjusted(-ring, -ring, ring, ring))
    p.setBrush(QBrush(look.ink))
    p.drawEllipse(rect.adjusted(-ring, -ring, ring, ring))
    p.setBrush(QBrush(fill))
    p.drawEllipse(rect)
    p.restore()


def paint_buttons(p: QPainter, card: QRectF, scale: float, state: TimerState, look: ArtLook):
    play, reset = buttons_geometry(card, scale, look)

    fill = QColor(look.button)
    if state.hovered_btn == "play_pause" and state.is_play_enabled:
        fill = fill.lighter(112)
    if state.pressed_btn == "play_pause" and state.is_play_enabled:
        fill = fill.darker(112)
    _paint_button_disc(p, play, fill, QColor("#ffffff"), scale, look, 1.0 if state.is_play_enabled else 0.4)
    c, icon = play.center(), 0.56 * play.width()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(look.play_icon))
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

    rfill = QColor(look.reset_fill)
    if state.hovered_btn == "reset":
        rfill = rfill.lighter(125)
    if state.pressed_btn == "reset":
        rfill = rfill.darker(115)
    _paint_button_disc(p, reset, rfill, look.button, scale, look)
    c = reset.center()
    r = 0.56 * reset.width() * 0.36
    pen = QPen(look.reset_icon, 0.56 * reset.width() * 0.125, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
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

def paint_art_timer(p: QPainter, rect: QRectF, state: TimerState | None = None, theme=None, art=None, *,
                    pack: SkinPack):
    """`rect` é o quadrado do widget (cartão + 8 px de folga). `theme` e `art` existem só para ter a mesma assinatura
    da skin Padrão: esta skin tem arte própria e não usa os temas do Timer."""
    look = look_for(pack)
    if state is None:
        state = TimerState()
    pad = 8.0
    card = QRectF(rect.x() + pad, rect.y() + pad, rect.width() - 2 * pad, rect.height() - 2 * pad)
    scale = max(0.8, min(card.width(), card.height()) / SIDE)

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    target = QRectF(card.left() + look.art_origin.x() * scale, card.top() + look.art_origin.y() * scale,
                    look.art_size.width() * scale, look.art_size.height() * scale)
    pm = look.art_for(target.width(), target.height())
    if pm is not None:
        p.drawPixmap(target, pm, QRectF(pm.rect()))
    else:   # arte ausente (pasta incompleta): fundo liso
        p.fillRect(card, look.fallback)

    paint_label(p, card.center().x(), card.top() + look.label_cy * scale, mode_label(state), scale, look)
    paint_digits(p, card, scale, state, look)
    paint_buttons(p, card, scale, state, look)

    if state.close_opacity > 0.01:
        close = QRectF(card.left() + 9.0 * scale, card.top() + 9.0 * scale, 22.0 * scale, 22.0 * scale)
        color = QColor(look.highlight)
        color.setAlpha(int(state.close_opacity * 255))
        p.setPen(QPen(color, 1.5 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c, arm = close.center(), 3.6 * scale
        p.drawLine(QPointF(c.x() - arm, c.y() - arm), QPointF(c.x() + arm, c.y() + arm))
        p.drawLine(QPointF(c.x() - arm, c.y() + arm), QPointF(c.x() + arm, c.y() - arm))
    p.restore()


class ArtTimerSkin(WindowsTimerSkin):
    """Skin de pacote: mesma interação da Padrão, com a arte, as letras e os botões do pacote (`pack`, definido por
    `make_art_skin_class`)."""

    pack: SkinPack

    @property
    def look(self) -> ArtLook:
        return look_for(self.pack)

    def _wanted_art_margin(self, side: int) -> int:
        """As pontas da arte podem passar do cartão: a janela ganha essa margem."""
        scale = max(0.8, (side - 2 * self.ART_FREE_PAD) / (self.DEFAULT_SIZE - 2 * self.ART_FREE_PAD))
        return max(0, int(math.ceil(self.look.tip_overshoot * scale + 1.0 - self.ART_FREE_PAD)))

    def anchor_card_radius(self) -> float:
        return 0.0   # sem arte, o cartão é um quadrado liso (fillRect em paint_art_timer)

    def anchor_card_path(self) -> QPainterPath | None:
        """A borda é a própria arte (com as pontas que passam do cartão): o brilho de ancorado segue o PNG."""
        return self.card_path_for(self.get_card_rect())

    def card_path_for(self, card: QRectF) -> QPainterPath | None:
        """Contorno da arte para um cartão em `card` (usado também antes da janela ter tamanho, para a margem)."""
        look = self.look
        outline = look.outline()
        if outline is None:
            return None       # sem arte: o retângulo do cartão, com cantos retos
        scale = max(0.8, min(card.width(), card.height()) / SIDE)   # a mesma conta de paint_art_timer
        target = QRectF(card.left() + look.art_origin.x() * scale, card.top() + look.art_origin.y() * scale,
                        look.art_size.width() * scale, look.art_size.height() * scale)
        key = (id(outline), target.x(), target.y(), target.width(), target.height())
        cached = getattr(self, "_outline_cache", None)
        if cached is None or cached[0] != key:
            t = QTransform.fromTranslate(target.x(), target.y()).scale(target.width(), target.height())
            cached = self._outline_cache = (key, t.map(outline))
        return cached[1]

    def reload_skin_theme(self):
        """Os temas do Timer valem só para a skin Padrão; esta tem arte própria."""

    def get_buttons_geometry(self) -> tuple[QRectF, QRectF]:
        play, reset = buttons_geometry(self.get_card_rect(), self.get_scale(), self.look)
        grow = 3.0 * self.get_scale()   # botões pequenos: a área de clique é um pouco maior que o desenho
        return play.adjusted(-grow, -grow, grow, grow), reset.adjusted(-grow, -grow, grow, grow)

    def get_digits_geometry(self):
        rects, texts, font, _baseline, _cell = digits_layout(
            self.get_card_rect(), self.get_scale(), self.current_seconds, self.look, self.mode, self.time_morph)
        return rects, texts, font

    def get_time_segment_at(self, pos: QPointF) -> str | None:
        if self.mode == "stopwatch":
            return None   # o Cronômetro não tem número para editar
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
            time_morph=self.time_morph,
        )
        m = float(self.art_margin)
        paint_art_timer(p, QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m), state, pack=self.pack)
        if self._hovered or self._is_resizing:
            self._paint_resize_grip(p, self.get_scale())
        p.end()


_classes: dict[tuple[str, str], type] = {}


def make_art_skin_class(pack: SkinPack) -> type[ArtTimerSkin]:
    """A classe de skin ligada a um pacote (o controlador instancia as skins só pela classe)."""
    key = (pack.id, pack.folder)
    cls = _classes.get(key)
    if cls is None:
        cls = _classes[key] = type(f"ArtTimerSkin_{pack.id}", (ArtTimerSkin,), {"pack": pack})
    return cls
