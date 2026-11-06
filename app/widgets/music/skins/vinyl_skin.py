import time
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QFont, QFontMetrics
from PySide6.QtSvg import QSvgRenderer

from app.core.paths import get_vinyl_asset
from app.core.typography import get_ui_font
from app.core.colorimetry import (
    lerp_palette,
    palettes_are_close,
    render_adaptive_card_background,
)
from app.ui_components.pill_button import draw_pill_button
from app.widgets.music.skins.base_skin import BaseMusicSkin

# Escala da janela desktop em relação ao canvas 16:9 (960 x 540 -> 480 x 270)
SCALE = 0.50
WIDGET_W = int(960 * SCALE)  # 480 px
WIDGET_H = int(540 * SCALE)  # 270 px


class VinylMusicSkin(BaseMusicSkin):
    """
    Skin de Vinil (Wide Vinyl Edition):
    - Toca-discos interativo com giro 33 RPM e scrubbing DJ na barra de progresso.
    - Física e keyframes exclusivos do braço da agulha (tonearm).
    - Listener exclusivo `tonearm_landed`: ao clicar Play no widget, aguarda a agulha pousar no disco antes de tocar.
    - Colorimetria Dinâmica (Passo 4): gradiente adaptativo extraído da capa do álbum com transição suave a 60 FPS.
    """
    tonearm_landed = Signal()

    def __init__(self):
        super().__init__(WIDGET_W, WIDGET_H)

        # Renderizadores SVG exclusivos da skin de Vinil
        self.svg_cover = QSvgRenderer(get_vinyl_asset("cover-placeholder.svg"))
        self.svg_vinyl = QSvgRenderer(get_vinyl_asset("vinyl.svg"))
        self.svg_glare = QSvgRenderer(get_vinyl_asset("vinyl-glare.svg"))
        self.svg_arm_base = QSvgRenderer(get_vinyl_asset("tonearm-base.svg"))
        self.svg_arm = QSvgRenderer(get_vinyl_asset("tonearm.svg"))
        self.svg_prev = QSvgRenderer(get_vinyl_asset("icon-prev.svg"))
        self.svg_play = QSvgRenderer(get_vinyl_asset("icon-play.svg"))
        self.svg_pause = QSvgRenderer(get_vinyl_asset("icon-pause.svg"))
        self.svg_next = QSvgRenderer(get_vinyl_asset("icon-next.svg"))

        # Parâmetros de ângulo da agulha
        self.park_angle = -22.0
        self.play_angle = 17.7
        self.drift_max = 4.5

        # Estado da Física do Toca-Discos
        self.arm_state = "parked"
        self.arm_anim_start = 0.0
        self.arm_anim_from = self.park_angle
        self.arm_current_angle = self.park_angle
        self._pending_play_on_land = False
        self._ignore_external_state_until = 0.0
        self._last_seek_sent = 0.0

        # Listener exclusivo da skin Vinyl: dispara quando o tonearm conclui a descida no vinil
        self.tonearm_landed.connect(self._on_tonearm_landed)

        self.vinyl_angle = 0.0
        self.scrub_velocity = 0.0

        # Estado de interação do Mouse
        self.hovered_btn = None
        self.pressed_btn = None
        self.is_dragging_bar = False
        self.press_bar_x = 0.0
        self.last_scrub_x = 0.0
        self.last_scrub_t = 0.0

        # Retângulos de colisão (convertidos via SCALE para hit-test)
        self.rect_main = QRectF(52 * SCALE, 402 * SCALE, 132 * SCALE, 60 * SCALE)
        self.rect_prev = QRectF(204 * SCALE, 402 * SCALE, 90 * SCALE, 60 * SCALE)
        self.rect_next = QRectF(310 * SCALE, 402 * SCALE, 90 * SCALE, 60 * SCALE)
        self.rect_bar_hit = QRectF(52 * SCALE, 310 * SCALE, 348 * SCALE, 36 * SCALE)

        # Loop de física a ~60 FPS
        self.last_tick = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._on_physics_tick)
        self.timer.start()

    def on_media_updated(self, title: str, artist: str, is_playing: bool, pos: float, dur: float, thumb_bytes: bytes):
        changed = False
        track_changed = (title != self.title_text or artist != self.artist_text)
        if track_changed:
            self.title_text = title
            self.artist_text = artist
            changed = True

        if self._update_and_cache_cover(thumb_bytes):
            changed = True

        now = time.perf_counter()
        if not self._pending_play_on_land and now >= self._ignore_external_state_until:
            if is_playing != self.is_playing:
                self._set_playing_state(is_playing)
                changed = True

        if dur > 0:
            self.duration = dur

        # Sincronização refinada da barra de progresso (sem saltos entre snapshots antigos e novos)
        can_sync_pos = (
            not self.is_dragging_bar
            and self.pressed_btn != "bar"
            and not self._pending_play_on_land
            and (now - self._last_seek_sent > 1.5)
        )
        if can_sync_pos and dur > 0:
            if track_changed:
                self.current_time = min(self.duration, max(0.0, pos))
                changed = True
            else:
                drift = pos - self.current_time
                if abs(drift) > 1.5:
                    # Salto real (ex: usuário avançou a música direto no Spotify/YouTube)
                    self.current_time = min(self.duration, max(0.0, pos))
                    changed = True
                elif abs(drift) > 0.15:
                    # Correção suave de micro-deriva sem causar tranco visual na barra
                    self.current_time = min(self.duration, max(0.0, self.current_time + drift * 0.35))
                    changed = True

        if changed:
            self.update()

    @staticmethod
    def _cubic_ease(t: float) -> float:
        return 3 * (t ** 2) - 2 * (t ** 3)

    def _compute_target_play_angle(self) -> float:
        progress = max(0.0, min(1.0, self.current_time / self.duration)) if self.duration > 0 else 0.0
        return self.play_angle + progress * self.drift_max

    def _set_playing_state(self, play_on: bool):
        self.is_playing = play_on
        self.arm_anim_start = time.perf_counter()
        self.arm_anim_from = self.arm_current_angle
        self.arm_state = "in" if self.is_playing else "out"
        self.update()

    def toggle_play(self):
        target_play_state = not self.is_playing
        self._set_playing_state(target_play_state)

        if target_play_state:
            # Na skin de Vinil: aguarda o listener tonearm_landed concluir a animação da agulha para tocar
            self._pending_play_on_land = True
        else:
            # Ao pausar: cancela qualquer play pendente e pausa o áudio imediatamente ao levantar a agulha
            self._pending_play_on_land = False
            self._ignore_external_state_until = time.perf_counter() + 1.2
            self.command_requested.emit("pause", None)

    def _on_tonearm_landed(self):
        """Listener exclusivo da skin de Vinil: acionado no exato frame em que o tonearm pousa no disco."""
        if self._pending_play_on_land and self.is_playing:
            self._pending_play_on_land = False
            self._ignore_external_state_until = time.perf_counter() + 1.2
            self.command_requested.emit("play", None)

    def _on_physics_tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self.last_tick)
        self.last_tick = now
        needs_update = False

        # --- 0. Transição Suave da Colorimetria Dinâmica (Passo 4) ---
        if not palettes_are_close(self.current_palette, self.target_palette):
            self.current_palette = lerp_palette(self.current_palette, self.target_palette, min(1.0, dt * 4.5))
            needs_update = True

        target_play = self._compute_target_play_angle()

        # --- 1. Animação de Keyframes da Agulha ---
        if self.arm_state == "in":
            elapsed = now - self.arm_anim_start
            dur = 1.15
            p = min(1.0, elapsed / dur)

            if p < 0.18:
                self.arm_current_angle = self.arm_anim_from
            elif p < 0.74:
                sub = self._cubic_ease((p - 0.18) / (0.74 - 0.18))
                self.arm_current_angle = self.arm_anim_from + (target_play + 1.6 - self.arm_anim_from) * sub
            elif p < 0.88:
                sub = self._cubic_ease((p - 0.74) / (0.88 - 0.74))
                self.arm_current_angle = (target_play + 1.6) + ((target_play - 0.4) - (target_play + 1.6)) * sub
            else:
                sub = self._cubic_ease((p - 0.88) / (1.0 - 0.88))
                self.arm_current_angle = (target_play - 0.4) + (target_play - (target_play - 0.4)) * sub

            if p >= 1.0:
                self.arm_state = "on"
                self.arm_current_angle = target_play
                self.tonearm_landed.emit()
            needs_update = True

        elif self.arm_state == "out":
            elapsed = now - self.arm_anim_start
            dur = 0.90
            p = min(1.0, elapsed / dur)

            if p < 0.18:
                self.arm_current_angle = self.arm_anim_from
            else:
                sub = self._cubic_ease((p - 0.18) / (1.0 - 0.18))
                self.arm_current_angle = self.arm_anim_from + (self.park_angle - self.arm_anim_from) * sub

            if p >= 1.0:
                self.arm_state = "parked"
                self.arm_current_angle = self.park_angle
            needs_update = True

        elif self.arm_state == "on":
            self.arm_current_angle = target_play

        # --- 2. Giro do Vinil e Avanço Contínuo do Tempo ---
        if self.is_dragging_bar:
            if abs(self.scrub_velocity) > 0.05:
                self.vinyl_angle = (self.vinyl_angle + self.scrub_velocity * dt) % 360.0
                self.scrub_velocity *= 0.82
                needs_update = True
        else:
            if abs(self.scrub_velocity) > 0.5:
                self.vinyl_angle = (self.vinyl_angle + self.scrub_velocity * dt) % 360.0
                self.scrub_velocity *= 0.85
                needs_update = True
            else:
                self.scrub_velocity = 0.0

            if self.is_playing and self.arm_state == "on":
                self.vinyl_angle = (self.vinyl_angle + 105.88 * dt) % 360.0
                if self.duration > 0:
                    self.current_time = min(self.duration, self.current_time + dt)
                needs_update = True

        if needs_update:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.scale(SCALE, SCALE)

        # --- 1. Card Arredondado (960x540, radius 40) com Colorimetria Dinâmica (Passo 4) ---
        card_rect = QRectF(0, 0, 960, 540)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(card_rect, 40, 40)
        painter.setClipPath(clip_path)

        render_adaptive_card_background(painter, card_rect, self.current_palette)

        painter.setPen(QPen(QColor(255, 255, 255, 26), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, 958, 538), 39, 39)

        # --- 2. Tipografia com Fonte "Inter" Unificada em Todo o App ---
        font_title = get_ui_font(44, QFont.Weight.Bold)
        font_title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.0)
        painter.setFont(font_title)
        painter.setPen(QColor("#FFFFFF"))
        fm_title = QFontMetrics(font_title)
        elided_title = fm_title.elidedText(self.title_text, Qt.TextElideMode.ElideRight, 356)
        painter.drawText(QRectF(52, 54, 356, 54), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        font_artist = get_ui_font(24, QFont.Weight.Medium)
        painter.setFont(font_artist)
        painter.setPen(QColor(255, 255, 255, 175))
        fm_artist = QFontMetrics(font_artist)
        elided_artist = fm_artist.elidedText(self.artist_text, Qt.TextElideMode.ElideRight, 356)
        painter.drawText(QRectF(52, 114, 356, 34), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_artist)

        # --- 3. Barra de Progresso e Tempos (left=52, top=326, w=348) ---
        progress_ratio = max(0.0, min(1.0, self.current_time / self.duration)) if self.duration > 0 else 0.0
        bar_x, bar_y, bar_w, bar_h = 52.0, 326.0, 348.0, 6.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 56))
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 3, 3)

        fill_w = bar_w * progress_ratio
        painter.setBrush(QColor("#FFFFFF"))
        if fill_w > 0:
            painter.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 3, 3)

        knob_x = bar_x + fill_w
        knob_y = bar_y + bar_h / 2.0
        knob_r = 9.5 if (self.hovered_btn == "bar" or self.pressed_btn == "bar") else 7.0

        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawEllipse(QPointF(knob_x, knob_y + 2), knob_r, knob_r)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(knob_x, knob_y), knob_r, knob_r)

        font_time = get_ui_font(22, QFont.Weight.DemiBold)
        painter.setFont(font_time)
        painter.setPen(QColor(255, 255, 255, 190))
        painter.drawText(QRectF(bar_x, bar_y + 14, 110, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._fmt_time(self.current_time))
        painter.drawText(QRectF(bar_x + bar_w - 110, bar_y + 14, 110, 26), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._fmt_time(self.duration))

        # --- 4. Botões Pill Translúcidos ---
        play_or_pause_svg = self.svg_pause if self.is_playing else self.svg_play
        draw_pill_button(painter, play_or_pause_svg, QRectF(52, 402, 132, 60), self.hovered_btn == "main", self.pressed_btn == "main")
        draw_pill_button(painter, self.svg_prev, QRectF(204, 402, 90, 60), self.hovered_btn == "prev", self.pressed_btn == "prev")
        draw_pill_button(painter, self.svg_next, QRectF(310, 402, 90, 60), self.hovered_btn == "next", self.pressed_btn == "next")

        font_lbl = get_ui_font(20, QFont.Weight.Medium)
        painter.setFont(font_lbl)
        painter.setPen(QColor(255, 255, 255, 175))
        lbl_str = "Pause" if self.is_playing else "Play"
        painter.drawText(QRectF(52, 470, 132, 26), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, lbl_str)

        # --- 5. Base Estática da Agulha (757.0, 28.9, 112.2x171.7) ---
        self.svg_arm_base.render(painter, QRectF(757.0, 28.9, 112.2, 171.7))

        # --- 6. O Disco de Vinil (440, 60, 420x420) ---
        disc_x, disc_y, disc_s = 440.0, 60.0, 420.0
        disc_cx = disc_x + disc_s / 2.0
        disc_cy = disc_y + disc_s / 2.0

        painter.setBrush(QColor(0, 10, 30, 130))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(disc_x + 8, disc_y + 16, disc_s - 16, disc_s - 16))

        painter.save()
        painter.translate(disc_cx, disc_cy)
        painter.rotate(self.vinyl_angle)

        cover_s = disc_s * 0.36
        cover_rect = QRectF(-cover_s / 2.0, -cover_s / 2.0, cover_s, cover_s)
        cover_clip = QPainterPath()
        cover_clip.addEllipse(cover_rect)
        painter.save()
        painter.setClipPath(cover_clip, Qt.ClipOperation.IntersectClip)

        if self.album_pixmap is not None and not self.album_pixmap.isNull():
            pw = self.album_pixmap.width()
            ph = self.album_pixmap.height()
            side = min(pw, ph)
            src_rect = QRectF((pw - side) / 2.0, (ph - side) / 2.0, side, side)
            painter.drawPixmap(cover_rect, self.album_pixmap, src_rect)
        else:
            self.svg_cover.render(painter, cover_rect)
        painter.restore()

        self.svg_vinyl.render(painter, QRectF(-disc_s / 2.0, -disc_s / 2.0, disc_s, disc_s))
        painter.restore()

        self.svg_glare.render(painter, QRectF(disc_x, disc_y, disc_s, disc_s))

        # --- 7. A Agulha (731.8, 23.0, 172.4x434.0, origin=73.2, 62.0) ---
        arm_left, arm_top, arm_w, arm_h = 731.8, 23.0, 172.4, 434.0
        origin_x, origin_y = 73.2, 62.0

        painter.save()
        painter.translate(arm_left + origin_x, arm_top + origin_y)
        painter.rotate(self.arm_current_angle)
        self.svg_arm.render(painter, QRectF(-origin_x, -origin_y, arm_w, arm_h))
        painter.restore()

    def _hit_test(self, pos):
        if self.rect_main.contains(pos):
            return "main"
        if self.rect_prev.contains(pos):
            return "prev"
        if self.rect_next.contains(pos):
            return "next"
        if self.rect_bar_hit.contains(pos):
            return "bar"
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            hit = self._hit_test(pos)

            if hit == "bar":
                self.pressed_btn = "bar"
                self.is_dragging_bar = False
                self.press_bar_x = pos.x()
                self.last_scrub_x = pos.x()
                self.last_scrub_t = time.perf_counter()
                self._seek_to_x(pos.x())
                self.update()
            elif hit in ("prev", "main", "next"):
                self.pressed_btn = hit
                self.update()
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        pos = event.position()

        if (event.buttons() & Qt.MouseButton.LeftButton) and self.pressed_btn == "bar":
            now = time.perf_counter()
            dx = pos.x() - self.last_scrub_x
            dt = max(0.004, now - self.last_scrub_t)

            if not self.is_dragging_bar and abs(pos.x() - self.press_bar_x) > 2.0:
                self.is_dragging_bar = True

            if self.is_dragging_bar:
                angle_delta = dx * 3.4
                self.vinyl_angle = (self.vinyl_angle + angle_delta) % 360.0
                self.scrub_velocity = max(-1800.0, min(1800.0, (angle_delta / dt) * 0.35))

                self.last_scrub_x = pos.x()
                self.last_scrub_t = now
                self._seek_to_x(pos.x())
                self.update()
            return

        if (event.buttons() & Qt.MouseButton.LeftButton) and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            return

        hit = self._hit_test(pos)
        if hit != self.hovered_btn:
            self.hovered_btn = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            hit = self._hit_test(pos)

            if self.pressed_btn == "main" and hit == "main":
                self.toggle_play()
            elif self.pressed_btn == "prev" and hit == "prev":
                self.current_time = 0.0
                self._last_seek_sent = time.perf_counter()
                self.command_requested.emit("prev", None)
            elif self.pressed_btn == "next" and hit == "next":
                self.current_time = 0.0
                self._last_seek_sent = time.perf_counter()
                self.command_requested.emit("next", None)
            elif self.pressed_btn == "bar":
                self._last_seek_sent = time.perf_counter()
                self.command_requested.emit("seek", self.current_time)

            self.pressed_btn = None
            self.is_dragging_bar = False
            self._drag_pos = QPoint()
            self.update()

    def _seek_to_x(self, x_widget: float):
        bar_start = 52.0 * SCALE
        bar_width = 348.0 * SCALE
        ratio = max(0.0, min(1.0, (x_widget - bar_start) / bar_width))
        self.current_time = ratio * self.duration
        if self.arm_state == "on":
            self.arm_current_angle = self._compute_target_play_angle()
