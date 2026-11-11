import math
import time
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

from app.core import osd_anchor
from app.core.typography import get_ui_font
from app.services.audio_endpoint_service import AudioEndpoint
from app.services.audio_mixer_service import AppAudioSession
from app.core.theme_art import (
    overflow_margins,
    paint_background,
    paint_card_shadow,
    paint_stickers,
    paint_stickers_behind,
)
from app.ui_components.fluent_slider import FluentSlider
from app.widgets.volume_mixer.theme import DEFAULT_THEME, MixerTheme, load_user_theme
from app.widgets.volume_mixer.app_volume_row import AppVolumeRow


class VolumeMixerFlyout(QWidget):
    """
    Flyout Redesign do Controle de Volume e Mixer por Aplicativo (Windows 11 / FluentFlyouts):
    - Posicionado no centro inferior da tela, logo acima da barra de tarefas.
    - Animação de entrada surgindo de baixo para cima em poucos ms (cubic-out).
    - Barra superior (240x50px): Ícone de Speaker (mute), Master Slider, Volume numérico e botão retrátil (^ / v).
    - Gaveta retrátil (até 240x270px): Lista de aplicativos com ícones nativos reais, sliders individuais e scroll suave.
    - Âncora configurável (8 posições, compartilhada com o Caps Lock; ver app/core/osd_anchor.py): a borda ancorada
      do card fica parada e a gaveta cresce para longe dela (para cima embaixo, para baixo no topo, dos dois lados
      no meio). Nada é desenhado de cabeça para baixo.
    """

    master_volume_dragged = Signal(int)
    master_mute_toggled = Signal()
    app_volume_dragged = Signal(str, int)
    app_mute_toggled = Signal(str)
    app_routing_changed = Signal(str, str, str)  # (app_id, flow, device_id)
    refresh_requested = Signal()
    card_top_changed = Signal(float, bool)
    card_bounds_changed = Signal(float, float, bool)   # (topo visual, base visual, ativo) em coordenadas de tela
    visibility_changed = Signal(bool)   # na tela / fora: o serviço só varre os apps com o mixer visível

    CARD_W = 240
    COLLAPSED_H = 50
    EXPANDED_MAX_H = 370
    HEADER_H = 48.5
    ROW_PITCH = 34.5
    FIRST_ROW_OFFSET_Y = 70.5
    MAX_VISIBLE_ROWS = 6

    SHADOW_MARGIN = 14
    SLIDE_TRAVEL_PX = 28
    TASKBAR_GAP_PX = 12

    HOLD_DURATION_MS = 2400
    SLIDE_IN_DURATION_S = 0.19
    SLIDE_OUT_DURATION_S = 0.16
    EXPAND_DURATION_S = 0.20

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        # Estado Master
        self.master_volume = 50
        self.master_muted = False
        self.master_slider = FluentSlider(x_start=45.0, x_end=162.0, cy=24.5)
        self.master_slider.value = 50
        self.theme: MixerTheme = DEFAULT_THEME
        # Folga da janela transparente (esq., topo, dir., base) e quanto a arte passa do card em cima/embaixo;
        # recalculados quando o tema muda
        self._margins = (float(self.SHADOW_MARGIN),) * 4
        self._art_top = 0.0
        self._art_bottom = 0.0
        self._art_left = 0.0
        self._art_right = 0.0
        self._canvas_expanded = False   # tamanho de janela em uso (recolhido ou com espaço para a gaveta)

        # Âncora na tela e empilhamento com o Caps Lock no meio da tela: o mixer desce metade da altura do
        # Caps Lock (+ o espaço entre eles) para o PAR ficar centralizado; animado para os dois se afastarem juntos
        self._anchor = osd_anchor.DEFAULT_ANCHOR
        self._caps_active = False
        self._caps_visual_h = 0.0
        self._stack_offset = 0.0
        self._stack_offset_target = 0.0

        # Estado de hover/press nos botões do cabeçalho
        self._speaker_hovered = False
        self._chevron_hovered = False
        self._chevron_pressed = False

        # Estado retrátil (Mixer de Apps)
        self.is_expanded = False
        self._expand_t = 0.0          # 0.0 = recolhido (50px), 1.0 = expandido (até EXPANDED_MAX_H)
        self._expand_start_t = 0.0
        self._expand_target_t = 0.0
        self._expand_anim_start = 0.0

        # Altura dinâmica contínua do container do card (interpolação a 144 Hz)
        self._anim_card_h = float(self.COLLAPSED_H)

        # Lista de linhas de aplicativos e rolagem (scroll)
        self._rows: list[AppVolumeRow] = []
        self._scroll_y = 0.0
        self._target_scroll_y = 0.0
        self._dragging_scrollbar = False
        self._scrollbar_drag_start_y = 0.0
        self._scrollbar_start_scroll = 0.0
        self._active_drag_row: AppVolumeRow | None = None

        # Roteamento de áudio por aplicativo (Opção B - Gaveta Inline)
        self._cached_outputs: list[AudioEndpoint] = []
        self._cached_inputs: list[AudioEndpoint] = []
        self._app_routing_map: dict[str, dict[str, str]] = {}

        # Barra de rolagem dinâmica (Fluent Design):
        # Só existe quando _max_scroll() > 0.5; aparece temporariamente em scroll ou hover
        self._scrollbar_opacity = 0.0
        self._scrollbar_target_opacity = 0.0
        self._scrollbar_hovered = False
        self._scrollbar_fade_timer = QTimer(self)
        self._scrollbar_fade_timer.setSingleShot(True)
        self._scrollbar_fade_timer.timeout.connect(self._on_scrollbar_fade_timeout)

        # Estado de animação de entrada/saída (Slide-up + Fade)
        self._slide_t = 0.0           # 0.0 = oculto embaixo, 1.0 = posição final acima da taskbar
        self._slide_start_t = 0.0
        self._slide_target_t = 0.0
        self._slide_anim_start = 0.0
        self._is_hiding = False

        # Timer de renderização sincronizado com o Refresh Rate (Hz) do monitor via PreciseTimer
        self._last_tick_time = time.perf_counter()
        self._anim_timer = QTimer(self)
        self._anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._sync_refresh_rate_interval()
        self._anim_timer.timeout.connect(self._on_tick)

        # Timer de auto-ocultação por inatividade
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._try_start_hide)

        self._apply_window_canvas_size(expanded_canvas=False)

    def _sync_refresh_rate_interval(self):
        """Ajusta o intervalo do timer para a taxa de atualização nativa do monitor onde o OSD aparece."""
        scr = self.screen() or (QApplication.instance().primaryScreen() if QApplication.instance() else None)
        hz = float(scr.refreshRate()) if scr and scr.refreshRate() > 10.0 else 60.0
        interval_ms = max(1, int(round(1000.0 / hz)))
        if self._anim_timer.interval() != interval_ms:
            self._anim_timer.setInterval(interval_ms)

    def _start_anim_timer(self):
        """Inicia o timer de animação garantindo timestamp atualizado sem freeze ou saltos residuais."""
        self._last_tick_time = time.perf_counter()
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _target_expanded_height(self) -> float:
        """Calcula a altura ideal do container adaptando-se às linhas de apps e gavetas inline abertas."""
        total_rows_h = sum(r.get_target_height() for r in self._rows)
        wanted = self.HEADER_H + total_rows_h + 14.0
        return min(float(self.EXPANDED_MAX_H), max(float(self.COLLAPSED_H), wanted))

    def _current_card_height(self) -> float:
        return self._anim_card_h

    def _visible_content_height(self) -> float:
        """Retorna a altura visível real disponível para a lista de aplicativos dentro do card."""
        current_h = self._anim_card_h if self._anim_card_h > self.COLLAPSED_H else self._target_expanded_height()
        return max(60.0, current_h - self.HEADER_H - 8.0)

    def _target_visible_content_height(self) -> float:
        """Retorna a altura visível que o card terá ao final da transição."""
        target_h = self._target_expanded_height() if self.is_expanded else float(self.COLLAPSED_H)
        return max(60.0, target_h - self.HEADER_H - 8.0)

    def on_endpoints_updated(self, outputs: list[AudioEndpoint], inputs: list[AudioEndpoint]):
        """Atualiza a lista de dispositivos de Saída e Entrada conhecidos pelo sistema."""
        self._cached_outputs = outputs
        self._cached_inputs = inputs
        for row in self._rows:
            rout = self._app_routing_map.get(row.app_id, {})
            row.set_endpoints(
                outputs,
                inputs,
                rout.get("output", "__default__"),
                rout.get("input", "__default__"),
            )
        if self.isVisible():
            self.update()

    def _on_row_routing_changed(self, app_id: str, flow: str, device_id: str):
        """Disparado quando o usuário altera a rota de um aplicativo na gaveta inline."""
        if app_id not in self._app_routing_map:
            self._app_routing_map[app_id] = {}
        self._app_routing_map[app_id][flow] = device_id
        self.app_routing_changed.emit(app_id, flow, device_id)
        self._restart_hide_timer()
        self._start_anim_timer()
        self.update()

    def _apply_window_canvas_size(self, expanded_canvas: bool):
        """Ajusta o tamanho da janela (recolhido ou com espaço para a gaveta) e a reposiciona pela âncora."""
        self._canvas_expanded = expanded_canvas
        ml, mt, mr, mb = self._margins
        win_w = int(self.CARD_W + ml + mr)
        win_h = int(self._slot_height() + mt + mb + self.SLIDE_TRAVEL_PX)
        self.setFixedSize(win_w, win_h)
        self._place_window()

    def _slot_height(self) -> float:
        """Altura máxima que o card pode ter com o tamanho de janela em uso."""
        return float(self.EXPANDED_MAX_H if self._canvas_expanded else self.COLLAPSED_H)

    def _vertical(self) -> str:
        return osd_anchor.vertical(self._anchor)

    def _place_window(self):
        """
        Move a janela para que a borda ANCORADA do card fique sempre no mesmo ponto da tela; a folga (e a arte
        que passa da borda) ficam por fora disso. Layout vertical da janela (o deslize vem do lado da âncora):
        - embaixo / meio: [folga][card][folga][deslize]
        - em cima:        [folga][deslize][card][folga]
        """
        avail = osd_anchor.primary_available_geometry()
        if avail is None:
            return
        ml, mt, _mr, mb = self._margins
        card_x = osd_anchor.card_left_x(self._anchor, avail, float(self.CARD_W), self._art_left, self._art_right)
        x = int(round(card_x - ml))
        edge_gap = self.TASKBAR_GAP_PX + self.SHADOW_MARGIN
        v = self._vertical()
        if v == "top":
            card_top = avail.y() + edge_gap + self._art_top
            y = card_top - mt - self.SLIDE_TRAVEL_PX
        elif v == "middle":
            center = avail.y() + avail.height() / 2.0 + self._stack_offset
            y = center - (mt + self._slot_height() / 2.0)
        else:
            card_bottom_gap = edge_gap + self._art_bottom
            y = avail.y() + avail.height() - card_bottom_gap + mb + self.SLIDE_TRAVEL_PX - self.height()
        self.move(x, int(round(y)))

    def _card_rect(self) -> QRectF:
        x0 = self._margins[0]
        mt = self._margins[1]
        card_h = self._current_card_height()
        slide_offset = (1.0 - self._slide_t) * self.SLIDE_TRAVEL_PX
        v = self._vertical()
        if v == "top":
            # topo fixo: a gaveta cresce para BAIXO e o card desliza vindo de cima
            y0 = mt + self.SLIDE_TRAVEL_PX - slide_offset
        elif v == "middle":
            # centro fixo: a gaveta cresce para os dois lados
            y0 = mt + self._slot_height() / 2.0 - card_h / 2.0 + slide_offset
        else:
            base_bottom = float(self.height() - self._margins[3] - self.SLIDE_TRAVEL_PX)
            y0 = base_bottom + slide_offset - card_h
        return QRectF(x0, y0, float(self.CARD_W), card_h)

    # --- Âncora e empilhamento com o Caps Lock ---

    def set_anchor(self, anchor: str):
        """Troca a âncora (Hub) e reposiciona na hora, inclusive com o flyout na tela."""
        anchor = osd_anchor.normalize(anchor)
        if anchor == self._anchor:
            return
        self._anchor = anchor
        self._update_stack_offset_target()
        self._stack_offset = self._stack_offset_target
        self._apply_window_canvas_size(expanded_canvas=self._canvas_expanded)
        if self.isVisible():
            self._notify_card_top()
            self.update()

    def anchor(self) -> str:
        return self._anchor

    def column_center_x(self) -> float | None:
        """Centro X (tela) do card na âncora atual, mesmo fora da tela: o Caps Lock se alinha por ele."""
        avail = osd_anchor.primary_available_geometry()
        if avail is None:
            return None
        left = osd_anchor.card_left_x(self._anchor, avail, float(self.CARD_W), self._art_left, self._art_right)
        return left + self.CARD_W / 2.0

    def _update_stack_offset_target(self):
        if self._vertical() == "middle" and self._caps_active:
            self._stack_offset_target = (self._caps_visual_h + osd_anchor.STACK_GAP_PX) / 2.0
        else:
            self._stack_offset_target = 0.0

    def on_caps_presence_changed(self, visual_h: float, is_active: bool):
        """O Caps Lock apareceu/sumiu: no meio da tela, abre (ou fecha) espaço para o par ficar centralizado."""
        self._caps_active = is_active
        self._caps_visual_h = float(visual_h) if is_active else 0.0
        self._update_stack_offset_target()
        if not self.isVisible():
            self._stack_offset = self._stack_offset_target
            return
        if abs(self._stack_offset - self._stack_offset_target) > 0.3:
            self._start_anim_timer()

    def _apply_theme(self, theme: MixerTheme):
        """Propaga o tema ao cabeçalho e a todas as linhas. Não faz nada se o tema não mudou."""
        if theme is self.theme:
            return
        self.theme = theme
        self.master_slider.apply_colors(
            theme.accent, theme.thumb, theme.thumb_outer, theme.thumb_border, theme.track_inactive
        )
        for row in self._rows:
            row.apply_theme(theme)
        self._update_margins()
        # A janela SEMPRE acompanha as margens (mesmo com o flyout na tela, ex.: trocar de tema no Hub): o card
        # fica no mesmo ponto da tela por construção, então não há salto; sem isso o card sairia cortado.
        self._apply_window_canvas_size(expanded_canvas=self._canvas_expanded)

    def _update_margins(self):
        """Folga da janela para sombra e figurinhas que passam da borda (senão a janela transparente as corta)."""
        base = float(self.SHADOW_MARGIN)
        ov_l, ov_t, ov_r, ov_b = overflow_margins(
            self.theme.stickers, self.theme.shadow, float(self.CARD_W), float(self.EXPANDED_MAX_H)
        )
        grow = lambda ov: max(base, math.ceil(ov) + 2.0) if ov else base
        self._margins = (grow(ov_l), grow(ov_t), grow(ov_r), grow(ov_b))
        self._art_top = float(math.ceil(ov_t)) if ov_t else 0.0
        self._art_bottom = float(math.ceil(ov_b)) if ov_b else 0.0
        self._art_left = float(math.ceil(ov_l)) if ov_l else 0.0
        self._art_right = float(math.ceil(ov_r)) if ov_r else 0.0

    def on_master_volume_changed(self, volume: int, is_muted: bool):
        """Sincroniza o estado do volume principal vindo do AudioMixerService."""
        self.master_volume = volume
        self.master_muted = is_muted
        if not self.master_slider.is_dragging:
            self.master_slider.value = volume
        self.master_slider.is_muted = is_muted
        if self.isVisible():
            self.update()

    def on_sessions_updated(self, sessions: list[AppAudioSession]):
        """Atualiza a lista de aplicativos preservando sliders e gavetas inline abertas."""
        existing_map = {r.app_id: r for r in self._rows}
        new_rows: list[AppVolumeRow] = []
        for s in sessions:
            rout = self._app_routing_map.get(s.app_id, {})
            sel_out = rout.get("output", "__default__")
            sel_in = rout.get("input", "__default__")
            if s.app_id in existing_map:
                row = existing_map[s.app_id]
                row.sync_from_session(s.volume, s.is_muted, s.icon)
                row.set_endpoints(self._cached_outputs, self._cached_inputs, sel_out, sel_in)
                new_rows.append(row)
            else:
                row = AppVolumeRow(
                    app_id=s.app_id,
                    name=s.name,
                    volume=s.volume,
                    is_muted=s.is_muted,
                    icon=s.icon,
                    on_routing_changed=self._on_row_routing_changed,
                )
                row.set_endpoints(self._cached_outputs, self._cached_inputs, sel_out, sel_in)
                row.apply_theme(self.theme)
                new_rows.append(row)
        self._rows = new_rows
        self._clamp_scroll()
        if not self._has_scrollable_content():
            self._target_scroll_y = 0.0
            self._scroll_y = 0.0
            self._scrollbar_opacity = 0.0
            self._scrollbar_target_opacity = 0.0
            self._scrollbar_hovered = False
            self._dragging_scrollbar = False
        if self.isVisible():
            self.update()

    def get_card_screen_top(self) -> float | None:
        """Retorna a coordenada Y global (tela) do topo do card se estiver visível e ativo."""
        if not self.isVisible():
            return None
        if self._is_hiding and self._slide_t <= 0.02:
            return None
        # topo VISUAL (inclui figurinhas e sombra acima do card): o Caps Lock empilha acima disso
        return float(self.y() + self._card_rect().top() - self._art_top)

    def get_card_screen_bounds(self) -> tuple[float, float] | None:
        """(topo, base) VISUAIS do card na tela, incluindo a arte que passa das bordas; None se não está ativo."""
        top = self.get_card_screen_top()
        if top is None:
            return None
        return top, float(self.y() + self._card_rect().bottom() + self._art_bottom)

    def _notify_card_top(self):
        bounds = self.get_card_screen_bounds()
        is_active = (bounds is not None)
        top, bottom = bounds if is_active else (0.0, 0.0)
        self.card_top_changed.emit(top, is_active)
        self.card_bounds_changed.emit(top, bottom, is_active)

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        # hide() direto (atalho que alterna o mixer) também precisa soltar o Caps Lock empilhado
        self.card_top_changed.emit(0.0, False)
        self.card_bounds_changed.emit(0.0, 0.0, False)
        self.visibility_changed.emit(False)
        super().hideEvent(event)

    def show_osd(self, volume: int | None = None, is_muted: bool | None = None):
        """
        Exibe o flyout animando de baixo para cima (estilo FluentFlyouts).
        Se já estiver visível, apenas atualiza os valores e renova o tempo de exposição.
        """
        self._apply_theme(load_user_theme())  # relê só se algum arquivo do tema mudou

        if volume is not None and is_muted is not None:
            self.on_master_volume_changed(volume, is_muted)

        self.refresh_requested.emit()

        now = time.perf_counter()
        if not self.isVisible() or self._is_hiding:
            if not self.isVisible():
                # Sempre inicia recolhido ao surgir por atalho de teclado
                self.is_expanded = False
                self._expand_t = 0.0
                self._expand_start_t = 0.0
                self._expand_target_t = 0.0
                self._anim_card_h = float(self.COLLAPSED_H)
                self._stack_offset = self._stack_offset_target   # já nasce no lugar certo do par
                self._apply_window_canvas_size(expanded_canvas=False)
                self._slide_t = 0.0
                for r in self._rows:
                    r.reset_routing()
                self._target_scroll_y = 0.0
                self._scroll_y = 0.0
                self.show()

            self._is_hiding = False
            self._slide_start_t = self._slide_t
            self._slide_target_t = 1.0
            self._slide_anim_start = now

        self._restart_hide_timer()
        self._sync_refresh_rate_interval()
        self._start_anim_timer()
        self._notify_card_top()
        self.update()

    def toggle_expanded(self):
        """Alterna a gaveta retrátil do mixer de volumes por aplicativo."""
        self.is_expanded = not self.is_expanded
        if self.is_expanded:
            self.refresh_requested.emit()
            self._apply_window_canvas_size(expanded_canvas=True)
        else:
            self._scrollbar_opacity = 0.0
            self._scrollbar_target_opacity = 0.0
            self._scrollbar_hovered = False
            self._dragging_scrollbar = False
            for r in self._rows:
                r.reset_routing()
            self._target_scroll_y = 0.0
            self._scroll_y = 0.0

        self._expand_start_t = self._expand_t
        self._expand_target_t = 1.0 if self.is_expanded else 0.0
        self._expand_anim_start = time.perf_counter()
        self._restart_hide_timer()
        self._sync_refresh_rate_interval()
        self._start_anim_timer()
        self._notify_card_top()
        self.update()

    def _flash_scrollbar(self):
        """Ativa a visibilidade temporária da barra de rolagem durante ou logo após o scroll."""
        if not self._has_scrollable_content():
            return
        self._scrollbar_target_opacity = 1.0
        self._scrollbar_fade_timer.stop()
        self._scrollbar_fade_timer.start(1000)
        self._start_anim_timer()

    def _on_scrollbar_fade_timeout(self):
        if not self._scrollbar_hovered and not self._dragging_scrollbar:
            self._scrollbar_target_opacity = 0.0
            self._start_anim_timer()

    def _restart_hide_timer(self):
        self._hide_timer.start(self.HOLD_DURATION_MS)

    def _is_user_interacting(self) -> bool:
        if self.master_slider.is_dragging or self._active_drag_row is not None or self._dragging_scrollbar:
            return True
        if self.underMouse():
            return True
        return False

    def _try_start_hide(self):
        if self._is_user_interacting():
            # Enquanto o mouse estiver sobre o card ou arrastando sliders, mantém aberto
            self._hide_timer.start(800)
            return
        self._is_hiding = True
        self._slide_start_t = self._slide_t
        self._slide_target_t = 0.0
        self._slide_anim_start = time.perf_counter()
        self._start_anim_timer()
        self._notify_card_top()

    def _on_tick(self):
        now = time.perf_counter()
        dt = max(0.001, min(0.05, now - self._last_tick_time))
        self._last_tick_time = now
        needs_update = False

        # 1. Animação de Slide-up / Slide-down + Opacidade
        if abs(self._slide_t - self._slide_target_t) > 0.004:
            dur = self.SLIDE_OUT_DURATION_S if self._is_hiding else self.SLIDE_IN_DURATION_S
            raw = min(1.0, max(0.0, (now - self._slide_anim_start) / dur))
            eased = 1.0 - (1.0 - raw) ** 3
            self._slide_t = self._slide_start_t + (self._slide_target_t - self._slide_start_t) * eased
            needs_update = True
        else:
            self._slide_t = self._slide_target_t

        # 2. Animação de Expansão / Retração do Mixer de Apps
        if abs(self._expand_t - self._expand_target_t) > 0.004:
            raw_e = min(1.0, max(0.0, (now - self._expand_anim_start) / self.EXPAND_DURATION_S))
            eased_e = 1.0 - (1.0 - raw_e) ** 3
            self._expand_t = self._expand_start_t + (self._expand_target_t - self._expand_start_t) * eased_e
            self._anim_card_h = self.COLLAPSED_H + (self._target_expanded_height() - self.COLLAPSED_H) * self._expand_t
            needs_update = True
            if raw_e >= 1.0 and not self.is_expanded:
                self._expand_t = 0.0
                self._anim_card_h = float(self.COLLAPSED_H)
                self._apply_window_canvas_size(expanded_canvas=False)
                for r in self._rows:
                    r.reset_routing()
                self._target_scroll_y = 0.0
                self._scroll_y = 0.0
        else:
            if self._expand_t != self._expand_target_t:
                self._expand_t = self._expand_target_t
                if not self.is_expanded:
                    self._anim_card_h = float(self.COLLAPSED_H)
                    self._apply_window_canvas_size(expanded_canvas=False)
                    for r in self._rows:
                        r.reset_routing()
                    self._target_scroll_y = 0.0
                    self._scroll_y = 0.0
                needs_update = True

            # Quando totalmente expandido, adapta a altura do container continuamente às gavetas e abas
            if self.is_expanded and abs(self._expand_t - 1.0) <= 0.004:
                target_card_h = self._target_expanded_height()
                diff_card_h = target_card_h - self._anim_card_h
                if abs(diff_card_h) > 0.15:
                    card_alpha = 1.0 - math.exp(-34.0 * dt)
                    self._anim_card_h += diff_card_h * card_alpha
                    needs_update = True
                else:
                    self._anim_card_h = target_card_h

        # 3. Interpolação suave de Scroll independente de FPS (rápida e fluida a 144 Hz)
        if abs(self._scroll_y - self._target_scroll_y) > 0.15:
            scroll_alpha = 1.0 - math.exp(-34.0 * dt)
            self._scroll_y += (self._target_scroll_y - self._scroll_y) * scroll_alpha
            needs_update = True
        else:
            self._scroll_y = self._target_scroll_y

        # 4. Animação dos thumbs dos sliders e gavetas inline dos apps a 144 Hz
        if self.master_slider.step_animation(dt):
            needs_update = True
        for r in self._rows:
            if r.step_animation(dt):
                needs_update = True
                self._clamp_scroll()

        # 5. Animação de Fade da Scrollbar (Fluent)
        if abs(self._scrollbar_opacity - self._scrollbar_target_opacity) > 0.01:
            sb_alpha = 1.0 - math.exp(-18.0 * dt)
            self._scrollbar_opacity += (self._scrollbar_target_opacity - self._scrollbar_opacity) * sb_alpha
            needs_update = True
        else:
            self._scrollbar_opacity = self._scrollbar_target_opacity

        # 6. Deslocamento do par no meio da tela (Caps Lock chegou/saiu): os dois se afastam/reaproximam do centro
        diff_off = self._stack_offset_target - self._stack_offset
        if abs(diff_off) > 0.3:
            self._stack_offset += diff_off * (1.0 - math.exp(-24.0 * dt))
            self._place_window()
            needs_update = True
        elif self._stack_offset != self._stack_offset_target:
            self._stack_offset = self._stack_offset_target
            self._place_window()
            needs_update = True

        # Notifica os limites do card para empilhar o Caps Lock cooperativamente em tempo real
        self._notify_card_top()

        if needs_update:
            self.update()

        target_card_h = self._target_expanded_height() if self.is_expanded else float(self.COLLAPSED_H)
        if (
            abs(self._slide_t - self._slide_target_t) <= 0.004
            and self._stack_offset == self._stack_offset_target
            and abs(self._expand_t - self._expand_target_t) <= 0.004
            and abs(self._anim_card_h - target_card_h) <= 0.15
            and abs(self._scroll_y - self._target_scroll_y) <= 0.15
            and abs(self._scrollbar_opacity - self._scrollbar_target_opacity) <= 0.01
            and not needs_update
        ):
            self._anim_timer.stop()
            if self._is_hiding and self._slide_t <= 0.01:
                self.hide()   # hideEvent avisa o Caps Lock que o mixer saiu
                for r in self._rows:
                    r.reset_routing()
                self._target_scroll_y = 0.0
                self._scroll_y = 0.0

    # =========================================================================
    # PINTURA 1:1 (FLUENT DESIGN)
    # =========================================================================
    def paintEvent(self, event):
        if self._slide_t <= 0.005:
            return

        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        p.setOpacity(min(1.0, self._slide_t * 1.15))

        th = self.theme
        card_rect = self._card_rect()
        x0 = card_rect.left()
        y0 = card_rect.top()

        # 1. Sombra externa: a do tema (suave, colorida) ou a multicamada original
        if th.shadow is not None:
            paint_card_shadow(p, card_rect, th.radius, th.shadow)
        else:
            for i in range(1, 6):
                sh_rect = card_rect.adjusted(-i * 1.6, -i * 1.0 + 2.0, i * 1.6, i * 2.0 + 2.0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, int(30 / i)))
                p.drawRoundedRect(sh_rect, th.radius + i, th.radius + i)

        # 1.1 Figurinhas "behind": atrás do card (só a parte que sai pelas bordas aparece)
        if th.stickers:
            paint_stickers_behind(p, card_rect, th.stickers)

        # 2. Fundo do Card (#1e1e1e) e Borda 1px (#373737)
        bg_rect = card_rect.adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(th.card_bg)
        p.setPen(QPen(th.border, 1.0))
        p.drawRoundedRect(bg_rect, th.radius, th.radius)

        # 2.1 Imagem de fundo (sobre o fundo liso, sob o conteúdo) e figurinhas "below"
        if th.background is not None:
            paint_background(p, card_rect, th.background, th.radius)
        if th.stickers:
            paint_stickers(p, card_rect, th.stickers, above=False)

        # 3. Cabeçalho: Controle Master (y0 .. y0 + 50)
        header_cy = y0 + 24.5
        self._draw_speaker_icon(p, x0 + 23.0, header_cy)

        self.master_slider.set_geometry(x0 + 45.0, x0 + 162.0, header_cy)
        self.master_slider.draw(p)

        # Número do Volume Master (ex: "40", "44")
        p.setFont(get_ui_font(14, QFont.Weight.Normal))
        p.setPen(th.muted_text if self.master_muted else th.text)
        num_rect = QRectF(x0 + 167.0, header_cy - 11.0, 31.0, 22.0)
        p.drawText(
            num_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            str(self.master_slider.value),
        )

        # Botão Retrátil (^ / v) em x0 + 203, y0 + 11 (26x26px)
        self._draw_chevron_button(p, x0 + 203.0, y0 + 11.0)

        # 4. Seção Retrátil: Mixer de Volumes por Aplicativo
        if self._expand_t > 0.01 and card_rect.height() > 52.0:
            p.save()
            clip_path = QPainterPath()
            clip_path.addRoundedRect(bg_rect, th.radius, th.radius)
            p.setClipPath(clip_path)

            # Linha divisória horizontal em y0 + 48.5 (#313131)
            sep_y = y0 + self.HEADER_H
            p.setPen(QPen(th.divider, 1.0))
            p.drawLine(QPointF(x0 + 1.0, sep_y), QPointF(x0 + self.CARD_W - 1.0, sep_y))

            # Recorte exclusivo para a área da lista de aplicativos (abaixo do divisor)
            list_clip = QRectF(x0, sep_y + 1.0, float(self.CARD_W), card_rect.height() - self.HEADER_H - 2.0)
            p.setClipRect(list_clip, Qt.ClipOperation.IntersectClip)

            curr_y = y0 + (self.FIRST_ROW_OFFSET_Y - self.ROW_PITCH * 0.5) - self._scroll_y
            for row in self._rows:
                row_h = row.get_total_height()
                if curr_y + row_h >= sep_y and curr_y <= card_rect.bottom():
                    row.draw(p, x0, curr_y)
                curr_y += row_h

            # Barra de rolagem lateral direita (x_rel = 232..235.5)
            self._draw_scrollbar(p, x0, y0, card_rect.height())
            p.restore()

        # 5. Figurinhas "above" (por cima de tudo, fora do recorte da lista)
        if th.stickers:
            paint_stickers(p, card_rect, th.stickers, above=True)

    def _draw_speaker_icon(self, p: QPainter, cx: float, cy: float):
        """Desenha o ícone vetorial de alto-falante fiel ao Windows 11 (com ondas dinâmicas ou mudo)."""
        if self._speaker_hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 20))
            p.drawRoundedRect(QRectF(cx - 12.0, cy - 12.0, 24.0, 24.0), 4.0, 4.0)

        pen = QPen(self.theme.icon, 1.45)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Cone do alto-falante (x: cx-6 .. cx+0.5, y: cy-5.5 .. cy+5.5)
        cone = QPainterPath()
        cone.moveTo(cx - 5.5, cy - 2.2)
        cone.lineTo(cx - 2.8, cy - 2.2)
        cone.lineTo(cx + 0.6, cy - 5.2)
        cone.lineTo(cx + 0.6, cy + 5.2)
        cone.lineTo(cx - 2.8, cy + 2.2)
        cone.lineTo(cx - 5.5, cy + 2.2)
        cone.closeSubpath()
        p.drawPath(cone)

        vol = self.master_slider.value
        if self.master_muted or vol == 0:
            # X de mudo à direita do cone
            p.drawLine(QPointF(cx + 3.2, cy - 2.4), QPointF(cx + 7.2, cy + 2.4))
            p.drawLine(QPointF(cx + 7.2, cy - 2.4), QPointF(cx + 3.2, cy + 2.4))
        else:
            # 1ª onda sonora
            p.drawArc(QRectF(cx + 0.2, cy - 3.3, 4.4, 6.6), -55 * 16, 110 * 16)
            # 2ª onda sonora (para volumes >= 35%)
            if vol >= 35:
                p.drawArc(QRectF(cx + 1.2, cy - 5.5, 6.6, 11.0), -55 * 16, 110 * 16)

    def _draw_chevron_button(self, p: QPainter, bx: float, by: float):
        """Desenha o botão quadrado 26x26px (#2c2c2c, borda #343434) com o chevron animado (^ <-> v)."""
        btn_rect = QRectF(bx, by, 26.0, 26.0)
        th = self.theme
        if self._chevron_pressed:
            bg = th.button_pressed
        elif self._chevron_hovered:
            bg = th.button_hover
        else:
            bg = th.button_bg

        p.setBrush(bg)
        p.setPen(QPen(th.button_border, 1.0))
        p.drawRoundedRect(btn_rect, th.button_radius, th.button_radius)

        # Chevron centralizado em (bx + 13, by + 13)
        # Quando recolhido (_expand_t = 0.0): aponta para CIMA (^)
        # Quando expandido (_expand_t = 1.0): aponta para BAIXO (v)
        cx = bx + 13.0
        cy = by + 13.3
        dy = -2.1 + 4.2 * self._expand_t  # -2.1 (topo do ^) -> +2.1 (ponta do v)
        if self._vertical() == "top":
            dy = -dy   # ancorado no topo a gaveta abre para baixo: a seta aponta para onde ela vai crescer

        ic = self.theme.icon  # a seta é ~4% mais escura que o ícone (padrão: 255 -> 245)
        chev_pen = QPen(QColor(ic.red() * 245 // 255, ic.green() * 245 // 255, ic.blue() * 245 // 255, ic.alpha()), 1.5)
        chev_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        chev_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(chev_pen)

        path = QPainterPath()
        path.moveTo(cx - 4.2, cy - dy)
        path.lineTo(cx, cy + dy)
        path.lineTo(cx + 4.2, cy - dy)
        p.drawPath(path)

    def _max_scroll(self) -> float:
        total_rows_h = sum(r.get_total_height() for r in self._rows)
        visible_h = self._visible_content_height()
        return max(0.0, total_rows_h - visible_h)

    def _target_max_scroll(self) -> float:
        total_rows_h = sum(r.get_target_height() for r in self._rows)
        visible_h = self._target_visible_content_height()
        return max(0.0, total_rows_h - visible_h)

    def _clamp_scroll(self):
        mx = self._target_max_scroll()
        self._target_scroll_y = max(0.0, min(mx, self._target_scroll_y))
        if self._scroll_y < 0.0:
            self._scroll_y = 0.0

    def _has_scrollable_content(self) -> bool:
        return self._target_max_scroll() > 0.5 or self._max_scroll() > 0.5

    def _ensure_row_drawer_visible(self, target_row: AppVolumeRow):
        """
        Rola suavemente para acomodar a gaveta aberta de um aplicativo quando o conteúdo
        ultrapassa a altura máxima suportada pelo card.
        - Se o container se adaptar naturalmente (até EXPANDED_MAX_H), nenhum scroll é necessário.
        - Se a gaveta ultrapassar a área visível: rola para cima até que todos
          os dispositivos fiquem visíveis (com o Guard Rail que nunca empurra o app para fora do topo).
        - Se a gaveta encolher (ex: aba com menos itens): ajusta suavemente o scroll para baixo,
          eliminando qualquer queda brusca e garantindo transição fluida a 144 Hz.
        """
        if not target_row.is_routing_open:
            return

        # Posição da linha do aplicativo na lista somando as alturas alvo das linhas anteriores
        row_top_in_list = 0.0
        for r in self._rows:
            if r is target_row:
                break
            row_top_in_list += r.get_target_height()

        target_row_h = target_row.get_target_height()
        row_bottom_in_list = row_top_in_list + target_row_h

        # Altura visível de referência adaptável da lista de aplicativos
        visible_h = self._target_visible_content_height()

        # 1. Se o rodapé da gaveta ultrapassar a área visível inferior atual (anima scroll para cima):
        current_visible_bottom = self._target_scroll_y + visible_h
        if row_bottom_in_list > current_visible_bottom:
            needed_scroll = row_bottom_in_list - visible_h
            # Guard Rail solicitado: o app escolhido nunca ultrapassa o topo do container
            max_allowed_scroll = row_top_in_list
            target_scroll = min(needed_scroll, max_allowed_scroll)
            max_scroll = self._target_max_scroll()
            self._target_scroll_y = max(self._target_scroll_y, min(max_scroll, target_scroll))
            self._flash_scrollbar()
        else:
            # 2. Se a gaveta encolheu (aba com menos itens): anima o scroll para baixo suavemente
            max_scroll = self._target_max_scroll()
            desired_bottom_scroll = max(0.0, row_bottom_in_list - visible_h)
            new_target = max(0.0, min(max_scroll, desired_bottom_scroll))
            if new_target < self._target_scroll_y:
                self._target_scroll_y = new_target
                self._flash_scrollbar()

        self._start_anim_timer()

    def _scrollbar_track_rect(self, x0: float, y0: float, card_h: float) -> QRectF:
        track_top = y0 + self.HEADER_H + 4.0
        track_bottom = y0 + card_h - 10.0
        track_h = max(20.0, track_bottom - track_top)
        return QRectF(x0 + 224.0, track_top, 15.0, track_h)

    def _scrollbar_thumb_rect(self, x0: float, y0: float, card_h: float) -> QRectF:
        if not self._has_scrollable_content():
            return QRectF()
        track_top = y0 + self.HEADER_H + 6.0
        track_bottom = y0 + card_h - 12.0
        track_h = max(20.0, track_bottom - track_top)
        mx = self._max_scroll()
        total_rows_h = max(1.0, sum(r.get_total_height() for r in self._rows))
        visible_h = max(60.0, card_h - self.HEADER_H - 8.0)
        ratio = min(1.0, visible_h / total_rows_h)
        thumb_h = max(28.0, track_h * ratio)
        scroll_ratio = max(0.0, min(1.0, self._scroll_y / mx)) if mx > 0.0 else 0.0
        thumb_y = track_top + (track_h - thumb_h) * scroll_ratio

        is_active = self._scrollbar_hovered or self._dragging_scrollbar
        w = 5.0 if is_active else 3.0
        thumb_x = x0 + 231.5 if is_active else x0 + 233.0
        return QRectF(thumb_x, thumb_y, w, thumb_h)

    def _draw_scrollbar(self, p: QPainter, x0: float, y0: float, card_h: float):
        if not self._has_scrollable_content() or self._scrollbar_opacity <= 0.01:
            return
        thumb_rect = self._scrollbar_thumb_rect(x0, y0, card_h)
        if thumb_rect.isEmpty():
            return
        is_active = self._scrollbar_hovered or self._dragging_scrollbar
        color = (
            QColor(220, 220, 220, int(255 * self._scrollbar_opacity))
            if is_active
            else QColor(160, 160, 160, int(210 * self._scrollbar_opacity))
        )
        radius = thumb_rect.width() * 0.5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(thumb_rect, radius, radius)

    # =========================================================================
    # INTERAÇÃO DE MOUSE (SLIDERS, MUTE, BOTÃO RETRÁTIL E SCROLL)
    # =========================================================================
    def _speaker_hit_rect(self, x0: float, y0: float) -> QRectF:
        return QRectF(x0 + 11.0, y0 + 11.0, 25.0, 26.0)

    def _chevron_hit_rect(self, x0: float, y0: float) -> QRectF:
        return QRectF(x0 + 202.0, y0 + 10.0, 28.0, 28.0)

    def mousePressEvent(self, event):
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            return
        pt = event.position()
        card_rect = self._card_rect()
        x0, y0 = card_rect.left(), card_rect.top()
        self._restart_hide_timer()

        # Interações de botão esquerdo no cabeçalho
        if event.button() == Qt.MouseButton.LeftButton:
            # 1. Clique no botão retrátil (^ / v)
            if self._chevron_hit_rect(x0, y0).contains(pt):
                self._chevron_pressed = True
                self.update()
                return

            # 2. Clique no ícone de alto-falante Master (Mute/Unmute)
            if self._speaker_hit_rect(x0, y0).contains(pt):
                self.master_mute_toggled.emit()
                return

            # 3. Clique/Arrasto no Slider Master
            self.master_slider.set_geometry(x0 + 45.0, x0 + 162.0, y0 + 24.5)
            if self.master_slider.contains(pt):
                self.master_slider.is_dragging = True
                new_val = self.master_slider.value_from_x(pt.x())
                self.master_slider.value = new_val
                self.master_volume_dragged.emit(new_val)
                self._start_anim_timer()
                self.update()
                return

        # 4. Interação na gaveta do Mixer de Apps (quando expandida)
        if self._expand_t > 0.5 and pt.y() > y0 + self.HEADER_H:
            # Scrollbar apenas no botão esquerdo
            if event.button() == Qt.MouseButton.LeftButton and self._has_scrollable_content():
                track_rect = self._scrollbar_track_rect(x0, y0, card_rect.height())
                if track_rect.contains(pt):
                    thumb_rect = self._scrollbar_thumb_rect(x0, y0, card_rect.height())
                    self._dragging_scrollbar = True
                    self._scrollbar_drag_start_y = pt.y()
                    self._scrollbar_start_scroll = self._scroll_y
                    self._scrollbar_target_opacity = 1.0
                    self._scrollbar_fade_timer.stop()
                    # Se clicou no track fora do thumb, centraliza o thumb na posição clicada
                    if not thumb_rect.contains(pt):
                        track_top = y0 + self.HEADER_H + 6.0
                        track_bottom = y0 + card_rect.height() - 12.0
                        track_h = max(20.0, track_bottom - track_top)
                        thumb_h = thumb_rect.height()
                        avail_travel = max(1.0, track_h - thumb_h)
                        ratio = max(0.0, min(1.0, (pt.y() - track_top - thumb_h * 0.5) / avail_travel))
                        self._target_scroll_y = ratio * self._max_scroll()
                        self._scroll_y = self._target_scroll_y
                        self._scrollbar_start_scroll = self._scroll_y
                    self._start_anim_timer()
                    self.update()
                    return

            curr_y = y0 + (self.FIRST_ROW_OFFSET_Y - self.ROW_PITCH * 0.5) - self._scroll_y
            for idx, row in enumerate(self._rows):
                row_h = row.get_total_height()
                if curr_y + row_h >= y0 + self.HEADER_H and curr_y <= card_rect.bottom():
                    cy = curr_y + row.MAIN_ROW_CY

                    # A) Botão DIREITO: abre/fecha gaveta inline de roteamento (Opção B)
                    if event.button() == Qt.MouseButton.RightButton:
                        if row.icon_hit_rect(x0, cy).contains(pt):
                            # Modo Accordion: fecha as outras para evitar poluição visual e excesso de rolagem
                            for other in self._rows:
                                if other is not row:
                                    other.close_routing()
                            row.handle_mouse_press(pt, Qt.MouseButton.RightButton, x0, curr_y)
                            # Se a gaveta acabou de abrir, acomoda com auto-scroll e Guard Rail
                            if row.is_routing_open:
                                self._ensure_row_drawer_visible(row)
                            else:
                                self._clamp_scroll()
                            self._start_anim_timer()
                            self.update()
                            return

                    # B) Botão ESQUERDO: mute no ícone, arrasto de volume ou cliques internos na gaveta
                    elif event.button() == Qt.MouseButton.LeftButton:
                        # Mute no ícone
                        if row.icon_hit_rect(x0, cy).contains(pt):
                            self.app_mute_toggled.emit(row.app_id)
                            return

                        # Slider do app
                        row.slider.set_geometry(x0 + 45.0, x0 + 186.0, cy)
                        if row.slider.contains(pt):
                            row.slider.is_dragging = True
                            self._active_drag_row = row
                            new_val = row.slider.value_from_x(pt.x())
                            row.slider.value = new_val
                            row.volume = new_val
                            self.app_volume_dragged.emit(row.app_id, new_val)
                            self._start_anim_timer()
                            self.update()
                            return

                        # Cliques dentro da gaveta inline (botão ✕, abas de saída/entrada, pill switches)
                        if row.is_routing_open and row.handle_mouse_press(pt, Qt.MouseButton.LeftButton, x0, curr_y):
                            if row.is_routing_open:
                                self._ensure_row_drawer_visible(row)
                            else:
                                self._clamp_scroll()
                            self._start_anim_timer()
                            self.update()
                            return

                curr_y += row_h

    def mouseMoveEvent(self, event):
        pt = event.position()
        card_rect = self._card_rect()
        x0, y0 = card_rect.left(), card_rect.top()
        self._restart_hide_timer()

        # 1. Arrastando Slider Master
        if self.master_slider.is_dragging:
            new_val = self.master_slider.value_from_x(pt.x())
            if new_val != self.master_slider.value:
                self.master_slider.value = new_val
                self.master_volume_dragged.emit(new_val)
                self.update()
            return

        # 2. Arrastando Slider de um Aplicativo
        if self._active_drag_row is not None:
            new_val = self._active_drag_row.slider.value_from_x(pt.x())
            if new_val != self._active_drag_row.slider.value:
                self._active_drag_row.slider.value = new_val
                self._active_drag_row.volume = new_val
                self.app_volume_dragged.emit(self._active_drag_row.app_id, new_val)
                self.update()
            return

        # 3. Arrastando Scrollbar
        if self._dragging_scrollbar and self._has_scrollable_content():
            track_top = y0 + self.HEADER_H + 6.0
            track_bottom = y0 + card_rect.height() - 12.0
            track_h = max(20.0, track_bottom - track_top)
            thumb_rect = self._scrollbar_thumb_rect(x0, y0, card_rect.height())
            thumb_h = max(28.0, thumb_rect.height())
            avail_travel = max(1.0, track_h - thumb_h)
            dy = pt.y() - self._scrollbar_drag_start_y
            mx = self._max_scroll()
            self._target_scroll_y = max(0.0, min(mx, self._scrollbar_start_scroll + (dy / avail_travel) * mx))
            self._scroll_y = self._target_scroll_y
            self.update()
            return

        # 4. Atualização de estados de Hover e Tooltips
        changed = False
        spk_hov = self._speaker_hit_rect(x0, y0).contains(pt)
        chv_hov = self._chevron_hit_rect(x0, y0).contains(pt)
        self.master_slider.set_geometry(x0 + 45.0, x0 + 162.0, y0 + 24.5)
        ms_hov = self.master_slider.contains(pt)

        # Hover na scrollbar
        if self._has_scrollable_content() and self._expand_t > 0.5 and pt.y() > y0 + self.HEADER_H:
            track_rect = self._scrollbar_track_rect(x0, y0, card_rect.height())
            sb_hov = track_rect.contains(pt)
            if sb_hov != self._scrollbar_hovered:
                self._scrollbar_hovered = sb_hov
                changed = True
                if sb_hov:
                    self._scrollbar_target_opacity = 1.0
                    self._scrollbar_fade_timer.stop()
                else:
                    if not self._dragging_scrollbar:
                        self._scrollbar_fade_timer.start(800)
        else:
            if self._scrollbar_hovered:
                self._scrollbar_hovered = False
                changed = True
                if not self._dragging_scrollbar:
                    self._scrollbar_fade_timer.start(800)

        changed = (
            changed
            or (spk_hov != self._speaker_hovered)
            or (chv_hov != self._chevron_hovered)
            or (ms_hov != self.master_slider.is_hovered)
        )
        self._speaker_hovered = spk_hov
        self._chevron_hovered = chv_hov
        self.master_slider.is_hovered = ms_hov

        hovered_app_name = ""
        curr_y = y0 + (self.FIRST_ROW_OFFSET_Y - self.ROW_PITCH * 0.5) - self._scroll_y
        for idx, row in enumerate(self._rows):
            row_h = row.get_total_height()
            visible = self._expand_t > 0.5 and (curr_y + row_h >= y0 + self.HEADER_H and curr_y <= card_rect.bottom())
            cy = curr_y + row.MAIN_ROW_CY
            ic_hov = visible and row.icon_hit_rect(x0, cy).contains(pt)
            row.slider.set_geometry(x0 + 45.0, x0 + 186.0, cy)
            sl_hov = visible and row.slider.contains(pt)

            if ic_hov != row.icon_hovered or sl_hov != row.slider.is_hovered:
                changed = True
            row.icon_hovered = ic_hov
            row.slider.is_hovered = sl_hov
            if ic_hov and not row.is_routing_open:
                hovered_app_name = row.name

            if row.is_routing_open and visible:
                if row.handle_mouse_move(pt, x0, curr_y):
                    changed = True

            curr_y += row_h

        if hovered_app_name:
            QToolTip.showText(event.globalPosition().toPoint(), hovered_app_name, self)
        else:
            QToolTip.hideText()

        if changed:
            self._start_anim_timer()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pt = event.position()
        card_rect = self._card_rect()
        x0, y0 = card_rect.left(), card_rect.top()

        if self._chevron_pressed:
            self._chevron_pressed = False
            if self._chevron_hit_rect(x0, y0).contains(pt):
                self.toggle_expanded()
            self.update()

        if self.master_slider.is_dragging:
            self.master_slider.is_dragging = False
            self._start_anim_timer()

        if self._active_drag_row is not None:
            self._active_drag_row.slider.is_dragging = False
            self._active_drag_row = None
            self._start_anim_timer()

        if self._dragging_scrollbar:
            self._dragging_scrollbar = False
            if not self._scrollbar_hovered:
                self._scrollbar_fade_timer.start(800)
            self._start_anim_timer()

        self._restart_hide_timer()

    def leaveEvent(self, event):
        self._speaker_hovered = False
        self._chevron_hovered = False
        self._chevron_pressed = False
        self.master_slider.is_hovered = False
        self._scrollbar_hovered = False
        if not self._dragging_scrollbar:
            self._scrollbar_target_opacity = 0.0
        for row in self._rows:
            row.icon_hovered = False
            row.slider.is_hovered = False
        self._start_anim_timer()
        self._restart_hide_timer()
        self.update()

    def wheelEvent(self, event: QWheelEvent):
        pt = event.position()
        card_rect = self._card_rect()
        y0 = card_rect.top()
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self._restart_hide_timer()

        # Se rolar o scroll sobre o cabeçalho (ou com mixer fechado), ajusta o volume Master em +-2%
        if not self.is_expanded or pt.y() <= y0 + self.HEADER_H:
            step = 2 if delta > 0 else -2
            new_vol = max(0, min(100, self.master_slider.value + step))
            self.master_slider.value = new_vol
            self.master_volume_dragged.emit(new_vol)
            self.update()
            return

        # Se rolar sobre a lista do mixer expandido, rola a lista de aplicativos suavemente
        if self._has_scrollable_content():
            mx = self._max_scroll()
            scroll_step = -self.ROW_PITCH * 0.85 if delta > 0 else self.ROW_PITCH * 0.85
            self._target_scroll_y = max(0.0, min(mx, self._target_scroll_y + scroll_step))
            self._flash_scrollbar()
            self._start_anim_timer()
            self.update()
