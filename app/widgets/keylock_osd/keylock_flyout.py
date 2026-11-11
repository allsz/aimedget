import math
import time
from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QFont
from PySide6.QtWidgets import QApplication, QWidget
from app.core import osd_anchor
from app.core.theme_art import overflow_margins
from app.core.typography import get_ui_font
from app.widgets.keylock_osd.skin import KeyLockState, card_size, paint_keylock
from app.widgets.keylock_osd.theme import DEFAULT_THEME, effective_scale, load_user_theme


class KeyLockFlyout(QWidget):
    """
    OSD Flyout para Caps Lock e Num Lock:
    - Container adaptável ao tamanho do conteúdo (sem espaço vazio à direita)
    - Posicionado levemente acima da barra de tarefas
    - Animação curta de entrada vinda de baixo (começa menor e mais abaixo, crescendo até o tamanho/posição real)
    - Cadeado vetorial com animação mecânica fluida ao fechar (ON) e ao abrir (OFF)
    - Barra inferior (pílula) animada entre 36px (#29414d) no OFF e 60px (#4cc2ff) no ON
    - Não rouba foco da janela ativa (WA_ShowWithoutActivating)
    - Âncora configurável (8 posições, compartilhada com o Mixer; ver app/core/osd_anchor.py)
    """

    # Altura visual (card + arte) ao aparecer, ou (0, False) ao sair: no meio da tela o mixer abre espaço para o par
    stack_presence_changed = Signal(float, bool)

    CARD_H = 50
    EDGE_GAP_Y = 10.0   # distância do card à borda de cima/baixo da área útil
    PAD_LEFT = 18.0
    ICON_W = 14.0
    ICON_TEXT_GAP = 15.0
    PAD_RIGHT = 18.0

    SHADOW_MARGIN_X = 16
    SHADOW_MARGIN_TOP = 16
    # Margem inferior extra na janela transparente para acomodar o surgimento vindo de baixo sem corte
    SLIDE_TRAVEL_Y = 26
    SHADOW_MARGIN_BOTTOM = 12 + SLIDE_TRAVEL_Y

    HOLD_DURATION_MS = 1450
    POPUP_ANIM_DURATION_S = 0.19
    LOCK_ANIM_DURATION_S = 0.28
    FADE_OUT_DURATION_S = 0.16

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

        self.key_label = "Caps Lock"
        self.is_on = False
        self.theme = DEFAULT_THEME
        self.card_w = 132.0
        self.card_h = float(self.CARD_H)   # altura do cartão (o tema pode definir outra com `size`)
        # Folga da janela transparente em volta do card (esq., topo, dir., base) e quanto a arte
        # (figurinhas) passa para baixo do card; recalculados a cada tema/texto em _recalculate_size
        self._margins = (float(self.SHADOW_MARGIN_X), float(self.SHADOW_MARGIN_TOP),
                         float(self.SHADOW_MARGIN_X), float(self.SHADOW_MARGIN_BOTTOM))
        self._art_bottom = 0.0
        self._art_top = 0.0
        self._art_left = 0.0
        self._art_right = 0.0
        self._scale = 1.0   # escala efetiva (tema x tela); recalculada junto com o tamanho
        self._anchor = osd_anchor.DEFAULT_ANCHOR
        self._column_provider = None   # ver set_column_provider (alinhamento com o mixer nas colunas laterais)

        # Estado da animação do cadeado e pílula:
        # 0.0 = totalmente aberto (OFF), 1.0 = totalmente fechado (ON)
        self._anim_start_val = 0.0
        self._anim_target_val = 0.0
        self._anim_val = 0.0
        self._anim_start_time = 0.0
        self._is_closing_anim = False

        # Progresso de presença do popup (0.0 = pequeno/abaixo/invisível, 1.0 = tamanho e posição reais)
        self._popup_progress = 0.0
        self._popup_target = 0.0
        self._last_tick_time = time.perf_counter()

        # Empilhamento cooperativo com VolumeMixerFlyout (Flyout Stacking):
        self._mixer_active = False
        self._mixer_card_top: float | None = None      # topo visual do mixer (com a arte), em coordenadas de tela
        self._mixer_card_bottom: float | None = None   # base visual do mixer (com a arte)
        self._current_win_y: float = 0.0
        self._target_win_y: float = 0.0
        self.GAP_BETWEEN_FLYOUTS = osd_anchor.STACK_GAP_PX

        # Timer de renderização sincronizado com o Refresh Rate (Hz) do monitor via PreciseTimer
        self._anim_timer = QTimer(self)
        self._anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._sync_refresh_rate_interval()
        self._anim_timer.timeout.connect(self._on_tick)

        # Timer para ocultar automaticamente após exibição
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade_out)

        self._recalculate_size()
        self.position_on_screen()

    def _sync_refresh_rate_interval(self):
        scr = self.screen() or (QApplication.instance().primaryScreen() if QApplication.instance() else None)
        hz = float(scr.refreshRate()) if scr and scr.refreshRate() > 10.0 else 60.0
        interval_ms = max(1, int(round(1000.0 / hz)))
        if self._anim_timer.interval() != interval_ms:
            self._anim_timer.setInterval(interval_ms)

    def _get_label_font(self) -> QFont:
        return get_ui_font(14, QFont.Weight.Normal)

    def _recalculate_size(self):
        """
        Calcula a largura exata do card com base no conteúdo (ícone + gap + texto + paddings simétricos)
        e o tamanho da janela: card (vezes a escala do tema) + folga para sombra e figurinhas que
        passam da borda (sem isso a janela transparente as cortaria).
        """
        size = card_size(self.theme, self.key_label)
        self.card_w, self.card_h = size.width(), size.height()

        s = self._scale = effective_scale(self.theme)
        ov_l, ov_t, ov_r, ov_b = overflow_margins(self.theme.stickers, self.theme.shadow, self.card_w, self.card_h)
        ml = max(float(self.SHADOW_MARGIN_X), math.ceil(ov_l * s) + 2.0) if ov_l else float(self.SHADOW_MARGIN_X)
        mr = max(float(self.SHADOW_MARGIN_X), math.ceil(ov_r * s) + 2.0) if ov_r else float(self.SHADOW_MARGIN_X)
        mt = max(float(self.SHADOW_MARGIN_TOP), math.ceil(ov_t * s) + 2.0) if ov_t else float(self.SHADOW_MARGIN_TOP)
        below = max(12.0, math.ceil(ov_b * s) + 2.0) if ov_b else 12.0  # folga sob o card, além do deslize de entrada
        # O deslize de entrada vem do lado da borda ancorada: de cima nas âncoras do topo, de baixo nas demais
        if self._slides_from_top():
            self._margins = (ml, mt + self.SLIDE_TRAVEL_Y, mr, below)
        else:
            self._margins = (ml, mt, mr, below + self.SLIDE_TRAVEL_Y)
        self._art_bottom = float(math.ceil(ov_b * s)) if ov_b else 0.0
        self._art_top = float(math.ceil(ov_t * s)) if ov_t else 0.0
        self._art_left = float(math.ceil(ov_l * s)) if ov_l else 0.0
        self._art_right = float(math.ceil(ov_r * s)) if ov_r else 0.0

        win_w = int(self.card_w * s + ml + mr)
        win_h = int(self.card_h * s + self._margins[1] + self._margins[3])
        if self.width() != win_w or self.height() != win_h:
            self.setFixedSize(win_w, win_h)

    # --- Âncora na tela ---

    def _slides_from_top(self) -> bool:
        return osd_anchor.vertical(self._anchor) == "top"

    def set_column_provider(self, provider):
        """
        `provider()` devolve o centro X da coluna em que o Caps Lock deve se alinhar (a do mixer, quando os dois
        dividem uma âncora lateral) ou None para usar a própria posição.
        """
        self._column_provider = provider

    def is_presenting(self) -> bool:
        """True enquanto está aparecendo ou na tela (False durante a saída)."""
        return self._popup_target == 1.0

    def set_anchor(self, anchor: str, force: bool = False):
        """Troca a âncora (Hub). Recalcula a janela (o deslize muda de lado) e reposiciona na hora."""
        anchor = osd_anchor.normalize(anchor)
        if anchor == self._anchor and not force:
            return
        self._anchor = anchor
        self._recalculate_size()
        self._target_win_y = self._compute_target_win_y()
        self._current_win_y = self._target_win_y
        self.move(self._get_centered_x(), int(round(self._current_win_y)))
        self.update()

    def anchor(self) -> str:
        return self._anchor

    def visual_height(self) -> float:
        """Altura que o flyout ocupa na tela: card escalado + a arte que passa da borda de cima e de baixo."""
        return self.card_h * self._scale + self._art_top + self._art_bottom

    def _get_centered_x(self) -> int:
        """X da janela que põe o CARD (não a janela inteira) na coluna da âncora (esquerda, centro ou direita)."""
        avail = osd_anchor.primary_available_geometry()
        if avail is None:
            return int(round(self.x()))
        ml, _mt, mr, _mb = self._margins
        card_px_w = self.width() - ml - mr
        column = self._column_provider() if self._column_provider is not None else None
        if column is not None:
            card_x = column - card_px_w / 2.0   # alinhado pelo centro com o mixer da mesma coluna
        else:
            card_x = osd_anchor.card_left_x(self._anchor, avail, card_px_w, self._art_left, self._art_right)
        # a arte que passa da lateral nunca sai da tela
        card_x = max(card_x, avail.x() + 4.0 + self._art_left)
        card_x = min(card_x, avail.x() + avail.width() - 4.0 - self._art_right - card_px_w)
        return int(round(card_x - ml))

    def _get_default_target_y(self) -> float:
        """Y da janela com o Caps Lock sozinho na tela, conforme a linha da âncora."""
        avail = osd_anchor.primary_available_geometry()
        if avail is None:
            return 0.0
        card_h_px = self.card_h * self._scale
        mt = self._margins[1]
        v = osd_anchor.vertical(self._anchor)
        if v == "top":
            # a arte que passa do topo do card não pode sair da tela: o card desce o equivalente
            return float(avail.y() + self.EDGE_GAP_Y + self._art_top - mt)
        if v == "middle":
            return float(avail.y() + avail.height() / 2.0 - card_h_px / 2.0 - mt)
        card_bottom_in_win = mt + card_h_px
        # a arte que pende sob o card não pode invadir a barra de tarefas: o card sobe o equivalente
        return float(avail.y() + avail.height() - card_bottom_in_win - self.EDGE_GAP_Y - self._art_bottom)

    def _compute_target_win_y(self) -> float:
        default_y = self._get_default_target_y()
        if not self._mixer_active or self._mixer_card_top is None:
            return default_y

        card_h_px = self.card_h * self._scale
        mt = self._margins[1]
        avail = osd_anchor.primary_available_geometry()
        v = osd_anchor.vertical(self._anchor)

        if v == "top":
            # Espelho do empilhamento: o mixer ocupa o topo e o Caps Lock desce para logo abaixo dele
            mixer_bottom = self._mixer_card_bottom if self._mixer_card_bottom is not None else self._mixer_card_top
            target_win_y = mixer_bottom + self.GAP_BETWEEN_FLYOUTS + self._art_top - mt
            if avail is not None:
                max_y = float(avail.y() + avail.height() - 4) - card_h_px - self._art_bottom - mt
                target_win_y = min(max_y, target_win_y)
            return max(default_y, target_win_y)

        # Embaixo e no meio: a base do Caps Lock fica GAP_BETWEEN_FLYOUTS pixels acima do topo do Mixer
        target_win_y = (self._mixer_card_top - self.GAP_BETWEEN_FLYOUTS - self._art_bottom - card_h_px) - mt
        if avail is not None:
            target_win_y = max(float(avail.y() + 4), target_win_y)
        if v == "middle":
            return target_win_y   # no meio o par todo se recentraliza: o Caps Lock pode subir ou descer
        return min(default_y, target_win_y)

    def on_mixer_geometry_changed(self, card_top: float, is_active: bool):
        """Compatibilidade: só o topo do mixer (suficiente para as âncoras de baixo e do meio)."""
        self.on_mixer_bounds_changed(card_top, card_top, is_active)

    def on_mixer_bounds_changed(self, card_top: float, card_bottom: float, is_active: bool):
        """
        Atualização em tempo real dos limites visuais do card do Volume Mixer para empilhar o Caps Lock.
        Quando o mixer está ativo, aplica sincronização lockstep 1:1 sem atraso de fase:
        o Caps Lock move-se no exato mesmo frame e pela mesma quantidade de pixels do mixer.
        """
        self._mixer_active = is_active
        self._mixer_card_top = card_top if is_active else None
        self._mixer_card_bottom = card_bottom if is_active else None
        self._target_win_y = self._compute_target_win_y()

        if is_active:
            # Sincronização 1:1 absoluta e sem atraso de fase (Lockstep) com o Volume Mixer:
            # Move o card no mesmo instante exato em que o topo do mixer se move.
            self._current_win_y = self._target_win_y
            if self.isVisible():
                self.move(self._get_centered_x(), int(round(self._current_win_y)))
                self.update()
        else:
            # Quando o mixer se fecha ou desaparece, o Caps Lock retorna suavemente à posição padrão
            if self.isVisible():
                if abs(self._current_win_y - self._target_win_y) > 0.4:
                    self._last_tick_time = time.perf_counter()
                    if not self._anim_timer.isActive():
                        self._anim_timer.start()
            else:
                self._current_win_y = self._target_win_y

    def position_on_screen(self):
        """Posiciona o OSD centralizado horizontalmente e na altura correta (acima da taskbar ou do mixer)."""
        x = self._get_centered_x()
        self._target_win_y = self._compute_target_win_y()
        if not self.isVisible() or self._current_win_y <= 0 or self._mixer_active:
            self._current_win_y = self._target_win_y
        self.move(x, int(round(self._current_win_y)))

    def show_osd(self, key_name: str, is_on: bool):
        """
        Exibe o flyout para 'Caps Lock' ou 'Num Lock', adaptando a largura ao texto,
        fazendo o card surgir de baixo crescendo até o tamanho real e animando o cadeado.
        """
        self.key_label = key_name
        self.is_on = is_on
        self.theme = load_user_theme()  # relê só se o arquivo mudou: editar o tema = ver na próxima tecla
        self._recalculate_size()
        self.position_on_screen()

        # Garante que a transição completa de abrir/fechar sempre seja visível:
        # Se ativou (ON), anima de aberto (0.0) -> fechado (1.0).
        # Se desativou (OFF), anima de fechado (1.0) -> aberto (0.0).
        self._anim_start_val = 0.0 if is_on else 1.0
        self._anim_target_val = 1.0 if is_on else 0.0
        self._anim_val = self._anim_start_val
        self._is_closing_anim = is_on
        self._anim_start_time = time.perf_counter()

        # Se estava oculto ou saindo, reinicia a animação de entrada vinda de baixo
        if not self.isVisible() or self._popup_target == 0.0:
            if not self.isVisible():
                self._popup_progress = 0.0
                self.show()

        self._popup_target = 1.0
        self._last_tick_time = time.perf_counter()
        self._hide_timer.start(self.HOLD_DURATION_MS)
        self._sync_refresh_rate_interval()
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        # Avisa o mixer (no meio da tela ele abre espaço para o par ficar centralizado)
        self.stack_presence_changed.emit(self.visual_height(), True)
        self.update()

    def _start_fade_out(self):
        self._popup_target = 0.0
        self._last_tick_time = time.perf_counter()
        self.stack_presence_changed.emit(0.0, False)
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def hideEvent(self, event):
        # Garante que o mixer não fique reservando espaço para um Caps Lock que já sumiu (ex.: hide() direto)
        self.stack_presence_changed.emit(0.0, False)
        super().hideEvent(event)

    def _on_tick(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_tick_time))
        self._last_tick_time = now

        # 1. Atualiza progresso de entrada/saída do popup (escala + subida + opacidade)
        if abs(self._popup_progress - self._popup_target) > 0.005:
            dur = self.POPUP_ANIM_DURATION_S if self._popup_target == 1.0 else self.FADE_OUT_DURATION_S
            step = dt / dur
            if self._popup_progress < self._popup_target:
                self._popup_progress = min(self._popup_target, self._popup_progress + step)
            else:
                self._popup_progress = max(self._popup_target, self._popup_progress - step)
        else:
            self._popup_progress = self._popup_target

        # 2. Atualiza progresso da animação do cadeado e barra
        elapsed = now - self._anim_start_time
        raw_t = min(1.0, max(0.0, elapsed / self.LOCK_ANIM_DURATION_S))
        eased_t = 1.0 - (1.0 - raw_t) ** 3
        self._anim_val = self._anim_start_val + (self._anim_target_val - self._anim_start_val) * eased_t

        # 3. Interpolação suave do movimento vertical Y ao retornar à posição padrão (quando mixer fecha)
        y_moving = False
        if not self._mixer_active:
            diff_y = self._target_win_y - self._current_win_y
            if abs(diff_y) > 0.4:
                alpha_y = 1.0 - math.exp(-26.0 * dt)
                self._current_win_y += diff_y * alpha_y
                self.move(self._get_centered_x(), int(round(self._current_win_y)))
                y_moving = True
            else:
                if abs(self._current_win_y - self._target_win_y) > 0.01:
                    self._current_win_y = self._target_win_y
                    self.move(self._get_centered_x(), int(round(self._current_win_y)))

        self.update()

        if raw_t >= 1.0 and abs(self._popup_progress - self._popup_target) <= 0.005 and not y_moving:
            self._anim_timer.stop()
            if self._popup_target == 0.0:
                self.hide()

    def paintEvent(self, event):
        if self._popup_progress <= 0.005:
            return

        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        # Curva suave (cubic out na entrada, quad in na saída)
        u = max(0.0, min(1.0, self._popup_progress))
        if self._popup_target == 1.0:
            ease_pop = 1.0 - (1.0 - u) ** 3
        else:
            ease_pop = u * u

        # O card surge da borda ancorada (de baixo, ou de cima nas âncoras do topo) e pequeno (escala 0.72 -> 1.0)
        scale = 0.72 + 0.28 * ease_pop
        slide_travel = 8.0 if self._mixer_active else float(self.SLIDE_TRAVEL_Y)
        if self._slides_from_top():
            slide_travel = -slide_travel
        y_slide = (1.0 - ease_pop) * slide_travel
        opacity = min(1.0, u * 1.35) if self._popup_target == 1.0 else ease_pop

        p.setOpacity(opacity)

        x0 = self._margins[0]
        y0 = self._margins[1]
        s = self._scale
        card_cx = x0 + self.card_w * s * 0.5
        card_cy = y0 + self.card_h * s * 0.5

        # Aplica transformação de escala e deslocamento vertical a partir do centro do card
        p.save()
        p.translate(card_cx, card_cy + y_slide)
        p.scale(scale, scale)
        p.translate(-card_cx, -card_cy)
        # A partir daqui o desenho é em unidades "lógicas" do card; a escala do tema amplia tudo junto
        p.translate(x0, y0)
        p.scale(s, s)

        card_rect = QRectF(0.0, 0.0, self.card_w, self.card_h)
        state = self._build_current_state()
        paint_keylock(p, card_rect, state)

        p.restore()

    def _build_current_state(self) -> KeyLockState:
        now = time.perf_counter()
        raw_t = min(1.0, max(0.0, (now - self._anim_start_time) / self.LOCK_ANIM_DURATION_S))

        if self._is_closing_anim:
            horiz_t = min(1.0, raw_t / 0.55)
            horiz_ease = 1.0 - (1.0 - horiz_t) ** 2
            shackle_x_shift = 1.25 * (1.0 - horiz_ease)

            drop_t = max(0.0, min(1.0, (raw_t - 0.22) / 0.78))
            drop_ease = 1.0 - (1.0 - drop_t) ** 3
            shackle_lift = -1.8 * (1.0 - drop_ease)
            left_leg_gap = 2.6 * (1.0 - drop_ease)

            body_recoil = 0.9 * math.sin(max(0.0, (raw_t - 0.45) / 0.55) * math.pi) if raw_t > 0.45 else 0.0
        else:
            lift_t = min(1.0, raw_t / 0.60)
            lift_ease = 1.0 - (1.0 - lift_t) ** 3
            overshoot = 0.45 * math.sin(raw_t * math.pi)
            shackle_lift = -1.8 * lift_ease - overshoot
            left_leg_gap = 2.6 * lift_ease

            shift_t = max(0.0, min(1.0, (raw_t - 0.25) / 0.75))
            shift_ease = 1.0 - (1.0 - shift_t) ** 2
            shackle_x_shift = 1.25 * shift_ease

            body_recoil = -0.5 * math.sin(raw_t * math.pi)

        return KeyLockState(
            label=self.key_label,
            is_on=self.is_on,
            anim_val=self._anim_val,
            shackle_x_shift=shackle_x_shift,
            shackle_lift=shackle_lift,
            left_leg_gap=left_leg_gap,
            body_recoil=body_recoil,
            draw_shadow=True,
            theme=self.theme,
        )
