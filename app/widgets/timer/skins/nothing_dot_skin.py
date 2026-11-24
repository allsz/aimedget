"""
NothingDotTimerSkin - Skin de hardware estilo Nothing / Teenage Engineering para o Timer Widget.

- Chassi squircle preto fosco (#141414) com tela superior rebaixada e dígitos em matriz de pontos 5x7.
- Botão circular grande à esquerda: Play / Pause na cor de destaque (vermelho Nothing #D71921 por padrão).
- Tema embutido "Aimedget": chassi no fundo do app (`bg`, off-white no claro), tela na cor dos cartões (`panel`,
  branca no claro), dígitos e rótulo no texto do app, dois-pontos e LED na cor de destaque do app.
- Grade circular perfurada 7x7 à direita: toda a área dos pontos funciona como botão de Reiniciar;
  ao clicar, o ponto branco superior-esquerdo dá uma volta completa de 360° pulando de ponto em ponto
  ("dot-to-dot hop", 320 ms). No alarme, a grade pulsa radialmente na cor de destaque.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

from app.core.config_manager import config_manager
from app.core.frame_clock import FrameTimer
from app.core.typography import get_ui_font
from app.core.widget_animator import animations_enabled
from app.hub.theme import HubTheme, THEME_DARK
from app.ui_components.dot_matrix import GLYPHS, NOTHING_RED
from app.widgets.timer import theme as timer_theme
from app.widgets.timer.skins.base_skin import BaseTimerSkin
from app.widgets.timer.skins.skin import (
    CORNER_RADIUS,
    DEFAULT_SIZE,
    SHADOW_PAD,
    TimerState,
    _paint_art,
    mode_label,
)

ORBIT_DURATION_S = 0.320   # duração do pulo 360° ponto-a-ponto ao reiniciar

# Grade circular 7x7 em coordenadas normalizadas (-3..+3) dentro do diâmetro da grade
_HOME_ANGLE = -3.0 * math.pi / 4.0   # canto superior esquerdo (referência)
_GRILLE_CELLS: list[tuple[int, int, float, float, float, float]] = []
for _r in range(7):
    for _c in range(7):
        _dx = (_c - 3) / 3.35
        _dy = (_r - 3) / 3.35
        _dist = math.hypot(_dx, _dy)
        if _dist <= 0.99:
            _ang = math.atan2(_dy, _dx)
            _GRILLE_CELLS.append((_r, _c, _dx, _dy, _dist, _ang))

_PERIMETER_CELLS = sorted(
    [
        (cell, (_HOME_ANGLE - cell[5]) % (2.0 * math.pi))
        for cell in _GRILLE_CELLS
        if cell[4] >= 0.70
    ],
    key=lambda item: item[1],
)
_PERIMETER_ONLY = [item[0] for item in _PERIMETER_CELLS]
_HOME_CELL = _PERIMETER_ONLY[0]


def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _mix(a: QColor, b: QColor, amount: float) -> QColor:
    """`a` com `amount` (0..1) de `b`, opaco."""
    return QColor(round(a.red() + (b.red() - a.red()) * amount),
                  round(a.green() + (b.green() - a.green()) * amount),
                  round(a.blue() + (b.blue() - a.blue()) * amount))


def _alpha(color, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def _resolve_nothing_colors(theme: HubTheme, art: Optional[timer_theme.TimerTheme]) -> dict[str, QColor]:
    """
    Resolve a paleta da skin Nothing Dot:
    - Tema padrão (sem cores customizadas e não é o tema Aimedget): vermelho Nothing (#D71921) + tinta branca.
    - Tema embutido "Aimedget" (is_app_accent=True): chassi no fundo do app (`bg`), tela nos cartões (`panel`),
      dígitos, grade e ponto de reiniciar no texto do app, destaque do app ao vivo (`accent`, `ink`).
    - Tema .aimskin / theme.json do usuário: respeita `card_bg`, `border`, `accent`, `on_accent`, `text`, `muted_text`.
    """
    custom_fields = {field for field, _col in art.colors} if art is not None else set()
    use_app = bool(art is not None and art.is_app_accent)

    if use_app:
        card_bg = QColor(theme.bg)
    else:
        card_bg = QColor(theme.panel) if "panel" in custom_fields else QColor("#141414")
    border = QColor(theme.line) if (use_app or "line" in custom_fields) else QColor(255, 255, 255, 22)
    digit_on = QColor(theme.text) if (use_app or "text" in custom_fields) else QColor("#F5F5F7")
    muted = QColor(theme.mute) if (use_app or "mute" in custom_fields) else QColor(255, 255, 255, 110)

    if use_app or "accent" in custom_fields:
        accent = QColor(theme.accent)
        on_accent = QColor(theme.ink) if (use_app or "ink" in custom_fields) else (
            QColor("#1A1305") if accent.lightnessF() > 0.62 else QColor("#FFFFFF")
        )
    else:
        accent = QColor(NOTHING_RED)
        on_accent = QColor("#FFFFFF")

    # Peças pintadas sobre o chassi: no "Aimedget" seguem o texto do app (num chassi claro, o branco sumiria)
    if use_app:
        fg = QColor(theme.text)
        grille_dot = _mix(card_bg, fg, 0.12)
        grille_dot_hover = _mix(card_bg, fg, 0.20)
        home_dot = QColor(fg)
    else:
        fg = QColor("#FFFFFF")
        grille_dot, grille_dot_hover, home_dot = QColor("#2E2E31"), QColor("#3E3E44"), QColor("#F2F2F4")

    # Tela rebaixada: visor escuro no Nothing; no "Aimedget", a cor dos cartões do app (branca no claro)
    if use_app:
        screen_top = screen_bottom = QColor(theme.panel)
        screen_border = QColor(theme.line)
        dot_off = _alpha(theme.text, 16)
        colon_dim = _alpha(theme.accent, 70)
        led_idle = _alpha(theme.accent, 80)
    else:
        screen_top, screen_bottom = QColor("#272729"), QColor("#222224")
        screen_border = QColor(255, 255, 255, 14)
        dot_off = QColor(255, 255, 255, 13)
        colon_dim = QColor(255, 255, 255, 32)
        led_idle = QColor(255, 255, 255, 48)

    return {
        "screen_top": screen_top,
        "screen_bottom": screen_bottom,
        "screen_border": screen_border,
        "dot_off": dot_off,
        "colon_dim": colon_dim,
        "led_idle": led_idle,
        "chassis_fg": fg,
        "grille_dot": grille_dot,
        "grille_dot_hover": grille_dot_hover,
        "home_dot": home_dot,
        "card_bg": card_bg,
        "border": border,
        "digit_on": digit_on,
        "muted": muted,
        "accent": accent,
        "on_accent": on_accent,
    }


def _display_parts(state: TimerState) -> tuple[list[tuple[str, str]], bool]:
    """
    Devolve ([(segmento, texto), ...], tem_horas) para a tela de matriz de pontos.
    Segmentos: 'h', 'm', 's', ':' — permite destacar o segmento sob o mouse no scroll inteligente.
    """
    if state.mode == "alarm":
        tot = int(state.alarm_time) % 86400
        hh = tot // 3600
        mm = (tot % 3600) // 60
        return [("h", f"{hh:02d}"), (":", ":"), ("m", f"{mm:02d}")], False

    tot = max(0, int(round(state.current_seconds)))
    hh = tot // 3600
    mm = (tot % 3600) // 60
    ss = tot % 60
    if hh > 0:
        return [("h", f"{hh:02d}"), (":", ":"), ("m", f"{mm:02d}"), (":", ":"), ("s", f"{ss:02d}")], True
    return [("m", f"{mm:02d}"), (":", ":"), ("s", f"{ss:02d}")], False


def _card_layout(card: QRectF) -> tuple[QRectF, QRectF, QRectF]:
    """Calcula (screen_rect, play_rect, grille_rect) proporcionais ao cartão quadrado."""
    pad = card.width() * 0.068
    inner_w = card.width() - 2.0 * pad
    screen_h = card.height() * 0.415
    screen = QRectF(card.left() + pad, card.top() + pad, inner_w, screen_h)

    deck_top = screen.bottom() + card.height() * 0.055
    deck_h = card.bottom() - pad - deck_top
    btn_d = min(deck_h * 0.94, inner_w * 0.445)
    cy = deck_top + deck_h * 0.5
    play_cx = card.left() + pad + inner_w * 0.245
    grille_cx = card.right() - pad - inner_w * 0.245

    play_rect = QRectF(play_cx - btn_d * 0.5, cy - btn_d * 0.5, btn_d, btn_d)
    grille_rect = QRectF(grille_cx - btn_d * 0.5, cy - btn_d * 0.5, btn_d, btn_d)
    return screen, play_rect, grille_rect


def _paint_screen_digits(
    p: QPainter,
    screen: QRectF,
    state: TimerState,
    colors: dict[str, QColor],
    hovered_segment: Optional[str],
    blink_off: bool,
    alarm_pulse: bool,
):
    parts, has_hours = _display_parts(state)
    chars: list[tuple[str, str]] = []
    for seg, txt in parts:
        for ch in txt:
            chars.append((seg, ch))

    # Calcula passo dos pontos para caber com folga dentro da tela rebaixada
    total_cols = 0.0
    for idx, (_seg, ch) in enumerate(chars):
        bmp = GLYPHS.get(ch, GLYPHS["0"])
        total_cols += len(bmp[0])
        if idx < len(chars) - 1:
            total_cols += 1.1

    avail_w = screen.width() * 0.86
    avail_h = screen.height() * 0.52
    step = min(avail_w / max(1.0, total_cols), avail_h / 7.0)
    dot_r = step * 0.37
    char_gap = step * 1.1
    total_w = total_cols * step
    x = screen.center().x() - total_w * 0.5
    y0 = screen.top() + screen.height() * 0.34 + (avail_h - 7.0 * step) * 0.5

    dot_off = colors["dot_off"]
    colon_dim = colors["colon_dim"]
    p.setPen(Qt.PenStyle.NoPen)

    for seg, ch in chars:
        bmp = GLYPHS.get(ch, GLYPHS["0"])
        cols = len(bmp[0])
        for row_i, row_bits in enumerate(bmp):
            for col_i, bit in enumerate(row_bits):
                cx = x + col_i * step + step * 0.5
                cy = y0 + row_i * step + step * 0.5
                if bit == "1":
                    if ch == ":" and blink_off:
                        col = colon_dim
                    elif ch == ":" or alarm_pulse or (hovered_segment is not None and seg == hovered_segment):
                        col = colors["accent"]
                    else:
                        col = colors["digit_on"]
                    p.setBrush(col)
                    p.drawEllipse(QPointF(cx, cy), dot_r, dot_r)
                elif ch != ":":
                    p.setBrush(dot_off)
                    p.drawEllipse(QPointF(cx, cy), dot_r * 0.82, dot_r * 0.82)
        x += cols * step + char_gap


def paint_nothing_dot_timer(
    p: QPainter,
    rect: QRectF,
    state: TimerState,
    theme: HubTheme,
    art: Optional[timer_theme.TimerTheme] = None,
    orbit_progress: float = -1.0,
    alarm_phase: float = 0.0,
    grille_hovered: bool = False,
    play_hovered: bool = False,
    play_pressed: bool = False,
    close_opacity: float = 0.0,
    close_hovered: bool = False,
    resize_hovered: bool = False,
    hovered_segment: Optional[str] = None,
    blink_off: bool = False,
):
    """Renderiza a skin Nothing Dot do Timer em `rect` (compartilhada entre o widget vivo e as miniaturas do Hub)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    pad = SHADOW_PAD
    card = QRectF(rect.x() + pad, rect.y() + pad, rect.width() - 2.0 * pad, rect.height() - 2.0 * pad)
    scale = max(0.75, min(card.width(), card.height()) / (DEFAULT_SIZE - 2.0 * pad))
    radius = min(CORNER_RADIUS * 1.15 * scale, card.width() * 0.21)
    colors = _resolve_nothing_colors(theme, art)

    # 1. Sombra suave externa
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 72))
    p.drawRoundedRect(card.adjusted(0.0, 2.5 * scale, 0.0, 4.0 * scale), radius, radius)

    # 2. Chassi squircle preto fosco
    p.setBrush(colors["card_bg"])
    p.drawRoundedRect(card, radius, radius)

    # 2b. Fundo / figurinhas abaixo do tema do usuário (se houver)
    if art is not None and (art.background is not None or art.stickers):
        _paint_art(p, card, scale, art, above=False)

    # Borda sutil do chassi
    border_pen = QPen(colors["accent"] if state.is_alarm_pulsing else colors["border"],
                      1.8 if state.is_alarm_pulsing else 1.0)
    p.setPen(border_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    screen, play_rect, grille_rect = _card_layout(card)

    # 3. Tela superior rebaixada (bezel escuro)
    scr_r = max(8.0, screen.height() * 0.20)
    scr_grad = QLinearGradient(screen.topLeft(), screen.bottomLeft())
    scr_grad.setColorAt(0.0, colors["screen_top"])
    scr_grad.setColorAt(1.0, colors["screen_bottom"])
    p.setPen(QPen(colors["screen_border"], 1.0))
    p.setBrush(scr_grad)
    p.drawRoundedRect(screen, scr_r, scr_r)

    # Cabeçalho dentro da tela: rótulo do modo + LED de status
    lbl_font = get_ui_font(max(6, int(round(7.2 * scale))), QFont.Weight.DemiBold)
    p.setFont(lbl_font)
    p.setPen(colors["muted"])
    top_pad_x = screen.width() * 0.075
    top_pad_y = screen.height() * 0.11
    p.drawText(
        QRectF(screen.left() + top_pad_x, screen.top() + top_pad_y, screen.width() * 0.72, 12.0 * scale),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        mode_label(state),
    )

    led_r = max(1.8, 2.2 * scale)
    led_c = QPointF(screen.right() - top_pad_x - led_r, screen.top() + top_pad_y + 5.5 * scale)
    p.setPen(Qt.PenStyle.NoPen)
    if state.is_running:
        glow = QColor(colors["accent"])
        glow.setAlpha(95)
        p.setBrush(glow)
        p.drawEllipse(led_c, led_r * 2.1, led_r * 2.1)
        p.setBrush(colors["accent"])
    else:
        p.setBrush(colors["led_idle"])
    p.drawEllipse(led_c, led_r, led_r)

    # Dígitos em matriz de pontos 5x7
    alarm_pulse = state.is_alarm_pulsing and (int(alarm_phase * 2.5) % 2 == 0)
    _paint_screen_digits(p, screen, state, colors, hovered_segment, state.is_running and blink_off, alarm_pulse)

    # 4. Botão grande Play / Pause à esquerda (cor de destaque)
    p.save()
    pc = play_rect.center()
    p.translate(pc)
    if play_pressed:
        p.scale(0.93, 0.93)
    btn_r = play_rect.width() * 0.5
    btn_col = QColor(colors["accent"])
    if play_hovered:
        btn_col = btn_col.lighter(108)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(btn_col)
    p.drawEllipse(QPointF(0.0, 0.0), btn_r, btn_r)

    # Realce sutil de hardware no aro superior do botão
    p.setPen(QPen(QColor(255, 255, 255, 45), max(1.0, 1.1 * scale)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(0.0, 0.0), btn_r - 0.8, btn_r - 0.8)

    # Ícone Play / Pause centralizado (0.32x radius ~ 9px em escala 100%)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colors["on_accent"])
    if state.is_running:
        bh = btn_r * 0.32
        bw = bh * 0.32
        gap = bh * 0.24
        rr = bw * 0.42
        p.drawRoundedRect(QRectF(-gap - bw, -bh * 0.5, bw, bh), rr, rr)
        p.drawRoundedRect(QRectF(gap, -bh * 0.5, bw, bh), rr, rr)
    else:
        tri_h = btn_r * 0.32
        tri_w = tri_h * 0.86
        ox = tri_h * 0.11
        path = QPainterPath()
        path.moveTo(-tri_w * 0.48 + ox, -tri_h * 0.5)
        path.lineTo(tri_w * 0.56 + ox, 0.0)
        path.lineTo(-tri_w * 0.48 + ox, tri_h * 0.5)
        path.closeSubpath()
        p.drawPath(path)
    p.restore()

    # 5. Grade circular 7x7 de alto-falante à direita + ponto branco de Reiniciar (pulo 360° ponto-a-ponto)
    gc = grille_rect.center()
    gr = grille_rect.width() * 0.5
    orbiting = 0.0 <= orbit_progress < 1.0
    base_dot_r = max(1.3, gr * 0.062)
    white_dot_r = max(2.8, gr * (0.148 if grille_hovered else 0.134))

    p.setPen(Qt.PenStyle.NoPen)
    for cell in _GRILLE_CELLS:
        r_i, c_i, dx, dy, dist_n, _ang = cell
        is_home = (r_i == _HOME_CELL[0] and c_i == _HOME_CELL[1])
        if is_home and not orbiting and not state.is_alarm_pulsing:
            continue
        px = gc.x() + dx * gr
        py = gc.y() + dy * gr
        if state.is_alarm_pulsing:
            wave = 0.5 + 0.5 * math.sin(alarm_phase * 8.0 - dist_n * 5.8)
            col = QColor(colors["accent"])
            col.setAlphaF(0.22 + wave * 0.74)
            p.setBrush(col)
            p.drawEllipse(QPointF(px, py), base_dot_r * (0.88 + wave * 0.48), base_dot_r * (0.88 + wave * 0.48))
        else:
            p.setBrush(colors["grille_dot_hover" if grille_hovered else "grille_dot"])
            p.drawEllipse(QPointF(px, py), base_dot_r, base_dot_r)

    # Ponto branco (parado no canto superior esquerdo ou pulando de ponto em ponto ao redor do perímetro)
    if orbiting:
        n_perim = len(_PERIMETER_ONLY)
        hop_idx = int(_ease_out_cubic(orbit_progress) * n_perim) % n_perim
        target_cell = _PERIMETER_ONLY[hop_idx]
        wx = gc.x() + target_cell[2] * gr
        wy = gc.y() + target_cell[3] * gr
        p.setBrush(colors["chassis_fg"])
        p.drawEllipse(QPointF(wx, wy), white_dot_r * 1.06, white_dot_r * 1.06)
    elif not state.is_alarm_pulsing:
        wx = gc.x() + _HOME_CELL[2] * gr
        wy = gc.y() + _HOME_CELL[3] * gr
        p.setBrush(colors["home_dot"])
        p.drawEllipse(QPointF(wx, wy), white_dot_r, white_dot_r)

    # 6. Figurinhas acima (se o tema tiver)
    if art is not None and art.stickers:
        _paint_art(p, card, scale, art, above=True)

    # 7. Botão fechar (aparece no hover no canto superior esquerdo do cartão)
    if close_opacity > 0.02:
        csz = 19.0 * scale
        cpad = 8.0 * scale
        close_r = QRectF(card.left() + cpad, card.top() + cpad, csz, csz)
        p.setPen(Qt.PenStyle.NoPen)
        fg = colors["chassis_fg"]
        p.setBrush(QColor(fg.red(), fg.green(), fg.blue(), int(close_opacity * (58 if close_hovered else 30))))
        p.drawEllipse(close_r)
        cc = close_r.center()
        arm = csz * 0.21
        p.setPen(QPen(QColor(fg.red(), fg.green(), fg.blue(), int(close_opacity * 225)), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cc.x() - arm, cc.y() - arm), QPointF(cc.x() + arm, cc.y() + arm))
        p.drawLine(QPointF(cc.x() + arm, cc.y() - arm), QPointF(cc.x() - arm, cc.y() + arm))

    # 8. Indicador sutil de redimensionamento no canto inferior direito
    if resize_hovered:
        grip_c = QColor(colors["chassis_fg"])
        grip_c.setAlpha(130)
        p.setPen(QPen(grip_c, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        rx, ry = card.right() - 8.0 * scale, card.bottom() - 8.0 * scale
        p.drawLine(QPointF(rx - 5.0 * scale, ry), QPointF(rx, ry - 5.0 * scale))
        p.drawLine(QPointF(rx - 2.0 * scale, ry), QPointF(rx, ry - 2.0 * scale))

    p.restore()


class NothingDotTimerSkin(BaseTimerSkin):
    """Janela interativa da skin Nothing Dot do Timer Widget."""

    SHADOW_PAD = SHADOW_PAD

    def __init__(self, width: int = BaseTimerSkin.DEFAULT_SIZE, height: int = BaseTimerSkin.DEFAULT_SIZE):
        super().__init__(width=width, height=height)
        # Nothing Dot usa exclusivamente seu próprio loader (Nothing Red ou destaque Aimedget),
        # sem herdar temas exclusivos/figurinhas da skin Windows Timer.
        self.skin_theme = timer_theme.nothing_loader.load()
        self.theme = self.skin_theme.apply_to(self._hub_theme)
        self.set_square_side(max(self.MIN_WIDTH, width))

        self._alarm_pulsing = False
        self._play_hovered = False
        self._play_pressed = False
        self._grille_hovered = False
        self._hovered_segment: Optional[str] = None
        self._orbit_t0: float = -1e9
        self._alarm_t0: float = time.perf_counter()
        self._is_dragging = False
        self._is_resizing = False
        self._drag_start_pos = QPoint()
        self._resize_start_pos = QPoint()
        self._resize_start_side = self.DEFAULT_SIZE

        self._anim_clock = FrameTimer(self)
        self._anim_clock.setInterval(16)
        self._anim_clock.timeout.connect(self._on_anim_frame)

    def reload_skin_theme(self):
        """Relê apenas o tema da skin Nothing Dot (Nothing Red ou destaque Aimedget)."""
        theme = timer_theme.nothing_loader.load()
        if theme is self.skin_theme:
            return
        self.skin_theme = theme
        self.theme = theme.apply_to(self._hub_theme)
        self.update()

    @property
    def is_alarm_pulsing(self) -> bool:
        return self._alarm_pulsing

    @is_alarm_pulsing.setter
    def is_alarm_pulsing(self, value: bool):
        val = bool(value)
        if val and not self._alarm_pulsing:
            self._alarm_t0 = time.perf_counter()
            self._ensure_anim_clock()
        self._alarm_pulsing = val
        self.update()

    def get_card_rect(self) -> QRectF:
        p = self.SHADOW_PAD + self.art_margin
        return QRectF(p, p, self.width() - 2 * p, self.height() - 2 * p)

    def get_close_btn_rect(self) -> QRectF:
        card = self.get_card_rect()
        scale = max(0.75, min(card.width(), card.height()) / (self.DEFAULT_SIZE - 2.0 * self.SHADOW_PAD))
        csz = 19.0 * scale
        cpad = 8.0 * scale
        return QRectF(card.left() + cpad, card.top() + cpad, csz, csz)

    def get_resize_grip_rect(self) -> QRectF:
        card = self.get_card_rect()
        scale = max(0.75, min(card.width(), card.height()) / (self.DEFAULT_SIZE - 2.0 * self.SHADOW_PAD))
        gs = 22.0 * scale
        return QRectF(card.right() - gs, card.bottom() - gs, gs, gs)

    def _start_reset_orbit(self):
        if animations_enabled():
            self._orbit_t0 = time.perf_counter()
            self._ensure_anim_clock()
        self.update()

    def _ensure_anim_clock(self):
        if not self._anim_clock.isActive():
            self._anim_clock.start()

    def _orbit_progress(self, now: float) -> float:
        elapsed = now - self._orbit_t0
        if 0.0 <= elapsed < ORBIT_DURATION_S:
            return elapsed / ORBIT_DURATION_S
        return -1.0

    def _on_anim_frame(self):
        now = time.perf_counter()
        orbit_active = 0.0 <= (now - self._orbit_t0) < ORBIT_DURATION_S
        if not orbit_active and not self.is_alarm_pulsing:
            self._anim_clock.stop()
        self.update()

    def _screen_segment_at(self, pos: QPointF, screen: QRectF) -> Optional[str]:
        if not screen.contains(pos) or not config_manager.is_timer_smart_hover_enabled():
            return None
        if self.mode == "stopwatch" or self.is_running:
            return None
        frac = (pos.x() - screen.left()) / max(1.0, screen.width())
        if self.mode == "alarm":
            return "h" if frac < 0.5 else "m"
        if self.current_seconds >= 3600:
            if frac < 0.36:
                return "h"
            return "m" if frac < 0.68 else "s"
        return "m" if frac < 0.52 else "s"

    # --- Pintura ---

    def paintEvent(self, event):
        p = QPainter(self)
        now = time.perf_counter()
        state = TimerState(
            current_seconds=self.current_seconds,
            is_running=self.is_running,
            mode=self.mode,
            is_alarm_pulsing=self.is_alarm_pulsing,
            alarm_time=self.alarm_time,
            alarm_finished=self.alarm_finished,
            time_morph=self.time_morph,
        )
        m = float(self.art_margin)
        rect = QRectF(m, m, self.width() - 2.0 * m, self.height() - 2.0 * m)
        blink_off = (int(now * 2.0) % 2) == 1
        paint_nothing_dot_timer(
            p,
            rect,
            state,
            self.theme,
            art=self.skin_theme,
            orbit_progress=self._orbit_progress(now),
            alarm_phase=max(0.0, now - self._alarm_t0),
            grille_hovered=self._grille_hovered,
            play_hovered=self._play_hovered,
            play_pressed=self._play_pressed,
            close_opacity=self._close_opacity,
            close_hovered=self._close_hovered,
            resize_hovered=self._resize_hovered,
            hovered_segment=self._hovered_segment,
            blink_off=blink_off,
        )
        p.end()

    # --- Interação ---

    def _in_circle(self, pos: QPointF, rect: QRectF) -> bool:
        c = rect.center()
        r = rect.width() * 0.5
        return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= r

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        card = self.get_card_rect()
        _screen, play_rect, grille_rect = _card_layout(card)

        if self._close_opacity > 0.2 and self.get_close_btn_rect().contains(pos):
            self.close_requested.emit()
            return
        if self.get_resize_grip_rect().contains(pos):
            self._is_resizing = True
            self._resize_start_pos = event.globalPosition().toPoint()
            self._resize_start_side = self.square_side()
            return
        if self._in_circle(pos, play_rect):
            self._play_pressed = True
            self.update()
            return
        if self._in_circle(pos, grille_rect):
            self._start_reset_orbit()
            self.reset_clicked.emit()
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
        screen, play_rect, grille_rect = _card_layout(card)

        prev = (self._close_hovered, self._resize_hovered, self._play_hovered, self._grille_hovered, self._hovered_segment)
        self._close_hovered = self._close_opacity > 0.2 and self.get_close_btn_rect().contains(pos)
        self._resize_hovered = self.get_resize_grip_rect().contains(pos)
        self._play_hovered = self._in_circle(pos, play_rect)
        self._grille_hovered = self._in_circle(pos, grille_rect)
        self._hovered_segment = self._screen_segment_at(pos, screen)

        if self._resize_hovered:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif self._close_hovered or self._play_hovered or self._grille_hovered:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._hovered_segment is not None:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if (self._close_hovered, self._resize_hovered, self._play_hovered, self._grille_hovered, self._hovered_segment) != prev:
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        card = self.get_card_rect()
        _screen, play_rect, _grille_rect = _card_layout(card)

        if self._play_pressed:
            self._play_pressed = False
            self.update()
            if self._in_circle(pos, play_rect):
                self.play_pause_clicked.emit()
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
        if not config_manager.is_timer_smart_hover_enabled() or self.is_running or self.mode == "stopwatch":
            return
        card = self.get_card_rect()
        screen, _play, _grille = _card_layout(card)
        seg = self._screen_segment_at(event.position(), screen)
        if seg is None:
            return
        step = 1 if event.angleDelta().y() > 0 else -1
        if self.mode == "alarm":
            delta = step * (3600 if seg == "h" else 60)
            self.alarm_time_changed.emit((self.alarm_time + delta) % 86400)
        else:
            mult = 3600 if seg == "h" else (60 if seg == "m" else 1)
            new_dur = max(0, min(99 * 3600 + 3599, int(round(self.current_seconds)) + step * mult))
            self.duration_changed.emit(new_dur)
        event.accept()

    def leaveEvent(self, event):
        self._play_hovered = False
        self._play_pressed = False
        self._grille_hovered = False
        self._hovered_segment = None
        super().leaveEvent(event)
