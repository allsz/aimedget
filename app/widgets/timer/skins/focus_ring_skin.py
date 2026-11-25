"""
FocusRingTimerSkin - Skin de foco minimalista sem números enquanto corre.

- Em repouso (idle): mostra a duração escolhida no centro do anel (`25m`, `1h30`, até `3h`) com botões `−` / `Iniciar` / `+`
  e suporte a scroll do mouse com passos progressivos (1–10m: ±1m, 10–60m: ±5m, 1h–3h: ±15m).
- Ao iniciar: os números e a barra inferior recolhem suavemente (morph) e dão lugar apenas ao anel luminoso branco e
  ao botão central de Pausar/Retomar — sem contagem regressiva visível para manter o foco.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from app.core.config_manager import config_manager
from app.core.frame_clock import FrameTimer
from app.core.i18n import t
from app.core.typography import get_ui_font
from app.hub.components.tab_pill import Blend
from app.hub.theme import HubTheme
from app.widgets.timer.skins.base_skin import BaseTimerSkin
from app.widgets.timer.skins.skin import CORNER_RADIUS, DEFAULT_SIZE, SHADOW_PAD, TimerState

FOCUS_MIN_MINUTES = 1
FOCUS_MAX_MINUTES = 180   # 3 horas
DEFAULT_FOCUS_MINUTES = 25


def step_focus_minutes(current_minutes: int, direction: int) -> int:
    """Passos progressivos confortáveis entre 1 min e 3 h (1–10m: ±1m, 10–60m: ±5m, 60–180m: ±15m)."""
    m = max(FOCUS_MIN_MINUTES, min(FOCUS_MAX_MINUTES, int(current_minutes)))
    if direction > 0:
        if m < 10:
            nxt = m + 1
        elif m < 60:
            nxt = ((m // 5) + 1) * 5
        else:
            nxt = ((m // 15) + 1) * 15
    elif direction < 0:
        if m <= 10:
            nxt = m - 1
        elif m <= 60:
            nxt = ((m - 1) // 5) * 5
        else:
            nxt = ((m - 1) // 15) * 15
    else:
        nxt = m
    return max(FOCUS_MIN_MINUTES, min(FOCUS_MAX_MINUTES, nxt))


def format_focus_duration(minutes: int) -> str:
    """Formatação compacta para o centro do anel: '25m', '1h', '1h30', '3h'."""
    m = max(FOCUS_MIN_MINUTES, min(FOCUS_MAX_MINUTES, int(minutes)))
    if m < 60:
        return f"{m}m"
    hrs, rem = divmod(m, 60)
    return f"{hrs}h" if rem == 0 else f"{hrs}h{rem:02d}"


def _focus_layout(card: QRectF, morph: float) -> tuple[QRectF, QRectF, QRectF, QRectF, QRectF, QRectF]:
    """
    Calcula retângulos proporcionais ao cartão:
    (ring_rect, center_rect, minus_rect, start_rect, plus_rect, reset_rect).
    `morph`: 0.0 = configuração (idle), 1.0 = foco ativo/pausado (anel centralizado).
    """
    s = card.width() / (DEFAULT_SIZE - 2.0 * SHADOW_PAD)
    dial_d_idle = card.width() * 0.54
    dial_d_active = card.width() * 0.64
    dial_d = dial_d_idle + (dial_d_active - dial_d_idle) * morph
    center_d = dial_d * 0.72
    cx = card.center().x()
    cy_idle = card.center().y() - 7.5 * s
    cy_active = card.center().y() + 5.0 * s
    cy = cy_idle + (cy_active - cy_idle) * morph

    ring_rect = QRectF(cx - dial_d * 0.5, cy - dial_d * 0.5, dial_d, dial_d)
    center_rect = QRectF(cx - center_d * 0.5, cy - center_d * 0.5, center_d, center_d)

    bar_h = 19.0 * s
    bar_y = card.bottom() - 9.0 * s - bar_h + morph * 10.0 * s
    step_w = 24.0 * s
    start_w = 50.0 * s
    gap = 5.0 * s
    total_w = step_w * 2.0 + start_w + gap * 2.0
    x0 = cx - total_w * 0.5
    minus_rect = QRectF(x0, bar_y, step_w, bar_h)
    start_rect = QRectF(minus_rect.right() + gap, bar_y, start_w, bar_h)
    plus_rect = QRectF(start_rect.right() + gap, bar_y, step_w, bar_h)

    rst_d = 19.0 * s
    reset_rect = QRectF(card.right() - 10.0 * s - rst_d, card.top() + 9.0 * s, rst_d, rst_d)
    return ring_rect, center_rect, minus_rect, start_rect, plus_rect, reset_rect


def paint_focus_ring_timer(
    p: QPainter,
    rect: QRectF,
    state: TimerState,
    theme: HubTheme,
    morph: float = 1.0,
    progress: float = 0.68,
    setup_minutes: int = DEFAULT_FOCUS_MINUTES,
    center_hovered: bool = False,
    center_pressed: bool = False,
    hovered_btn: Optional[str] = None,
    close_opacity: float = 0.0,
    close_hovered: bool = False,
    resize_hovered: bool = False,
    alarm_phase: float = 0.0,
):
    """Pintura vetorial pura da skin Focus Ring (compartilhada entre o widget vivo e a miniatura do Hub)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    pad = SHADOW_PAD
    card = QRectF(rect.x() + pad, rect.y() + pad, rect.width() - 2.0 * pad, rect.height() - 2.0 * pad)
    scale = max(0.75, min(card.width(), card.height()) / (DEFAULT_SIZE - 2.0 * pad))
    radius = min(CORNER_RADIUS * 1.15 * scale, card.width() * 0.20)
    m = max(0.0, min(1.0, float(morph)))

    # 1. Sombra suave externa
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 74))
    p.drawRoundedRect(card.adjusted(0.0, 2.5 * scale, 0.0, 4.0 * scale), radius, radius)

    # 2. Corpo escuro fosco (gradiente sutil igual à referência)
    bg_grad = QLinearGradient(card.topLeft(), card.bottomLeft())
    bg_grad.setColorAt(0.0, QColor("#1B1B1D"))
    bg_grad.setColorAt(1.0, QColor("#141416"))
    p.setBrush(bg_grad)
    p.drawRoundedRect(card, radius, radius)

    # Borda sutil
    border_col = QColor(255, 255, 255, 190 if state.is_alarm_pulsing else 18)
    p.setPen(QPen(border_col, 1.4 if state.is_alarm_pulsing else 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    # 3. Cabeçalho: "Foco" / "Focus" no topo esquerdo (desloca levemente se o botão Fechar aparecer)
    title_x = card.left() + (28.0 * scale if close_opacity > 0.25 else 13.0 * scale)
    f_title = get_ui_font(max(8, int(round(10.0 * scale))), QFont.Weight.Medium)
    p.setFont(f_title)
    p.setPen(QColor(255, 255, 255, 224))
    p.drawText(
        QRectF(title_x, card.top() + 9.0 * scale, card.width() * 0.55, 18.0 * scale),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        t("timer_focus_title"),
    )

    ring_rect, center_rect, minus_rect, start_rect, plus_rect, reset_rect = _focus_layout(card, m)

    # 4. Anel de progresso luminoso (trilho escuro + arco branco com glow suave)
    stroke = max(5.5, ring_rect.width() * 0.088)
    arc_rect = ring_rect.adjusted(stroke * 0.5, stroke * 0.5, -stroke * 0.5, -stroke * 0.5)

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 17), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawEllipse(arc_rect)

    # Fração do arco: em idle mostra fração sutil da duração escolhida; ativo mostra progresso restante
    idle_frac = max(0.06, min(1.0, setup_minutes / float(FOCUS_MAX_MINUTES)))
    draw_frac = idle_frac * (1.0 - m) + max(0.0, min(1.0, progress)) * m
    arc_alpha = 0.26 + 0.74 * m
    if state.is_alarm_pulsing:
        pulse = 0.5 + 0.5 * math.sin(alarm_phase * 7.5)
        draw_frac = 1.0
        arc_alpha = 0.35 + 0.65 * pulse

    if draw_frac > 0.004:
        span_16 = -int(round(draw_frac * 360.0 * 16.0))
        # Halo luminoso suave atrás do arco branco
        for mult, alpha in ((1.85, 0.10), (1.42, 0.20)):
            glow_col = QColor(255, 255, 255, int(255 * alpha * arc_alpha))
            p.setPen(QPen(glow_col, stroke * mult, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc_rect, 90 * 16, span_16)
        # Arco branco nítido
        main_col = QColor(255, 255, 255, int(255 * arc_alpha))
        p.setPen(QPen(main_col, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc_rect, 90 * 16, span_16)

    # 5. Disco central tátil (botão Play/Pause ou leitura de duração no idle)
    p.save()
    cc = center_rect.center()
    p.translate(cc)
    if center_pressed:
        p.scale(0.94, 0.94)
    cr = center_rect.width() * 0.5
    c_grad = QRadialGradient(QPointF(0.0, -cr * 0.28), cr * 1.25)
    c_grad.setColorAt(0.0, QColor("#323236" if center_hovered else "#2B2B2E"))
    c_grad.setColorAt(1.0, QColor("#232327" if center_hovered else "#1F1F22"))
    p.setPen(QPen(QColor(255, 255, 255, 18), 1.0))
    p.setBrush(c_grad)
    p.drawEllipse(QPointF(0.0, 0.0), cr, cr)

    # Camada A (idle): números compactos no centro (encolhem e somem conforme morph -> 1)
    if m < 0.99:
        p.save()
        p.setOpacity(1.0 - m)
        sc_num = 1.0 - 0.22 * m
        p.scale(sc_num, sc_num)
        f_num = get_ui_font(max(10, int(round(16.5 * scale))), QFont.Weight.DemiBold)
        p.setFont(f_num)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(-cr, -cr, cr * 2.0, cr * 2.0), Qt.AlignmentFlag.AlignCenter, format_focus_duration(setup_minutes))
        p.restore()

    # Camada B (ativo/pausado): ícone Play / Pause branco centralizado (0.30x radius ~ 10px em escala 100%)
    if m > 0.01:
        p.save()
        p.setOpacity(m)
        sc_ico = 0.78 + 0.22 * m
        p.scale(sc_ico, sc_ico)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        if state.is_running:
            bh = cr * 0.30
            bw = bh * 0.32
            gap = bh * 0.24
            rr = bw * 0.42
            p.drawRoundedRect(QRectF(-gap - bw, -bh * 0.5, bw, bh), rr, rr)
            p.drawRoundedRect(QRectF(gap, -bh * 0.5, bw, bh), rr, rr)
        else:
            tri_h = cr * 0.30
            tri_w = tri_h * 0.86
            ox = tri_h * 0.11
            path = QPainterPath()
            path.moveTo(-tri_w * 0.48 + ox, -tri_h * 0.5)
            path.lineTo(tri_w * 0.56 + ox, 0.0)
            path.lineTo(-tri_w * 0.48 + ox, tri_h * 0.5)
            path.closeSubpath()
            p.drawPath(path)
        p.restore()
    p.restore()

    # 6. Barra inferior de configuração (− | Iniciar | +) — desliza e some ao iniciar
    if m < 0.98:
        p.save()
        p.setOpacity(1.0 - m)
        f_btn = get_ui_font(max(7, int(round(9.0 * scale))), QFont.Weight.DemiBold)
        p.setFont(f_btn)
        for key, r_btn, label, primary in (
            ("minus", minus_rect, "−", False),
            ("start", start_rect, t("timer_focus_start"), True),
            ("plus", plus_rect, "+", False),
        ):
            hov = hovered_btn == key
            if primary:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#FFFFFF" if hov else "#EDEDEF"))
                p.drawRoundedRect(r_btn, r_btn.height() * 0.42, r_btn.height() * 0.42)
                p.setPen(QColor("#141416"))
            else:
                p.setPen(QPen(QColor(255, 255, 255, 28 if hov else 18), 1.0))
                p.setBrush(QColor("#2E2E33" if hov else "#232326"))
                p.drawRoundedRect(r_btn, r_btn.height() * 0.40, r_btn.height() * 0.40)
                p.setPen(QColor("#FFFFFF" if hov else "#D4D4D8"))
            p.drawText(r_btn, Qt.AlignmentFlag.AlignCenter, label)
        p.restore()

    # 7. Botão discreto de Reset (↺) no topo direito — visível no hover quando o foco está ativo/pausado
    if m > 0.35 and (close_opacity > 0.05 or not state.is_running):
        rst_op = m * (1.0 if hovered_btn == "reset" else max(close_opacity, 0.45 if not state.is_running else 0.0))
        if rst_op > 0.04:
            p.save()
            p.setOpacity(rst_op)
            p.setPen(QPen(QColor(255, 255, 255, 32), 1.0))
            p.setBrush(QColor(255, 255, 255, 36 if hovered_btn == "reset" else 16))
            p.drawEllipse(reset_rect)
            rc = reset_rect.center()
            rr = reset_rect.width() * 0.25
            p.setPen(QPen(QColor("#FFFFFF"), 1.35 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(rc.x() - rr, rc.y() - rr, rr * 2.0, rr * 2.0), 45 * 16, 275 * 16)
            p.restore()

    # 8. Botão Fechar (hover no topo esquerdo)
    if close_opacity > 0.02:
        csz = 18.0 * scale
        cpad = 8.0 * scale
        close_r = QRectF(card.left() + cpad, card.top() + cpad, csz, csz)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(close_opacity * (58 if close_hovered else 28))))
        p.drawEllipse(close_r)
        cc2 = close_r.center()
        arm = csz * 0.21
        p.setPen(QPen(QColor(255, 255, 255, int(close_opacity * 225)), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cc2.x() - arm, cc2.y() - arm), QPointF(cc2.x() + arm, cc2.y() + arm))
        p.drawLine(QPointF(cc2.x() + arm, cc2.y() - arm), QPointF(cc2.x() - arm, cc2.y() + arm))

    # 9. Alça sutil de redimensionamento no canto inferior direito
    if resize_hovered:
        p.setPen(QPen(QColor(255, 255, 255, 130), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        rx, ry = card.right() - 8.0 * scale, card.bottom() - 8.0 * scale
        p.drawLine(QPointF(rx - 5.0 * scale, ry), QPointF(rx, ry - 5.0 * scale))
        p.drawLine(QPointF(rx - 2.0 * scale, ry), QPointF(rx, ry - 2.0 * scale))

    p.restore()


class FocusRingTimerSkin(BaseTimerSkin):
    """Janela interativa da skin Focus Ring do Timer Widget."""

    SHADOW_PAD = SHADOW_PAD
    SUPPORTS_MODES = False

    def __init__(self, width: int = BaseTimerSkin.DEFAULT_SIZE, height: int = BaseTimerSkin.DEFAULT_SIZE):
        super().__init__(width=width, height=height)
        self._alarm_pulsing = False
        self._alarm_t0 = time.perf_counter()
        self._center_hovered = False
        self._center_pressed = False
        self._hovered_btn: Optional[str] = None
        self._is_dragging = False
        self._is_resizing = False
        self._drag_start_pos = QPoint()
        self._resize_start_pos = QPoint()
        self._resize_start_side = self.DEFAULT_SIZE

        saved_sec = int(config_manager.get_timer_duration(DEFAULT_FOCUS_MINUTES * 60) or 0)
        init_min = int(round(saved_sec / 60.0)) if saved_sec >= 60 else DEFAULT_FOCUS_MINUTES
        self._setup_minutes: int = max(FOCUS_MIN_MINUTES, min(FOCUS_MAX_MINUTES, init_min))
        self._session_total: float = float(self._setup_minutes * 60)
        self._in_session: bool = False

        self._morph_blend = Blend(0.0, self.update, self)
        self._alarm_clock = FrameTimer(self)
        self._alarm_clock.setInterval(16)
        self._alarm_clock.timeout.connect(self._on_alarm_frame)

    @property
    def is_alarm_pulsing(self) -> bool:
        return self._alarm_pulsing

    @is_alarm_pulsing.setter
    def is_alarm_pulsing(self, value: bool):
        val = bool(value)
        if val and not self._alarm_pulsing:
            self._alarm_t0 = time.perf_counter()
            if not self._alarm_clock.isActive():
                self._alarm_clock.start()
        self._alarm_pulsing = val
        self.update()

    def _on_alarm_frame(self):
        if not self._alarm_pulsing:
            self._alarm_clock.stop()
        self.update()

    def get_card_rect(self) -> QRectF:
        p = self.SHADOW_PAD
        return QRectF(p, p, self.width() - 2 * p, self.height() - 2 * p)

    def get_close_btn_rect(self) -> QRectF:
        card = self.get_card_rect()
        scale = max(0.75, min(card.width(), card.height()) / (self.DEFAULT_SIZE - 2.0 * self.SHADOW_PAD))
        csz = 18.0 * scale
        cpad = 8.0 * scale
        return QRectF(card.left() + cpad, card.top() + cpad, csz, csz)

    def get_resize_grip_rect(self) -> QRectF:
        card = self.get_card_rect()
        scale = max(0.75, min(card.width(), card.height()) / (self.DEFAULT_SIZE - 2.0 * self.SHADOW_PAD))
        gs = 22.0 * scale
        return QRectF(card.right() - gs, card.bottom() - gs, gs, gs)

    def set_time_state(self, current_seconds: float, is_running: bool, mode: str):
        super().set_time_state(current_seconds, is_running, mode)
        if is_running:
            if not self._in_session:
                self._session_total = max(float(current_seconds), float(self._setup_minutes * 60), 60.0)
                self._in_session = True
            self._morph_blend.set(1.0, animated=self.isVisible())
        elif current_seconds <= 0.5:
            # Resetado ou concluído: volta suavemente para os números no centro
            self._in_session = False
            self._morph_blend.set(0.0, animated=self.isVisible())
        else:
            # Pausado no meio da sessão ou duração ajustada no idle
            if self._in_session:
                self._morph_blend.set(1.0, animated=self.isVisible())
            else:
                mins = max(FOCUS_MIN_MINUTES, min(FOCUS_MAX_MINUTES, int(round(current_seconds / 60.0))))
                self._setup_minutes = mins
                self._session_total = float(mins * 60)
                self._morph_blend.set(0.0, animated=self.isVisible())
        self.update()

    def _adjust_minutes(self, direction: int):
        self._setup_minutes = step_focus_minutes(self._setup_minutes, direction)
        self._session_total = float(self._setup_minutes * 60)
        self.duration_changed.emit(self._setup_minutes * 60)
        self.update()

    def _start_focus(self):
        if self.mode != "timer":
            self.mode_changed.emit("timer")
        if not self._in_session or self.current_seconds <= 0.5:
            self._session_total = float(self._setup_minutes * 60)
            self._in_session = True
            self.duration_changed.emit(self._setup_minutes * 60)
        self._morph_blend.set(1.0, animated=self.isVisible())
        self.play_pause_clicked.emit()

    def _reset_focus(self):
        self._in_session = False
        self._morph_blend.set(0.0, animated=self.isVisible())
        self.reset_clicked.emit()

    def _in_circle(self, pos: QPointF, rect: QRectF) -> bool:
        c = rect.center()
        return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= rect.width() * 0.5

    def paintEvent(self, event):
        p = QPainter(self)
        now = time.perf_counter()
        state = TimerState(
            current_seconds=self.current_seconds,
            is_running=self.is_running,
            mode=self.mode,
            is_alarm_pulsing=self._alarm_pulsing,
            alarm_time=self.alarm_time,
            alarm_finished=self.alarm_finished,
            time_morph=self.time_morph,
        )
        progress = (self.current_seconds / self._session_total) if self._session_total > 0 else 0.0
        paint_focus_ring_timer(
            p,
            QRectF(0.0, 0.0, float(self.width()), float(self.height())),
            state,
            self.theme,
            morph=self._morph_blend.value,
            progress=progress,
            setup_minutes=self._setup_minutes,
            center_hovered=self._center_hovered,
            center_pressed=self._center_pressed,
            hovered_btn=self._hovered_btn,
            close_opacity=self._close_opacity,
            close_hovered=self._close_hovered,
            resize_hovered=self._resize_hovered,
            alarm_phase=max(0.0, now - self._alarm_t0),
        )
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        card = self.get_card_rect()
        m = self._morph_blend.value
        _ring, center_rect, minus_rect, start_rect, plus_rect, reset_rect = _focus_layout(card, m)

        if self._close_opacity > 0.2 and self.get_close_btn_rect().contains(pos):
            self.close_requested.emit()
            return
        if self.get_resize_grip_rect().contains(pos):
            self._is_resizing = True
            self._resize_start_pos = event.globalPosition().toPoint()
            self._resize_start_side = self.square_side()
            return
        if m > 0.4 and reset_rect.contains(pos):
            self._reset_focus()
            return
        if m < 0.5:
            if minus_rect.contains(pos):
                self._adjust_minutes(-1)
                return
            if plus_rect.contains(pos):
                self._adjust_minutes(1)
                return
            if start_rect.contains(pos):
                self._start_focus()
                return
        if self._in_circle(pos, center_rect):
            self._center_pressed = True
            self.update()
            return

        self._is_dragging = True
        self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._is_resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            side = max(self.MIN_WIDTH, min(self.MAX_WIDTH, self._resize_start_side + max(delta.x(), delta.y())))
            self.set_square_side(side)
            return
        if self._is_dragging:
            self._drag_window_to(event.globalPosition().toPoint() - self._drag_start_pos)
            return

        pos = event.position()
        card = self.get_card_rect()
        m = self._morph_blend.value
        _ring, center_rect, minus_rect, start_rect, plus_rect, reset_rect = _focus_layout(card, m)

        prev = (self._close_hovered, self._resize_hovered, self._center_hovered, self._hovered_btn)
        self._close_hovered = self._close_opacity > 0.2 and self.get_close_btn_rect().contains(pos)
        self._resize_hovered = self.get_resize_grip_rect().contains(pos)
        self._center_hovered = self._in_circle(pos, center_rect)
        hov_btn: Optional[str] = None
        if m > 0.4 and reset_rect.contains(pos):
            hov_btn = "reset"
        elif m < 0.5:
            if minus_rect.contains(pos):
                hov_btn = "minus"
            elif start_rect.contains(pos):
                hov_btn = "start"
            elif plus_rect.contains(pos):
                hov_btn = "plus"
        self._hovered_btn = hov_btn

        if self._resize_hovered:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif self._close_hovered or self._center_hovered or hov_btn is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if (self._close_hovered, self._resize_hovered, self._center_hovered, self._hovered_btn) != prev:
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        card = self.get_card_rect()
        _ring, center_rect, _m, _s, _p, _r = _focus_layout(card, self._morph_blend.value)

        if self._center_pressed:
            self._center_pressed = False
            self.update()
            if self._in_circle(pos, center_rect):
                if self._in_session:
                    self.play_pause_clicked.emit()
                else:
                    self._start_focus()
            return
        if self._is_resizing:
            self._is_resizing = False
            self.size_committed.emit(self.square_side())
            return
        if self._is_dragging:
            self._is_dragging = False
            self._drag_window_end()
            if config_manager.is_timer_position_remembered():
                origin = self.square_origin()
                config_manager.save_timer_position(origin.x(), origin.y())
            self.drag_finished.emit()

    def wheelEvent(self, event):
        if self._in_session or self.is_running:
            return
        if not config_manager.is_timer_smart_hover_enabled():
            return
        direction = 1 if event.angleDelta().y() > 0 else -1
        self._adjust_minutes(direction)
        event.accept()

    def leaveEvent(self, event):
        self._center_hovered = False
        self._center_pressed = False
        self._hovered_btn = None
        super().leaveEvent(event)
