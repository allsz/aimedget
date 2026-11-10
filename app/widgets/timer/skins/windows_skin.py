import math
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QToolTip, QApplication

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.widgets.timer.duration_rules import MIN_RUN_SECONDS, step_duration
from app.core.typography import get_ui_font
from app.widgets.timer.skins.base_skin import BaseTimerSkin
from app.widgets.timer.skins.skin import TimerState, paint_windows_timer


class WindowsTimerSkin(BaseTimerSkin):
    """
    Skin Padrão do Timer inspirada no Windows 11 PIP Timer:
    - Display digital proeminente com tipografia Inter tabular
    - Tons refinados escuro e claro herdados do Aimedget Hub
    - Botões circulares Play/Pause e Reset com microinterações
    - Botão Fechar oculto no topo esquerdo revelado ao hover
    - Redimensionamento interativo suave mantendo proporções harmônicas
    - Ajuste rápido do tempo via scroll do mouse quando pausado
    """

    SHADOW_PAD = 8.0
    CORNER_RADIUS = 16.0

    def __init__(self, width: int = BaseTimerSkin.DEFAULT_SIZE, height: int = BaseTimerSkin.DEFAULT_SIZE):
        super().__init__(width, height)
        self.pressed_btn: str | None = None
        self.hovered_btn: str | None = None
        self.hovered_time_segment: str | None = None

        # Efeito de flash / pulso ao finalizar contagem regressiva
        self.is_alarm_pulsing = False

    def get_card_rect(self) -> QRectF:
        """Retorna o retângulo da superfície do card descontando a margem de sombra."""
        p = self.SHADOW_PAD
        return QRectF(p, p, self.width() - 2 * p, self.height() - 2 * p)

    def get_scale(self) -> float:
        """Fator de escala proporcional ao tamanho padrão de 164px."""
        card = self.get_card_rect()
        return max(0.8, min(card.width(), card.height()) / (self.DEFAULT_SIZE - 2 * self.SHADOW_PAD))

    def get_close_btn_rect(self) -> QRectF:
        card = self.get_card_rect()
        scale = self.get_scale()
        size = 22.0 * scale
        pad = 9.0 * scale
        return QRectF(card.left() + pad, card.top() + pad, size, size)

    def get_buttons_geometry(self) -> tuple[QRectF, QRectF]:
        """Calcula a geometria dos botões circulares Play/Pause e Reset."""
        card = self.get_card_rect()
        scale = self.get_scale()

        play_diam = 40.0 * scale
        reset_diam = 32.0 * scale
        gap = 12.0 * scale

        total_w = play_diam + gap + reset_diam
        start_x = card.left() + (card.width() - total_w) / 2.0
        center_y = card.bottom() - 32.0 * scale

        play_rect = QRectF(start_x, center_y - play_diam / 2.0, play_diam, play_diam)
        reset_rect = QRectF(start_x + play_diam + gap, center_y - reset_diam / 2.0, reset_diam, reset_diam)
        return play_rect, reset_rect

    def get_resize_grip_rect(self) -> QRectF:
        card = self.get_card_rect()
        grip_size = 22.0 * self.get_scale()
        return QRectF(card.right() - grip_size, card.bottom() - grip_size, grip_size, grip_size)

    def get_digits_geometry(self) -> tuple[dict[str, QRectF], dict[str, str], QFont]:
        """
        Calcula as geometrias exatas de cada segmento de tempo (horas, minutos, segundos e separadores).
        Permite detecção precisa de hover inteligente e renderização desacoplada.
        """
        card = self.get_card_rect()
        scale = self.get_scale()
        tot = max(0, int(round(self.current_seconds)))
        hrs = tot // 3600
        mins = (tot % 3600) // 60
        secs = tot % 60

        hh_str = f"{hrs:02d}"
        mm_str = f"{mins:02d}"
        ss_str = f"{secs:02d}"
        colon = ":"

        digits_font_size = max(16, int(25 * scale))
        font = get_ui_font(digits_font_size, QFont.Weight.DemiBold)
        fm = QFontMetricsF(font)

        w_hh = fm.horizontalAdvance(hh_str)
        w_c1 = fm.horizontalAdvance(colon)
        w_mm = fm.horizontalAdvance(mm_str)
        w_c2 = fm.horizontalAdvance(colon)
        w_ss = fm.horizontalAdvance(ss_str)

        total_w = w_hh + w_c1 + w_mm + w_c2 + w_ss
        start_x = card.left() + (card.width() - total_w) / 2.0
        y = card.top() + 32 * scale
        h = 40 * scale

        rects = {
            "hours": QRectF(start_x, y, w_hh, h),
            "colon1": QRectF(start_x + w_hh, y, w_c1, h),
            "minutes": QRectF(start_x + w_hh + w_c1, y, w_mm, h),
            "colon2": QRectF(start_x + w_hh + w_c1 + w_mm, y, w_c2, h),
            "seconds": QRectF(start_x + w_hh + w_c1 + w_mm + w_c2, y, w_ss, h),
        }
        texts = {
            "hours": hh_str,
            "colon1": colon,
            "minutes": mm_str,
            "colon2": colon,
            "seconds": ss_str,
        }
        return rects, texts, font

    def get_time_segment_at(self, pos: QPointF) -> str | None:
        """Retorna 'hours', 'minutes' ou 'seconds' se o mouse estiver sobre o segmento numérico correspondente."""
        rects, _, _ = self.get_digits_geometry()
        card = self.get_card_rect()
        scale = self.get_scale()
        y_top = card.top() + 28 * scale
        y_bottom = card.top() + 76 * scale

        if not (y_top <= pos.y() <= y_bottom):
            return None

        px = pos.x()
        c1_mid = rects["colon1"].center().x()
        c2_mid = rects["colon2"].center().x()

        if rects["hours"].left() - 6 * scale <= px <= c1_mid:
            return "hours"
        elif c1_mid < px <= c2_mid:
            return "minutes"
        elif c2_mid < px <= rects["seconds"].right() + 6 * scale:
            return "seconds"

        return None

    def is_play_enabled(self) -> bool:
        """Sem 10 s ou mais definidos, o temporizador não pode iniciar."""
        return self.is_running or self.mode != "timer" or self.target_duration >= MIN_RUN_SECONDS

    def _hit_test_for_play(self) -> str:
        """Classificação do centro do botão Play (usada também pelos testes)."""
        play_rect, _ = self.get_buttons_geometry()
        return self._hit_test(play_rect.center())

    def _hit_test(self, pos: QPointF) -> str:
        """Determina em qual elemento interativo o mouse está posicionado."""
        if self._close_opacity > 0.1 and self.get_close_btn_rect().contains(pos):
            return "close"

        play_rect, reset_rect = self.get_buttons_geometry()
        # Teste circular para o botão Play
        play_center = play_rect.center()
        play_radius = play_rect.width() / 2.0
        if math.hypot(pos.x() - play_center.x(), pos.y() - play_center.y()) <= play_radius:
            return "play_pause" if self.is_play_enabled() else "play_disabled"

        # Teste circular para o botão Reset
        reset_center = reset_rect.center()
        reset_radius = reset_rect.width() / 2.0
        if math.hypot(pos.x() - reset_center.x(), pos.y() - reset_center.y()) <= reset_radius:
            return "reset"

        if self.get_resize_grip_rect().contains(pos):
            return "resize_grip"

        if config_manager.is_timer_smart_hover_enabled() and not self.is_running:
            seg = self.get_time_segment_at(pos)
            if seg:
                return f"time_{seg}"

        if self.get_card_rect().contains(pos):
            return "surface"

        return "none"

    # --- Renderização Visual com QPainter ---

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
        )
        paint_windows_timer(p, QRectF(0, 0, float(self.width()), float(self.height())), state, self.theme)
        if self._hovered or self._is_resizing:
            scale = self.get_scale()
            self._paint_resize_grip(p, scale)
        p.end()

    def _paint_play_pause_button(self, p: QPainter, rect: QRectF, scale: float):
        t = self.theme
        is_pressed = self.pressed_btn == "play_pause"
        is_hover = self.hovered_btn == "play_pause"

        # Cor do botão Play (Acento do Hub)
        if is_hover:
            btn_color = QColor(t.accent_hover)
        else:
            btn_color = QColor(t.accent)

        if is_pressed:
            btn_color = btn_color.darker(115)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(btn_color))
        p.drawEllipse(rect)

        # Ícone interno (Play ou Pause)
        icon_color = QColor(t.ink)
        p.setBrush(QBrush(icon_color))

        center = rect.center()
        icon_size = 13.0 * scale

        if self.is_running:
            # Ícone de Pause: dois traços arredondados verticais
            bar_w = 3.2 * scale
            bar_h = icon_size
            gap = 3.4 * scale
            left_bar = QRectF(center.x() - bar_w - gap / 2.0, center.y() - bar_h / 2.0, bar_w, bar_h)
            right_bar = QRectF(center.x() + gap / 2.0, center.y() - bar_h / 2.0, bar_w, bar_h)
            p.drawRoundedRect(left_bar, 1.2 * scale, 1.2 * scale)
            p.drawRoundedRect(right_bar, 1.2 * scale, 1.2 * scale)
        else:
            # Ícone de Play: triângulo apontando para a direita
            tri = QPainterPath()
            offset_x = 1.0 * scale
            half_w = (icon_size * 0.9) / 2.0
            half_h = icon_size / 2.0
            tri.moveTo(center.x() - half_w + offset_x, center.y() - half_h)
            tri.lineTo(center.x() + half_w + offset_x, center.y())
            tri.lineTo(center.x() - half_w + offset_x, center.y() + half_h)
            tri.closeSubpath()
            p.drawPath(tri)

    def _paint_reset_button(self, p: QPainter, rect: QRectF, scale: float):
        t = self.theme
        is_pressed = self.pressed_btn == "reset"
        is_hover = self.hovered_btn == "reset"

        # Cor do botão Reset (Superfície secundária do Hub)
        btn_color = QColor(t.panel2)
        if is_hover:
            btn_color = btn_color.lighter(120) if t.is_dark else btn_color.darker(108)
        if is_pressed:
            btn_color = btn_color.darker(115)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(btn_color))
        p.drawEllipse(rect)

        # Ícone interno de Reset (Seta circular vetorial)
        center = rect.center()
        r = 5.2 * scale
        arc_rect = QRectF(center.x() - r, center.y() - r, 2 * r, 2 * r)

        pen = QPen(QColor(t.body), 1.6 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(arc_rect, int(35 * 16), int(290 * 16))

        # Cabeça da seta
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.body)))
        arrow_head = QPainterPath()
        tip_x = center.x() + r * math.cos(math.radians(35))
        tip_y = center.y() - r * math.sin(math.radians(35))
        arrow_head.moveTo(tip_x, tip_y - 3.2 * scale)
        arrow_head.lineTo(tip_x + 3.0 * scale, tip_y + 1.5 * scale)
        arrow_head.lineTo(tip_x - 3.0 * scale, tip_y + 1.5 * scale)
        arrow_head.closeSubpath()
        p.drawPath(arrow_head)

    def _paint_close_button(self, p: QPainter, scale: float):
        rect = self.get_close_btn_rect()
        alpha = int(self._close_opacity * 255)

        if self._close_hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(232, 17, 35, int(self._close_opacity * 220))))
            p.drawEllipse(rect)
            cross_color = QColor(255, 255, 255, alpha)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            bg_alpha = 40 if self.theme.is_dark else 25
            p.setBrush(QBrush(QColor(255, 255, 255, int(self._close_opacity * bg_alpha))))
            p.drawEllipse(rect)
            cross_color = QColor(self.theme.mute)
            cross_color.setAlpha(alpha)

        # Cruz vetorial ✕
        center = rect.center()
        s = 3.5 * scale
        pen = QPen(cross_color, 1.4 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(center.x() - s, center.y() - s), QPointF(center.x() + s, center.y() + s))
        p.drawLine(QPointF(center.x() + s, center.y() - s), QPointF(center.x() - s, center.y() + s))

    def _paint_resize_grip(self, p: QPainter, scale: float):
        card = self.get_card_rect()
        grip_x = card.right() - 8 * scale
        grip_y = card.bottom() - 8 * scale

        alpha = 240 if self._resize_hovered else (160 if self._hovered else 80)
        dot_color = QColor(self.theme.mute)
        dot_color.setAlpha(alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dot_color))

        r = 1.2 * scale
        spacing = 3.6 * scale
        # 3 pequenos pontos diagonais
        p.drawEllipse(QPointF(grip_x, grip_y), r, r)
        p.drawEllipse(QPointF(grip_x - spacing, grip_y), r, r)
        p.drawEllipse(QPointF(grip_x, grip_y - spacing), r, r)

    # --- Tratamento de Eventos de Mouse ---

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            hit = self._hit_test(pos)

            if hit == "resize_grip":
                self._is_resizing = True
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_size = self.size()
            elif hit in ("close", "play_pause", "reset"):
                self.pressed_btn = hit
                self.update()
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        pos = event.position()

        # 1. Redimensionamento suave interativo
        if self._is_resizing and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            avg_delta = (delta.x() + delta.y()) // 2
            new_side = max(self.MIN_WIDTH, min(self.MAX_WIDTH, self._resize_start_size.width() + avg_delta))
            self.resize(new_side, new_side)
            self.update()
            return

        # 2. Arraste livre de janela (Free drag)
        if not self._drag_pos.isNull() and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            return

        # 3. Teste de hover e atualização de cursor
        hit = self._hit_test(pos)
        self._close_hovered = (hit == "close")

        prev_seg = self.hovered_time_segment
        if hit.startswith("time_"):
            self.hovered_time_segment = hit.replace("time_", "")
        else:
            self.hovered_time_segment = None

        if prev_seg != self.hovered_time_segment:
            self.update()

        if hit != self.hovered_btn:
            if self.hovered_btn == "play_disabled":
                QToolTip.hideText()
            self.hovered_btn = hit
            if hit == "play_disabled":
                self.setCursor(Qt.CursorShape.ForbiddenCursor)
                QToolTip.showText(event.globalPosition().toPoint(), t("timer_min_start_hint"), self)
            elif hit in ("close", "play_pause", "reset"):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif hit.startswith("time_"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif hit == "resize_grip":
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self.hovered_time_segment = None
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging = not self._drag_pos.isNull()
            was_resizing = self._is_resizing
            hit = self._hit_test(event.position())

            if was_dragging:
                self._drag_pos = QPoint()
                if config_manager.is_timer_position_remembered():
                    config_manager.save_timer_position(self.x(), self.y())

            if was_resizing:
                self._is_resizing = False
                config_manager.save_timer_size(self.width(), self.height())

            if self.pressed_btn == "close" and hit == "close":
                self.close_requested.emit()
            elif self.pressed_btn == "play_pause" and hit == "play_pause":
                self.play_pause_clicked.emit()
            elif self.pressed_btn == "reset" and hit == "reset":
                self.reset_clicked.emit()

            self.pressed_btn = None
            self.update()

    def wheelEvent(self, event: QWheelEvent):
        """Scroll do mouse inteligente: ajusta individualmente horas, minutos ou segundos."""
        if not self.is_running:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            direction = 1 if delta > 0 else -1
            shift_pressed = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

            is_smart = config_manager.is_timer_smart_hover_enabled()
            seg = self.hovered_time_segment if is_smart else None

            if seg == "hours":
                step = 3600
            elif seg == "minutes":
                step = 300 if shift_pressed else 60
            elif seg == "seconds":
                step = 5 if shift_pressed else 1
            else:
                step = 300 if shift_pressed else 60

            change = step * direction
            base_val = self.target_duration if self.mode == "timer" else self.current_seconds
            if self.mode == "timer":
                new_val = step_duration(int(base_val), change)   # 0 ou >= 10 s (sem valores mortos)
            else:
                new_val = max(1, min(86400 * 24, int(base_val + change)))

            if self.mode == "timer":
                self.target_duration = float(new_val)
                self.current_seconds = float(new_val)
                self.duration_changed.emit(new_val)
            else:
                self.current_seconds = float(new_val)
                self.update()

            event.accept()
        else:
            super().wheelEvent(event)
