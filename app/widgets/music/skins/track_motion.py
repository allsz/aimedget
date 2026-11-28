"""
Troca de faixa com movimento nas skins Ecos, Capa Completa e Vinil. Protótipo: mockups/music-track-change.html.

Antes a capa, o título, a barra e (no Vinil) o braço trocavam no corte. Agora cada skin tem 4 efeitos (escolhidos no
menu de contexto, como os efeitos da Capa Empilhada) e tudo o que muda na troca anda na MESMA linha do tempo: capa,
título/artista, barra de progresso e braço do toca-discos. Sem animações do Windows, troca na hora, como antes.

Como funciona:
- Só o estado ANTIGO é fotografado (`TrackSnapshot`: textos, progresso, pixmaps da capa, ângulo do braço). O estado
  novo é sempre o vivo da skin, então uma capa que chega no meio da transição entra direto na camada nova.
- Faixa trocou mas a capa nova ainda não chegou: a skin segura o estado antigo parado por até `COVER_WAIT_S` (a capa
  costuma chegar logo depois do título); chegou a capa ou passou o tempo, a transição começa.
- Só a capa mudou (mesma faixa, capa achada depois): transição na hora, sem mexer no texto.

Este módulo só calcula (curvas, fatias de tempo, estado). Quem pinta é cada skin.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.widget_animator import animations_enabled

# --- Efeitos por skin (o primeiro é o padrão, escolhido no protótipo) ---
EFFECTS: dict[str, tuple[str, ...]] = {
    "ripple": ("spin", "ripple", "shock", "depth"),
    "fullcover": ("zoom", "push", "iris", "blur"),
    "vinyl": ("hop", "drop", "flip", "bloom"),
}
DEFAULTS: dict[str, str] = {skin: effects[0] for skin, effects in EFFECTS.items()}

# Duração de cada efeito (s), as do protótipo
DURATION_S: dict[str, float] = {
    "spin": 1.0, "ripple": 0.9, "shock": 0.95, "depth": 0.8,
    "zoom": 0.8, "push": 0.65, "iris": 0.85, "blur": 0.8,
    "hop": 1.1, "drop": 1.5, "flip": 0.65, "bloom": 0.8,
}

# Fatias da linha do tempo (fração da duração) do texto e da barra; o resto usa o padrão
TEXT_SPAN: dict[str, tuple[float, float]] = {"drop": (0.18, 0.80), "hop": (0.25, 0.85), "flip": (0.0, 0.9),
                                             "bloom": (0.0, 0.9)}
BAR_SPAN: dict[str, tuple[float, float]] = {"drop": (0.55, 1.0), "hop": (0.45, 1.0)}
DEFAULT_TEXT_SPAN = (0.0, 1.0)
DEFAULT_BAR_SPAN = (0.10, 0.70)

COVER_WAIT_S = 0.25      # faixa nova sem capa ainda: segura o estado antigo no máximo isto
DIRECTION_HINT_S = 4.0   # um clique em "anterior" vale como direção da próxima troca por este tempo

# Curvas e molas compartilhadas (app/core/motion_curves.py); reexportadas para as skins
from app.core.motion_curves import (  # noqa: E402,F401
    LIFT, MORPH, SETTLE, SLIDE, bump, clamp, ease_in, ease_in_out, ease_out, ease_out4, lerp, smooth, span, spring,
)


def text_layers(tp: float, idx: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """
    Texto antigo sobe e some, o novo sobe de baixo e aparece; o artista (idx 1) vem um pouco depois do título.
    Devolve ((alfa, dy) do antigo, (alfa, dy) do novo), dy em px do canvas.
    """
    u = tp - idx * 0.05
    out = ease_in(span(u, 0.0, 0.34))
    inn = span(u, 0.20, 0.70)
    return (1.0 - out, -16.0 * out), (ease_out(inn), 18.0 * (1.0 - ease_out4(inn)))


# --- Estado ---

@dataclass
class TrackSnapshot:
    """O que estava na tela antes da troca. `covers` é da skin (pixmaps já prontos, nada é recalculado)."""
    title: str
    artist: str
    progress: float
    covers: dict = field(default_factory=dict)
    palette: object = None
    arm: Optional[float] = None    # ângulo do braço (Vinil), None se ele não estava no disco


class TrackTransition:
    """Uma troca em andamento: `frm` é o estado antigo; `p` vai de 0 a 1 (0 também enquanto espera a capa)."""

    def __init__(self):
        self.frm: Optional[TrackSnapshot] = None
        self.started: Optional[float] = None
        self.pending_since = 0.0
        self.direction = 1
        self.effect = ""
        self.duration = 1.0
        self.p = 1.0

    @property
    def busy(self) -> bool:
        return self.frm is not None

    @property
    def pending(self) -> bool:
        return self.frm is not None and self.started is None

    def hold(self, snap: TrackSnapshot, now: float, direction: int, effect: str):
        """Faixa trocou: congela o estado antigo. Se já estava esperando, o antigo na tela continua o mesmo."""
        if not self.pending:
            self.frm = snap
        self.started = None
        self.pending_since = now
        self.direction = 1 if direction >= 0 else -1
        self.effect = effect
        self.duration = DURATION_S.get(effect, 0.8)
        self.p = 0.0

    def go(self, now: float):
        if self.frm is not None and self.started is None:
            self.started = now

    def cancel(self):
        self.frm = None
        self.started = None
        self.p = 1.0

    def tick(self, now: float) -> bool:
        """Avança; True se precisa de um quadro novo (inclusive o último, que assenta no estado final)."""
        if self.frm is None:
            return False
        if self.started is None:
            if now - self.pending_since >= COVER_WAIT_S:
                self.started = now
            else:
                return False
        self.p = clamp((now - self.started) / max(0.001, self.duration))
        if self.p >= 1.0:
            self.cancel()
        return True


class TrackMotionMixin:
    """
    Troca de faixa animada para Ecos, Capa Completa e Vinil. A skin define `TRACK_MOTION_SKIN` e `_motion_covers()`,
    chama `_motion_snapshot()` no começo de `on_media_updated` e `_motion_after_update(...)` no fim, e pinta usando
    `self._motion` (ver `_paint_track_text` e `_shown_progress`).
    """

    TRACK_MOTION_SKIN = ""

    def _init_track_motion(self):
        self._motion = TrackTransition()
        saved = config_manager.get_music_track_effect(self.TRACK_MOTION_SKIN, DEFAULTS[self.TRACK_MOTION_SKIN])
        self.track_effect = saved if saved in EFFECTS[self.TRACK_MOTION_SKIN] else DEFAULTS[self.TRACK_MOTION_SKIN]
        self._media_synced = False
        self._direction_hint = (1, -1e9)
        self._last_motion_from: Optional[TrackSnapshot] = None

    # --- Hooks da skin ---

    def _motion_covers(self) -> dict:
        return {}

    def _motion_arm(self) -> Optional[float]:
        return None

    # --- Estado ---

    def _live_progress(self) -> float:
        dur = float(getattr(self, "duration", 0.0) or 0.0)
        return clamp(self.current_time / dur) if dur > 0 else 0.0

    def _motion_snapshot(self) -> TrackSnapshot:
        return TrackSnapshot(
            title=self.shown_title(), artist=self.shown_artist(), progress=self._shown_progress(self._live_progress()),
            covers=self._motion_covers(), palette=getattr(self, "current_palette", None), arm=self._motion_arm(),
        )

    def _motion_allowed(self) -> bool:
        return animations_enabled() and self.isVisible()

    def _note_direction(self, direction: int):
        """O usuário pediu anterior (-1) ou próxima (+1): a próxima troca vai nesse sentido."""
        self._direction_hint = (direction, time.perf_counter())

    def _take_direction(self, now: float) -> int:
        direction, at = self._direction_hint
        self._direction_hint = (1, -1e9)
        return direction if now - at <= DIRECTION_HINT_S else 1

    def _motion_after_update(self, pre: TrackSnapshot, track_changed: bool, cover_changed: bool):
        """Decide se a atualização vira uma transição (chamado depois de a skin aplicar o estado novo)."""
        now = time.perf_counter()
        first = not self._media_synced
        self._media_synced = True
        if first or not self._motion_allowed():
            self._motion.cancel()     # primeira sincronização (troca de skin, abertura) e sem animações: na hora
            return
        if track_changed:
            self._motion.hold(pre, now, self._take_direction(now), self.track_effect)
            self._last_motion_from = self._motion.frm
            if cover_changed:
                self._motion.go(now)
        elif cover_changed:
            if self._motion.pending:
                self._motion.go(now)
            elif not self._motion.busy:
                self._motion.hold(pre, now, 1, self.track_effect)
                self._motion.go(now)
        if self._motion.busy:
            self.update()

    def _track_motion_tick(self, now: float) -> bool:
        return self._motion.tick(now)

    # --- Pintura ---

    def _motion_p(self) -> float:
        return self._motion.p if self._motion.busy else 1.0

    def _shown_progress(self, live: float) -> float:
        """A barra desliza do progresso antigo ao novo na linha do tempo da troca (antes ela pulava para 0)."""
        m = getattr(self, "_motion", None)
        if m is None or not m.busy:
            return live
        a, b = BAR_SPAN.get(m.effect, DEFAULT_BAR_SPAN)
        return lerp(m.frm.progress, live, ease_in_out(span(m.p, a, b)))

    def _paint_track_text(self, painter: QPainter):
        """Título e artista: o antigo sai subindo, o novo entra de baixo. Mesmo texto (só a capa mudou) fica parado."""
        cur = (self.shown_title(), self.shown_artist())
        lines = (self._draw_title_line, self._draw_artist_line)
        m = self._motion
        if not m.busy:
            for draw, text in zip(lines, cur):
                draw(painter, text, 1.0, 0.0)
            return
        a, b = TEXT_SPAN.get(m.effect, DEFAULT_TEXT_SPAN)
        tp = span(m.p, a, b)
        for idx, (draw, old, new) in enumerate(zip(lines, (m.frm.title, m.frm.artist), cur)):
            if old == new:
                draw(painter, new, 1.0, 0.0)
                continue
            (oa, ody), (na, ndy) = text_layers(tp, idx)
            if oa > 0.004:
                draw(painter, old, oa, ody)
            if na > 0.004:
                draw(painter, new, na, ndy)

    def _draw_title_line(self, painter: QPainter, text: str, alpha: float, dy: float):
        raise NotImplementedError

    def _draw_artist_line(self, painter: QPainter, text: str, alpha: float, dy: float):
        raise NotImplementedError

    # --- Menu de contexto (como os efeitos da Capa Empilhada) ---

    def set_track_effect(self, effect: str, preview: bool = True):
        if effect not in EFFECTS[self.TRACK_MOTION_SKIN]:
            return
        self.track_effect = effect
        config_manager.set_music_track_effect(self.TRACK_MOTION_SKIN, effect)
        if preview and self._last_motion_from is not None and self._motion_allowed():
            # Prévia: repete a última troca com o efeito novo
            now = time.perf_counter()
            self._motion.cancel()
            self._motion.hold(self._last_motion_from, now, 1, effect)
            self._motion.go(now)
        self.update()

    def _get_skin_effects_title(self) -> str:
        return t("music_menu_track_change")

    def _get_skin_effects_icon(self, is_dark: bool = True) -> QIcon:
        return effect_icon(self.track_effect, True, is_dark)

    def _populate_skin_effects_menu(self, menu: QMenu, is_dark: bool = True) -> bool:
        for effect in EFFECTS[self.TRACK_MOTION_SKIN]:
            is_curr = effect == self.track_effect
            act = QAction(effect_icon(effect, is_curr, is_dark), t(f"music_track_fx_{effect}"), self)
            if hasattr(menu, "set_trailing_check"):
                menu.set_trailing_check(act, is_curr)
            else:
                act.setCheckable(True)
                act.setChecked(is_curr)
            act.triggered.connect(lambda checked=False, e=effect: self.set_track_effect(e, preview=True))
            menu.addAction(act)
        return True


def effect_icon(effect: str, active: bool = False, is_dark: bool = True) -> QIcon:
    """Ícone de traço do menu, no mesmo estilo dos efeitos da Capa Empilhada."""
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if is_dark:
        base = QColor(255, 255, 255) if active else QColor(160, 160, 168)
    else:
        base = QColor(31, 30, 29) if active else QColor(120, 119, 116)

    def pen(alpha: float, w: float = 1.8) -> QPen:
        c = QColor(base)
        c.setAlpha(int(255 * alpha))
        pn = QPen(c, w)
        pn.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pn

    def dot(x: float, y: float, r: float = 2.3):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(base)
        p.drawEllipse(QPointF(x, y), r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)

    c = QPointF(16.0, 16.0)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if effect in ("spin", "hop"):
        p.setPen(pen(0.45, 1.5))
        p.drawEllipse(c, 6.0, 6.0)
        p.setPen(pen(0.95))
        p.drawArc(QRectF(4.0, 4.0, 24.0, 24.0), 30 * 16, 250 * 16)
        p.drawLine(QPointF(26.4, 10.0), QPointF(26.6, 5.6) if effect == "spin" else QPointF(22.5, 7.0))
        dot(16.0, 16.0, 2.0)
    elif effect in ("ripple", "bloom"):
        dot(16.0, 16.0)
        for r, a in ((5.6, 0.9), (9.2, 0.6), (12.8, 0.3)) if effect == "ripple" else ((6.5, 0.9), (12.0, 0.35)):
            p.setPen(pen(a, 1.7))
            p.drawEllipse(c, r, r)
    elif effect == "shock":
        p.setPen(pen(0.95))
        p.drawEllipse(c, 4.6, 4.6)
        p.setPen(pen(0.55, 1.6))
        p.drawEllipse(c, 9.0, 9.0)
        p.setPen(pen(0.3, 1.4))
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(QPointF(16 + 11.5 * math.cos(a), 16 + 11.5 * math.sin(a)),
                       QPointF(16 + 14.0 * math.cos(a), 16 + 14.0 * math.sin(a)))
    elif effect in ("depth", "zoom"):
        p.setPen(pen(0.95))
        p.drawRoundedRect(QRectF(10.5, 10.5, 11.0, 11.0), 3.0, 3.0)
        p.setPen(pen(0.5, 1.6))
        p.drawRoundedRect(QRectF(5.0, 5.0, 22.0, 22.0), 5.0, 5.0)
        if effect == "zoom":
            p.setPen(pen(0.7, 1.5))
            p.drawLine(QPointF(7.5, 7.5), QPointF(10.0, 10.0))
            p.drawLine(QPointF(24.5, 24.5), QPointF(22.0, 22.0))
    elif effect == "push":
        p.setPen(pen(0.45, 1.6))
        p.drawRoundedRect(QRectF(3.5, 8.0, 14.0, 16.0), 3.5, 3.5)
        p.setPen(pen(0.95))
        p.drawRoundedRect(QRectF(13.5, 8.0, 15.0, 16.0), 3.5, 3.5)
    elif effect == "iris":
        p.setPen(pen(0.5, 1.6))
        p.drawRoundedRect(QRectF(4.0, 6.0, 24.0, 20.0), 5.0, 5.0)
        p.setPen(pen(0.95))
        p.drawEllipse(QPointF(20.0, 19.0), 5.5, 5.5)
    elif effect == "blur":
        for r, a in ((4.0, 0.95), (7.5, 0.5), (11.0, 0.22)):
            p.setPen(pen(a, 2.6 if r > 4 else 1.9))
            p.drawEllipse(c, r, r)
    elif effect == "drop":
        p.setPen(pen(0.95))
        p.drawEllipse(QPointF(16.0, 19.0), 9.0, 9.0)
        dot(16.0, 19.0, 2.0)
        p.setPen(pen(0.55, 1.6))
        p.drawLine(QPointF(16.0, 3.0), QPointF(16.0, 7.0))
        p.drawLine(QPointF(13.5, 5.0), QPointF(16.0, 7.5))
        p.drawLine(QPointF(18.5, 5.0), QPointF(16.0, 7.5))
    elif effect == "flip":
        p.setPen(pen(0.95))
        p.drawEllipse(c, 5.0, 11.0)
        p.setPen(pen(0.4, 1.5))
        p.drawEllipse(c, 11.0, 11.0)
    p.end()
    return QIcon(pm)
