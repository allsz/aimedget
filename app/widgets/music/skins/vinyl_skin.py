import math
import os
import time
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QFont, QFontMetrics, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.core.paths import get_vinyl_asset, get_provider_icon_path
from app.core.typography import get_ui_font
from app.core.colorimetry import (
    lerp_palette,
    palettes_are_close,
    render_adaptive_card_background,
)
from app.ui_components.soundwave_visualizer import SoundWaveVisualizer
from app.ui_components.tactile_button import draw_tactile_physical_button
from app.widgets.music.skins.base_skin import BaseMusicSkin
from app.widgets.music.skins.track_motion import (
    LIFT, MORPH, SETTLE, TrackMotionMixin, bump, clamp, ease_in, ease_in_out, ease_out, lerp, smooth, span, spring,
)
from app.core.frame_clock import FrameTimer

# Dimensões nativas do canvas 16:9
CANVAS_W = 960
CANVAS_H = 540
DISC_CENTER = QPointF(690.0, 270.0)
DISC_SIZE = 420.0
LABEL_SIZE = DISC_SIZE * 0.36
HOP_ANGLE = 9.0   # "Salto da agulha": o braço sai do sulco até aqui (fora do disco, que começa em ~11,5°)


class VinylMusicSkin(TrackMotionMixin, BaseMusicSkin):
    """
    Skin de Vinil (Wide Vinyl Edition):
    - Toca-discos interativo com giro 33 RPM e scrubbing DJ na barra de progresso.
    - Física e keyframes exclusivos do braço da agulha (tonearm).
    - Listener exclusivo `tonearm_landed`: ao clicar Play no widget, aguarda a agulha pousar no disco antes de tocar.
    - Colorimetria Dinâmica (Passo 4): gradiente adaptativo extraído da capa do álbum com transição suave a 60 FPS.
    """
    tonearm_landed = Signal()
    CARD_RADIUS: float = 40.0
    TRACK_MOTION_SKIN = "vinyl"

    def __init__(self, scale: float | None = None):
        super().__init__(CANVAS_W, CANVAS_H, scale=scale)
        self._init_track_motion()

        # Renderizadores SVG exclusivos da skin de Vinil
        self.svg_cover = QSvgRenderer(get_vinyl_asset("cover-placeholder.svg"))
        self.svg_vinyl = QSvgRenderer(get_vinyl_asset("vinyl.svg"))
        self.svg_glare = QSvgRenderer(get_vinyl_asset("vinyl-glare.svg"))
        self.svg_arm_base = QSvgRenderer(get_vinyl_asset("tonearm-base.svg"))
        self.svg_arm = QSvgRenderer(get_vinyl_asset("tonearm.svg"))
        # SVGs PARADOS rasterizados uma vez no tamanho real em pixels (ver _svg_pixmap): redesenhar o brilho vetorial
        # a 60 FPS custava ~3 ms por quadro. O que gira (disco, agulha, capa) continua vetorial: raster girado borra.
        self._svg_cache: dict[tuple, QPixmap] = {}

        # Visualizador de Onda Sonora Animada (Fallback reativo da imagem do usuário)
        self.soundwave = SoundWaveVisualizer()

        # Renderizadores SVG dos provedores oficiais de streaming
        self.provider_renderers = {}
        for p_name in ("spotify", "youtube_music", "apple_music", "deezer", "tidal", "amazon_music", "soundcloud"):
            p_path = get_provider_icon_path(p_name)
            if os.path.exists(p_path):
                self.provider_renderers[p_name] = QSvgRenderer(p_path)

        self.provider_display_names = {
            "spotify": "Spotify",
            "youtube_music": "YouTube Music",
            "apple_music": "Apple Music",
            "deezer": "Deezer",
            "tidal": "Tidal",
            "amazon_music": "Amazon Music",
            "soundcloud": "SoundCloud",
            "generic": "Áudio",
        }

        # Parâmetros de ângulo da agulha
        self.park_angle = 0.0
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

        # Estado de interação do Mouse e Arraste do Braço (Tonearm)
        self.hovered_btn = None
        self.pressed_btn = None
        self.is_dragging_bar = False
        self.press_bar_x = 0.0
        self.last_scrub_x = 0.0
        self.last_scrub_t = 0.0

        self._arm_drag_started = False
        self._arm_press_pos = QPointF()
        self._arm_mouse_initial_angle = 0.0
        self._arm_drag_initial_angle = self.park_angle
        self._arm_started_on_disc = False

        # Retângulos de colisão para os botões físicos e barra de progresso expandida
        self._update_hitboxes()

        # Loop de física a ~60 FPS
        self.last_tick = time.perf_counter()
        self.timer = FrameTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._on_physics_tick)  # iniciado/pausado pela base (show/hide)

    def _update_hitboxes(self):
        s = self.scale
        btn_y = 398.0
        btn_w = 110.0
        btn_h = 78.0
        gap = 16.0
        self.rect_main = QRectF(52 * s, btn_y * s, btn_w * s, btn_h * s)
        self.rect_prev = QRectF((52 + btn_w + gap) * s, btn_y * s, btn_w * s, btn_h * s)
        self.rect_next = QRectF((52 + (btn_w + gap) * 2) * s, btn_y * s, btn_w * s, btn_h * s)
        self.rect_bar_hit = QRectF(52 * s, 310 * s, 405 * s, 36 * s)

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
        pre = self._motion_snapshot()   # o que está na tela antes desta atualização (troca de faixa animada)
        changed = False
        track_changed = (title != self.title_text or artist != self.artist_text)
        if track_changed:
            self.title_text = title
            self.artist_text = artist
            changed = True

        if provider != self.provider:
            self.provider = provider
            changed = True

        cover_changed = self._update_and_cache_cover(thumb_bytes)
        if cover_changed:
            changed = True

        now = time.perf_counter()
        if not self._pending_play_on_land and now >= self._ignore_external_state_until and self.arm_state != "dragging":
            if is_playing != self.is_playing:
                self._set_playing_state(is_playing)
                changed = True

        # Faixa nova sem duração (o player ainda não mandou a dela): zera em vez de herdar a da faixa anterior
        if dur > 0 or track_changed:
            self.duration = dur

        # Sincronização refinada da barra de progresso (sem saltos entre snapshots antigos e novos)
        can_sync_pos = (
            not self.is_dragging_bar
            and self.pressed_btn not in ("bar", "arm")
            and not self._pending_play_on_land
            and (now - self._last_seek_sent > 1.5)
        )
        if can_sync_pos and (dur > 0 or track_changed):
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

        self._motion_after_update(pre, track_changed, cover_changed)
        if changed:
            self.update()

    # --- Troca de faixa animada (protótipo: mockups/music-track-change.html, aba Vinyl) ---

    def _motion_covers(self) -> dict:
        return {"album": self.album_pixmap}

    def _motion_arm(self):
        """Ângulo do braço antes da troca, só se ele estava tocando no disco (parado ou arrastado, ele não se move)."""
        return self.arm_current_angle if self.arm_state == "on" else None

    def _arm_with_motion(self, target: float) -> float:
        """Braço no disco durante a troca: sai e volta (salto/troca de disco) ou desliza até o começo da faixa nova."""
        m = self._motion
        if not m.busy or m.frm.arm is None:
            return target
        p, a0 = m.p, m.frm.arm
        if m.effect in ("hop", "drop"):
            out = HOP_ANGLE if m.effect == "hop" else self.park_angle
            lift_end, land_at = (0.30, 0.46) if m.effect == "hop" else (0.28, 0.62)
            if p < lift_end:
                return lerp(a0, out, ease_in_out(p / lift_end))
            if p < land_at:
                return out
            return lerp(out, target, spring(span(p, land_at, 1.0), SETTLE))
        return lerp(a0, target, ease_in_out(span(p, 0.1, 0.9)))

    def _spin_multiplier(self) -> float:
        """O disco acelera durante o salto da agulha e o selo crescendo."""
        m = self._motion
        if not m.busy or m.started is None:
            return 1.0
        if m.effect == "hop":
            return 1.0 + 5.0 * bump(span(m.p, 0.1, 0.9))
        if m.effect == "bloom":
            return 1.0 + 2.5 * bump(m.p)
        return 1.0

    def _draw_label(self, painter: QPainter, pm: QPixmap | None, scx: float = 1.0, grow: float = 1.0,
                    alpha: float = 1.0):
        """O selo (capa redonda) no centro do disco, girando com ele. Coordenadas: centro do disco."""
        r = LABEL_SIZE / 2.0
        painter.save()
        if scx != 1.0:
            painter.scale(scx, 1.0)
        painter.rotate(self.vinyl_angle)
        clip = QPainterPath()
        clip.addEllipse(QPointF(0.0, 0.0), max(0.01, r * grow), max(0.01, r * grow))
        painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        painter.setOpacity(painter.opacity() * alpha)
        cover_rect = QRectF(-r, -r, LABEL_SIZE, LABEL_SIZE)
        if pm is not None and not pm.isNull():
            pw, ph = pm.width(), pm.height()
            side = min(pw, ph)
            painter.drawPixmap(cover_rect, pm, QRectF((pw - side) / 2.0, (ph - side) / 2.0, side, side))
        else:
            self.svg_cover.render(painter, cover_rect)
        painter.restore()

    def _draw_disc(self, painter: QPainter, label, sc: float = 1.0, alpha: float = 1.0, dx: float = 0.0,
                   dy: float = 0.0, lift: float = 0.0):
        """Sombra, selo (`label(painter)`, no centro do disco), disco e brilho. `lift` afasta a sombra (disco no ar)."""
        cx, cy = DISC_CENTER.x() + dx, DISC_CENTER.y() + dy
        painter.save()
        painter.setOpacity(painter.opacity() * alpha)
        painter.setBrush(QColor(0, 10, 30, int(130 * (1.0 - 0.45 * lift))))
        painter.setPen(Qt.PenStyle.NoPen)
        shadow_r = (DISC_SIZE - 16.0) / 2.0 * sc
        painter.drawEllipse(QPointF(cx + lift * 12.0, cy + 8.0 + lift * 24.0), shadow_r, shadow_r)
        painter.translate(cx, cy)
        if sc != 1.0:
            painter.scale(sc, sc)
        label(painter)
        disc_rect = QRectF(-DISC_SIZE / 2.0, -DISC_SIZE / 2.0, DISC_SIZE, DISC_SIZE)
        painter.save()
        painter.rotate(self.vinyl_angle)
        # O disco GIRA: fica vetorial (girar um raster borra os sulcos finos). Só o que fica parado usa o cache.
        self.svg_vinyl.render(painter, disc_rect)
        painter.restore()
        self._draw_svg(painter, self.svg_glare, disc_rect)
        painter.restore()

    def _paint_discs(self, painter: QPainter):
        m = self._motion
        new = self.album_pixmap
        if not m.busy:
            self._draw_disc(painter, lambda pa: self._draw_label(pa, new))
            return
        p, d, effect = m.p, m.direction, m.effect
        old = m.frm.covers.get("album")
        if effect == "drop":
            # Como trocar o disco: o antigo sobe e some, o novo cai no prato (mola LIFT)
            old_k, new_k = span(p, 0.10, 0.50), span(p, 0.36, 0.84)
            if old_k < 1.0:
                self._draw_disc(painter, lambda pa: self._draw_label(pa, old), sc=1.0 + 0.12 * ease_in(old_k),
                                alpha=1.0 - ease_in(old_k), dx=-d * 40.0 * ease_out(old_k), dy=-30.0 * ease_out(old_k),
                                lift=ease_out(old_k))
            if new_k > 0.0:
                s = spring(new_k, LIFT)
                self._draw_disc(painter, lambda pa: self._draw_label(pa, new), sc=1.0 + 0.14 * (1.0 - s),
                                alpha=smooth(span(new_k, 0.0, 0.4)), dx=d * 40.0 * (1.0 - s), dy=-34.0 * (1.0 - s),
                                lift=clamp(1.0 - s))
        elif effect == "flip":
            # Só o selo vira, como uma moeda, com uma leve subida
            phi = math.pi * spring(p, MORPH)
            scx = max(0.02, abs(math.cos(phi)))
            pm = new if phi > math.pi / 2.0 else old

            def flip_label(pa):
                pa.setPen(Qt.PenStyle.NoPen)
                pa.setBrush(QColor("#0d0d10"))
                pa.drawEllipse(QPointF(0.0, 0.0), LABEL_SIZE / 2.0, LABEL_SIZE / 2.0)
                self._draw_label(pa, pm, scx=scx)
            self._draw_disc(painter, flip_label, sc=1.0 + 0.02 * bump(p))
        elif effect == "bloom":
            # O selo novo cresce do pino e manda um anel pelos sulcos
            q = clamp(spring(span(p, 0.0, 0.8), MORPH))

            def bloom_label(pa):
                self._draw_label(pa, old)
                if q > 0.001:
                    self._draw_label(pa, new, grow=q)
            self._draw_disc(painter, bloom_label)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for delay, strength in ((0.0, 1.0), (0.12, 0.6)):
                u = span(p, delay, 0.8 + delay * 0.5)
                if 0.0 < u < 1.0:
                    painter.setPen(QPen(QColor(255, 255, 255, int(102 * (1.0 - u) * strength)), 3.0))
                    r = LABEL_SIZE / 2.0 + (DISC_SIZE / 2.0 - LABEL_SIZE / 2.0) * ease_out(u)
                    painter.drawEllipse(DISC_CENTER, r, r)
        else:   # "hop": o selo troca enquanto a agulha está fora e o disco acelera
            swap = smooth(span(p, 0.34, 0.52))

            def hop_label(pa):
                self._draw_label(pa, old)
                self._draw_label(pa, new, alpha=swap)
            self._draw_disc(painter, hop_label, sc=1.0 + 0.014 * bump(p))

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

        # --- 0.1 Atualização da Onda Sonora Animada (Fallback) ---
        self.soundwave.update(dt, self.is_playing)
        if self.provider == "generic" and self.is_playing:
            needs_update = True

        if self._track_motion_tick(now):   # troca de faixa animada (track_motion.py)
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

        elif self.arm_state == "landing":
            elapsed = now - self.arm_anim_start
            dur = 0.16
            p = min(1.0, elapsed / dur)
            sub = self._cubic_ease(p)
            self.arm_current_angle = self.arm_anim_from + (target_play - self.arm_anim_from) * sub

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
            self.arm_current_angle = self._arm_with_motion(target_play)

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
                self.vinyl_angle = (self.vinyl_angle + 105.88 * self._spin_multiplier() * dt) % 360.0
                if self.duration > 0:
                    self.current_time = min(self.duration, self.current_time + dt)
                needs_update = True

        if needs_update:
            self.update()

    def _svg_pixmap(self, renderer: QSvgRenderer, w: float, h: float) -> QPixmap:
        """
        O SVG rasterizado no tamanho que ele ocupa na tela (canvas x escala do widget x DPI do monitor). Muda a escala
        ou o monitor, muda o tamanho em pixels e o cache refaz sozinho; o vetor nunca é redesenhado a cada quadro.
        """
        dpr = self.devicePixelRatioF() or 1.0
        pw = max(1, int(round(w * self.scale * dpr)))
        ph = max(1, int(round(h * self.scale * dpr)))
        key = (id(renderer), pw, ph)
        pm = self._svg_cache.get(key)
        if pm is None:
            if len(self._svg_cache) > 24:   # trocas de escala/monitor deixam tamanhos velhos para trás
                self._svg_cache.clear()
            pm = QPixmap(pw, ph)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            renderer.render(p, QRectF(0, 0, pw, ph))
            p.end()
            self._svg_cache[key] = pm
        return pm

    def _draw_svg(self, painter: QPainter, renderer: QSvgRenderer, rect: QRectF):
        """Desenha o SVG em `rect` (coordenadas do canvas, mesma semântica de QSvgRenderer.render) usando o cache."""
        pm = self._svg_pixmap(renderer, rect.width(), rect.height())
        painter.drawPixmap(rect, pm, QRectF(0, 0, pm.width(), pm.height()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.translate(self.art_margin, self.art_margin)   # o cartão começa depois da margem da janela
        painter.scale(self.scale, self.scale)

        # --- 1. Card Arredondado (960x540, radius 40) com Colorimetria Dinâmica (Passo 4) ---
        card_rect = QRectF(0, 0, 960, 540)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(card_rect, 40, 40)
        painter.setClipPath(clip_path)

        render_adaptive_card_background(painter, card_rect, self.current_palette)

        painter.setPen(QPen(QColor(255, 255, 255, 26), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, 958, 538), 39, 39)

        # --- 2. Logo Monocromático Branco do Provedor ou Onda Sonora Animada ---
        logo_x = 52.0
        logo_y = 52.0
        logo_s = 44.0

        if self.provider in self.provider_renderers:
            # Provedor oficial reconhecido: logotipo monocromático branco
            icon_rect = QRectF(logo_x, logo_y, logo_s, logo_s)
            self._draw_svg(painter, self.provider_renderers[self.provider], icon_rect)
        else:
            # Player genérico/não reconhecido: onda sonora com 7 barras animadas
            wave_rect = QRectF(logo_x, logo_y, logo_s, logo_s)
            self.soundwave.render(painter, wave_rect, QColor(255, 255, 255, 240))

        # --- 3. Tipografia com Espaço Expandido no Meio do Widget (título y=186, artista y=248, 405px) ---
        self._paint_track_text(painter)

        # --- 3. Barra de Progresso Expandida (left=52, top=326, w=405) ---
        progress_ratio = self._shown_progress(self._live_progress())
        bar_x, bar_y, bar_w, bar_h = 52.0, 326.0, 405.0, 6.0

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

        # --- 4. Botões Físicos Estilizados (Fiel aos SVGs e Mockup do Usuário) ---
        btn_y = 398.0
        btn_w = 110.0
        btn_h = 78.0
        gap = 16.0
        r_main = QRectF(52, btn_y, btn_w, btn_h)
        r_prev = QRectF(52 + btn_w + gap, btn_y, btn_w, btn_h)
        r_next = QRectF(52 + (btn_w + gap) * 2, btn_y, btn_w, btn_h)

        main_kind = "pause" if self.is_playing else "play"
        draw_tactile_physical_button(
            painter, r_main, self.current_palette, main_kind,
            is_hovered=(self.hovered_btn == "main"), is_pressed=(self.pressed_btn == "main")
        )
        draw_tactile_physical_button(
            painter, r_prev, self.current_palette, "prev",
            is_hovered=(self.hovered_btn == "prev"), is_pressed=(self.pressed_btn == "prev")
        )
        draw_tactile_physical_button(
            painter, r_next, self.current_palette, "next",
            is_hovered=(self.hovered_btn == "next"), is_pressed=(self.pressed_btn == "next")
        )

        # --- 5. Base Estática da Agulha (Alinhada com o disco mais à direita) ---
        self._draw_svg(painter, self.svg_arm_base, QRectF(821.5, 74.9, 99.5, 148.8))

        # --- 6. O Disco de Vinil (centro 690,270; 420px) com o selo, e o brilho parado por cima ---
        self._paint_discs(painter)

        # --- 7. A Agulha Reduzida em 8% (Pivô alinhado com a base) ---
        arm_left, arm_top, arm_w, arm_h = 800.2, 70.0, 158.6, 399.3
        origin_x, origin_y = 67.34, 57.04

        painter.save()
        painter.translate(arm_left + origin_x, arm_top + origin_y)
        painter.rotate(self.arm_current_angle)
        self.svg_arm.render(painter, QRectF(-origin_x, -origin_y, arm_w, arm_h))   # gira: vetorial (é barato)
        painter.restore()

        self.paint_resize_grip(painter)

    def _draw_title_line(self, painter: QPainter, text: str, alpha: float, dy: float):
        font_title = get_ui_font(44, QFont.Weight.Bold)
        font_title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.0)
        painter.save()
        painter.setOpacity(alpha)
        painter.setFont(font_title)
        painter.setPen(QColor("#FFFFFF"))
        elided = QFontMetrics(font_title).elidedText(text, Qt.TextElideMode.ElideRight, 405)
        painter.drawText(QRectF(52, 186.0 + dy, 405, 54), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        painter.restore()

    def _draw_artist_line(self, painter: QPainter, text: str, alpha: float, dy: float):
        font_artist = get_ui_font(24, QFont.Weight.Medium)
        painter.save()
        painter.setOpacity(alpha)
        painter.setFont(font_artist)
        painter.setPen(QColor(255, 255, 255, 175))
        elided = QFontMetrics(font_artist).elidedText(text, Qt.TextElideMode.ElideRight, 405)
        painter.drawText(QRectF(52, 248.0 + dy, 405, 34), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        painter.restore()

    def _is_pos_on_arm(self, pos) -> bool:
        """Verifica se o ponto (em coordenadas do widget) colide com a geometria do tonearm."""
        cx = pos.x() / self.scale
        cy = pos.y() / self.scale
        dx = cx - 857.54
        dy = cy - 127.04

        rad = math.radians(-self.arm_current_angle)
        lx = dx * math.cos(rad) - dy * math.sin(rad)
        ly = dx * math.sin(rad) + dy * math.cos(rad)

        return (-45.0 <= lx <= 65.0) and (-45.0 <= ly <= 390.0)

    def _hit_test(self, pos):
        if self._is_pos_on_arm(pos):
            return "arm"
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
        if self.handle_resize_press(event):
            return

        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.card_pos(event)   # coordenadas do cartão (sem a margem da janela)
            hit = self._hit_test(pos)

            if hit == "arm":
                self.pressed_btn = "arm"
                self._arm_press_pos = pos
                self._arm_drag_started = False

                cx = pos.x() / self.scale
                cy = pos.y() / self.scale
                self._arm_mouse_initial_angle = math.degrees(math.atan2(cy - 127.04, cx - 857.54))
                self._arm_drag_initial_angle = self.arm_current_angle

                # Detecta se a agulha estava sobre o disco de vinil
                arm_on_disc = (self.arm_current_angle >= 11.5 or self.is_playing or self.arm_state in ("on", "in"))
                self._arm_started_on_disc = arm_on_disc

                if arm_on_disc:
                    # Pausa imediata da reprodução
                    self.is_playing = False
                    self._pending_play_on_land = False
                    self._ignore_external_state_until = time.perf_counter() + 1.2
                    self.command_requested.emit("pause", None)

                self.arm_state = "dragging"
                self.update()
            elif hit == "bar":
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
        if self.handle_resize_move(event):
            return

        pos = self.card_pos(event)   # coordenadas do cartão (sem a margem da janela)

        # Arraste físico do Braço do Toca-Discos
        if (event.buttons() & Qt.MouseButton.LeftButton) and self.pressed_btn == "arm":
            cx = pos.x() / self.scale
            cy = pos.y() / self.scale
            dx = cx - 857.54
            dy = cy - 127.04

            dist = (pos - self._arm_press_pos).manhattanLength()
            if dist > 3.0:
                self._arm_drag_started = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)

            if self._arm_drag_started:
                current_mouse_angle = math.degrees(math.atan2(dy, dx))
                delta = current_mouse_angle - self._arm_mouse_initial_angle
                target_angle = self._arm_drag_initial_angle + delta
                # Limite mecânico do braço: descanso (-1.5°) a sulco interno máximo (24.0°)
                self.arm_current_angle = max(-1.5, min(24.0, target_angle))
                self.arm_state = "dragging"
                self.update()
            return

        # Arraste da barra de progresso (DJ Scrubbing)
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

        # Movimentação da janela na área de trabalho
        if (event.buttons() & Qt.MouseButton.LeftButton) and not self._drag_pos.isNull():
            self._drag_window_to(event.globalPosition().toPoint() - self._drag_pos)
            return

        # Atualização dinâmica de hover e cursores
        if self.handle_resize_hover(event.position()):
            return

        hit = self._hit_test(pos)
        if hit != self.hovered_btn:
            self.hovered_btn = hit
            if hit == "arm":
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif hit:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        if self.handle_resize_release(event):
            return

        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging_window = not self._drag_pos.isNull()
            pos = self.card_pos(event)   # coordenadas do cartão (sem a margem da janela)
            hit = self._hit_test(pos)

            if self.pressed_btn == "arm":
                if not self._arm_drag_started:
                    # Usuário apenas clicou no braço sem arrastar
                    if self._arm_started_on_disc:
                        # Estava no disco: o som de scratch e o pause já ocorreram no press.
                        # O braço agora sai sozinho até a posição de descanso
                        self.arm_anim_start = time.perf_counter()
                        self.arm_anim_from = self.arm_current_angle
                        self.arm_state = "out"
                    else:
                        # Estava em descanso: anima sozinho até o disco e toca ao aterrissar
                        self._set_playing_state(True)
                        self._pending_play_on_land = True
                else:
                    # Usuário arrastou o braço
                    if self.arm_current_angle >= 11.5:
                        # Soltou sobre o disco de vinil:
                        # 1. Ajusta o seek correspondente ao ponto onde a agulha pousou
                        if self.duration > 0:
                            progress = max(0.0, min(1.0, (self.arm_current_angle - self.play_angle) / self.drift_max))
                            self.current_time = progress * self.duration
                            self._last_seek_sent = time.perf_counter()
                            self.command_requested.emit("seek", self.current_time)

                        # 2. Pouso suave (landing) com som característico e retomada do áudio
                        self.arm_anim_start = time.perf_counter()
                        self.arm_anim_from = self.arm_current_angle
                        self.arm_state = "landing"
                        self._pending_play_on_land = True
                        self.is_playing = True
                    else:
                        # Soltou fora do disco / próximo da base: recolhe sozinho para descanso
                        self.arm_anim_start = time.perf_counter()
                        self.arm_anim_from = self.arm_current_angle
                        self.arm_state = "out"
                        self.is_playing = False
                        self._pending_play_on_land = False

                self.pressed_btn = None
                self._arm_drag_started = False
                self.setCursor(Qt.CursorShape.OpenHandCursor if self._is_pos_on_arm(pos) else Qt.CursorShape.ArrowCursor)
                self.update()

            elif self.pressed_btn == "main" and hit == "main":
                self.toggle_play()
            elif self.pressed_btn == "prev" and hit == "prev":
                self._note_direction(-1)
                self.current_time = 0.0
                self._last_seek_sent = time.perf_counter()
                self.command_requested.emit("prev", None)
            elif self.pressed_btn == "next" and hit == "next":
                self._note_direction(1)
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
            if was_dragging_window:
                self._on_window_drag_finished()

    def _seek_to_x(self, x_widget: float):
        bar_start = 52.0 * self.scale
        bar_width = 405.0 * self.scale
        ratio = max(0.0, min(1.0, (x_widget - bar_start) / bar_width))
        self.current_time = ratio * self.duration
        if self.arm_state == "on":
            self.arm_current_angle = self._compute_target_play_angle()
