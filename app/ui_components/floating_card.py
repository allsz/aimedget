"""
FloatingCard - Container reutilizável de cartão flutuante da suíte Aimedget.

Compartilhado por widgets de cartão (Clima, Desempenho, etc.):
- Dimensões de referência (300x262, raio 27), sombra suave com transição ao fixar no desktop.
- Arraste livre entre monitores, redimensionamento proporcional pelo canto inferior direito e presets de escala.
- Fixação na área de trabalho (`desktop_layer` + `DesktopPinGuard` + `show_desktop_watcher`) com onda de pontos.
- Relógio de quadros sob demanda: só roda enquanto há animação ativa (custo zero parado).
"""

import math
import time
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from app.core import desktop_layer
from app.core.anchor_manager import anchor_manager
from app.core.desktop_pin_guard import DesktopPinGuard
from app.core.position_glide import glide_widget_to
from app.core.refresh_rate import refresh_interval_ms
from app.core.scale_animator import ScaleAnimator
from app.core.screen_metrics import get_screen_scale_ratio
from app.core.show_desktop_watcher import show_desktop_watcher
from app.core.typography import init_app_font
from app.core.widget_animator import AnimatedSkinMixin, animations_enabled
from app.core.frame_clock import FrameTimer
from app.core.theme_crossfade import DURATION_MS as THEME_FADE_MS, SHRINK as THEME_FADE_SHRINK, ease_out_cubic

CARD_W = 300.0
CARD_H = 262.0
CARD_RADIUS = 27.0

SCALES = (0.85, 1.0, 1.2)
APPEAR_MS, HIDE_MS = 200, 160
MIN_SCALE, MAX_SCALE = 0.7, 1.6
GRIP = 22.0
SHADOW = 18.0
MIN_FRAME_MS = 16
AMBIENT_FRAME_MS = 33
SCREEN_MARGIN = 24

# Onda de pontos ao fixar/soltar da área de trabalho
WAVE_DUR = 0.750
WAVE_GAP = 5.0
WAVE_BAND = 0.35
WAVE_SWITCH_AT = 0.5
SETTLE_DUR = 0.300
WAVE_LEVELS = 12


def ease_in_out_cubic(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if x < 0.5:
        return 4.0 * x * x * x
    return 1.0 - ((-2.0 * x + 2.0) ** 3) / 2.0


def card_path(w: float = CARD_W, h: float = CARD_H, radius: float = CARD_RADIUS) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    return path


def paint_dot_wave(
    p: QPainter,
    rect: QRectF,
    progress: float,
    gap: float = WAVE_GAP,
    band: float = WAVE_BAND,
    card_w: float = CARD_W,
    card_h: float = CARD_H,
    radius: float = CARD_RADIUS,
):
    """Faixa diagonal de pontos brancos que atravessa o cartão ao fixar/soltar do desktop."""
    if not 0.0 < progress < 1.0:
        return
    s = rect.width() / card_w
    front = -band + ease_in_out_cubic(progress) * (1.0 + 2.0 * band)
    r_max = gap * 0.42
    levels = [[] for _ in range(WAVE_LEVELS + 1)]
    diag = card_w + card_h
    y = gap / 2.0
    while y < card_h + gap:
        x_lo = max(gap / 2.0, (front - band) * diag - y)
        x_hi = min(card_w + gap, (front + band) * diag - y)
        if x_lo < x_hi:
            x = gap / 2.0 + math.ceil((x_lo - gap / 2.0) / gap) * gap
            while x < x_hi:
                u = (front - (x + y) / diag) / band
                if abs(u) < 1.0:
                    k = math.cos(u * math.pi / 2.0)
                    level = int(round(k * WAVE_LEVELS))
                    if level > 0:
                        levels[level].append((x, y))
                x += gap
        y += gap

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.topLeft())
    p.scale(s, s)
    p.setClipPath(card_path(card_w, card_h, radius))
    p.setPen(Qt.PenStyle.NoPen)
    for level, points in enumerate(levels):
        if not points:
            continue
        k = level / WAVE_LEVELS
        p.setBrush(QColor(255, 255, 255, int(0.9 * k * 255)))
        dot_r = r_max * k
        for x, y in points:
            p.drawEllipse(QPointF(x, y), dot_r, dot_r)
    p.restore()


# --- Utilitários compartilhados de posicionamento multi-monitor ---


def is_rect_on_screen(x: int, y: int, w: int, h: int) -> bool:
    """Confere se pelo menos uma parte utilizável do cartão cabe em algum monitor conectado."""
    app = QApplication.instance()
    if not app:
        return True
    rect = QRect(x, y, max(1, w), max(1, h))
    for screen in app.screens():
        inter = screen.geometry().intersected(rect)
        if inter.width() >= min(w, 50) and inter.height() >= min(h, 50):
            return True
    return False


def place_card_default(card: "FloatingCard", margin: int = SCREEN_MARGIN):
    """Posiciona o cartão no canto superior direito da tela principal."""
    app = QApplication.instance()
    if app and app.primaryScreen():
        geo = app.primaryScreen().availableGeometry()
        w, _h = card.card_size()
        card.move_card_to(geo.right() - w - margin + 1, geo.y() + margin)


def restore_card_position(
    card: "FloatingCard",
    remember: bool,
    saved_pos,
    margin: int = SCREEN_MARGIN,
):
    """Restaura a posição salva (em qualquer monitor) ou cai na posição padrão."""
    if remember and isinstance(saved_pos, (list, tuple)) and len(saved_pos) >= 2:
        w, h = card.card_size()
        x, y = int(saved_pos[0]), int(saved_pos[1])
        if is_rect_on_screen(x, y, w, h):
            card.move_card_to(x, y)
            return
    place_card_default(card, margin=margin)


class FloatingCard(AnimatedSkinMixin, QWidget):
    """Base de janela flutuante sem moldura com sombra, escala, arraste e fixação no desktop."""

    close_requested = Signal()
    configure_requested = Signal()   # "Configurar" no menu: abre o Hub na página do widget
    scale_changed = Signal(float)   # pedido de um tamanho novo (menu, roda, soltar a alça): quem decide é o controlador
    scale_applied = Signal(float)   # o tamanho de fato aplicado, a cada quadro (o Hub acompanha a animação)
    desktop_mode_changed = Signal(bool)
    remember_position_changed = Signal(bool)

    ANCHOR_KEY: Optional[str] = None   # chave do widget na ancoragem ("weather", "performance"); ver anchor_manager

    def __init__(
        self,
        scale: float = 1.0,
        desktop_mode: bool = False,
        card_w: float = CARD_W,
        card_h: float = CARD_H,
        radius: float = CARD_RADIUS,
    ):
        super().__init__()
        init_app_font()
        self._card_w = float(card_w)
        self._card_h = float(card_h)
        self._card_radius = float(radius)
        self._desktop_mode = bool(desktop_mode)

        self.setWindowFlags(self._window_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._init_animator()

        self._scale = 1.0
        self._shadows: dict = {}
        self._wave_t0: Optional[float] = None
        self._wave_target: Optional[bool] = None
        self._settle_from = 1.0 if self._desktop_mode else 0.0
        self._settle_t0 = -1e9
        self._skin_swap_prev: Optional[QPixmap] = None
        self._skin_swap_t0: float = -1e9
        self._skin_swap_dur: float = 0.160
        self._drag_offset: Optional[QPoint] = None
        self._dragged = False
        self._resize_start: Optional[tuple] = None
        self._grip_hovered = False
        self._hovered = False
        self.scale_auto = False        # True: o tamanho acompanha a resolução da tela (o controlador liga)
        self._scale_animator = ScaleAnimator(self, self.set_scale, tolerance=0.003)
        self.set_scale(scale)

        self._pin_guard = DesktopPinGuard(self)
        self._sd_suspended = False
        self._sd_subscribed = False
        self._clock = FrameTimer(self)
        self._clock.setTimerType(Qt.TimerType.PreciseTimer)
        self._clock.timeout.connect(self._on_frame)

    # --- Geometria ---

    def scale(self) -> float:
        return self._scale

    def margin(self) -> float:
        return SHADOW * self._scale

    def card_rect(self) -> QRectF:
        m = self.margin()
        return QRectF(m, m, self._card_w * self._scale, self._card_h * self._scale)

    def card_size(self) -> tuple[int, int]:
        return int(round(self._card_w * self._scale)), int(round(self._card_h * self._scale))

    def card_origin(self) -> QPoint:
        """Canto do CARTÃO na tela (sem a folga da sombra e sem o deslocamento da animação de surgir)."""
        m = int(round(self.margin()))
        return self.rest_pos() + QPoint(m, m)

    def move_card_to(self, x: int, y: int):
        m = int(round(self.margin()))
        self.move(x - m, y - m)

    def glide_card_to(self, x: int, y: int):
        m = int(round(self.margin()))
        glide_widget_to(self, x - m, y - m)

    def set_scale(self, scale: float):
        origin = self.card_origin() if self.isVisible() else None
        self._scale = max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        m = 2.0 * self.margin()
        self.setFixedSize(
            int(round(self._card_w * self._scale + m)),
            int(round(self._card_h * self._scale + m)),
        )
        self._shadows = {}
        if origin is not None:
            self.move_card_to(origin.x(), origin.y())
            anchor_manager().member_resized(self)   # num grupo, os vizinhos acompanham o tamanho novo
        self.update()
        self.scale_applied.emit(self._scale)

    def animate_scale_to(self, target: float):
        """Leva o tamanho até `target` com mola; sem animações do Windows ou com o cartão oculto, vale na hora."""
        target = max(MIN_SCALE, min(MAX_SCALE, float(target)))
        if not animations_enabled() or not self.isVisible() or abs(self._scale - target) < 0.004:
            self._scale_animator.stop()
            self.set_scale(target)
            return
        self._scale_animator.start(self._scale, target)

    def is_scale_animating(self) -> bool:
        return self._scale_animator.is_active()

    def stop_scale_animation(self):
        self._scale_animator.stop()

    def auto_scale_target(self) -> float:
        """Tamanho proporcional à tela onde o cartão está (1440p = 100%), dentro dos limites do cartão."""
        return max(MIN_SCALE, min(MAX_SCALE, get_screen_scale_ratio(widget=self)))

    def _retarget_auto_scale(self):
        """Soltou o cartão (talvez em outra tela): no automático, o tamanho acompanha a tela nova, com movimento."""
        if self.scale_auto:
            target = self.auto_scale_target()
            if abs(self._scale - target) >= 0.02:
                self.animate_scale_to(target)

    def _to_card(self, pos) -> QPointF:
        r = self.card_rect()
        return QPointF((pos.x() - r.x()) / self._scale, (pos.y() - r.y()) / self._scale)

    # --- Relógio ---

    def now(self) -> float:
        return time.perf_counter()

    def kick(self):
        """Algo mudou: redesenha e garante o relógio rodando enquanto houver movimento."""
        self.update()
        if self.isVisible() and self._needs_frames():
            self._set_frame_interval()

    def _card_needs_frames(self, now: float) -> bool:
        return False

    def _card_is_busy(self, now: float) -> bool:
        return False

    def _needs_frames(self) -> bool:
        now = self.now()
        return self._busy(now) or self._card_needs_frames(now)

    def begin_skin_crossfade(self, duration_ms: int = THEME_FADE_MS):
        """Captura a aparência atual do cartão para fazer crossfade suave ao trocar de skin ou tema."""
        if not self.isVisible() or not animations_enabled():
            self._skin_swap_prev = None
            return
        rect = self.card_rect()
        dpr = max(1.0, self.devicePixelRatioF())
        pm = QPixmap(max(1, int(round(rect.width() * dpr))), max(1, int(round(rect.height() * dpr))))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self.paint_card_content(p, QRectF(0.0, 0.0, rect.width(), rect.height()), self.now())
        p.end()
        self._skin_swap_prev = pm
        self._skin_swap_t0 = self.now()
        self._skin_swap_dur = max(0.04, duration_ms / 1000.0)
        self.kick()

    def _skin_swap_progress(self, now: float) -> Optional[float]:
        if self._skin_swap_prev is None:
            return None
        p = (now - self._skin_swap_t0) / self._skin_swap_dur
        if p >= 1.0:
            self._skin_swap_prev = None
            return None
        return max(0.0, min(1.0, p))

    def _busy(self, now: float) -> bool:
        return (
            self._wave_t0 is not None
            or now < self._settle_t0 + SETTLE_DUR
            or self._skin_swap_progress(now) is not None
            or self._card_is_busy(now)
        )

    def _set_frame_interval(self):
        busy = self._busy(self.now())
        interval = max(MIN_FRAME_MS, refresh_interval_ms(self)) if busy else AMBIENT_FRAME_MS
        if not self._clock.isActive():
            self._clock.start(interval)
        elif self._clock.interval() != interval:
            self._clock.setInterval(interval)

    def _on_frame(self):
        self._step_wave(self.now())
        if not self.isVisible() or not self._needs_frames():
            self._clock.stop()
        else:
            self._set_frame_interval()
        self.update()

    def _on_before_show(self):
        pass

    def showEvent(self, event):
        self._on_before_show()
        super().showEvent(event)
        desktop_layer.apply_layer(int(self.winId()), self._desktop_mode)
        self._sync_pin_guard()
        self._sync_show_desktop()
        anchor_manager().register(self)
        self.kick()

    def hideEvent(self, event):
        self._clock.stop()
        self._scale_animator.finish()   # oculto não anima: assenta no tamanho final
        if self._wave_target is not None:
            target, self._wave_target = self._wave_target, None
            self._apply_desktop_mode(target)
        self._wave_t0 = None
        self._pin_guard.stop()
        super().hideEvent(event)
        self._sync_show_desktop()

    def _sync_pin_guard(self):
        if self._desktop_mode and self.isVisible():
            self._pin_guard.start()
        else:
            self._pin_guard.stop()

    def pin_guard(self) -> DesktopPinGuard:
        return self._pin_guard

    # --- Win+D sem fixar: esconder junto com as janelas ---

    def _sync_show_desktop(self):
        want = desktop_layer.IS_WINDOWS and not self._desktop_mode and (self.isVisible() or self._sd_suspended)
        if want == self._sd_subscribed:
            return
        watcher = show_desktop_watcher()
        if want:
            watcher.active_changed.connect(self._on_show_desktop)
            watcher.acquire()
        else:
            watcher.active_changed.disconnect(self._on_show_desktop)
            watcher.release()
        self._sd_subscribed = want

    def _on_show_desktop(self, active: bool):
        if active:
            if not self._desktop_mode and self.isVisible() and not self.animator.is_hiding():
                self._sd_suspended = True
                self.animator.hide(HIDE_MS)
        elif self._sd_suspended:
            self._sd_suspended = False
            if not self._desktop_mode:
                self.animator.show(APPEAR_MS)
            self._sync_show_desktop()

    def is_suspended_by_show_desktop(self) -> bool:
        return self._sd_suspended

    def forget_show_desktop(self):
        self._sd_suspended = False
        self._sync_show_desktop()

    # --- Nível na pilha de janelas ---

    def _window_flags(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow
        if not desktop_layer.IS_WINDOWS and not self._desktop_mode:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    def is_desktop_mode(self) -> bool:
        return self._desktop_mode

    def desktop_mode_target(self) -> bool:
        """A camada para onde o cartão vai (durante a onda de pontos a troca ainda não aconteceu)."""
        return self._wave_target if self._wave_target is not None else self._desktop_mode

    def set_desktop_mode(self, enabled: bool):
        enabled = bool(enabled)
        target = self.desktop_mode_target()
        if enabled == target:
            return
        anchor_manager().member_layer_changed(self, enabled)   # num grupo ancorado, todos mudam de camada juntos
        if self.isVisible() and animations_enabled():
            if self._wave_t0 is None:
                self._wave_t0 = self.now()
            self._wave_target = enabled
            self.kick()
            return
        self._wave_t0 = None
        self._wave_target = None
        self._apply_desktop_mode(enabled)

    def _step_wave(self, now: float):
        if self._wave_t0 is None:
            return
        progress = (now - self._wave_t0) / WAVE_DUR
        if progress >= WAVE_SWITCH_AT and self._wave_target is not None:
            self._apply_desktop_mode(self._wave_target)
            self._wave_target = None
        if progress >= 1.0:
            self._wave_t0 = None

    def wave_progress(self, now: float) -> Optional[float]:
        return None if self._wave_t0 is None else (now - self._wave_t0) / WAVE_DUR

    def _apply_desktop_mode(self, enabled: bool):
        if enabled == self._desktop_mode:
            return
        now = self.now()
        self._settle_from = self._settle_value(now)
        self._settle_t0 = now if self.isVisible() and animations_enabled() else -1e9
        self._desktop_mode = enabled
        if not desktop_layer.IS_WINDOWS:
            was_visible = self.isVisible()
            self.setWindowFlags(self._window_flags())
            if was_visible:
                self.show()
            return
        if self.isVisible():
            desktop_layer.apply_layer(int(self.winId()), enabled)
        if enabled and self._sd_suspended:
            self._sd_suspended = False
            self.animator.show(APPEAR_MS)
        self._sync_pin_guard()
        self._sync_show_desktop()

    def nativeEvent(self, event_type, message):
        if self._desktop_mode and desktop_layer.IS_WINDOWS:
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == desktop_layer.WM_WINDOWPOSCHANGING:
                    desktop_layer.on_window_pos_changing(msg.lParam, int(msg.hWnd or 0))
            except (TypeError, ValueError, OSError):
                pass
        return False, 0

    # --- Pintura ---

    def _settle_value(self, now: float) -> float:
        target = 1.0 if self._desktop_mode else 0.0
        p = min(1.0, max(0.0, (now - self._settle_t0) / SETTLE_DUR)) if SETTLE_DUR > 0 else 1.0
        e = ease_in_out_cubic(p)
        return self._settle_from + (target - self._settle_from) * e

    def _shadow_pixmap(self, settled: bool) -> QPixmap:
        dpr = self.devicePixelRatioF()
        key = (settled, round(dpr, 2))
        pm = self._shadows.get(key)
        if pm is not None:
            return pm
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = self.card_rect()
        steps = 14
        spread = self.margin() * (0.38 if settled else 0.9)
        offset = (2.5 if settled else 6.0) * self._scale
        strength = 0.8 if settled else 1.0
        for i in range(steps):
            f = i / (steps - 1)
            grow = spread * (1.0 - f) - 4.0 * self._scale
            alpha = (0.012 + 0.03 * f * f) * strength
            p.setBrush(QColor(0, 0, 0, int(alpha * 255)))
            rad = self._card_radius * self._scale + grow
            p.drawRoundedRect(r.adjusted(-grow, -grow + offset, grow, grow + offset), rad, rad)
        p.end()
        self._shadows[key] = pm
        return pm

    def paint_card_content(self, p: QPainter, rect: QRectF, now: float):
        """Subclasses desenham o interior do cartão em `rect`."""
        raise NotImplementedError

    def paintEvent(self, event):
        now = self.now()
        p = QPainter(self)
        settle = self._settle_value(now)
        if settle < 1.0:
            p.setOpacity(1.0 - settle)
            p.drawPixmap(0, 0, self._shadow_pixmap(False))
        if settle > 0.0:
            p.setOpacity(settle)
            p.drawPixmap(0, 0, self._shadow_pixmap(True))
        p.setOpacity(1.0)
        rect = self.card_rect()
        swap_p = self._skin_swap_progress(now)
        if swap_p is not None and self._skin_swap_prev is not None:
            e = ease_out_cubic(swap_p)   # a mesma curva e duração de toda troca de tema (app/core/theme_crossfade.py)
            cx, cy = rect.center().x(), rect.center().y()
            # Skin antiga saindo com fade e leve redução
            p.save()
            p.setOpacity(1.0 - e)
            s_out = 1.0 - THEME_FADE_SHRINK * e
            p.translate(cx, cy)
            p.scale(s_out, s_out)
            p.translate(-cx, -cy)
            p.drawPixmap(rect.topLeft(), self._skin_swap_prev)
            p.restore()
            # Skin nova entrando com fade e leve expansão
            p.save()
            p.setOpacity(e)
            s_in = (1.0 - THEME_FADE_SHRINK) + THEME_FADE_SHRINK * e
            p.translate(cx, cy)
            p.scale(s_in, s_in)
            p.translate(-cx, -cy)
            self.paint_card_content(p, rect, now)
            p.restore()
            p.setOpacity(1.0)
        else:
            self.paint_card_content(p, rect, now)
        wave = self.wave_progress(now)
        if wave is not None:
            paint_dot_wave(
                p, rect, wave,
                card_w=self._card_w, card_h=self._card_h, radius=self._card_radius,
            )
        if self._hovered or self._resize_start is not None:
            self._paint_grip(p, rect)
        p.end()

    def _paint_grip(self, p: QPainter, rect: QRectF):
        s = self._scale
        alpha = 0.85 if (self._grip_hovered or self._resize_start is not None) else 0.45
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(rect.topLeft())
        p.scale(s, s)
        p.setPen(QPen(QColor(255, 255, 255, int(alpha * 255)), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(self._card_w - 9, self._card_h - 17), QPointF(self._card_w - 17, self._card_h - 9))
        p.drawLine(QPointF(self._card_w - 9, self._card_h - 11.5), QPointF(self._card_w - 11.5, self._card_h - 9))
        p.restore()

    # --- Mouse ---

    def _grip_blocked(self, card_pos: QPointF) -> bool:
        return False

    def _on_grip(self, card_pos: QPointF) -> bool:
        if card_pos.x() < self._card_w - GRIP or card_pos.y() < self._card_h - GRIP:
            return False
        if card_pos.x() > self._card_w or card_pos.y() > self._card_h:
            return False
        return not self._grip_blocked(card_pos)

    def _on_card_press(self, card_pos: QPointF) -> bool:
        return False

    def _on_card_move(self, card_pos: QPointF) -> bool:
        return False

    def _on_card_hover(self, card_pos: QPointF, grip: bool) -> bool:
        """Retorna True se o cursor deve ser PointingHandCursor."""
        return False

    def _on_card_release(self, card_pos: QPointF) -> bool:
        return False

    def _on_card_leave(self):
        pass

    def _on_drag_finished(self, origin: QPoint):
        pass

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        card_pos = self._to_card(event.position())
        if self._on_grip(card_pos):
            self._scale_animator.stop()
            self._resize_start = (event.globalPosition(), self._scale)
            return
        if self._on_card_press(card_pos):
            return
        self._drag_offset = event.globalPosition().toPoint() - self.pos()
        self._dragged = False

    def mouseMoveEvent(self, event):
        if self._resize_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            start, start_scale = self._resize_start
            delta = event.globalPosition() - start
            grow = (delta.x() / self._card_w + delta.y() / self._card_h) / 2.0
            self.set_scale(start_scale + grow)
            return
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            anchor_manager().drag_to(self, event.globalPosition().toPoint() - self._drag_offset)   # grupo + ímã
            self._dragged = True
            return
        card_pos = self._to_card(event.position())
        if event.buttons() & Qt.MouseButton.LeftButton and self._on_card_move(card_pos):
            return
        grip = self._on_grip(card_pos)
        pointer = self._on_card_hover(card_pos, grip)
        if grip != self._grip_hovered:
            self._grip_hovered = grip
            self.update()
        if grip:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor if pointer else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if self._resize_start is not None:
            self._resize_start = None
            self.scale_changed.emit(self._scale)
            self.update()
            return
        if self._on_card_release(self._to_card(event.position())):
            return
        if self._drag_offset is not None and self._dragged:
            anchor_manager().drag_end(self)
            self._on_drag_finished(self.card_origin())
            self._retarget_auto_scale()
        self._drag_offset = None

    def anchor_position_committed(self):
        """Num grupo, este cartão foi movido junto com outro: grava a posição como se tivesse sido arrastado."""
        self._on_drag_finished(self.card_origin())

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._grip_hovered = False
        self._on_card_leave()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)
