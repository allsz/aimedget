import math
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
    render_adaptive_card_background,
    extract_palette_from_image,
    get_default_palette,
)
from app.ui_components.soundwave_visualizer import SoundWaveVisualizer
from app.ui_components.crisp_icons import CrispIconsMixin
from app.widgets.music.skins.base_skin import BaseMusicSkin
from app.widgets.music.skins.track_motion import (
    MORPH, SETTLE, TrackMotionMixin, bump, clamp, ease_in_out, ease_out, smooth, span, spring,
)
from app.core.frame_clock import FrameTimer

# Dimensões nativas do canvas 16:9
CANVAS_W = 960
CANVAS_H = 540
SQUARE_PX = 640   # capa quadrada usada só durante a troca de faixa (os anéis giram/escalam um a um)


class RippleSkin(CrispIconsMixin, TrackMotionMixin, BaseMusicSkin):
    """
    Skin Wide Ripple (inspirada em wide_ripple.html - Circle Cover Widget):
    - 4 círculos concêntricos da capa do álbum expandindo do centro (600px, 810px, 1020px, 1230px no canvas 960x540)
      com escurecimento progressivo (0%, 50%, 72%, 88%) e anéis translúcidos sutis.
    - Pré-renderização bicúbica em alta definição (SmoothTransformation) para nitidez máxima sem custo por frame.
    - Badge superior esquerdo com logo monocromático branco do provedor ou equalizador animado.
    - Tipografia limpa à esquerda (Título + Artista em caixa alta).
    - Botão circular branco flutuante de Play/Pause à direita.
    - Barra inferior integrada: Anterior, Barra de Progresso com marcador vertical, Próximo, Shuffle e Repeat.
    """

    # Anéis concêntricos convertidos de 640x370 (400, 540, 680, 820) para 960x540 (escala 1.5x)
    # Formato: (diâmetro_px, opacidade_sombra_preta_0_255, opacidade_borda_branca_0_255, espessura_borda)
    RIPPLE_RINGS = (
        (1230, 224, 36, 1.5),  # 820 * 1.5 -> shade 0.88, border rgba(255,255,255,0.14)
        (1020, 184, 36, 1.5),  # 680 * 1.5 -> shade 0.72, border rgba(255,255,255,0.14)
        (810, 128, 36, 1.5),   # 540 * 1.5 -> shade 0.50, border rgba(255,255,255,0.14)
        (600, 0, 72, 3.0),     # 400 * 1.5 -> shade 0.00, border 2px rgba(255,255,255,0.28)
    )
    CARD_RADIUS: float = 42.0
    TRACK_MOTION_SKIN = "ripple"
    _fallback_square_pm: QPixmap | None = None

    def __init__(self, scale: float | None = None):
        super().__init__(CANVAS_W, CANVAS_H, scale=scale)

        self.svg_prev = QSvgRenderer(get_vinyl_asset("icon-prev.svg"))
        self.svg_next = QSvgRenderer(get_vinyl_asset("icon-next.svg"))
        self.soundwave = SoundWaveVisualizer()
        self._ripple_pixmap: QPixmap | None = None
        self._ripple_square: QPixmap | None = None
        self._init_track_motion()

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
        self.timer = FrameTimer(self)
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

    @classmethod
    def _prepare_crisp_ripple(cls, img: QImage) -> QPixmap:
        """
        Gera o fundo de ondas concêntricas (Ripple) em alta definição (960x540)
        pré-escalando cada anel circular com SmoothTransformation da CPU.
        """
        w, h = img.width(), img.height()
        # Se vier miniatura 16:9 com barras laterais (comum no YouTube), recorta o quadrado central
        if w > h * 1.18:
            side = h
            x0 = (w - side) // 2
            img = img.copy(x0, 0, side, side)
        elif h > w * 1.18:
            side = w
            y0 = (h - side) // 2
            img = img.copy(0, y0, side, side)

        canvas = QImage(960, 540, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(QColor("#0b0b0d"))

        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        cx, cy = 480.0, 270.0

        for diameter, shade_alpha, border_alpha, border_w in cls.RIPPLE_RINGS:
            scaled = img.scaled(
                diameter,
                diameter,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sw, sh = scaled.width(), scaled.height()
            sx = max(0, (sw - diameter) // 2)
            sy = max(0, (sh - diameter) // 2)

            ring_rect = QRectF(cx - diameter / 2.0, cy - diameter / 2.0, diameter, diameter)

            p.save()
            clip = QPainterPath()
            clip.addEllipse(ring_rect)
            p.setClipPath(clip)

            p.drawImage(ring_rect, scaled, QRectF(sx, sy, diameter, diameter))

            if shade_alpha > 0:
                p.fillRect(QRectF(0, 0, 960, 540), QColor(0, 0, 0, shade_alpha))
            p.restore()

            # Borda circular translúcida de cada onda
            p.setPen(QPen(QColor(255, 255, 255, border_alpha), border_w))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring_rect)

        p.end()
        return QPixmap.fromImage(canvas)

    @staticmethod
    def _prepare_square(img: QImage) -> QPixmap:
        """A capa recortada no quadrado central e pré-escalada uma vez: fonte dos anéis durante a troca de faixa."""
        w, h = img.width(), img.height()
        side = min(w, h)
        img = img.copy((w - side) // 2, (h - side) // 2, side, side)
        return QPixmap.fromImage(img.scaled(SQUARE_PX, SQUARE_PX, Qt.AspectRatioMode.IgnoreAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))

    @classmethod
    def _fallback_square(cls) -> QPixmap:
        """Sem capa: o fundo adaptativo padrão no lugar dela (feito uma vez)."""
        if cls._fallback_square_pm is None:
            pm = QPixmap(SQUARE_PX, SQUARE_PX)
            pm.fill(QColor("#0b0b0d"))
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            render_adaptive_card_background(p, QRectF(0, 0, SQUARE_PX, SQUARE_PX), get_default_palette())
            p.end()
            cls._fallback_square_pm = pm
        return cls._fallback_square_pm

    def _update_and_cache_cover(self, thumb_bytes: bytes) -> bool:
        if thumb_bytes and thumb_bytes != self._last_thumb_bytes:
            self._last_thumb_bytes = thumb_bytes
            img = QImage.fromData(thumb_bytes)
            if not img.isNull():
                self.album_pixmap = QPixmap.fromImage(img)
                self._ripple_pixmap = self._prepare_crisp_ripple(img)
                self._ripple_square = self._prepare_square(img)
                self.target_palette = extract_palette_from_image(img)
                self._note_cover_for_track()
                return True
        elif not thumb_bytes and self._default_cover_due():
            if self._last_thumb_bytes:
                self._last_thumb_bytes = b""
                self.album_pixmap = None
                self._ripple_pixmap = None
                self._ripple_square = None
                self.target_palette = get_default_palette()
                return True
        return False

    def _motion_covers(self) -> dict:
        return {"square": self._ripple_square}

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
        if now >= self._ignore_external_state_until:
            if is_playing != self.is_playing:
                self.is_playing = is_playing
                changed = True

        # Faixa nova sem duração (o player ainda não mandou a dela): zera em vez de herdar a da faixa anterior
        if dur > 0 or track_changed:
            self.duration = dur

        if self._sync_playback_position(pos, dur, track_changed, now):
            changed = True

        self._motion_after_update(pre, track_changed, cover_changed)
        if changed:
            self.update()

    # --- Troca de faixa animada (protótipo: mockups/music-track-change.html, aba Echos) ---

    def _draw_ring(self, painter: QPainter, square: QPixmap, i: int, sc: float = 1.0, rot: float = 0.0,
                   alpha: float = 1.0, grow: float | None = None, shrink: float | None = None, isc: float = 1.0,
                   border: bool = True):
        """
        Um anel (i=0 o de fora, 3 o do meio) desenhado da capa quadrada: `sc` escala o anel inteiro, `rot` (rad) gira
        a capa dentro dele, `grow`/`shrink` revelam só um disco/anel a partir do centro/da borda e `isc` escala a capa
        dentro do círculo.
        """
        diameter, shade_alpha, border_alpha, border_w = self.RIPPLE_RINGS[i]
        r_full = diameter / 2.0
        painter.save()
        painter.translate(480.0, 270.0)
        if sc != 1.0:
            painter.scale(sc, sc)
        path = QPainterPath()
        if shrink is not None:
            path.addEllipse(QPointF(0.0, 0.0), r_full, r_full)
            hole = QPainterPath()
            r_in = max(0.0, r_full * (1.0 - shrink))
            hole.addEllipse(QPointF(0.0, 0.0), r_in, r_in)
            path = path.subtracted(hole)
        else:
            r = max(0.01, r_full * (1.0 if grow is None else grow))
            path.addEllipse(QPointF(0.0, 0.0), r, r)
        painter.save()
        painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
        painter.setOpacity(painter.opacity() * alpha)
        if rot:
            painter.rotate(math.degrees(rot))
        if isc != 1.0:
            painter.scale(isc, isc)
        painter.drawPixmap(QRectF(-r_full, -r_full, diameter, diameter), square, QRectF(square.rect()))
        if shade_alpha > 0:
            painter.fillRect(QRectF(-2 * r_full, -2 * r_full, 4 * r_full, 4 * r_full), QColor(0, 0, 0, shade_alpha))
        painter.restore()
        if border:
            painter.setPen(QPen(QColor(255, 255, 255, int(border_alpha * alpha)), border_w))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(0.0, 0.0), r_full, r_full)
        painter.restore()

    def _draw_wavefront(self, painter: QPainter, radius: float, sc: float, alpha: float):
        painter.save()
        painter.translate(480.0, 270.0)
        painter.scale(sc, sc)
        painter.setPen(QPen(QColor(255, 255, 255, int(255 * alpha)), 3.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0.0, 0.0), max(0.1, radius), max(0.1, radius))
        painter.restore()

    def _draw_motion_rings(self, painter: QPainter, card_rect: QRectF):
        """Os anéis durante a troca: capa antiga embaixo, a nova entra pelo efeito escolhido."""
        m = self._motion
        p, d, effect = m.p, m.direction, m.effect
        old = m.frm.covers.get("square") or self._fallback_square()
        new = self._ripple_square or self._fallback_square()
        painter.fillRect(card_rect, QColor("#0b0b0d"))
        for i in range(4):
            depth = 3 - i                     # 0 = anel do meio, 3 = o de fora
            k = depth if d > 0 else i         # ordem da onda: próxima de dentro para fora, anterior de fora para dentro
            if effect == "ripple":
                sc = 1.0 + 0.03 * bump(span(p, 0.0, 0.5)) if i == 3 else 1.0
                self._draw_ring(painter, old, i, sc=sc)
                q = clamp(spring(span(p, k * 0.07, k * 0.07 + 0.68), MORPH))
                if q > 0.001:
                    if d > 0:
                        self._draw_ring(painter, new, i, sc=sc, grow=q, border=False)
                    else:
                        self._draw_ring(painter, new, i, sc=sc, shrink=q, border=False)
                    if q < 0.995:
                        r_full = self.RIPPLE_RINGS[i][0] / 2.0
                        self._draw_wavefront(painter, r_full * q if d > 0 else r_full * (1.0 - q), sc, 0.6 * (1.0 - q))
            elif effect == "shock":
                q = span(p, k * 0.07, 1.0)
                amp = 0.05 + 0.025 * depth
                sc = 1.0 - amp * math.exp(-4.2 * q) * math.sin(2.0 * math.pi * 1.3 * q)
                self._draw_ring(painter, old, i, sc=sc)
                self._draw_ring(painter, new, i, sc=sc, alpha=smooth(span(q, 0.06, 0.2)), border=False)
            elif effect == "depth":
                q = span(p, k * 0.08, k * 0.08 + 0.62)
                self._draw_ring(painter, old, i)
                self._draw_ring(painter, new, i, alpha=ease_out(span(q, 0.0, 0.5)),
                                isc=1.16 - 0.16 * spring(q, SETTLE), border=False)
            else:   # "spin": o do meio dá uma volta e troca no meio do giro; os de fora balançam ao contrário
                if i == 3:
                    rot = d * 2.0 * math.pi * ease_in_out(p)
                    sw = smooth(span(p, 0.34, 0.52))
                    sc = 1.0 - 0.05 * bump(p)
                else:
                    rot = -d * 0.12 * depth * bump(span(p, k * 0.05, 1.0))
                    sw = smooth(span(p, 0.34 + k * 0.04, 0.52 + k * 0.04))
                    sc = 1.0
                self._draw_ring(painter, old, i, sc=sc, rot=rot)
                self._draw_ring(painter, new, i, sc=sc, rot=rot, alpha=sw, border=False)

    def _draw_ripple_background(self, painter: QPainter, card_rect: QRectF):
        """
        Renderiza os 4 círculos concêntricos (Ripple) e aplica o gradiente escuro inferior
        fiel ao wide_ripple.html: linear-gradient(to top, rgba(0,0,0,.85) 0%, rgba(0,0,0,.35) 38%, transparent 60%).
        """
        if self._motion.busy:
            self._draw_motion_rings(painter, card_rect)
        elif self._ripple_pixmap is not None and not self._ripple_pixmap.isNull():
            painter.drawPixmap(
                card_rect,
                self._ripple_pixmap,
                QRectF(0, 0, self._ripple_pixmap.width(), self._ripple_pixmap.height()),
            )
        else:
            # Fallback com paleta adaptativa + anéis concêntricos estilizados quando não há capa
            render_adaptive_card_background(painter, card_rect, self.current_palette)
            cx, cy = card_rect.center().x(), card_rect.center().y()
            for diameter, shade_alpha, border_alpha, border_w in self.RIPPLE_RINGS:
                ring_rect = QRectF(cx - diameter / 2.0, cy - diameter / 2.0, diameter, diameter)
                if shade_alpha > 0:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(0, 0, 0, int(shade_alpha * 0.45)))
                    painter.drawEllipse(ring_rect)
                painter.setPen(QPen(QColor(255, 255, 255, border_alpha), border_w))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(ring_rect)

        # Vinheta lateral esquerda suave para leitura perfeita do título sobre o círculo central
        c_dark = QColor(0, 0, 0, 115)
        c_trans = QColor(0, 0, 0, 0)
        left_grad = QLinearGradient(0.0, 0.0, 420.0, 0.0)
        left_grad.setColorAt(0.0, c_dark)
        left_grad.setColorAt(1.0, c_trans)
        painter.fillRect(card_rect, left_grad)

        # Gradiente vertical inferior idêntico ao wide_ripple.html:
        # linear-gradient(to top, rgba(0,0,0,.85) 0%, rgba(0,0,0,.35) 38%, transparent 60%)
        bot_grad = QLinearGradient(0.0, card_rect.height(), 0.0, 0.0)
        bot_grad.setColorAt(0.00, QColor(0, 0, 0, 217))
        bot_grad.setColorAt(0.38, QColor(0, 0, 0, 89))
        bot_grad.setColorAt(0.60, QColor(0, 0, 0, 0))
        bot_grad.setColorAt(1.00, QColor(0, 0, 0, 0))
        painter.fillRect(card_rect, bot_grad)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.translate(self.art_margin, self.art_margin)   # o cartão começa depois da margem da janela
        painter.scale(self.scale, self.scale)

        # --- 1. Card Arredondado (960x540, radius 42 = 28px * 1.5) ---
        card_rect = QRectF(0, 0, 960, 540)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(card_rect, 42, 42)
        painter.setClipPath(clip_path)

        self._draw_ripple_background(painter, card_rect)

        # Borda interna sutil de acabamento
        painter.setPen(QPen(QColor(255, 255, 255, 28), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, 958, 538), 41, 41)

        # --- 2. Badge Superior Esquerdo: Logo Monocromático ou Onda Sonora Animada ---
        logo_x, logo_y, logo_s = 56.0, 52.0, 44.0
        if self.provider in self.provider_renderers:
            self.provider_renderers[self.provider].render(painter, QRectF(logo_x, logo_y, logo_s, logo_s))
        else:
            self.soundwave.render(painter, QRectF(logo_x, logo_y, logo_s, logo_s), QColor(255, 255, 255, 245))

        # --- 3. Título da Música e Artista (Meio-Esquerda, fiel ao wide_ripple.html) ---
        self._paint_track_text(painter)

        # --- 4. Botão Circular Flutuante Play/Pause à Direita ---
        self._draw_floating_play_button(painter, QPointF(842.0, 256.0))

        # --- 5. Barra de Controles Inferior (y_center = 480) ---
        self._draw_bottom_controls(painter, 480.0)

    def _draw_title_line(self, painter: QPainter, text: str, alpha: float, dy: float):
        font_title = get_ui_font(36, QFont.Weight.Bold)
        font_title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 99.0)
        painter.save()
        painter.setOpacity(alpha)
        painter.setFont(font_title)
        painter.setPen(QColor("#FFFFFF"))
        elided = QFontMetrics(font_title).elidedText(text, Qt.TextElideMode.ElideRight, 690)
        painter.drawText(QRectF(56, 336.0 + dy, 690, 46), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        painter.restore()

    def _draw_artist_line(self, painter: QPainter, text: str, alpha: float, dy: float):
        font_artist = get_ui_font(20, QFont.Weight.DemiBold)
        font_artist.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 106.0)
        painter.save()
        painter.setOpacity(alpha)
        painter.setFont(font_artist)
        painter.setPen(QColor(255, 255, 255, 200))
        elided = QFontMetrics(font_artist).elidedText(text.upper(), Qt.TextElideMode.ElideRight, 690)
        painter.drawText(QRectF(56, 384.0 + dy, 690, 30), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        painter.restore()

    def _draw_floating_play_button(self, painter: QPainter, center: QPointF):
        is_hover = (self.hovered_btn == "main")
        is_press = (self.pressed_btn == "main")
        radius = 50.0 if is_press else (56.0 if is_hover else 54.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 102))
        painter.drawEllipse(QPointF(center.x(), center.y() + 8.0), radius, radius)

        circle_color = QColor(255, 255, 255, 250) if is_hover else QColor(255, 255, 255, 235)
        painter.setBrush(circle_color)
        painter.drawEllipse(center, radius, radius)

        icon_color = QColor("#111111")

        if self.is_playing:
            bar_w, bar_h, gap = 6.5, 26.0, 9.0
            painter.setBrush(icon_color)
            painter.drawRoundedRect(QRectF(center.x() - gap / 2.0 - bar_w, center.y() - bar_h / 2.0, bar_w, bar_h), 2.0, 2.0)
            painter.drawRoundedRect(QRectF(center.x() + gap / 2.0, center.y() - bar_h / 2.0, bar_w, bar_h), 2.0, 2.0)
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
        # Atualiza verticalmente os retângulos de clique caso cy seja 480
        s = self.scale
        self.rect_prev = QRectF(42 * s, (cy - 28) * s, 56 * s, 56 * s)
        self.rect_bar_hit = QRectF(132 * s, (cy - 24) * s, 486 * s, 48 * s)
        self.rect_next = QRectF(648 * s, (cy - 28) * s, 56 * s, 56 * s)
        self.rect_shuffle = QRectF(738 * s, (cy - 28) * s, 56 * s, 56 * s)
        self.rect_repeat = QRectF(828 * s, (cy - 28) * s, 56 * s, 56 * s)

        self._draw_skip_icon(painter, QPointF(70.0, cy), is_next=False, hovered=(self.hovered_btn == "prev"))

        bar_x, bar_w, bar_h = 136.0, 478.0, 3.2
        bar_y = cy - bar_h / 2.0
        progress = self._shown_progress(self._live_progress())

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 76))
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 1.6, 1.6)

        fill_w = bar_w * progress
        painter.setBrush(QColor("#FFFFFF"))
        if fill_w > 0:
            painter.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 1.6, 1.6)

        tick_x = bar_x + fill_w
        is_bar_active = (self.hovered_btn == "bar" or self.pressed_btn == "bar")
        tick_w = 4.6 if is_bar_active else 3.2
        tick_h = 20.0 if is_bar_active else 15.0
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
            pos = self.card_pos(event)   # coordenadas do cartão (sem a margem da janela)
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

        pos = self.card_pos(event)   # coordenadas do cartão (sem a margem da janela)
        if (event.buttons() & Qt.MouseButton.LeftButton) and self.pressed_btn == "bar":
            self._seek_to_x(pos.x())
            self.update()
            return

        if (event.buttons() & Qt.MouseButton.LeftButton) and not self._drag_pos.isNull():
            self._drag_window_to(event.globalPosition().toPoint() - self._drag_pos)
            return

        if self.handle_resize_hover(event.position()):
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
            pos = self.card_pos(event)   # coordenadas do cartão (sem a margem da janela)
            hit = self._hit_test(pos)

            if self.pressed_btn == "main" and hit == "main":
                self.is_playing = not self.is_playing
                self._ignore_external_state_until = time.perf_counter() + 1.0
                self.command_requested.emit("play" if self.is_playing else "pause", None)
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
