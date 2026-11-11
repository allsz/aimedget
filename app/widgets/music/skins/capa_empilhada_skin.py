import math
import os
import random
import threading
import time
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QTimer, Signal
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
    QIcon,
    QAction,
)
from PySide6.QtWidgets import QMenu

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.paths import APP_ICON_SVG
from app.core.theme_art import paint_background, paint_stickers
from app.core.widget_theme import art_margin_px
from app.core.typography import get_ui_font
from app.services.media_worker import fetch_stack_extras
from app.widgets.music.skins.base_skin import BaseMusicSkin
from app.widgets.music.skins.stack_palette import PastelStackTheme, get_default_pastel_theme
from app.widgets.music.skins import stack_theme

# Proporção fiel à referência capaEmpilhada.png (615 x 301 -> razão ~2.042:1)
# Canvas 2x Ultra-HD: 980 x 480
CANVAS_W = 980
CANVAS_H = 480


def _lerp_val(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_rect(r1: QRectF, r2: QRectF, t: float) -> QRectF:
    return QRectF(
        _lerp_val(r1.x(), r2.x(), t),
        _lerp_val(r1.y(), r2.y(), t),
        _lerp_val(r1.width(), r2.width(), t),
        _lerp_val(r1.height(), r2.height(), t),
    )


def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - ((1.0 - t) ** 3)


def _lerp_c(c1: QColor, c2: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
        int(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


def lerp_pastel_theme(p1: PastelStackTheme, p2: PastelStackTheme, t: float) -> PastelStackTheme:
    return PastelStackTheme(
        card_bg=_lerp_c(p1.card_bg, p2.card_bg, t),
        title_color=_lerp_c(p1.title_color, p2.title_color, t),
        subtitle_color=_lerp_c(p1.subtitle_color, p2.subtitle_color, t),
        btn_grad_tl=_lerp_c(p1.btn_grad_tl, p2.btn_grad_tl, t),
        btn_grad_br=_lerp_c(p1.btn_grad_br, p2.btn_grad_br, t),
        btn_shadow=_lerp_c(p1.btn_shadow, p2.btn_shadow, t),
        accent_main=_lerp_c(p1.accent_main, p2.accent_main, t),
        accent_muted=_lerp_c(p1.accent_muted, p2.accent_muted, t),
    )


def pastel_themes_are_close(p1: PastelStackTheme, p2: PastelStackTheme, threshold: int = 2) -> bool:
    for attr in ("card_bg", "title_color", "subtitle_color", "btn_grad_tl", "btn_grad_br", "accent_main", "accent_muted"):
        c1: QColor = getattr(p1, attr)
        c2: QColor = getattr(p2, attr)
        if (
            abs(c1.red() - c2.red()) > threshold
            or abs(c1.green() - c2.green()) > threshold
            or abs(c1.blue() - c2.blue()) > threshold
        ):
            return False
    return True


def extract_pastel_theme_from_image(img: QImage | None) -> PastelStackTheme:
    """
    Extrai o matiz dominante da capa do álbum e constrói uma paleta pastel luminosa
    fiel à estética da capaEmpilhada.png.
    """
    if img is None or img.isNull():
        return get_default_pastel_theme()

    small = img.scaled(40, 40, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    small = small.convertToFormat(QImage.Format.Format_ARGB32)

    num_bins = 18
    bin_weights = [0.0] * num_bins
    bin_cos = [0.0] * num_bins
    bin_sin = [0.0] * num_bins
    bin_sat = [0.0] * num_bins

    for y in range(2, small.height() - 2):
        for x in range(2, small.width() - 2):
            c = small.pixelColor(x, y)
            if c.alpha() < 128:
                continue
            hue, sat, val, _ = c.getHsvF()
            if val < 0.12 or sat < 0.10 or hue < 0.0:
                continue
            weight = (sat ** 1.3) * (0.3 + 0.7 * val)
            b = int(hue * num_bins) % num_bins
            angle = hue * 2.0 * math.pi
            bin_weights[b] += weight
            bin_cos[b] += math.cos(angle) * weight
            bin_sin[b] += math.sin(angle) * weight
            bin_sat[b] += sat * weight

    max_w = max(bin_weights) if bin_weights else 0.0
    if max_w < 0.25:
        return get_default_pastel_theme()

    best_bin = bin_weights.index(max_w)
    sum_w, sum_cos, sum_sin, sum_sat = 0.0, 0.0, 0.0, 0.0
    for offset in (-1, 0, 1):
        idx = (best_bin + offset) % num_bins
        factor = 1.0 if offset == 0 else 0.45
        w_b = bin_weights[idx] * factor
        sum_w += w_b
        sum_cos += bin_cos[idx] * factor
        sum_sin += bin_sin[idx] * factor
        sum_sat += bin_sat[idx] * factor

    mean_angle = math.atan2(sum_sin, sum_cos)
    if mean_angle < 0:
        mean_angle += 2.0 * math.pi
    dom_hue = (mean_angle / (2.0 * math.pi)) % 1.0
    dom_sat = (sum_sat / sum_w) if sum_w > 0 else 0.70

    # Ajusta luminância para matizes muito claros (amarelo/verde)
    is_bright_hue = 0.12 <= dom_hue <= 0.45
    accent_val = 0.78 if is_bright_hue else 0.90
    accent_sat = max(0.58, min(0.82, dom_sat * 1.05))

    return PastelStackTheme(
        card_bg=QColor.fromHsvF(dom_hue, 0.095, 0.99),
        title_color=QColor.fromHsvF(dom_hue, 0.45, 0.09),
        subtitle_color=QColor.fromHsvF(dom_hue, max(0.45, accent_sat * 0.68), 0.76 if not is_bright_hue else 0.62),
        btn_grad_tl=QColor.fromHsvF(dom_hue, 0.19, 0.96),
        btn_grad_br=QColor.fromHsvF(dom_hue, 0.05, 1.00),
        btn_shadow=QColor.fromHsvF(dom_hue, 0.35, 0.82, 0.22),
        accent_main=QColor.fromHsvF(dom_hue, accent_sat, accent_val),
        accent_muted=QColor.fromHsvF(dom_hue, max(0.38, accent_sat * 0.62), min(0.92, accent_val * 1.02)),
    )


class CapaEmpilhadaSkin(BaseMusicSkin):
    """
    Skin Capa Empilhada (fiel à referência Referências Visuais/Music Widget/capaEmpilhada.png):
    - Proporção 2.04:1 (980x480 em canvas 2x -> 490x240 no desktop) e curva generosa nas bordas (radius 88 no card).
    - Pilha de 3 capas de álbum à esquerda com cantos curvos (radius 38 na capa principal, 31 na segunda, 26 na terceira).
    - Barra de progresso em cápsula alojada na parte inferior interna da capa principal.
    - Animação 1: Ao trocar de música, a capa da frente dá zoom para frente esmaecendo até desaparecer,
      enquanto a capa de trás avança suavemente para assumir a posição principal.
    - Animação 2: Arrastar (puxar) a capa para a esquerda aciona a transição e pula a música ("next");
      puxar a capa para a direita aciona a transição reversa e volta a música ("prev").
    """
    _extras_ready = Signal(str, str, list)

    # Geometria no canvas 980x480 (1.595x da referência 615x301)
    CARD_RADIUS = 88.0
    COVER1_RECT = QRectF(52.0, 54.0, 372.0, 372.0)
    COVER1_RADIUS = 38.0
    COVER2_RECT = QRectF(132.0, 81.0, 316.0, 318.0)
    COVER2_RADIUS = 31.0
    COVER3_RECT = QRectF(201.0, 102.0, 272.0, 276.0)
    COVER3_RADIUS = 26.0

    # Barra de progresso na parte inferior interna da capa principal
    BAR_X = 86.0
    BAR_Y = 374.0
    BAR_W = 304.0
    BAR_H = 14.0

    # Botões à direita
    PLAY_BTN_RECT = QRectF(518.0, 276.0, 120.0, 120.0)
    PLAY_BTN_RADIUS = 38.0
    REPEAT_CENTER = QPointF(700.0, 336.0)
    SHUFFLE_CENTER = QPointF(794.0, 336.0)

    # Duração da animação de transição de capas (segundos)
    STACK_ANIM_DURATION = 0.48
    REVEAL_DURATION = 0.56
    REVEAL_MODES = ("ripple", "bloom", "sleeve")
    REVEAL_LABELS = {
        "ripple": "Ripple Wave",
        "bloom": "Label Bloom",
        "sleeve": "Sleeve Slide",
    }
    SWIPE_THRESHOLD_CANVAS = 44.0  # ~22px na janela desktop

    def __init__(self, scale: float | None = None):
        super().__init__(CANVAS_W, CANVAS_H, scale=scale)

        self.title_text = "Nenhuma mídia ativa"
        self.artist_text = "O que vamos ouvir hoje?"
        self.album_text = ""
        self._last_track_key = ""
        self._has_received_initial_sync = False

        # Tema visual escolhido no Hub (themes/music/): paleta fixa ou adaptativa, fundo, figurinhas, barra
        self.skin_theme: stack_theme.StackTheme = stack_theme.load_user_theme()
        # Figurinhas que passam da borda pedem uma margem transparente em volta do cartão (janela maior)
        self.art_margin = self._wanted_art_margin()
        self.setFixedSize(*self._window_size())
        # Paleta pastel (adaptativa à capa ou fixa pelo tema) com interpolação a 60 FPS
        self.pastel_theme: PastelStackTheme = self._palette_for(None)
        self.target_pastel_theme: PastelStackTheme = self._palette_for(None)

        # Capas pré-filtradas em alta definição (Principal + fila procedural V2 de capas com vinil central)
        self._proc_seed_counter: int = 1
        self._main_cover_pm: QPixmap = self._build_default_main_cover()
        # _active_front_vinyl_pm guarda exclusivamente o vinil procedural promovido para a 1ª posição (COVER1),
        # garantindo que ele NUNCA seja igual ao vinil da 2ª posição (_procedural_stack[0])!
        self._active_front_vinyl_pm: QPixmap = self._build_procedural_vinyl_cover(101)
        self._fallback_stack2_pm: QPixmap = self._build_procedural_vinyl_cover(305)
        self._fallback_stack3_pm: QPixmap = self._build_procedural_vinyl_cover(712)
        self._procedural_stack: list[QPixmap] = [
            self._fallback_stack2_pm,
            self._fallback_stack3_pm,
        ]
        self._history_covers: list[QPixmap] = []
        self._artist_extra_covers: list[QPixmap] = []
        self._queued_extra_covers: list[QPixmap] | None = None
        self._locked_stack2_pm: QPixmap | None = self._fallback_stack2_pm
        self._locked_stack3_pm: QPixmap | None = self._fallback_stack3_pm
        self._cover_updated_for_current_track: bool = False
        self._stale_track_thumb_bytes: bytes = b""

        self._extras_ready.connect(self._on_extras_loaded)

        # Estado da Animação da Pilha de Capas (Zoom + Fade Out da frente & avanço da capa de trás)
        self._anim_active: bool = False
        self._anim_direction: str = "next"  # "next" (frente dá zoom/some, trás avança) ou "prev" (reverso)
        self._anim_start_time: float = 0.0
        self._anim_progress: float = 0.0
        self._anim_start_dx: float = 0.0
        self._anim_start_t: float = 0.0
        self._anim_outgoing_pm: QPixmap | None = None
        self._anim_cov2_snapshot: QPixmap | None = None
        self._anim_cov3_snapshot: QPixmap | None = None
        self._pending_external_anim: bool = False
        self._pending_external_since: float = 0.0
        self._Pending_outgoing_pm: QPixmap | None = None
        self._last_user_swipe_time: float = 0.0
        self._awaiting_swipe_track_change: bool = False

        # Estado da Animação de Revelação (do vinil procedural "falso" para a capa real)
        saved_mode = config_manager.get_stacked_cover_effect(default="ripple")
        self.reveal_mode: str = saved_mode if saved_mode in self.REVEAL_MODES else "ripple"
        self._reveal_active: bool = False
        self._reveal_start_time: float = 0.0
        self._reveal_progress: float = 0.0
        self._reveal_from_pm: QPixmap | None = None
        self._pending_reveal_real_pm: QPixmap | None = None

        # Estado de Arrasto (Swipe) da Capa Principal com o Mouse
        self._is_dragging_cover: bool = False
        self._cover_drag_start_x: float = 0.0
        self._cover_drag_dx_canvas: float = 0.0

        # Estado de interação geral
        self.hovered_btn = None
        self.pressed_btn = None
        self.is_dragging_bar = False
        self.is_shuffle = False
        self.repeat_mode = 0  # 0: off, 1: repeat all, 2: repeat one
        self._last_seek_sent = 0.0
        self._ignore_external_state_until = 0.0

        # Retângulos de clique proporcionais à escala atual
        self._update_hitboxes()

        # Loop a ~60 FPS
        self.last_tick = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._on_tick)  # iniciado/pausado pela base (show/hide)

    # --- Tema visual ---

    def _palette_for(self, img: QImage | None) -> PastelStackTheme:
        """Paleta fixa do tema; sem ela, a paleta tirada da capa (ou a coral original, sem capa)."""
        if self.skin_theme.palette is not None:
            return lerp_pastel_theme(self.skin_theme.palette, self.skin_theme.palette, 0.0)   # cópia
        return extract_pastel_theme_from_image(img)

    def apply_preview_media(self, media):
        """
        Miniatura do Hub: visual ORIGINAL da skin (os temas têm a própria galeria, em stack_theme_specs) com a capa
        direto na frente da pilha, sem a animação de revelação do player.
        """
        self.skin_theme = stack_theme.DEFAULT_THEME
        # A margem transparente nasceu do tema do usuário; com o tema padrão ela some. Sem recalcular, a janela
        # continua maior que o natural_size (490x240) e o cartão sai descentralizado no palco do Hub.
        self._apply_art_margin()
        self.album_pixmap = QPixmap.fromImage(media.cover)
        self._main_cover_pm = self._prepare_square_cover(media.cover, 380)
        self.pastel_theme = self.target_pastel_theme = self._palette_for(media.backdrop)

    def reload_skin_theme(self):
        """Relê o tema escolhido (barato se nada mudou). Chamado ao mostrar o widget e quando o Hub aplica um tema."""
        theme = stack_theme.load_user_theme()
        if theme is self.skin_theme:
            return
        self.skin_theme = theme
        img = self.album_pixmap.toImage() if self.album_pixmap is not None else None
        self.target_pastel_theme = self._palette_for(img)
        self._apply_art_margin()   # figurinhas novas podem pedir (ou dispensar) a margem em volta do cartão
        self.update()

    def showEvent(self, event):
        self.reload_skin_theme()
        super().showEvent(event)

    def _paint_theme_art(self, painter: QPainter, above: bool):
        """Fundo (só na camada de baixo) e figurinhas do tema, em px do widget no tamanho padrão (490 x 240)."""
        art = self.skin_theme
        if not art.stickers and (above or art.background is None):
            return
        painter.save()
        painter.scale(CANVAS_W / stack_theme.CARD_SIZE[0], CANVAS_H / stack_theme.CARD_SIZE[1])
        rect = QRectF(0.0, 0.0, *stack_theme.CARD_SIZE)
        if not above and art.background is not None:
            paint_background(painter, rect, art.background, self.CARD_RADIUS * stack_theme.CARD_SIZE[0] / CANVAS_W)
        if not above:
            painter.setClipping(False)   # figurinhas "below" podem passar da borda do cartão (o restore() religa o recorte)
        paint_stickers(painter, rect, art.stickers, above=above)
        painter.restore()

    def _wanted_art_margin(self) -> int:
        """Margem transparente (px de tela) para as figurinhas do tema que passam da borda do cartão."""
        card_w, card_h = stack_theme.CARD_SIZE
        return art_margin_px(self.skin_theme.stickers, card_w, card_h, k=self.canvas_w * self.scale / card_w)

    def _update_hitboxes(self):
        s = self.scale
        m = float(self.art_margin)   # as coordenadas do cartão começam depois da margem transparente
        self.rect_bar_hit = QRectF(m + (self.BAR_X - 10) * s, m + (self.BAR_Y - 16) * s, (self.BAR_W + 20) * s, 46 * s)
        self.rect_cover_drag = QRectF(
            m + self.COVER1_RECT.x() * s,
            m + self.COVER1_RECT.y() * s,
            (self.COVER3_RECT.right() - self.COVER1_RECT.x()) * s,
            self.COVER1_RECT.height() * s,
        )
        self.rect_main = QRectF(
            m + self.PLAY_BTN_RECT.x() * s,
            m + self.PLAY_BTN_RECT.y() * s,
            self.PLAY_BTN_RECT.width() * s,
            self.PLAY_BTN_RECT.height() * s,
        )
        self.rect_repeat = QRectF(m + (self.REPEAT_CENTER.x() - 32) * s, m + (self.REPEAT_CENTER.y() - 32) * s, 64 * s, 64 * s)
        self.rect_shuffle = QRectF(m + (self.SHUFFLE_CENTER.x() - 32) * s, m + (self.SHUFFLE_CENTER.y() - 32) * s, 64 * s, 64 * s)

    @staticmethod
    def _prepare_square_cover(img: QImage, size: int = 380) -> QPixmap:
        """Recorta em quadrado central (caso 16:9) e pré-escala com SmoothTransformation para nitidez máxima."""
        w, h = img.width(), img.height()
        if w > h * 1.08:
            side = h
            img = img.copy((w - side) // 2, 0, side, side)
        elif h > w * 1.08:
            side = w
            img = img.copy(0, (h - side) // 2, side, side)

        scaled = img.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QPixmap.fromImage(scaled)

    @staticmethod
    def _build_default_main_cover() -> QPixmap:
        """Gera a capa padrão do Aimedget para a skin de Capa Empilhada."""
        from PySide6.QtSvg import QSvgRenderer

        size = 380
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("#0e0e11"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Sulcos sutis concêntricos em tom âmbar translúcido
        cx, cy = size * 0.5, size * 0.5
        for r, alpha in [(290, 15), (240, 22), (190, 30), (140, 40)]:
            p.setPen(QColor(255, 161, 61, alpha))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r / 2.0, r / 2.0)

        # Logotipo âmbar oficial do Aimedget no centro
        if os.path.exists(APP_ICON_SVG):
            renderer = QSvgRenderer(APP_ICON_SVG)
            icon_w = size * 0.58
            icon_h = size * 0.58
            icon_rect = QRectF((size - icon_w) / 2.0, (size - icon_h) / 2.0, icon_w, icon_h)
            renderer.render(p, icon_rect)

        p.end()
        return QPixmap.fromImage(img)

    @staticmethod
    def _build_procedural_vinyl_cover(seed: int, size: int = 380) -> QPixmap:
        """
        Gera uma capa procedural estilo Mockup V2:
        - Manga (sleeve) com gradiente diagonal, duotone ou monocromático vibrante/variado.
        - Lombada sutil e detalhes gráficos minimalistas na borda direita exposta na pilha.
        - Disco de vinil centralizado com sulcos, sombra e selo colorido combinando com a manga.
        """
        rnd = random.Random(seed)
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg_style = rnd.choice(["gradient_diag", "split", "duotone", "monochrome"])
        h1 = rnd.random()
        s1 = rnd.uniform(0.70, 0.95)
        v1 = rnd.uniform(0.75, 0.95)
        c1 = QColor.fromHsvF(h1, s1, v1)

        h2 = (h1 + rnd.uniform(0.20, 0.40)) % 1.0
        c2 = QColor.fromHsvF(h2, rnd.uniform(0.70, 0.95), rnd.uniform(0.80, 0.98))

        if bg_style == "gradient_diag":
            g = QLinearGradient(0, 0, size, size)
            g.setColorAt(0.0, c1)
            g.setColorAt(1.0, c2)
            p.fillRect(0, 0, size, size, g)
        elif bg_style == "split":
            p.fillRect(0, 0, size, size, c1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c2)
            p.drawRect(int(size * 0.65), 0, int(size * 0.35), size)
        elif bg_style == "duotone":
            g = QLinearGradient(0, 0, 0, size)
            g.setColorAt(0.0, c1)
            g.setColorAt(1.0, c2)
            p.fillRect(0, 0, size, size, g)
        else:
            p.fillRect(0, 0, size, size, c1)

        # Detalhe de lombada e barras gráficas minimalistas na borda direita visível na pilha
        edge_x = int(size * 0.78)
        p.setPen(QPen(QColor(0, 0, 0, 42), 3.0))
        p.drawLine(edge_x, 0, edge_x, size)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 170))
        for y_bar in range(int(size * 0.18), int(size * 0.85), 38):
            bw = rnd.randint(18, 42)
            p.drawRoundedRect(QRectF(edge_x + 8, y_bar, bw, 6), 3, 3)

        # Disco de Vinil centralizado na capa
        disc_r = size * 0.40
        cx, cy = size * 0.48, size * 0.50

        # Sombra do disco
        p.setBrush(QColor(0, 0, 0, 85))
        p.drawEllipse(QPointF(cx + 3, cy + 5), disc_r, disc_r)

        # Corpo preto do vinil e sulcos circulares
        p.setBrush(QColor("#0c0d10"))
        p.drawEllipse(QPointF(cx, cy), disc_r, disc_r)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1.2))
        for r in range(int(disc_r * 0.40), int(disc_r * 0.95), 8):
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Selo central colorido (label) e furo central
        label_r = disc_r * 0.35
        p.setBrush(c2)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), label_r, label_r)

        p.setBrush(QColor("#0c0d10"))
        p.drawEllipse(QPointF(cx, cy), 8, 8)

        p.end()
        return QPixmap.fromImage(img)

    def _next_procedural_cover(self) -> QPixmap:
        """Gera uma nova capa procedural de vinil com semente única para renovar a pilha."""
        self._proc_seed_counter += 1
        seed = 1000 + self._proc_seed_counter * 137
        return self._build_procedural_vinyl_cover(seed)

    def _start_cover_reveal(self, from_proc_pm: QPixmap | None = None):
        """
        Inicia a animação de revelação que transforma o vinil procedural ("falso")
        na capa real do álbum usando o modo escolhido (`ripple`, `bloom` ou `sleeve`).
        Sempre utiliza `_active_front_vinyl_pm` como base, garantindo que a 1ª capa
        jamais duplique o vinil da 2ª posição (`_procedural_stack[0]`) nem use uma capa real antiga.
        """
        base_pm = from_proc_pm if (from_proc_pm is not None and not from_proc_pm.isNull()) else self._active_front_vinyl_pm
        # Garante que a base nunca seja igual à capa real nem igual à 2ª capa da pilha
        stack2_key = self._procedural_stack[0].cacheKey() if self._procedural_stack else 0
        if base_pm.cacheKey() == self._main_cover_pm.cacheKey() or base_pm.cacheKey() == stack2_key:
            base_pm = self._active_front_vinyl_pm
            if base_pm.cacheKey() == stack2_key or base_pm.cacheKey() == self._main_cover_pm.cacheKey():
                self._active_front_vinyl_pm = self._next_procedural_cover()
                base_pm = self._active_front_vinyl_pm

        self._reveal_from_pm = base_pm
        self._reveal_start_time = time.perf_counter()
        self._reveal_progress = 0.0
        self._reveal_active = True
        self.update()

    def set_reveal_mode(self, mode: str, preview: bool = True):
        """Define o modo de transição de revelação ('ripple', 'bloom' ou 'sleeve'), salva nas preferências e exibe prévia imediata."""
        if mode not in self.REVEAL_MODES:
            return
        self.reveal_mode = mode
        config_manager.set_stacked_cover_effect(mode)
        if preview:
            self._start_cover_reveal(from_proc_pm=self._active_front_vinyl_pm)
        else:
            self.update()

    def cycle_reveal_mode(self):
        """Alterna ciclicamente entre as 3 opções de transição (Ripple -> Bloom -> Sleeve)."""
        idx = self.REVEAL_MODES.index(self.reveal_mode) if self.reveal_mode in self.REVEAL_MODES else 0
        next_mode = self.REVEAL_MODES[(idx + 1) % len(self.REVEAL_MODES)]
        self.set_reveal_mode(next_mode, preview=True)

    def _start_stack_transition(
        self,
        direction: str = "next",
        outgoing_pm: QPixmap | None = None,
        start_dx: float = 0.0,
        start_t: float = 0.0,
    ):
        """
        Inicia a animação de transição das capas empilhadas:
        - direction == "next": A capa da frente (`outgoing_pm`) dá zoom para frente e esmaece até sumir,
          enquanto a 2ª capa (vinil procedural `cov2`) avança de `COVER2_RECT` para `COVER1_RECT` e a 3ª (`cov3`) avança para `COVER2_RECT`.
          Ao pousar em `COVER1_RECT`, dispara a revelação (`ripple`, `bloom` ou `sleeve`) para a capa real.
        - direction == "prev": Animação reversa ao puxar para a direita (capa anterior surge da frente
          reduzindo o zoom para `COVER1_RECT`, enquanto a capa atual recua para `COVER2_RECT`).
        """
        cov1, cov2, cov3 = self._get_stack_pixmaps()
        self._anim_outgoing_pm = outgoing_pm if outgoing_pm is not None else cov1
        self._reveal_active = False

        if direction == "next":
            # O vinil procedural que estava em COVER2 (`cov2`) é promovido para ser o vinil da frente (`COVER1`)!
            self._active_front_vinyl_pm = cov2

            if outgoing_pm is None:
                # Swipe do usuário: salva a capa real que estava tocando no histórico e promove `cov2`
                self._history_covers = [
                    pm for pm in self._history_covers if pm.cacheKey() != cov1.cacheKey()
                ]
                self._history_covers.append(cov1)
                self._history_covers = self._history_covers[-6:]
                self._main_cover_pm = cov2
                self._pending_reveal_real_pm = None
            else:
                # Troca externa: se a capa real nova já chegou em _main_cover_pm, desliza o vinil procedural cov2
                # primeiro até COVER1_RECT e agenda a revelação para o instante em que ele pousar na frente!
                if cov1.cacheKey() != outgoing_pm.cacheKey():
                    self._pending_reveal_real_pm = cov1
                    self._main_cover_pm = cov2
                else:
                    self._pending_reveal_real_pm = None
                    self._main_cover_pm = cov2

            # Avança a fila procedural V2: a 3ª capa (`cov3`) vira a 2ª e um novo vinil procedural entra na 3ª posição!
            new_proc3 = self._next_procedural_cover()
            self._procedural_stack = [cov3, new_proc3]
            self._anim_cov2_snapshot = cov3
            self._anim_cov3_snapshot = new_proc3

        elif direction == "prev":
            self._active_front_vinyl_pm = self._next_procedural_cover()
            if outgoing_pm is None:
                if self._history_covers:
                    prev_cov = self._history_covers.pop()
                    self._main_cover_pm = prev_cov
                else:
                    self._main_cover_pm = self._active_front_vinyl_pm
            # Na volta, a 2ª capa recua para a 3ª e uma capa procedural nova ocupa a 2ª posição
            new_proc2 = self._next_procedural_cover()
            self._procedural_stack = [new_proc2, cov2]
            self._anim_cov2_snapshot = new_proc2
            self._anim_cov3_snapshot = cov2

        # Trava as capas secundárias (2 e 3) para que nunca fiquem iguais à capa 1 nem pisquem
        self._locked_stack2_pm = self._anim_cov2_snapshot
        self._locked_stack3_pm = self._anim_cov3_snapshot

        self._anim_direction = direction
        self._anim_start_dx = start_dx
        self._anim_start_t = max(0.0, min(0.55, start_t))
        self._anim_start_time = time.perf_counter()
        self._anim_progress = 0.0
        self._anim_active = True
        self._pending_external_anim = False
        self.update()

    def _update_and_cache_cover(self, thumb_bytes: bytes) -> bool:
        now = time.perf_counter()
        # Enquanto aguardamos o player confirmar a nova faixa após um swipe do usuário,
        # ignoramos o thumbnail antigo da faixa anterior para evitar que a capa antiga reapareça!
        if self._awaiting_swipe_track_change and (now - self._last_user_swipe_time < 4.5):
            if not thumb_bytes or thumb_bytes == self._stale_track_thumb_bytes:
                return False

        # Mesmo após o título mudar, ignoramos por até 1.4s se o navegador ainda estiver enviando os bytes da capa anterior
        if (
            not self._cover_updated_for_current_track
            and self._stale_track_thumb_bytes
            and thumb_bytes == self._stale_track_thumb_bytes
            and (now - self._last_user_swipe_time < 2.2)
        ):
            return False

        if thumb_bytes and thumb_bytes != self._last_thumb_bytes:
            self._last_thumb_bytes = thumb_bytes
            img = QImage.fromData(thumb_bytes)
            if not img.isNull():
                old_main_pm = self._main_cover_pm
                was_first_cover_for_track = not self._cover_updated_for_current_track

                if was_first_cover_for_track:
                    if self.album_pixmap is not None and not old_main_pm.isNull():
                        self._history_covers = [
                            pm for pm in self._history_covers if pm.cacheKey() != old_main_pm.cacheKey()
                        ]
                        self._history_covers.insert(0, old_main_pm)
                        self._history_covers = self._history_covers[:4]
                    self._cover_updated_for_current_track = True

                self.album_pixmap = QPixmap.fromImage(img)
                new_real_pm = self._prepare_square_cover(img, 380)
                self.target_pastel_theme = self._palette_for(img)

                if self._pending_external_anim:
                    # Troca externa aguardando a capa: inicia o avanço da pilha e agenda a revelação ao pousar
                    self._main_cover_pm = new_real_pm
                    out_pm = self._Pending_outgoing_pm or old_main_pm
                    self._start_stack_transition(direction="next", outgoing_pm=out_pm, start_dx=0.0)
                elif self._anim_active:
                    # O vinil procedural ainda está deslizando de COVER2 para COVER1:
                    # aguarda ele pousar em COVER1 para disparar a revelação!
                    self._pending_reveal_real_pm = new_real_pm
                else:
                    # Já está na posição frontal (COVER1):
                    self._main_cover_pm = new_real_pm
                    _, c2, c3 = self._compute_pool_pixmaps()
                    self._locked_stack2_pm = c2
                    self._locked_stack3_pm = c3
                    if was_first_cover_for_track or not self._reveal_active:
                        # Sempre revela a partir do vinil procedural da frente (_active_front_vinyl_pm),
                        # e NUNCA de uma capa real anterior ou da 2ª capa da pilha!
                        if was_first_cover_for_track:
                            self._start_cover_reveal(from_proc_pm=self._active_front_vinyl_pm)
                return True
        elif not thumb_bytes and self.title_text == "Nenhuma mídia ativa":
            if self._last_thumb_bytes:
                self._last_thumb_bytes = b""
                self.album_pixmap = None
                self._main_cover_pm = self._build_default_main_cover()
                self._pending_reveal_real_pm = None
                self._reveal_active = False
                self._locked_stack2_pm = None
                self._locked_stack3_pm = None
                self.target_pastel_theme = self._palette_for(None)
                return True
        return False

    def _trigger_extras_fetch(self, title: str, artist: str):
        track_key = f"{title}|{artist}"
        if track_key == self._last_track_key:
            return
        self._last_track_key = track_key

        def _worker():
            album_name, extra_bytes_list = fetch_stack_extras(title, artist)
            self._extras_ready.emit(track_key, album_name, extra_bytes_list)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_extras_loaded(self, track_key: str, album_name: str, extra_bytes_list: list):
        if track_key != self._last_track_key:
            return
        if album_name and album_name != self.album_text:
            self.album_text = album_name
            self.update()

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
        now = time.perf_counter()
        track_changed = (title != self.title_text or artist != self.artist_text)

        if track_changed:
            was_initial = not self._has_received_initial_sync
            self._has_received_initial_sync = True
            self._cover_updated_for_current_track = False
            self._stale_track_thumb_bytes = self._last_thumb_bytes
            # Reseta _last_thumb_bytes para que, mesmo que a próxima música seja do mesmo álbum,
            # a capa real seja revelada sobre o vinil procedural!
            self._last_thumb_bytes = b""
            old_main_pm = self._main_cover_pm

            # Se havia capas extras pré-carregadas na fila, aplica antes da transição começar
            if self._queued_extra_covers is not None:
                self._artist_extra_covers = self._queued_extra_covers
                self._queued_extra_covers = None

            self.title_text = title
            self.artist_text = artist
            # Limpa imediatamente o álbum anterior para não exibir o álbum do artista antigo
            # enquanto o fetch assíncrono busca o novo álbum!
            self.album_text = ""
            if title != "Nenhuma mídia ativa":
                self._trigger_extras_fetch(title, artist)

            # Se a mudança de faixa veio do swipe que o usuário acabou de fazer no card,
            # a pilha já avançou no momento do swipe — não dispara uma 2ª transição duplicada!
            if self._awaiting_swipe_track_change and (now - self._last_user_swipe_time < 5.0):
                self._awaiting_swipe_track_change = False
                self._pending_external_anim = False
            elif not was_initial:
                self._pending_external_anim = True
                self._pending_external_since = now
                self._Pending_outgoing_pm = old_main_pm

            changed = True
        elif not self._has_received_initial_sync:
            self._has_received_initial_sync = True

        if provider != self.provider:
            self.provider = provider
            changed = True

        if self._update_and_cache_cover(thumb_bytes):
            changed = True

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

        # 1. Interpolação suave do tema pastel
        if not pastel_themes_are_close(self.pastel_theme, self.target_pastel_theme):
            self.pastel_theme = lerp_pastel_theme(self.pastel_theme, self.target_pastel_theme, min(1.0, dt * 5.0))
            needs_update = True

        # 2. Se houve troca externa de faixa e a capa demorou > 0.22s para mudar, dispara a animação mesmo assim
        if self._pending_external_anim and (now - self._pending_external_since >= 0.22):
            out_pm = self._Pending_outgoing_pm or self._main_cover_pm
            self._start_stack_transition(direction="next", outgoing_pm=out_pm, start_dx=0.0)
            needs_update = True

        # 3. Progresso da animação de transição de capas (60 FPS)
        if self._anim_active:
            elapsed = now - self._anim_start_time
            self._anim_progress = min(1.0, elapsed / self.STACK_ANIM_DURATION)
            if self._anim_progress >= 1.0:
                self._anim_active = False
                self._anim_outgoing_pm = None
                self._anim_cov2_snapshot = None
                self._anim_cov3_snapshot = None
                # Assim que o vinil procedural pousar em COVER1_RECT, se a capa real já chegou, dispara a revelação!
                if self._pending_reveal_real_pm is not None:
                    self._main_cover_pm = self._pending_reveal_real_pm
                    self._pending_reveal_real_pm = None
                    self._start_cover_reveal(from_proc_pm=self._active_front_vinyl_pm)
            needs_update = True

        # 3b. Progresso da animação de revelação (do vinil procedural para a capa real)
        if self._reveal_active:
            rev_elapsed = now - self._reveal_start_time
            self._reveal_progress = min(1.0, rev_elapsed / self.REVEAL_DURATION)
            if self._reveal_progress >= 1.0:
                self._reveal_active = False
                self._reveal_from_pm = None
            needs_update = True

        # 4. Retorno elástico suave caso o usuário tenha soltado a capa antes do limiar de swipe
        if not self._is_dragging_cover and abs(self._cover_drag_dx_canvas) > 0.5:
            self._cover_drag_dx_canvas *= 0.72
            if abs(self._cover_drag_dx_canvas) <= 0.5:
                self._cover_drag_dx_canvas = 0.0
            needs_update = True

        # 5. Avanço contínuo do tempo da música
        if self.is_playing and not self.is_dragging_bar:
            if self.duration > 0:
                self.current_time = min(self.duration, self.current_time + dt)
            needs_update = True

        if needs_update:
            self.update()

    def _compute_pool_pixmaps(self, outgoing_pm: QPixmap | None = None) -> tuple[QPixmap, QPixmap, QPixmap]:
        """Retorna (capa_principal, capa_procedural_2, capa_procedural_3) garantindo que as 3 capas sejam sempre distintas."""
        while len(self._procedural_stack) < 2:
            self._procedural_stack.append(self._next_procedural_cover())
        main_k = self._main_cover_pm.cacheKey()
        front_v_k = self._active_front_vinyl_pm.cacheKey()
        if self._procedural_stack[0].cacheKey() in (main_k, front_v_k):
            self._procedural_stack[0] = self._next_procedural_cover()
        if (
            self._procedural_stack[1].cacheKey() in (main_k, front_v_k)
            or self._procedural_stack[1].cacheKey() == self._procedural_stack[0].cacheKey()
        ):
            self._procedural_stack[1] = self._next_procedural_cover()
        return self._main_cover_pm, self._procedural_stack[0], self._procedural_stack[1]

    def _get_stack_pixmaps(self) -> tuple[QPixmap, QPixmap, QPixmap]:
        """
        Retorna (capa_principal, capa_empilhada_2, capa_empilhada_3) estáveis:
        - Durante a animação, usa os snapshots congelados no início da transição.
        - Em repouso, mantém as capas 2 e 3 travadas para que nenhuma atualização em background cause piscadas!
        """
        if self._anim_active and self._anim_cov2_snapshot is not None and self._anim_cov3_snapshot is not None:
            return self._main_cover_pm, self._anim_cov2_snapshot, self._anim_cov3_snapshot

        if self._locked_stack2_pm is not None and self._locked_stack3_pm is not None:
            main_k = self._main_cover_pm.cacheKey()
            if self._locked_stack2_pm.cacheKey() != main_k and self._locked_stack3_pm.cacheKey() != main_k:
                return self._main_cover_pm, self._locked_stack2_pm, self._locked_stack3_pm

        c1, c2, c3 = self._compute_pool_pixmaps()
        self._locked_stack2_pm = c2
        self._locked_stack3_pm = c3
        return c1, c2, c3

    @staticmethod
    def _draw_rounded_pixmap(
        painter: QPainter,
        rect: QRectF,
        radius: float,
        pixmap: QPixmap,
        opacity: float = 1.0,
    ):
        """Desenha um QPixmap com recorte de bordas curvas suaves e opacidade configurável."""
        if opacity <= 0.005:
            return
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, opacity)))
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        painter.drawPixmap(rect, pixmap, QRectF(0, 0, pixmap.width(), pixmap.height()))
        painter.restore()

    @staticmethod
    def _scale_rect_centered(rect: QRectF, scale_factor: float, dx: float = 0.0, dy: float = 0.0) -> QRectF:
        cx = rect.center().x() + dx
        cy = rect.center().y() + dy
        w = rect.width() * scale_factor
        h = rect.height() * scale_factor
        return QRectF(cx - w / 2.0, cy - h / 2.0, w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.translate(self.art_margin, self.art_margin)   # o cartão começa depois da margem transparente
        painter.scale(self.scale, self.scale)

        # --- 1. Card Principal com Proporção 2.04:1 (980x480) e Curva de Borda Acentuada (radius=88) ---
        card_rect = QRectF(0, 0, CANVAS_W, CANVAS_H)
        card_clip = QPainterPath()
        card_clip.addRoundedRect(card_rect, self.CARD_RADIUS, self.CARD_RADIUS)
        painter.setClipPath(card_clip)

        painter.fillRect(card_rect, self.pastel_theme.card_bg)
        self._paint_theme_art(painter, above=False)

        # --- 2. Pilha de 3 Capas de Álbum à Esquerda (com suporte a Swipe e Animação Zoom/Stack) ---
        self._draw_cover_stack_layer(painter)

        # --- 3. Tipografia à Direita (Título + Subtítulo "Artista | Álbum") ---
        self._draw_typography(painter)

        # --- 4. Controles à Direita: Botão Play/Pause Squircle Neumórfico + Repeat + Shuffle ---
        self._draw_squircle_play_button(painter)
        self._draw_repeat_icon(painter, self.REPEAT_CENTER, hovered=(self.hovered_btn == "repeat"), mode=self.repeat_mode)
        self._draw_shuffle_icon(painter, self.SHUFFLE_CENTER, hovered=(self.hovered_btn == "shuffle"), active=self.is_shuffle)
        painter.setClipping(False)                   # as figurinhas de cima podem sair da borda do cartão
        self._paint_theme_art(painter, above=True)

        self.paint_resize_grip(painter)

    def _draw_cover_stack_layer(self, painter: QPainter):
        cov1, cov2, cov3 = self._get_stack_pixmaps()

        # Caso A: Animação ativa de transição entre faixas
        if self._anim_active:
            p = self._anim_progress
            e = _ease_out_cubic(p)
            eff_e = _lerp_val(self._anim_start_t, 1.0, e)
            outgoing_pm = self._anim_outgoing_pm or cov1

            if self._anim_direction == "next":
                # 1. Nova 3ª capa surgindo suavemente no fundo da pilha
                r3_in = self._scale_rect_centered(self.COVER3_RECT, _lerp_val(0.86, 1.0, e))
                self._draw_rounded_pixmap(painter, r3_in, self.COVER3_RADIUS, cov3, opacity=e)

                # 2. Antiga 3ª capa avançando para a posição da 2ª capa (COVER3 -> COVER2)
                r3_to_2 = _lerp_rect(self.COVER3_RECT, self.COVER2_RECT, eff_e)
                rad3_to_2 = _lerp_val(self.COVER3_RADIUS, self.COVER2_RADIUS, eff_e)
                self._draw_rounded_pixmap(painter, r3_to_2, rad3_to_2, cov2, opacity=1.0)

                # 3. Capa de trás avançando para a posição principal da frente (COVER2 -> COVER1)
                r2_to_1 = _lerp_rect(self.COVER2_RECT, self.COVER1_RECT, eff_e)
                rad2_to_1 = _lerp_val(self.COVER2_RADIUS, self.COVER1_RADIUS, eff_e)
                bar_alpha = max(0.0, min(1.0, (eff_e - 0.30) / 0.70))
                self._draw_main_cover_with_progress(
                    painter,
                    cov1,
                    rect=r2_to_1,
                    radius=rad2_to_1,
                    opacity=1.0,
                    bar_opacity=bar_alpha,
                )

                # 4. Capa antiga da frente dando ZOOM para frente, esmaecendo e desaparecendo continuamente
                start_zoom = 1.0 + 0.11 * (self._anim_start_t / 0.45) if self._anim_start_t > 0 else 1.0
                zoom_scale = _lerp_val(start_zoom, 1.26, e)
                target_dx = (self._anim_start_dx - 80.0) if self._anim_start_dx < -5.0 else -28.0
                shift_x = _lerp_val(self._anim_start_dx, target_dx, e)
                r_front_zoom = self._scale_rect_centered(self.COVER1_RECT, zoom_scale, dx=shift_x)
                rad_front = self.COVER1_RADIUS * zoom_scale
                start_alpha = max(0.55, 1.0 - 0.22 * (self._anim_start_t / 0.45)) if self._anim_start_t > 0 else 1.0
                fade_alpha = max(0.0, start_alpha * ((1.0 - p) ** 1.75))
                self._draw_rounded_pixmap(painter, r_front_zoom, rad_front, outgoing_pm, opacity=fade_alpha)
                return

            else:
                # direction == "prev" (Puxou para a direita -> voltar música)
                # 1. Antiga 2ª capa recua para a 3ª posição (COVER2 -> COVER3)
                r2_to_3 = _lerp_rect(self.COVER2_RECT, self.COVER3_RECT, eff_e)
                rad2_to_3 = _lerp_val(self.COVER2_RADIUS, self.COVER3_RADIUS, eff_e)
                self._draw_rounded_pixmap(painter, r2_to_3, rad2_to_3, cov3, opacity=1.0)

                # 2. Antiga capa da frente recua para a 2ª posição (COVER1 -> COVER2)
                start_r1 = self.COVER1_RECT.translated(self._anim_start_dx, 0.0)
                r1_to_2 = _lerp_rect(start_r1, self.COVER2_RECT, e)
                rad1_to_2 = _lerp_val(self.COVER1_RADIUS, self.COVER2_RADIUS, e)
                self._draw_rounded_pixmap(painter, r1_to_2, rad1_to_2, outgoing_pm, opacity=1.0)

                # 3. Capa da música anterior vem da frente (zoom 1.24 -> 1.0 + fade-in) pousando em COVER1_RECT
                zoom_in = _lerp_val(1.24, 1.0, e)
                shift_in = _lerp_val(-48.0, 0.0, e)
                r_prev_in = self._scale_rect_centered(self.COVER1_RECT, zoom_in, dx=shift_in)
                rad_prev_in = self.COVER1_RADIUS * zoom_in
                bar_alpha = max(0.0, min(1.0, (e - 0.35) / 0.65))
                self._draw_main_cover_with_progress(
                    painter,
                    cov1,
                    rect=r_prev_in,
                    radius=rad_prev_in,
                    opacity=e,
                    bar_opacity=bar_alpha,
                )
                return

        # Caso B: Usuário está puxando/arrastando a capa em tempo real (feedback tátil antes de soltar)
        if abs(self._cover_drag_dx_canvas) > 0.5:
            dx = self._cover_drag_dx_canvas
            drag_t = min(1.0, abs(dx) / 140.0)

            if dx < 0:
                # Puxando para a esquerda (preparando para pular música):
                # 3ª capa avança levemente para a 2ª, 2ª avança levemente para a 1ª, e 1ª desloca dando zoom
                r3 = _lerp_rect(self.COVER3_RECT, self.COVER2_RECT, drag_t * 0.42)
                rad3 = _lerp_val(self.COVER3_RADIUS, self.COVER2_RADIUS, drag_t * 0.42)
                self._draw_rounded_pixmap(painter, r3, rad3, cov3, opacity=1.0)

                r2 = _lerp_rect(self.COVER2_RECT, self.COVER1_RECT, drag_t * 0.42)
                rad2 = _lerp_val(self.COVER2_RADIUS, self.COVER1_RADIUS, drag_t * 0.42)
                self._draw_rounded_pixmap(painter, r2, rad2, cov2, opacity=1.0)

                zoom_s = 1.0 + 0.11 * drag_t
                r1 = self._scale_rect_centered(self.COVER1_RECT, zoom_s, dx=dx * 0.82)
                self._draw_main_cover_with_progress(
                    painter,
                    cov1,
                    rect=r1,
                    radius=self.COVER1_RADIUS * zoom_s,
                    opacity=1.0 - 0.22 * drag_t,
                    bar_opacity=1.0 - 0.60 * drag_t,
                )
                return
            else:
                # Puxando para a direita (preparando para voltar música):
                # 1ª capa desliza em direção à 2ª posição, 2ª desliza para a 3ª
                self._draw_rounded_pixmap(painter, self.COVER3_RECT, self.COVER3_RADIUS, cov3, opacity=1.0 - 0.4 * drag_t)

                r2 = _lerp_rect(self.COVER2_RECT, self.COVER3_RECT, drag_t * 0.55)
                rad2 = _lerp_val(self.COVER2_RADIUS, self.COVER3_RADIUS, drag_t * 0.55)
                self._draw_rounded_pixmap(painter, r2, rad2, cov2, opacity=1.0)

                r1 = _lerp_rect(self.COVER1_RECT, self.COVER2_RECT, drag_t * 0.55)
                rad1 = _lerp_val(self.COVER1_RADIUS, self.COVER2_RADIUS, drag_t * 0.55)
                self._draw_main_cover_with_progress(
                    painter,
                    cov1,
                    rect=r1,
                    radius=rad1,
                    opacity=1.0,
                    bar_opacity=1.0 - 0.60 * drag_t,
                )
                return

        # Caso C: Estado estático em repouso
        self._draw_rounded_pixmap(painter, self.COVER3_RECT, self.COVER3_RADIUS, cov3, opacity=1.0)
        self._draw_rounded_pixmap(painter, self.COVER2_RECT, self.COVER2_RADIUS, cov2, opacity=1.0)
        self._draw_main_cover_with_progress(painter, cov1, rect=self.COVER1_RECT, radius=self.COVER1_RADIUS)

    def _draw_main_cover_with_progress(
        self,
        painter: QPainter,
        cov1: QPixmap,
        rect: QRectF | None = None,
        radius: float | None = None,
        opacity: float = 1.0,
        bar_opacity: float = 1.0,
    ):
        if opacity <= 0.005:
            return
        target_rect = rect if rect is not None else self.COVER1_RECT
        target_radius = radius if radius is not None else self.COVER1_RADIUS

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, opacity)))

        clip = QPainterPath()
        clip.addRoundedRect(target_rect, target_radius, target_radius)
        painter.setClipPath(clip)

        # Se a animação de revelação (do vinil procedural para a capa real) estiver ativa:
        if self._reveal_active and not self._anim_active and self._reveal_from_pm is not None:
            proc_pm = self._reveal_from_pm
            p_rev = max(0.0, min(1.0, self._reveal_progress))
            e_rev = _ease_out_cubic(p_rev)

            # 1. Base: desenha a capa de vinil procedural ("falsa")
            painter.drawPixmap(target_rect, proc_pm, QRectF(0, 0, proc_pm.width(), proc_pm.height()))

            # Centro óptico do disco de vinil procedural (0.48, 0.50)
            vcx = target_rect.x() + target_rect.width() * 0.48
            vcy = target_rect.y() + target_rect.height() * 0.50

            if self.reveal_mode == "ripple":
                # Opção 1: Ripple Wave Reveal — onda concêntrica expandindo do centro do vinil
                max_r = math.hypot(target_rect.width() * 0.58, target_rect.height() * 0.58) * 1.28
                cur_r = max_r * e_rev

                painter.save()
                wave_clip = QPainterPath()
                wave_clip.addEllipse(QPointF(vcx, vcy), cur_r, cur_r)
                painter.setClipPath(clip.intersected(wave_clip))
                painter.drawPixmap(target_rect, cov1, QRectF(0, 0, cov1.width(), cov1.height()))
                painter.restore()

                # Anéis luminosos concêntricos na crista da onda com opacidade graduada
                fade_out = max(0.0, 1.0 - (p_rev ** 2.1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for dr, sw, base_a in ((0.0, 4.4, 215), (-14.0, 2.6, 130), (-28.0, 1.5, 68)):
                    rr = cur_r + dr
                    if rr > 2.0:
                        ring_col = QColor(255, 255, 255, int(base_a * fade_out)) if dr == 0.0 else QColor(self.pastel_theme.accent_main)
                        if dr != 0.0:
                            ring_col.setAlpha(int(base_a * fade_out))
                        painter.setPen(QPen(ring_col, sw))
                        painter.drawEllipse(QPointF(vcx, vcy), rr, rr)

            elif self.reveal_mode == "bloom":
                # Opção 2: Label Bloom & Spin — nasce do selo central do vinil girando e desabrochando em squircle
                scale_f = target_rect.width() / self.COVER1_RECT.width()
                start_size = 104.0 * scale_f
                cur_w = _lerp_val(start_size, target_rect.width(), e_rev)
                cur_h = _lerp_val(start_size, target_rect.height(), e_rev)
                cur_rad = _lerp_val(start_size / 2.0, target_radius, e_rev)
                cx_m = _lerp_val(vcx, target_rect.center().x(), e_rev)
                cy_m = _lerp_val(vcy, target_rect.center().y(), e_rev)
                angle = (1.0 - e_rev) * -108.0

                painter.save()
                painter.translate(cx_m, cy_m)
                painter.rotate(angle)
                local_rect = QRectF(-cur_w / 2.0, -cur_h / 2.0, cur_w, cur_h)
                bloom_clip = QPainterPath()
                bloom_clip.addRoundedRect(local_rect, cur_rad, cur_rad)
                painter.setClipPath(bloom_clip, Qt.ClipOperation.IntersectClip)
                painter.drawPixmap(local_rect, cov1, QRectF(0, 0, cov1.width(), cov1.height()))

                if p_rev < 0.96:
                    b_alpha = int(175 * (1.0 - p_rev))
                    painter.setPen(QPen(QColor(255, 255, 255, b_alpha), 3.0))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(local_rect, cur_rad, cur_rad)
                painter.restore()

            else:
                # Opção 3: Sleeve Slide — a capa real desliza da esquerda vestindo o vinil como um envelope físico
                slide_x = _lerp_val(-target_rect.width(), 0.0, e_rev)
                sleeve_rect = target_rect.translated(slide_x, 0.0)
                edge_x = sleeve_rect.right()

                if p_rev < 0.98:
                    sh_grad = QLinearGradient(edge_x - 6.0, 0.0, edge_x + 28.0, 0.0)
                    sh_grad.setColorAt(0.0, QColor(0, 0, 0, int(135 * (1.0 - p_rev * 0.4))))
                    sh_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
                    painter.fillRect(QRectF(edge_x - 6.0, target_rect.y(), 34.0, target_rect.height()), sh_grad)

                painter.save()
                sleeve_clip = QPainterPath()
                sleeve_clip.addRoundedRect(sleeve_rect, target_radius, target_radius)
                painter.setClipPath(clip.intersected(sleeve_clip))
                painter.drawPixmap(sleeve_rect, cov1, QRectF(0, 0, cov1.width(), cov1.height()))
                if p_rev < 0.97:
                    painter.setPen(QPen(QColor(255, 255, 255, int(150 * (1.0 - p_rev))), 2.5))
                    painter.drawLine(QPointF(edge_x - 1.0, target_rect.y()), QPointF(edge_x - 1.0, target_rect.bottom()))
                painter.restore()
        else:
            painter.drawPixmap(target_rect, cov1, QRectF(0, 0, cov1.width(), cov1.height()))

        if bar_opacity > 0.01:
            painter.setOpacity(max(0.0, min(1.0, opacity * bar_opacity)))

            # Escala proporcionalmente a posição da barra caso a capa esteja interpolando de COVER2 para COVER1
            scale_x = target_rect.width() / self.COVER1_RECT.width()
            scale_y = target_rect.height() / self.COVER1_RECT.height()

            # Vinheta escura suave na base interna da capa para contraste perfeito da barra de progresso
            bot_grad = QLinearGradient(
                0.0,
                target_rect.bottom() - 80.0 * scale_y,
                0.0,
                target_rect.bottom(),
            )
            bot_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            bot_grad.setColorAt(1.0, QColor(0, 0, 0, 125))
            painter.fillRect(target_rect, bot_grad)

            # Barra de progresso em cápsula na parte inferior da capa
            is_bar_active = (self.hovered_btn == "bar" or self.pressed_btn == "bar")
            base_h = (16.0 if is_bar_active else self.BAR_H) * scale_y
            rel_x = (self.BAR_X - self.COVER1_RECT.x()) * scale_x
            rel_y = (self.BAR_Y - self.COVER1_RECT.y()) * scale_y
            bar_x = target_rect.x() + rel_x
            bar_w = self.BAR_W * scale_x
            bar_y = target_rect.y() + rel_y - (base_h - self.BAR_H * scale_y) / 2.0
            bar_r = base_h / 2.0

            progress = max(0.0, min(1.0, self.current_time / self.duration)) if self.duration > 0 else 0.0

            # Trilho translúcido da barra (idêntico à referência)
            painter.setPen(Qt.PenStyle.NoPen)
            track = self.skin_theme.progress_track
            painter.setBrush(track if track is not None else QColor(185, 175, 175, 125))
            painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, base_h), bar_r, bar_r)

            # Preenchimento branco em cápsula
            if progress > 0.0:
                fill_w = max(base_h, bar_w * progress)
                fill = self.skin_theme.progress_fill
                painter.setBrush(fill if fill is not None else QColor("#FFFFFF"))
                painter.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, base_h), bar_r, bar_r)

        painter.restore()

    def _draw_typography(self, painter: QPainter):
        text_x = 516.0
        max_w = 414.0

        # Título em negrito escuro (ex: "Mist of Capricorn")
        font_title = get_ui_font(38, QFont.Weight.Bold)
        font_title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.5)
        painter.setFont(font_title)
        painter.setPen(self.pastel_theme.title_color)
        fm_title = QFontMetrics(font_title)
        elided_title = fm_title.elidedText(self.shown_title(), Qt.TextElideMode.ElideRight, int(max_w))
        painter.drawText(
            QRectF(text_x, 122.0, max_w, 52.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_title,
        )

        # Subtítulo "Artista | Álbum" em tom acento suave (ex: "Agam | A Dream To Remember")
        font_sub = get_ui_font(21, QFont.Weight.Medium)
        painter.setFont(font_sub)
        painter.setPen(self.pastel_theme.subtitle_color)
        fm_sub = QFontMetrics(font_sub)

        clean_album = (self.album_text or "").strip()
        if clean_album and clean_album.lower() != self.title_text.lower():
            subtitle_str = f"{self.shown_artist()} | {clean_album}"
        else:
            subtitle_str = self.shown_artist()

        elided_sub = fm_sub.elidedText(subtitle_str, Qt.TextElideMode.ElideRight, int(max_w))
        painter.drawText(
            QRectF(text_x, 184.0, max_w, 34.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_sub,
        )

    def _draw_squircle_play_button(self, painter: QPainter):
        painter.save()
        is_hover = (self.hovered_btn == "main")
        is_press = (self.pressed_btn == "main")

        btn_rect = self.PLAY_BTN_RECT
        if is_press:
            btn_rect = btn_rect.adjusted(2.5, 2.5, -2.5, -2.5)
        elif is_hover:
            btn_rect = btn_rect.adjusted(-1.5, -1.5, 1.5, 1.5)

        # Gradiente neumórfico idêntico à referência (sombra interna rosada no topo-esquerdo -> creme claro na base-direita)
        grad = QLinearGradient(btn_rect.topLeft(), btn_rect.bottomRight())
        grad.setColorAt(0.0, self.pastel_theme.btn_grad_tl)
        grad.setColorAt(0.42, _lerp_c(self.pastel_theme.btn_grad_tl, self.pastel_theme.card_bg, 0.72))
        grad.setColorAt(1.0, self.pastel_theme.btn_grad_br)

        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(btn_rect, self.PLAY_BTN_RADIUS, self.PLAY_BTN_RADIUS)

        # Ícone central Play/Pause na cor acento vibrante (#EB5757)
        cx, cy = btn_rect.center().x(), btn_rect.center().y()
        icon_col = self.pastel_theme.accent_main.darker(106) if is_hover else self.pastel_theme.accent_main
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(icon_col)

        if self.is_playing:
            # Duas barras verticais em cápsula arredondada idênticas à referência
            bar_w, bar_h, gap = 11.0, 42.0, 14.0
            r = bar_w / 2.0
            painter.drawRoundedRect(QRectF(cx - gap / 2.0 - bar_w, cy - bar_h / 2.0, bar_w, bar_h), r, r)
            painter.drawRoundedRect(QRectF(cx + gap / 2.0, cy - bar_h / 2.0, bar_w, bar_h), r, r)
        else:
            # Triângulo Play com cantos arredondados
            pen = QPen(icon_col, 6.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(icon_col)
            play_path = QPainterPath()
            ox = cx + 3.0
            play_path.moveTo(ox - 13.0, cy - 17.0)
            play_path.lineTo(ox + 16.0, cy)
            play_path.lineTo(ox - 13.0, cy + 17.0)
            play_path.closeSubpath()
            painter.drawPath(play_path)

        painter.restore()

    def _draw_repeat_icon(self, painter: QPainter, center: QPointF, hovered: bool, mode: int):
        """Desenha o ícone de Repeat fiel à referência capaEmpilhada.png."""
        painter.save()
        cx, cy = center.x(), center.y()
        is_active = (mode > 0)

        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            c_bg = QColor(self.pastel_theme.accent_main)
            c_bg.setAlpha(24)
            painter.setBrush(c_bg)
            painter.drawEllipse(center, 28.0, 28.0)

        col = self.pastel_theme.accent_main if (is_active or hovered) else self.pastel_theme.accent_muted
        pen = QPen(col, 3.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Topo: curva esquerda subindo + reta superior + seta para a direita
        p_top = QPainterPath()
        p_top.moveTo(cx - 17.0, cy - 2.0)
        p_top.lineTo(cx - 17.0, cy - 7.0)
        p_top.cubicTo(cx - 17.0, cy - 11.5, cx - 13.5, cy - 14.0, cx - 9.0, cy - 14.0)
        p_top.lineTo(cx + 15.0, cy - 14.0)
        painter.drawPath(p_top)

        arr_top = QPainterPath()
        arr_top.moveTo(cx + 9.0, cy - 20.0)
        arr_top.lineTo(cx + 16.0, cy - 14.0)
        arr_top.lineTo(cx + 9.0, cy - 8.0)
        painter.drawPath(arr_top)

        # Base: curva direita descendo + reta inferior + seta para a esquerda
        p_bot = QPainterPath()
        p_bot.moveTo(cx + 17.0, cy + 2.0)
        p_bot.lineTo(cx + 17.0, cy + 7.0)
        p_bot.cubicTo(cx + 17.0, cy + 11.5, cx + 13.5, cy + 14.0, cx + 9.0, cy + 14.0)
        p_bot.lineTo(cx - 15.0, cy + 14.0)
        painter.drawPath(p_bot)

        arr_bot = QPainterPath()
        arr_bot.moveTo(cx - 9.0, cy + 8.0)
        arr_bot.lineTo(cx - 16.0, cy + 14.0)
        arr_bot.lineTo(cx - 9.0, cy + 20.0)
        painter.drawPath(arr_bot)

        if mode == 2:
            font_one = get_ui_font(12, QFont.Weight.Bold)
            painter.setFont(font_one)
            painter.setPen(col)
            painter.drawText(QRectF(cx - 9, cy - 8, 18, 16), Qt.AlignmentFlag.AlignCenter, "1")

        if is_active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.pastel_theme.accent_main)
            painter.drawEllipse(QPointF(cx, cy + 25.0), 3.0, 3.0)

        painter.restore()

    def _draw_shuffle_icon(self, painter: QPainter, center: QPointF, hovered: bool, active: bool):
        """Desenha o ícone de setas cruzadas (Shuffle) fiel à referência capaEmpilhada.png."""
        painter.save()
        cx, cy = center.x(), center.y()

        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            c_bg = QColor(self.pastel_theme.accent_main)
            c_bg.setAlpha(24)
            painter.setBrush(c_bg)
            painter.drawEllipse(center, 28.0, 28.0)

        col = self.pastel_theme.accent_main if (active or hovered) else self.pastel_theme.accent_muted
        pen = QPen(col, 3.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Diagonal principal: topo-esquerdo -> base-direita com seta
        painter.drawLine(QPointF(cx - 15.0, cy - 15.0), QPointF(cx + 15.0, cy + 15.0))
        arr_br = QPainterPath()
        arr_br.moveTo(cx + 6.5, cy + 15.5)
        arr_br.lineTo(cx + 15.5, cy + 15.5)
        arr_br.lineTo(cx + 15.5, cy + 6.5)
        painter.drawPath(arr_br)

        # Diagonal cruzada: base-esquerda -> topo-direito (com gap sutil no cruzamento como na referência)
        painter.drawLine(QPointF(cx - 15.0, cy + 15.0), QPointF(cx - 4.5, cy + 4.5))
        painter.drawLine(QPointF(cx + 4.5, cy - 4.5), QPointF(cx + 15.0, cy - 15.0))
        arr_tr = QPainterPath()
        arr_tr.moveTo(cx + 6.5, cy - 15.5)
        arr_tr.lineTo(cx + 15.5, cy - 15.5)
        arr_tr.lineTo(cx + 15.5, cy - 6.5)
        painter.drawPath(arr_tr)

        if active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.pastel_theme.accent_main)
            painter.drawEllipse(QPointF(cx, cy + 25.0), 3.0, 3.0)

        painter.restore()

    @staticmethod
    @staticmethod
    def _build_minimal_transition_icon(mode: str, active: bool = False, is_dark: bool = True) -> QIcon:
        """Gera ícone vetorial minimalista com opacidade concêntrica graduada para o menu de contexto."""
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if is_dark:
            base = QColor(255, 255, 255) if active else QColor(160, 160, 168)
        else:
            base = QColor(31, 30, 29) if active else QColor(120, 119, 116)

        cx, cy = 16.0, 16.0

        if mode == "ripple":
            c_dot = QColor(base)
            c_dot.setAlpha(255)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c_dot)
            p.drawEllipse(QPointF(cx, cy), 2.4, 2.4)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for r, sw, af in ((5.4, 1.9, 0.88), (8.5, 1.7, 0.64), (11.6, 1.5, 0.40), (14.4, 1.3, 0.20)):
                rc = QColor(base)
                rc.setAlpha(int(255 * af))
                p.setPen(QPen(rc, sw))
                p.drawEllipse(QPointF(cx, cy), r, r)

        elif mode == "bloom":
            c_dot = QColor(base)
            c_dot.setAlpha(255)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c_dot)
            p.drawEllipse(QPointF(cx, cy), 2.3, 2.3)
            p.setBrush(Qt.BrushStyle.NoBrush)
            c1 = QColor(base)
            c1.setAlpha(int(255 * 0.86))
            p.setPen(QPen(c1, 1.8))
            p.drawEllipse(QPointF(cx, cy), 5.8, 5.8)
            c2 = QColor(base)
            c2.setAlpha(int(255 * 0.54))
            p.setPen(QPen(c2, 1.6))
            p.drawRoundedRect(QRectF(cx - 9.5, cy - 9.5, 19.0, 19.0), 5.5, 5.5)
            c3 = QColor(base)
            c3.setAlpha(int(255 * 0.25))
            p.setPen(QPen(c3, 1.4))
            p.drawRoundedRect(QRectF(cx - 13.0, cy - 13.0, 26.0, 26.0), 6.8, 6.8)

        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            c1 = QColor(base)
            c1.setAlpha(int(255 * 0.94))
            p.setPen(QPen(c1, 1.9))
            p.drawRoundedRect(QRectF(4.0, 6.0, 14.5, 20.0), 4.0, 4.0)
            for r_arc, sw, af in ((4.8, 1.8, 0.84), (8.0, 1.6, 0.52), (11.2, 1.4, 0.24)):
                ca = QColor(base)
                ca.setAlpha(int(255 * af))
                p.setPen(QPen(ca, sw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawArc(QRectF(18.5 - r_arc, cy - r_arc, r_arc * 2.0, r_arc * 2.0), -68 * 16, 136 * 16)

        p.end()
        return QIcon(pm)

    def _get_skin_effects_title(self) -> str:
        return t("music_menu_effects_cover")

    def _get_skin_effects_icon(self, is_dark: bool = True) -> QIcon:
        return self._build_minimal_transition_icon(self.reveal_mode, active=True, is_dark=is_dark)

    def _populate_skin_effects_menu(self, menu: QMenu, is_dark: bool = True) -> bool:
        """Adiciona as opções de transição do vinil apenas ao submenu desta skin."""
        for mode_id, label in (
            ("ripple", "Ripple Wave"),
            ("bloom", "Label Bloom"),
            ("sleeve", "Sleeve Slide"),
        ):
            is_curr = (self.reveal_mode == mode_id)
            act = QAction(self._build_minimal_transition_icon(mode_id, is_curr, is_dark=is_dark), label, self)
            if hasattr(menu, "set_trailing_check"):
                menu.set_trailing_check(act, is_curr)
            else:
                act.setCheckable(True)
                act.setChecked(is_curr)
            act.triggered.connect(lambda checked=False, m=mode_id: self.set_reveal_mode(m, preview=True))
            menu.addAction(act)
        return True

    def _hit_test(self, pos):
        if self.rect_bar_hit.contains(pos):
            return "bar"
        if self.rect_main.contains(pos):
            return "main"
        if self.rect_repeat.contains(pos):
            return "repeat"
        if self.rect_shuffle.contains(pos):
            return "shuffle"
        if self.rect_cover_drag.contains(pos):
            return "cover"
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
            elif hit == "cover":
                self.pressed_btn = "cover"
                self._is_dragging_cover = True
                self._cover_drag_start_x = pos.x()
                self._cover_drag_dx_canvas = 0.0
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
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

        if (event.buttons() & Qt.MouseButton.LeftButton) and self.pressed_btn == "cover":
            dx_win = pos.x() - self._cover_drag_start_x
            self._cover_drag_dx_canvas = max(-180.0, min(180.0, dx_win / self.scale))
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
            if hit == "cover":
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
            pos = event.position()
            hit = self._hit_test(pos)

            if self.pressed_btn == "cover":
                dx_canvas = self._cover_drag_dx_canvas
                self._is_dragging_cover = False
                self._cover_drag_dx_canvas = 0.0
                self.setCursor(Qt.CursorShape.OpenHandCursor if hit == "cover" else Qt.CursorShape.ArrowCursor)

                if dx_canvas <= -self.SWIPE_THRESHOLD_CANVAS:
                    # Puxou a capa para a ESQUERDA -> Ativa animação de Zoom/Fade + avanço da pilha e pula a música
                    self._last_user_swipe_time = time.perf_counter()
                    self._awaiting_swipe_track_change = True
                    self._stale_track_thumb_bytes = self._last_thumb_bytes
                    self.current_time = 0.0
                    self._last_seek_sent = time.perf_counter()
                    drag_t = min(1.0, abs(dx_canvas) / 140.0)
                    self._start_stack_transition(
                        direction="next",
                        outgoing_pm=None,
                        start_dx=dx_canvas * 0.82,
                        start_t=drag_t * 0.42,
                    )
                    self.command_requested.emit("next", None)
                elif dx_canvas >= self.SWIPE_THRESHOLD_CANVAS:
                    # Puxou a capa para a DIREITA -> Ativa animação reversa e volta a música
                    prev_track_pos = self.current_time
                    self._last_user_swipe_time = time.perf_counter()
                    self._awaiting_swipe_track_change = True
                    self._stale_track_thumb_bytes = self._last_thumb_bytes
                    self.current_time = 0.0
                    self._last_seek_sent = time.perf_counter()
                    drag_t = min(1.0, abs(dx_canvas) / 140.0)
                    self._start_stack_transition(
                        direction="prev",
                        outgoing_pm=None,
                        start_dx=dx_canvas * 0.55,
                        start_t=drag_t * 0.45,
                    )
                    # Opção A: se a faixa já tocou por mais de 2.5s, um único comando 'prev' apenas
                    # reiniciaria a música atual para 0:00. Enviamos 'force_double' para que o player
                    # realmente retorne para a faixa anterior, alinhando com a capa visual que voltou!
                    need_double_prev = (prev_track_pos > 2.5)
                    self.command_requested.emit("prev", "force_double" if need_double_prev else None)

            elif self.pressed_btn == "main" and hit == "main":
                self.is_playing = not self.is_playing
                self._ignore_external_state_until = time.perf_counter() + 1.0
                self.command_requested.emit("play" if self.is_playing else "pause", None)
            elif self.pressed_btn == "repeat" and hit == "repeat":
                self.repeat_mode = self.next_repeat_mode()
                self.command_requested.emit("repeat", self.repeat_mode)
            elif self.pressed_btn == "shuffle" and hit == "shuffle":
                self.is_shuffle = not self.is_shuffle
                self.command_requested.emit("shuffle", self.is_shuffle)
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
        bar_start = self.art_margin + self.BAR_X * self.scale
        bar_width = self.BAR_W * self.scale
        ratio = max(0.0, min(1.0, (x_widget - bar_start) / bar_width))
        self.current_time = ratio * self.duration
