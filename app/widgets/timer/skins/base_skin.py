from typing import Optional
from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from app.core.config_manager import config_manager
from app.core.i18n import i18n, t
from app.core.widget_theme import art_margin_px
from app.core.typography import get_ui_font, init_app_font
from app.hub.theme import HubTheme, resolve_theme
from app.ui_components.fluent_menu import get_fluent_menu_stylesheet
from app.widgets.timer import theme as timer_theme


class FluentTimerMenu(QMenu):
    """
    Menu de contexto com visual Fluent e indicador de status (trailing check)
    com adaptação de contraste para modos Claro e Escuro.
    """

    def __init__(self, title_or_parent=None, parent=None, theme: Optional[HubTheme] = None):
        if isinstance(title_or_parent, str):
            super().__init__(title_or_parent, parent)
        else:
            super().__init__(title_or_parent)
        self.theme = theme
        self._trailing_checked_actions = set()

    def set_trailing_check(self, action: QAction, is_checked: bool):
        if is_checked:
            self._trailing_checked_actions.add(action)
        else:
            self._trailing_checked_actions.discard(action)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._trailing_checked_actions:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_dark = not self.theme or self.theme.is_dark
        check_color = QColor(255, 255, 255, 240) if is_dark else QColor(31, 30, 29, 230)

        for action in self._trailing_checked_actions:
            if not action.isVisible():
                continue
            rect = self.actionGeometry(action)
            if rect.isEmpty():
                continue

            check_size = 16
            chk_x = rect.right() - 24
            chk_y = rect.top() + (rect.height() - check_size) // 2

            path = QPainterPath()
            path.moveTo(chk_x + 3.5, chk_y + 8.5)
            path.lineTo(chk_x + 6.5, chk_y + 11.5)
            path.lineTo(chk_x + 12.5, chk_y + 4.5)

            pen = QPen(
                check_color,
                1.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        p.end()


class BaseTimerSkin(QWidget):
    """
    Classe base para skins do Timer Widget:
    - Janela frameless flutuante com fundo translúcido e Always-On-Top
    - Arraste livre (free drag) e persistência de posição ("Lembrar posição")
    - Redimensionamento interativo suave (resize) a partir do canto inferior direito
    - Botão Fechar oculto no topo esquerdo que se revela ao passar o mouse (hover)
    - Menu de contexto Fluent com alternância de modo, ajuste inteligente e fixação
    """

    play_pause_clicked = Signal()
    reset_clicked = Signal()
    duration_changed = Signal(int)
    alarm_time_changed = Signal(int)   # horário do modo Alarme (segundos desde a meia-noite)
    mode_changed = Signal(str)
    close_requested = Signal()
    skin_switch_requested = Signal(str)

    DEFAULT_SIZE = 164
    MIN_SCALE_RATIO = 0.75
    MAX_SCALE_RATIO = 1.55
    MIN_WIDTH = int(round(DEFAULT_SIZE * MIN_SCALE_RATIO))   # 123 px
    MIN_HEIGHT = MIN_WIDTH
    MAX_WIDTH = int(round(DEFAULT_SIZE * MAX_SCALE_RATIO))   # 254 px
    MAX_HEIGHT = MAX_WIDTH

    def __init__(self, width: int = DEFAULT_SIZE, height: int = DEFAULT_SIZE):
        super().__init__()
        init_app_font()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        # Tema visual escolhido no Hub (themes/timer/): cores por cima das do app, fundo e figurinhas
        self.skin_theme: timer_theme.TimerTheme = timer_theme.load_user_theme()
        self._hub_theme: HubTheme = self._resolve_active_theme()
        self.theme: HubTheme = self.skin_theme.apply_to(self._hub_theme)   # cores efetivas usadas no desenho

        # O "quadrado" é o cartão com a folga da sombra (o que sempre foi a janela). Figurinhas que passam da borda
        # pedem uma margem transparente EXTRA em volta dele: a janela fica maior, o quadrado não muda.
        side = max(self.MIN_WIDTH, width)
        self.art_margin = self._wanted_art_margin(side)
        self.resize(side + 2 * self.art_margin, side + 2 * self.art_margin)

        # Estado do Timer
        self.current_seconds: float = 300.0
        self.target_duration: float = 300.0
        self.is_running: bool = False
        self.mode: str = config_manager.get_timer_mode("timer")  # 'timer', 'stopwatch' ou 'alarm'
        self.alarm_time: int = 0            # horário do Alarme (o controller mantém atualizado)
        self.alarm_finished: bool = False   # o alarme tocou: rótulo "CONCLUÍDO" até a próxima ação
        i18n.language_changed.connect(self.update)   # o rótulo do topo é desenhado no idioma do app

        # Interações de mouse
        self._drag_pos = QPoint()
        self._is_resizing = False
        self._resize_start_pos = QPoint()
        self._resize_start_size = QSize()
        self._resize_start_side = 0
        self._hovered = False
        self._close_hovered = False
        self._resize_hovered = False

        # Animação de revelação do botão fechar (Fade-in no hover)
        self._close_opacity = 0.0
        self._close_target_opacity = 0.0
        self._close_anim_timer = QTimer(self)
        self._close_anim_timer.setInterval(16)
        self._close_anim_timer.timeout.connect(self._step_close_anim)

    # --- Quadrado x janela (margem transparente para arte que passa da borda) ---

    ART_FREE_PAD = 8.0   # folga que já existe em volta do cartão (a margem da sombra)

    def square_side(self) -> int:
        """Lado do quadrado (cartão + folga da sombra), sem a margem de arte. É o que o usuário redimensiona e salva."""
        return self.width() - 2 * self.art_margin

    def square_origin(self) -> QPoint:
        """Canto superior esquerdo do quadrado na tela: as posições salvas falam dele, não da janela."""
        return self.pos() + QPoint(self.art_margin, self.art_margin)

    def move_square_to(self, x: int, y: int):
        self.move(x - self.art_margin, y - self.art_margin)

    def _wanted_art_margin(self, side: int) -> int:
        """Margem extra (px) que o tema pede para um quadrado de `side` px: o quanto as figurinhas passam da folga."""
        scale = max(0.8, (side - 2 * self.ART_FREE_PAD) / (self.DEFAULT_SIZE - 2 * self.ART_FREE_PAD))
        card = self.DEFAULT_SIZE - 2 * self.ART_FREE_PAD   # px lógicos do cartão no tamanho padrão
        return art_margin_px(self.skin_theme.stickers, card, card, k=scale, free=self.ART_FREE_PAD)

    def set_square_side(self, side: int):
        """
        Dá ao quadrado o lado `side` (já dentro de MIN/MAX) e ajusta a margem ao tema e à escala, mantendo o
        canto do quadrado exatamente onde está (a janela cresce/encolhe em volta dele).
        """
        origin = self.square_origin()
        self.art_margin = self._wanted_art_margin(side)
        full = side + 2 * self.art_margin
        self.setGeometry(origin.x() - self.art_margin, origin.y() - self.art_margin, full, full)
        self.update()

    def _resolve_active_theme(self) -> HubTheme:
        hub_pref = config_manager.get_hub_theme("system")
        return resolve_theme(hub_pref)

    def update_theme(self, theme: Optional[HubTheme] = None):
        """Atualiza a paleta de cores para acompanhar o Hub em tempo real (o tema do Timer continua por cima)."""
        self._hub_theme = theme if theme is not None else self._resolve_active_theme()
        self.theme = self.skin_theme.apply_to(self._hub_theme)
        self.update()

    def reload_skin_theme(self):
        """Relê o tema escolhido (barato se nada mudou). Chamado ao mostrar o widget e quando o Hub aplica um tema."""
        theme = timer_theme.load_user_theme()
        if theme is self.skin_theme:
            return
        self.skin_theme = theme
        self.theme = theme.apply_to(self._hub_theme)
        self.set_square_side(self.square_side())   # figurinhas novas podem pedir (ou dispensar) a margem
        self.update()

    def showEvent(self, event):
        self.reload_skin_theme()
        super().showEvent(event)

    def set_time_state(self, current_seconds: float, is_running: bool, mode: str):
        """Atualiza o estado de contagem vindo do TimerController."""
        self.current_seconds = current_seconds
        self.is_running = is_running
        self.mode = mode
        if not is_running and mode == "timer":
            self.target_duration = current_seconds
        self.update()

    @staticmethod
    def format_time_digits(seconds: float) -> str:
        """Formata o tempo no padrão clássico do Windows Timer (HH:MM:SS)."""
        tot = max(0, int(round(seconds)))
        hrs = tot // 3600
        mins = (tot % 3600) // 60
        secs = tot % 60
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"

    # --- Animação do Botão Fechar no Topo Esquerdo ---

    def enterEvent(self, event):
        self._hovered = True
        self._close_target_opacity = 1.0
        if not self._close_anim_timer.isActive():
            self._close_anim_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._close_hovered = False
        self._resize_hovered = False
        self._close_target_opacity = 0.0
        if not self._close_anim_timer.isActive():
            self._close_anim_timer.start()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def _step_close_anim(self):
        diff = self._close_target_opacity - self._close_opacity
        if abs(diff) < 0.04:
            self._close_opacity = self._close_target_opacity
            self._close_anim_timer.stop()
        else:
            self._close_opacity += diff * 0.3
        self.update()

    # --- Geometrias e Hit Testing ---

    def get_close_btn_rect(self) -> QRectF:
        """Retorna o retângulo do botão fechar no topo esquerdo do card."""
        pad = 12.0
        size = 22.0
        return QRectF(pad, pad, size, size)

    def get_resize_grip_rect(self) -> QRectF:
        """Retorna a área de clique para redimensionamento no canto inferior direito."""
        grip_size = 20.0
        return QRectF(self.width() - grip_size, self.height() - grip_size, grip_size, grip_size)

    # --- Menu de Contexto Fluent Adaptativo ---

    def _build_menu_qss(self) -> str:
        # O menu é do Windows/Hub, não do tema do Timer: o texto do tema (ex.: branco) sobre o fundo do menu claro o
        # deixaria ilegível, e a borda translúcida do tema aparece mais clara nas curvas.
        return get_fluent_menu_stylesheet(self._hub_theme)

    def contextMenuEvent(self, event):
        # Atualiza o tema do Hub (claro/escuro/destaque) SEM perder o tema do Timer que vai por cima no widget: antes
        # isto atribuía o tema do Hub a `self.theme` e descartava as cores do tema (destaque, borda, botões).
        self.update_theme()
        menu_qss = self._build_menu_qss()

        menu = FluentTimerMenu(parent=self, theme=self._hub_theme)
        menu.setFont(get_ui_font(13))
        menu.setStyleSheet(menu_qss)

        # 1. Lembrar posição
        is_remembered = config_manager.is_timer_position_remembered()
        act_remember = QAction(t("timer_menu_remember"), self)
        menu.set_trailing_check(act_remember, is_remembered)
        act_remember.triggered.connect(lambda: self._toggle_remember_position(not is_remembered))
        menu.addAction(act_remember)

        # 2. Ajuste inteligente de tempo (hover & scroll por dígito)
        is_smart = config_manager.is_timer_smart_hover_enabled()
        act_smart = QAction(t("timer_menu_smart_hover"), self)
        menu.set_trailing_check(act_smart, is_smart)
        act_smart.triggered.connect(lambda: self._toggle_smart_hover(not is_smart))
        menu.addAction(act_smart)
        menu.addSeparator()

        # 3. Alternar Modo (Temporizador vs Cronômetro)
        mode_menu = FluentTimerMenu(t("timer_menu_mode"), menu, theme=self._hub_theme)
        mode_menu.setFont(get_ui_font(13))
        mode_menu.setStyleSheet(menu_qss)

        act_timer = QAction(t("timer_mode_timer"), self)
        mode_menu.set_trailing_check(act_timer, self.mode == "timer")
        act_timer.triggered.connect(lambda: self.mode_changed.emit("timer"))
        mode_menu.addAction(act_timer)

        act_stopwatch = QAction(t("timer_mode_stopwatch"), self)
        mode_menu.set_trailing_check(act_stopwatch, self.mode == "stopwatch")
        act_stopwatch.triggered.connect(lambda: self.mode_changed.emit("stopwatch"))
        mode_menu.addAction(act_stopwatch)

        act_alarm = QAction(t("timer_mode_alarm"), self)
        mode_menu.set_trailing_check(act_alarm, self.mode == "alarm")
        act_alarm.triggered.connect(lambda: self.mode_changed.emit("alarm"))
        mode_menu.addAction(act_alarm)
        menu.addMenu(mode_menu)

        menu.addSeparator()

        # 4. Redefinir tamanho
        act_reset_size = QAction(t("timer_menu_reset_size"), self)
        act_reset_size.triggered.connect(self._reset_default_size)
        menu.addAction(act_reset_size)

        menu.addSeparator()

        # 6. Fechar Widget
        act_close = QAction(t("menu_close_widget"), self)
        act_close.triggered.connect(self.close_requested.emit)
        menu.addAction(act_close)

        menu.exec(event.globalPos())

    def _toggle_remember_position(self, checked: bool):
        if checked:
            origin = self.square_origin()
            config_manager.set_timer_position_remembered(True, origin.x(), origin.y())
        else:
            config_manager.set_timer_position_remembered(False)

    def _toggle_smart_hover(self, checked: bool):
        config_manager.set_timer_smart_hover_enabled(checked)
        self.update()

    def _reset_default_size(self):
        from app.core.screen_metrics import get_auto_timer_size
        auto_w, auto_h = get_auto_timer_size(widget=self)
        self.set_square_side(max(self.MIN_WIDTH, min(self.MAX_WIDTH, auto_w)))
        config_manager.save_timer_size(auto_w, auto_h)
        self.update()
