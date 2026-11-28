"""
Troca de skin dos widgets (Music, Timer, Clima, Desempenho) com movimento. Protótipo: mockups/widget-skin-switch.html.

Antes: Music e Timer dissolviam uma janela sobre a outra (150 ms) e Clima/Desempenho dissolviam uma foto do cartão
antigo encolhendo 2,5% (160 ms); as duas pareciam uma piscada. Agora o efeito é uma escolha do app inteiro no Hub
(Visão geral > "Troca de skin"), padrão "Mola" (morph):

- fade   o dissolver de antes (160 ms)
- morph  o cartão vira o novo na mola MORPH (tamanho e cantos), conteúdo antigo sai e o novo entra (o do mixer)
- press  afunda como botão, troca no fundo e volta passando um pouco do tamanho (mola PRESS)
- flip   vira em volta do eixo vertical; a troca de tamanho acontece de perfil
- wave   a onda de pontos de "Fixar na área de trabalho" passa e atrás dela o cartão já é o novo
- iris   o novo abre num círculo a partir do ponteiro
- rise   o antigo afunda e some, o novo sobe para o lugar (mola LIFT)
- focus  desfoca o antigo enquanto o novo entra em foco (desfoque pronto, nunca ao vivo)

O canto superior esquerdo do cartão fica parado (como antes). Sem animações do Windows, troca na hora.

Quem pinta: `paint_switch` desenha um quadro a partir de duas `Layer` (algo que sabe se pintar com o canto do cartão
em (0, 0)). O FloatingCard (Clima, Desempenho) usa a foto do antigo e pinta o novo ao vivo; Music e Timer (duas janelas)
usam `SkinSwitchOverlay`, uma janela transparente por cima com as fotos das duas, enquanto a nova espera invisível.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from app.core.config_manager import config_manager
from app.core.motion_curves import (
    LIFT, MORPH, PRESS, bump, clamp, ease_in, ease_in_out, ease_out, lerp, smooth, span, spring,
)

EFFECTS = ("fade", "morph", "press", "flip", "wave", "iris", "rise", "focus")
DEFAULT_EFFECT = "morph"
DURATION_S = {
    "fade": 0.16, "morph": 0.36, "press": 0.46, "flip": 0.56,
    "wave": 0.62, "iris": 0.56, "rise": 0.50, "focus": 0.44,
}
OVERLAY_ROOM = 40       # px em volta das duas janelas: a subida, o excesso da mola e a virada não são cortados
BLUR_DIVISOR = 10       # "focus": a foto reduzida a 1/10 e ampliada de volta
WAVE_GAP = 10.0         # espaço entre os pontos da onda


def current_effect() -> str:
    v = config_manager.get_skin_switch_effect(DEFAULT_EFFECT)
    return v if v in EFFECTS else DEFAULT_EFFECT


def duration_s(effect: str) -> float:
    return DURATION_S.get(effect, DURATION_S[DEFAULT_EFFECT])


@dataclass
class Layer:
    """
    Uma aparência do widget. `paint(p)` pinta com o canto superior esquerdo do CARTÃO em (0, 0); `size` é o cartão;
    `bounds` é tudo o que ela pinta (o cartão e o que passa dele, como figurinhas), no mesmo sistema.
    """
    paint: Callable[[QPainter], None]
    size: tuple[float, float]
    bounds: QRectF
    radius: float = 12.0
    _blurred: Optional[QPixmap] = field(default=None, repr=False)

    @classmethod
    def from_pixmap(cls, pm: QPixmap, card: QRectF, radius: float) -> "Layer":
        """Foto de uma janela inteira (`pm`) cujo cartão está em `card` (coordenadas da janela)."""
        dpr = pm.devicePixelRatio() or 1.0
        off = QPointF(-card.x(), -card.y())
        bounds = QRectF(off.x(), off.y(), pm.width() / dpr, pm.height() / dpr)
        return cls(lambda p: p.drawPixmap(off, pm), (card.width(), card.height()), bounds, radius)

    def blurred(self) -> QPixmap:
        """A camada desfocada, feita uma vez: pintada pequena e ampliada com suavização."""
        if self._blurred is None:
            b = self.bounds
            w = max(1, int(round(b.width() / BLUR_DIVISOR)))
            h = max(1, int(round(b.height() / BLUR_DIVISOR)))
            small = QPixmap(w, h)
            small.fill(Qt.GlobalColor.transparent)
            p = QPainter(small)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.scale(w / max(1.0, b.width()), h / max(1.0, b.height()))
            p.translate(-b.x(), -b.y())
            self.paint(p)
            p.end()
            self._blurred = small
        return self._blurred

    def paint_blurred(self, p: QPainter):
        b = self.bounds
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(b, self.blurred(), QRectF(self.blurred().rect()))
        p.restore()


def _draw(p: QPainter, layer: Layer, alpha: float = 1.0, stretch: tuple[float, float] = (1.0, 1.0),
          sc: float = 1.0, fx: float = 1.0, dx: float = 0.0, dy: float = 0.0, blurred: bool = False):
    """
    Pinta a camada: `stretch` estica o cartão a partir do canto (o morph de tamanho); `sc` e `fx` (só horizontal,
    a virada) escalam em volta do centro do cartão já esticado; `dx`/`dy` deslocam.
    """
    if alpha <= 0.003:
        return
    w, h = layer.size[0] * stretch[0], layer.size[1] * stretch[1]
    p.save()
    p.setOpacity(p.opacity() * clamp(alpha))
    p.translate(dx + w / 2.0, dy + h / 2.0)
    p.scale(sc * fx, sc)
    p.translate(-w / 2.0, -h / 2.0)
    if stretch != (1.0, 1.0):
        p.scale(stretch[0], stretch[1])
    if blurred:
        layer.paint_blurred(p)
    else:
        layer.paint(p)
    p.restore()


def union_bounds(old: Layer, new: Layer) -> QRectF:
    return old.bounds.united(new.bounds)


def paint_switch(p: QPainter, effect: str, t: float, old: Layer, new: Layer, origin: Optional[QPointF] = None):
    """Um quadro da troca, com o canto do cartão em (0, 0). `t` de 0 a 1; `origin` é de onde a íris abre."""
    t = clamp(t)
    wa, ha = old.size
    wb, hb = new.size
    if effect == "morph":
        s = spring(t, MORPH)
        w, h = lerp(wa, wb, s), lerp(ha, hb, s)
        _draw(p, old, 1.0 - smooth(span(t, 0.2, 0.7)), stretch=(w / wa, h / ha))
        _draw(p, new, smooth(span(t, 0.1, 0.6)), stretch=(w / wb, h / hb),
              dy=6.0 * (1.0 - ease_out(span(t, 0.1, 0.8))))
    elif effect == "press":
        down = ease_in_out(span(t, 0.0, 0.32))
        sc = 1.0 - 0.07 * down if t < 0.36 else 0.93 + 0.07 * spring(span(t, 0.36, 1.0), PRESS)
        k = smooth(span(t, 0.26, 0.48))
        w, h = lerp(wa, wb, k), lerp(ha, hb, k)
        _draw(p, old, 1.0 - smooth(span(t, 0.34, 0.5)), stretch=(w / wa, h / ha), sc=sc)
        _draw(p, new, k, stretch=(w / wb, h / hb), sc=sc)
    elif effect == "flip":
        f = spring(t, MORPH)
        phi = math.pi * f
        fx = max(0.015, abs(math.cos(phi)))
        _draw(p, new if phi > math.pi / 2.0 else old, 1.0, sc=1.0 + 0.05 * bump(f), fx=fx)
    elif effect == "wave":
        b = union_bounds(old, new)
        x = lerp(b.left() - 40.0, b.right() + 40.0, ease_in_out(t))
        p.save()
        p.setClipRect(QRectF(x, b.top() - OVERLAY_ROOM, b.right() - x + OVERLAY_ROOM, b.height() + 2 * OVERLAY_ROOM))
        _draw(p, old)
        p.restore()
        p.save()
        p.setClipRect(QRectF(b.left() - OVERLAY_ROOM, b.top() - OVERLAY_ROOM, x - b.left() + OVERLAY_ROOM,
                             b.height() + 2 * OVERLAY_ROOM))
        _draw(p, new)
        p.restore()
        strength = bump(t)
        if strength > 0.02:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            hh = max(ha, hb)
            y = WAVE_GAP * 0.6
            while y < hh:
                for k in range(-5, 3):
                    d = abs(k + 1.5) / 4.0
                    a = clamp(1.0 - d) * strength
                    if a < 0.02:
                        continue
                    p.setBrush(QColor(255, 255, 255, int(215 * a)))
                    r = 1.6 + 1.4 * (1.0 - d)
                    p.drawEllipse(QPointF(x + k * WAVE_GAP, y), r, r)
                y += WAVE_GAP
            p.restore()
    elif effect == "iris":
        b = union_bounds(old, new)
        o = origin if origin is not None else QPointF(wb * 0.8, hb * 0.25)
        far = max(math.hypot(cx - o.x(), cy - o.y()) for cx in (b.left(), b.right()) for cy in (b.top(), b.bottom()))
        q = clamp(spring(span(t, 0.0, 0.9), MORPH))
        r = max(0.1, far * q)
        _draw(p, old, 1.0 - smooth(span(t, 0.45, 1.0)))
        p.save()
        clip = QPainterPath()
        clip.addEllipse(o, r, r)
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        _draw(p, new)
        p.restore()
        _draw(p, new, smooth(span(t, 0.6, 1.0)))
        if q < 0.995:
            p.save()
            p.setPen(QPen(QColor(255, 255, 255, int(128 * (1.0 - q))), 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(o, r, r)
            p.restore()
    elif effect == "rise":
        o = ease_in(span(t, 0.0, 0.4))
        n = spring(span(t, 0.22, 1.0), LIFT)
        _draw(p, old, 1.0 - o, sc=1.0 - 0.03 * o, dy=10.0 * o)
        _draw(p, new, smooth(span(t, 0.22, 0.6)), sc=0.96 + 0.04 * n, dy=18.0 * (1.0 - n))
    elif effect == "focus":
        out_a = 1.0 - smooth(span(t, 0.2, 0.75))
        blur_old = ease_in(span(t, 0.0, 0.6))
        sc_old = 1.0 + 0.03 * ease_out(span(t, 0.0, 0.6))
        _draw(p, old, out_a * (1.0 - blur_old), sc=sc_old)
        _draw(p, old, out_a * blur_old, sc=sc_old, blurred=True)
        u = span(t, 0.15, 1.0)
        in_a = smooth(span(t, 0.15, 0.65))
        blur_new = 1.0 - ease_out(u)
        sc_new = 1.03 - 0.03 * ease_out(u)
        _draw(p, new, in_a * blur_new, sc=sc_new, blurred=True)
        _draw(p, new, in_a * (1.0 - blur_new), sc=sc_new)
    else:   # "fade": o de antes
        e = ease_out(t)
        _draw(p, old, 1.0 - e, sc=1.0 - 0.025 * e)
        _draw(p, new, e, sc=0.975 + 0.025 * e)


def cursor_origin(card_global_top_left: QPoint, old: Layer, new: Layer) -> Optional[QPointF]:
    """O ponteiro em coordenadas do cartão, se estiver em cima do widget (a íris abre dali); senão None."""
    pos = QCursor.pos() - card_global_top_left
    pt = QPointF(pos)
    return pt if union_bounds(old, new).adjusted(-8, -8, 8, 8).contains(pt) else None


# --- Música e Timer: troca entre duas janelas ---

def window_card_rect(w: QWidget) -> QRectF:
    """O cartão em coordenadas da janela (Music: `card_rect`; Timer: o quadrado depois da margem)."""
    if hasattr(w, "card_rect"):
        return QRectF(w.card_rect())
    m = float(getattr(w, "art_margin", 0))
    side = float(w.square_side()) if hasattr(w, "square_side") else float(min(w.width(), w.height()))
    return QRectF(m, m, side, side)


def window_layer(w: QWidget) -> Layer:
    card = window_card_rect(w)
    radius = float(w.anchor_card_radius()) if hasattr(w, "anchor_card_radius") else 12.0
    return Layer.from_pixmap(w.grab(), card, radius)


class SkinSwitchOverlay(QWidget):
    """
    Janela transparente, sem foco e sem clique, por cima das duas skins enquanto a troca anda. Termina chamando
    `on_done` (que mostra a skin nova de verdade) e se fecha.
    """

    def __init__(self, effect: str, old: Layer, new: Layer, card_top_left: QPoint, on_done: Callable[[], None]):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.effect, self.old, self.new = effect, old, new
        self.duration = duration_s(effect)
        self.origin = cursor_origin(card_top_left, old, new)
        b = union_bounds(old, new).adjusted(-OVERLAY_ROOM, -OVERLAY_ROOM, OVERLAY_ROOM, OVERLAY_ROOM)
        self._card_offset = QPointF(-b.x(), -b.y())
        self.setGeometry(QRect(card_top_left + QPoint(int(math.floor(b.x())), int(math.floor(b.y()))),
                               b.size().toSize() + QRect(0, 0, 2, 2).size()))
        self._on_done = on_done
        self._t0 = time.perf_counter()
        self.t = 0.0
        from app.core.frame_clock import FrameTimer
        self._timer = FrameTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._t0 = time.perf_counter()
        self.show()
        self._timer.start()

    def _tick(self):
        self.t = clamp((time.perf_counter() - self._t0) / max(0.001, self.duration))
        self.update()
        if self.t >= 1.0:
            self.finish()

    def finish(self):
        if self._on_done is None:
            return
        self._timer.stop()
        done, self._on_done = self._on_done, None
        done()          # a skin nova aparece de verdade primeiro (o último quadro daqui é igual a ela)
        self.close()
        self.deleteLater()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(self._card_offset)
        paint_switch(p, self.effect, self.t, self.old, self.new, self.origin)
        p.end()
