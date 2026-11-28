"""
Mini OSD de volume do Music Widget.

Uma única barra vertical em cápsula (a mesma linguagem da barra de progresso da skin
Capa Empilhada): trilho cinza translúcido e preenchimento branco. Aparece ao lado do
widget ao rolar a roda do mouse e some sozinha.

Legibilidade: a barra é sempre branca, com halo suave que a mantém visível até sobre fundo
branco (valores escolhidos no mockup `mockups/volume-white-survival.html`). A adaptação
ao fundo (amostrar a tela e usar grafite sobre fundo claro) continua no código, desligada
por `ADAPT_TO_BACKDROP`.

- Janela ultraleve: sem moldura, sem foco, sempre no topo e transparente a cliques
  (nunca rouba o scroll nem o clique do widget abaixo).
- Sem timers de animação contínuos: fades via QPropertyAnimation e valor da barra via
  QVariantAnimation curta. Em repouso a janela está oculta e não consome CPU.
"""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.core.osd_anchor import (
    EDGE_GAP,
    SCREEN_MARGIN,
    SIDE_HYSTERESIS,
    compute_osd_placement,
    compute_osd_position,
)
from app.core.screen_metrics import get_screen_for_widget

# Geometria (px lógicos)
BAR_W = 8                 # espessura da cápsula
SHADOW_MARGIN = 8         # área transparente ao redor para o halo suave
HEIGHT_RATIO = 0.60       # altura da barra em relação à altura do widget
MIN_BAR_H = 72
MAX_BAR_H = 240

HIDE_DELAY_MS = 1200
FADE_IN_MS = 90
FADE_OUT_MS = 180
VALUE_ANIM_MS = 80

# Cores (trilho idêntico ao da barra de progresso da Capa Empilhada)
TRACK_COLOR = QColor(60, 60, 70, 113)
FILL_COLOR = QColor("#FFFFFF")
EDGE_COLOR = QColor(0, 0, 0, 0)   # fio escuro ao redor (alpha 0 = desligado)
EDGE_WIDTH = 0.75
# Halo (valores do mockup volume-white-survival.html)
HALO_LAYERS = 4
HALO_GROW = 1.5           # blur 6px / 4 camadas
HALO_LAYER_ALPHA = 10     # ~38 no total
HALO_Y = 1.0
# Sombra do preenchimento (0 = desligada)
FILL_SHADOW_LAYERS = 4
FILL_SHADOW_GROW = 1.0
FILL_SHADOW_LAYER_ALPHA = 0

# Variante grafite para fundo claro (desligada por padrão: a barra branca é sempre usada).
# Para voltar a adaptar ao fundo, troque ADAPT_TO_BACKDROP para True.
ADAPT_TO_BACKDROP = False
TRACK_ON_LIGHT = QColor(70, 70, 78, 105)
FILL_ON_LIGHT = QColor("#1C1C22")

# Luminância relativa (WCAG) onde branco e grafite têm o mesmo contraste (~0.20):
# acima disso o grafite contrasta mais; abaixo, o branco.
LIGHT_BACKDROP_THRESHOLD = 0.20


def bar_height_for(anchor_height: int) -> int:
    """Altura da barra: ~60% do widget, sempre menor que ele."""
    h = int(round(anchor_height * HEIGHT_RATIO))
    h = max(MIN_BAR_H, min(MAX_BAR_H, h))
    return max(32, min(h, anchor_height - 16))


def is_light_backdrop(luminance: float | None) -> bool:
    """True se o fundo é claro o bastante para exigir a variante grafite."""
    return luminance is not None and luminance > LIGHT_BACKDROP_THRESHOLD


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def sample_backdrop_luminance(screen, rect: QRect) -> float | None:
    """
    Luminância relativa média (0..1) dos pixels reais da tela em `rect` (coords globais).
    Deve ser chamada com o OSD oculto, para não amostrar a si mesmo.
    Retorna None se a captura não estiver disponível.
    """
    try:
        local = rect.translated(-screen.geometry().topLeft())
        img = screen.grabWindow(0, local.x(), local.y(), local.width(), local.height()).toImage()
        if img.isNull() or img.width() == 0 or img.height() == 0:
            return None
        total = 0.0
        count = 0
        step_y = max(1, img.height() // 24)
        for y in range(0, img.height(), step_y):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                total += (
                    0.2126 * _srgb_to_linear(c.redF())
                    + 0.7152 * _srgb_to_linear(c.greenF())
                    + 0.0722 * _srgb_to_linear(c.blueF())
                )
                count += 1
        return total / count if count else None
    except Exception:
        return None


class MusicVolumeOSD(QWidget):
    """Barra vertical de volume: cápsula branca sobre trilho cinza translúcido."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._bar_h = MIN_BAR_H
        self._apply_size()
        self._anchor: QWidget | None = None   # widget ao qual a barra está ancorada
        self._side: str | None = None         # lado atual (para a histerese)

        self._volume = 0
        self._muted = False
        self._on_light = False    # fundo claro => variante grafite (só com ADAPT_TO_BACKDROP)
        self._shown_value = 0.0   # valor animado (0..100)

        self._value_anim = QVariantAnimation(self)
        self._value_anim.setDuration(VALUE_ANIM_MS)
        self._value_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._value_anim.valueChanged.connect(self._on_value_anim)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._on_fade_finished)
        self._fading_out = False

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(HIDE_DELAY_MS)
        self._hide_timer.timeout.connect(self._start_fade_out)

    def _apply_size(self):
        self.setFixedSize(BAR_W + SHADOW_MARGIN * 2, self._bar_h + SHADOW_MARGIN * 2)

    # --- API pública ---

    def show_for(self, anchor: QWidget, volume: int, muted: bool):
        """Exibe/atualiza a barra ao lado do widget `anchor` e reinicia o timer de inatividade."""
        volume = max(0, min(100, int(volume)))
        was_visible = self.isVisible()

        if not was_visible:
            self._side = None  # nova exibição: sem histerese herdada
        self._track(anchor)
        pos = self._reposition(anchor)

        if not was_visible:
            if ADAPT_TO_BACKDROP:
                # Amostra o fundo ANTES de aparecer (a barra oculta não contamina a captura)
                screen = get_screen_for_widget(anchor)
                if screen is not None and pos is not None:
                    backdrop = QRect(pos, QSize(BAR_W, self._bar_h))
                    self._on_light = is_light_backdrop(sample_backdrop_luminance(screen, backdrop))
            self._shown_value = float(volume)  # abre já no valor certo, sem "subida"
        else:
            self._value_anim.stop()
            self._value_anim.setStartValue(self._shown_value)
            self._value_anim.setEndValue(float(volume))
            self._value_anim.start()

        self._volume = volume
        self._muted = bool(muted)

        self._hide_timer.start()
        if not was_visible:
            self.setWindowOpacity(0.0)
            self.show()
        self._animate_opacity(1.0, FADE_IN_MS)
        self.update()

    # --- Posicionamento ---

    def _reposition(self, anchor: QWidget) -> QPoint | None:
        screen = get_screen_for_widget(anchor)
        if screen is None:
            return None
        # Posição de repouso: ignora o deslize da animação de surgir/sumir do widget
        top_left = anchor.rest_pos() if hasattr(anchor, "rest_pos") else anchor.mapToGlobal(QPoint(0, 0))
        anchor_rect = QRect(top_left, anchor.size())
        card_local = anchor.card_rect() if hasattr(anchor, "card_rect") else None
        if card_local is not None:
            # Altura da barra acompanha o cartão (figurinhas no topo/base não esticam a barra)
            card_h = int(round(card_local.height()))
            bar_h = bar_height_for(card_h)
            if bar_h != self._bar_h:
                self._bar_h = bar_h
                self._apply_size()
            # Folga horizontal na faixa vertical da barra (desvia de figurinhas laterais como o Shooky)
            band_top = card_local.center().y() - self._bar_h * 0.5
            band_bot = card_local.center().y() + self._bar_h * 0.5
            if hasattr(anchor, "visual_bounds_rect"):
                vis = anchor.visual_bounds_rect(y_band=(band_top, band_bot))
            else:
                vis = card_local
            vis_r = vis.toAlignedRect()
            anchor_rect = QRect(top_left + vis_r.topLeft(), vis_r.size())
        else:
            bar_h = bar_height_for(anchor_rect.height())  # acompanha mudanças de escala do widget
            if bar_h != self._bar_h:
                self._bar_h = bar_h
                self._apply_size()

        pos, self._side = compute_osd_placement(
            anchor_rect,
            QSize(BAR_W, self._bar_h),
            screen.availableGeometry(),
            previous_side=self._side,
        )
        self.move(pos.x() - SHADOW_MARGIN, pos.y() - SHADOW_MARGIN)
        return pos

    # --- Ancoragem ao widget ---

    def _track(self, anchor: QWidget):
        """Passa a acompanhar `anchor`: a barra o segue enquanto ele é arrastado ou redimensionado."""
        if self._anchor is anchor:
            return
        self._untrack()
        self._anchor = anchor
        anchor.installEventFilter(self)
        anchor.destroyed.connect(self._on_anchor_destroyed)

    def _untrack(self):
        if self._anchor is not None:
            try:
                self._anchor.removeEventFilter(self)
                self._anchor.destroyed.disconnect(self._on_anchor_destroyed)
            except (RuntimeError, TypeError):
                pass
        self._anchor = None

    def _on_anchor_destroyed(self, *_):
        self._anchor = None
        if self.isVisible():
            self._hide_timer.stop()
            self._start_fade_out()

    def eventFilter(self, obj, event):
        if obj is self._anchor and self.isVisible():
            kind = event.type()
            if kind in (QEvent.Type.Move, QEvent.Type.Resize):
                self._reposition(obj)
            elif kind in (QEvent.Type.Hide, QEvent.Type.Close) and not self._fading_out:
                # O widget saiu de cena: a barra não fica flutuando sozinha
                self._hide_timer.stop()
                self._start_fade_out()
        return False

    # --- Fades ---

    def _animate_opacity(self, target: float, duration_ms: int):
        self._fading_out = target == 0.0
        self._fade.stop()
        self._fade.setDuration(duration_ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(target)
        self._fade.start()

    def _start_fade_out(self):
        self._animate_opacity(0.0, FADE_OUT_MS)

    def _on_fade_finished(self):
        if self._fading_out:
            self._fading_out = False
            self.hide()
            self._untrack()
            self._side = None

    def _on_value_anim(self, value):
        self._shown_value = float(value)
        self.update()

    # --- Pintura ---

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        track = QRectF(SHADOW_MARGIN, SHADOW_MARGIN, BAR_W, self._bar_h)
        r = BAR_W / 2.0

        # Halo suave: garante leitura do branco em qualquer fundo (inclusive branco)
        if not self._on_light:
            for i in range(HALO_LAYERS, 0, -1):
                grow = i * HALO_GROW
                p.setBrush(QColor(0, 0, 0, HALO_LAYER_ALPHA))
                p.drawRoundedRect(track.adjusted(-grow, -grow + HALO_Y, grow, grow + HALO_Y), r + grow, r + grow)

        p.setBrush(TRACK_ON_LIGHT if self._on_light else TRACK_COLOR)
        p.drawRoundedRect(track, r, r)

        frac = max(0.0, min(1.0, self._shown_value / 100.0))
        if frac > 0.0:
            fill_h = max(float(BAR_W), self._bar_h * frac)
            fill_rect = QRectF(track.left(), track.bottom() - fill_h, BAR_W, fill_h)

            # Sombra do próprio branco, só dentro do trilho: destaca o topo do preenchimento
            clip = QPainterPath()
            clip.addRoundedRect(track, r, r)
            p.save()
            p.setClipPath(clip)
            for i in range(FILL_SHADOW_LAYERS, 0, -1):
                grow = i * FILL_SHADOW_GROW
                p.setBrush(QColor(0, 0, 0, FILL_SHADOW_LAYER_ALPHA))
                p.drawRoundedRect(fill_rect.adjusted(-grow, -grow - 1.0, grow, grow - 1.0), r + grow, r + grow)
            p.restore()

            fill = QColor(FILL_ON_LIGHT if self._on_light else FILL_COLOR)
            if self._muted:
                fill.setAlpha(95)  # mudo: o nível continua visível, porém apagado
            p.setBrush(fill)
            p.drawRoundedRect(fill_rect, r, r)

        # Fio escuro ao redor da cápsula: o contorno do branco sobre branco
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(EDGE_COLOR, EDGE_WIDTH))
        p.drawRoundedRect(track.adjusted(-EDGE_WIDTH / 2, -EDGE_WIDTH / 2, EDGE_WIDTH / 2, EDGE_WIDTH / 2),
                          r + EDGE_WIDTH / 2, r + EDGE_WIDTH / 2)
        p.end()
