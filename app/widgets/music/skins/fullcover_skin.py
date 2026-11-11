import os
import time
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QTimer
from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QPen,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QImage,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer

from app.core.paths import get_vinyl_asset, get_provider_icon_path
from app.core.typography import get_ui_font
from app.core.colorimetry import (
    lerp_palette,
    palettes_are_close,
    render_adaptive_card_background,
    extract_palette_from_image,
    get_default_palette,
)
from app.ui_components.soundwave_visualizer import SoundWaveVisualizer
from app.ui_components.crisp_icons import CrispIconsMixin
from app.widgets.music.skins.base_skin import BaseMusicSkin

# Dimensões nativas do canvas 16:9
CANVAS_W = 960
CANVAS_H = 540


class FullCoverSkin(CrispIconsMixin, BaseMusicSkin):
    """
    Skin Wide FullCover (inspirada em wide_fullcover.png):
    - Fundo imersivo (Full Bleed) em alta definição (pré-filtrado via SmoothTransformation sem fantasma duplo).
    - Badge superior esquerdo com logo monocromático branco do provedor ou equalizador animado.
    - Tipografia limpa à esquerda (Título + Artista em caixa alta/média).
    - Botão circular branco flutuante de Play/Pause à direita com ícone contrastante escuro.
    - Barra inferior integrada: Anterior, Barra de Progresso com marcador vertical, Próximo, Fila e Favorito.
    """
    CARD_RADIUS: float = 48.0

    def __init__(self, scale: float | None = None):
        super().__init__(CANVAS_W, CANVAS_H, scale=scale)

        self.svg_prev = QSvgRenderer(get_vinyl_asset("icon-prev.svg"))
        self.svg_next = QSvgRenderer(get_vinyl_asset("icon-next.svg"))
        self.soundwave = SoundWaveVisualizer()
        self._fullbleed_pixmap: QPixmap | None = None

        # Renderizadores SVG monocromáticos brancos dos provedores
        self.provider_renderers = {}
        for p_name in ("spotify", "youtube_music", "apple_music", "deezer", "tidal", "amazon_music", "soundcloud"):
            p_path = get_provider_icon_path(p_name)
            if os.path.exists(p_path):
                self.provider_renderers[p_name] = QSvgRenderer(p_path)

        # Estado de interação
        self.hovered_btn = None
        self.pressed_btn = None
        self.is_dragging_bar = False
        self.is_shuffle = False
        self.repeat_mode = 0  # 0: off, 1: repeat playlist, 2: repeat track (1)
        self._last_seek_sent = 0.0
        self._ignore_external_state_until = 0.0

        # Áreas de clique proporcionais à escala atual
        self._update_hitboxes()

        # Loop a ~60 FPS
        self.last_tick = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._on_tick)  # iniciado/pausado pela base (show/hide)

    def _update_hitboxes(self):
        s = self.scale
        self.rect_main = QRectF((842 - 54) * s, (256 - 54) * s, 108 * s, 108 * s)
        self.rect_prev = QRectF(42 * s, 420 * s, 56 * s, 56 * s)
        self.rect_bar_hit = QRectF(132 * s, 424 * s, 486 * s, 48 * s)
        self.rect_next = QRectF(648 * s, 420 * s, 56 * s, 56 * s)
        self.rect_shuffle = QRectF(738 * s, 420 * s, 56 * s, 56 * s)
        self.rect_repeat = QRectF(828 * s, 420 * s, 56 * s, 56 * s)

    @staticmethod
    def _prepare_crisp_fullbleed(img: QImage) -> QPixmap:
        """
        Prepara um QPixmap em alta definição (960x540) usando interpolação bicúbica/área
        (SmoothTransformation) da CPU, eliminando serrilhado e baixa nitidez do escalonamento em tempo real.
        """
        w, h = img.width(), img.height()
        # Se vier miniatura 16:9 com barras laterais/superiores (comum no YouTube), recorta o quadrado central
        if w > h * 1.18:
            side = h
            x0 = (w - side) // 2
            img = img.copy(x0, 0, side, side)

        # Escala proporcionalmente para cobrir 960x540 com nitidez máxima
        scaled = img.scaled(
            960,
            960,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Recorta a faixa 960x540 priorizando o terço superior/central (onde ficam rostos e arte principal)
        sw, sh = scaled.width(), scaled.height()
        crop_x = max(0, (sw - 960) // 2)
        crop_y = max(0, int((sh - 540) * 0.36))
        cropped = scaled.copy(crop_x, crop_y, min(960, sw), min(540, sh))
        return QPixmap.fromImage(cropped)

    def _update_and_cache_cover(self, thumb_bytes: bytes) -> bool:
        if thumb_bytes and thumb_bytes != self._last_thumb_bytes:
            self._last_thumb_bytes = thumb_bytes
            img = QImage.fromData(thumb_bytes)
            if not img.isNull():
                self.album_pixmap = QPixmap.fromImage(img)
                self._fullbleed_pixmap = self._prepare_crisp_fullbleed(img)
                self.target_palette = extract_palette_from_image(img)
                self._note_cover_for_track()
                return True
        elif not thumb_bytes and self._default_cover_due():
            if self._last_thumb_bytes:
                self._last_thumb_bytes = b""
                self.album_pixmap = None
                self._fullbleed_pixmap = None
                self.target_palette = get_default_palette()
                return True
        return False

    def on_media_updated(
        self,
        title: str,
        artist: str,
        is_playing: bool,
        pos: float,
        dur: float,
        thumb_bytes: bytes,
        provider: str = "generic",
    ):
        changed = False
        track_changed = (title != self.title_text or artist != self.artist_text)
        if track_changed:
            self.title_text = title
            self.artist_text = artist
            changed = True

        if provider != self.provider:
            self.provider = provider
            changed = True

        if self._update_and_cache_cover(thumb_bytes):
            changed = True

        now = time.perf_counter()
        if now >= self._ignore_external_state_until:
            if is_playing != self.is_playing:
                self.is_playing = is_playing
                changed = True

        # Faixa nova sem duração (o player ainda não mandou a dela): zera em vez de herdar a da faixa anterior
        if dur > 0 or track_changed:
            self.duration = dur

        can_sync_pos = (
            not self.is_dragging_bar
            and self.pressed_btn != "bar"
            and (now - self._last_seek_sent > 1.5)
        )
        if can_sync_pos and (dur > 0 or track_changed):
            if track_changed:
                self.current_time = min(self.duration, max(0.0, pos))
                changed = True
            else:
                drift = pos - self.current_time
                if abs(drift) > 1.5:
                    self.current_time = min(self.duration, max(0.0, pos))
                    changed = True
                elif abs(drift) > 0.15:
                    self.current_time = min(self.duration, max(0.0, self.current_time + drift * 0.35))
                    changed = True

        if changed:
            self.update()

    def _on_tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self.last_tick)
        self.last_tick = now
        needs_update = False

        if not palettes_are_close(self.current_palette, self.target_palette):
            self.current_palette = lerp_palette(self.current_palette, self.target_palette, min(1.0, dt * 4.5))
            needs_update = True

        self.soundwave.update(dt, self.is_playing)
        if self.provider == "generic" and self.is_playing:
            needs_update = True

        if self.is_playing and not self.is_dragging_bar:
            if self.duration > 0:
                self.current_time = min(self.duration, self.current_time + dt)
            needs_update = True

        if needs_update:
            self.update()

    def _draw_fullbleed_cover(self, painter: QPainter, card_rect: QRectF):
        """
        Renderiza a capa do álbum em alta nitidez (1 camada única pré-filtrada em Ultra-HD)
        com vinheta suave à esquerda e na base para legibilidade perfeita.
        """
        if self._fullbleed_pixmap is not None and not self._fullbleed_pixmap.isNull():
            painter.drawPixmap(card_rect, self._fullbleed_pixmap, QRectF(0, 0, self._fullbleed_pixmap.width(), self._fullbleed_pixmap.height()))

            # Vinheta suave à esquerda para leitura nítida do título e artista
            c_dark = QColor(self.current_palette.stop0)
            c_dark.setAlpha(185)
            c_mid = QColor(self.current_palette.stop0)
            c_mid.setAlpha(85)
            c_trans = QColor(self.current_palette.stop0)
            c_trans.setAlpha(0)

            left_grad = QLinearGradient(0, 0, 480, 0)
            left_grad.setColorAt(0.0, c_dark)
            left_grad.setColorAt(0.55, c_mid)
            left_grad.setColorAt(1.0, c_trans)
            painter.fillRect(card_rect, left_grad)
        else:
            render_adaptive_card_background(painter, card_rect, self.current_palette)

        # Vinheta inferior sutil para contraste da barra de progresso e ícones
        bot_grad = QLinearGradient(0, card_rect.height() - 180, 0, card_rect.height())
        bot_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        bot_grad.setColorAt(1.0, QColor(6, 5, 8, 175))
        painter.fillRect(card_rect, bot_grad)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.scale(self.scale, self.scale)

        # --- 1. Card Arredondado (960x540, radius 48) ---
        card_rect = QRectF(0, 0, 960, 540)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(card_rect, 48, 48)
        painter.setClipPath(clip_path)

        self._draw_fullbleed_cover(painter, card_rect)

        # Borda interna sutil de acabamento
        painter.setPen(QPen(QColor(255, 255, 255, 28), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, 958, 538), 47, 47)

        # --- 2. Badge Superior Esquerdo: Logo Monocromático ou Onda Sonora Animada ---
        logo_x, logo_y, logo_s = 56.0, 52.0, 44.0
        if self.provider in self.provider_renderers:
            self.provider_renderers[self.provider].render(painter, QRectF(logo_x, logo_y, logo_s, logo_s))
        else:
            self.soundwave.render(painter, QRectF(logo_x, logo_y, logo_s, logo_s), QColor(255, 255, 255, 245))

        # --- 3. Título da Música e Artista (Meio-Esquerda, amplo espaço horizontal) ---
        title_y = 224.0
        font_title = get_ui_font(38, QFont.Weight.DemiBold)
        font_title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 99.0)
        painter.setFont(font_title)
        painter.setPen(QColor("#FFFFFF"))
        fm_title = QFontMetrics(font_title)
        elided_title = fm_title.elidedText(self.shown_title(), Qt.TextElideMode.ElideRight, 690)
        painter.drawText(QRectF(56, title_y, 690, 48), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        artist_y = 276.0
        font_artist = get_ui_font(23, QFont.Weight.Medium)
        font_artist.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 102.0)
        painter.setFont(font_artist)
        painter.setPen(QColor(255, 255, 255, 185))
        fm_artist = QFontMetrics(font_artist)
        elided_artist = fm_artist.elidedText(self.shown_artist().upper(), Qt.TextElideMode.ElideRight, 690)
        painter.drawText(QRectF(56, artist_y, 690, 34), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_artist)

        # --- 4. Botão Circular Flutuante Play/Pause à Direita ---
        self._draw_floating_play_button(painter, QPointF(842.0, 256.0))

        # --- 5. Barra de Controles Inferior (y_center = 448) ---
        self._draw_bottom_controls(painter, 448.0)

    def _draw_floating_play_button(self, painter: QPainter, center: QPointF):
        is_hover = (self.hovered_btn == "main")
        is_press = (self.pressed_btn == "main")
        radius = 46.0 if is_press else (51.0 if is_hover else 49.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 85))
        painter.drawEllipse(QPointF(center.x(), center.y() + 4.0), radius, radius)

        circle_color = QColor(255, 255, 255, 250) if is_hover else QColor(246, 241, 240, 242)
        painter.setBrush(circle_color)
        painter.drawEllipse(center, radius, radius)

        icon_color = QColor(self.current_palette.stop0).darker(120)
        icon_color.setAlpha(245)

        if self.is_playing:
            bar_w, bar_h, gap = 6.5, 28.0, 10.0
            painter.setBrush(icon_color)
            painter.drawRoundedRect(QRectF(center.x() - gap / 2.0 - bar_w, center.y() - bar_h / 2.0, bar_w, bar_h), 2.5, 2.5)
            painter.drawRoundedRect(QRectF(center.x() + gap / 2.0, center.y() - bar_h / 2.0, bar_w, bar_h), 2.5, 2.5)
        else:
            play_path = QPainterPath()
            ox = center.x() + 2.5
            oy = center.y()
            play_path.moveTo(ox - 10.0, oy - 14.0)
            play_path.lineTo(ox + 14.0, oy)
            play_path.lineTo(ox - 10.0, oy + 14.0)
            play_path.closeSubpath()
            painter.setBrush(icon_color)
            painter.drawPath(play_path)

    def _draw_bottom_controls(self, painter: QPainter, cy: float):
        self._draw_skip_icon(painter, QPointF(70.0, cy), is_next=False, hovered=(self.hovered_btn == "prev"))

        bar_x, bar_w, bar_h = 136.0, 478.0, 3.6
        bar_y = cy - bar_h / 2.0
        progress = max(0.0, min(1.0, self.current_time / self.duration)) if self.duration > 0 else 0.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 75))
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 1.8, 1.8)

        fill_w = bar_w * progress
        painter.setBrush(QColor(255, 255, 255, 235))
        if fill_w > 0:
            painter.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 1.8, 1.8)

        tick_x = bar_x + fill_w
        is_bar_active = (self.hovered_btn == "bar" or self.pressed_btn == "bar")
        tick_w = 5.0 if is_bar_active else 3.6
        tick_h = 22.0 if is_bar_active else 16.0
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(QRectF(tick_x - tick_w / 2.0, cy - tick_h / 2.0, tick_w, tick_h), tick_w / 2.0, tick_w / 2.0)

        self._draw_skip_icon(painter, QPointF(676.0, cy), is_next=True, hovered=(self.hovered_btn == "next"))
        self._draw_shuffle_icon(painter, QPointF(766.0, cy), hovered=(self.hovered_btn == "shuffle"), active=self.is_shuffle)
        self._draw_repeat_icon(painter, QPointF(856.0, cy), hovered=(self.hovered_btn == "repeat"), mode=self.repeat_mode)

        self.paint_resize_grip(painter)

    def _draw_skip_icon(self, painter: QPainter, center: QPointF, is_next: bool, hovered: bool):
        painter.save()
        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 28))
            painter.drawEllipse(center, 24.0, 24.0)

        pen = QPen(QColor(255, 255, 255, 245 if hovered else 215), 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = center.x(), center.y()
        if not is_next:
            painter.drawLine(QPointF(cx - 9.0, cy - 10.0), QPointF(cx - 9.0, cy + 10.0))
            tri = QPainterPath()
            tri.moveTo(cx + 9.0, cy - 10.0)
            tri.lineTo(cx - 6.0, cy)
            tri.lineTo(cx + 9.0, cy + 10.0)
            tri.closeSubpath()
            painter.drawPath(tri)
        else:
            tri = QPainterPath()
            tri.moveTo(cx - 9.0, cy - 10.0)
            tri.lineTo(cx + 6.0, cy)
            tri.lineTo(cx - 9.0, cy + 10.0)
            tri.closeSubpath()
            painter.drawPath(tri)
            painter.drawLine(QPointF(cx + 9.0, cy - 10.0), QPointF(cx + 9.0, cy + 10.0))
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
        if self.rect_shuffle.contains(pos):
            return "shuffle"
        if self.rect_repeat.contains(pos):
            return "repeat"
        return None

    def mousePressEvent(self, event):
        if self.handle_resize_press(event):
            return

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            hit = self._hit_test(pos)
            if hit == "bar":
                self.pressed_btn = "bar"
                self.is_dragging_bar = True
                self._seek_to_x(pos.x())
                self.update()
            elif hit is not None:
                self.pressed_btn = hit
                self.update()
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.handle_resize_move(event):
            return

        pos = event.position()
        if (event.buttons() & Qt.MouseButton.LeftButton) and self.pressed_btn == "bar":
            self._seek_to_x(pos.x())
            self.update()
            return

        if (event.buttons() & Qt.MouseButton.LeftButton) and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            return

        if self.handle_resize_hover(pos):
            return

        hit = self._hit_test(pos)
        if hit != self.hovered_btn:
            self.hovered_btn = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        if self.handle_resize_release(event):
            return

        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging_window = not self._drag_pos.isNull()
            pos = event.position()
            hit = self._hit_test(pos)

            if self.pressed_btn == "main" and hit == "main":
                self.is_playing = not self.is_playing
                self._ignore_external_state_until = time.perf_counter() + 1.0
                self.command_requested.emit("play" if self.is_playing else "pause", None)
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
            elif self.pressed_btn == "shuffle" and hit == "shuffle":
                self.is_shuffle = not self.is_shuffle
                self.command_requested.emit("shuffle", self.is_shuffle)
            elif self.pressed_btn == "repeat" and hit == "repeat":
                self.repeat_mode = self.next_repeat_mode()
                self.command_requested.emit("repeat", self.repeat_mode)

            self.pressed_btn = None
            self.is_dragging_bar = False
            self._drag_pos = QPoint()
            self.update()
            if was_dragging_window:
                self._on_window_drag_finished()

    def _seek_to_x(self, x_widget: float):
        bar_start = 136.0 * self.scale
        bar_width = 478.0 * self.scale
        ratio = max(0.0, min(1.0, (x_widget - bar_start) / bar_width))
        self.current_time = ratio * self.duration
