import os
from typing import Optional
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from app.core.config_manager import config_manager
from app.core.paths import ASSETS_DIR
from app.core.typography import get_ui_font, init_app_font
from app.hub.theme import HubTheme, resolve_theme
from app.ui_components.fluent_menu import get_fluent_menu_stylesheet


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
        self.resize(max(self.MIN_WIDTH, width), max(self.MIN_HEIGHT, height))

        # Estado do Timer
        self.current_seconds: float = 300.0
        self.target_duration: float = 300.0
        self.is_running: bool = False
        self.mode: str = config_manager.get_timer_mode("timer")  # 'timer' ou 'stopwatch'
        self.theme: HubTheme = self._resolve_active_theme()

        # Interações de mouse
        self._drag_pos = QPoint()
        self._is_resizing = False
        self._resize_start_pos = QPoint()
        self._resize_start_size = QSize()
        self._hovered = False
        self._close_hovered = False
        self._resize_hovered = False

        # Animação de revelação do botão fechar (Fade-in no hover)
        self._close_opacity = 0.0
        self._close_target_opacity = 0.0
        self._close_anim_timer = QTimer(self)
        self._close_anim_timer.setInterval(16)
        self._close_anim_timer.timeout.connect(self._step_close_anim)

    def _resolve_active_theme(self) -> HubTheme:
        hub_pref = config_manager.get_hub_theme("system")
        return resolve_theme(hub_pref)

    def update_theme(self, theme: Optional[HubTheme] = None):
        """Atualiza a paleta de cores para acompanhar o Hub em tempo real."""
        self.theme = theme if theme is not None else self._resolve_active_theme()
        self.update()

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
        return get_fluent_menu_stylesheet(self.theme)

    def contextMenuEvent(self, event):
        self.theme = self._resolve_active_theme()
        menu_qss = self._build_menu_qss()

        menu = FluentTimerMenu(parent=self, theme=self.theme)
        menu.setFont(get_ui_font(13))
        menu.setStyleSheet(menu_qss)

        # 1. Lembrar posição
        is_remembered = config_manager.is_timer_position_remembered()
        act_remember = QAction("Lembrar posição", self)
        menu.set_trailing_check(act_remember, is_remembered)
        act_remember.triggered.connect(lambda: self._toggle_remember_position(not is_remembered))
        menu.addAction(act_remember)

        # 2. Ajuste inteligente de tempo (hover & scroll por dígito)
        is_smart = config_manager.is_timer_smart_hover_enabled()
        act_smart = QAction("Ajuste inteligente (Scroll nos dígitos)", self)
        menu.set_trailing_check(act_smart, is_smart)
        act_smart.triggered.connect(lambda: self._toggle_smart_hover(not is_smart))
        menu.addAction(act_smart)
        menu.addSeparator()

        # 3. Alternar Modo (Temporizador vs Cronômetro)
        mode_menu = FluentTimerMenu("Modo", menu, theme=self.theme)
        mode_menu.setFont(get_ui_font(13))
        mode_menu.setStyleSheet(menu_qss)

        act_timer = QAction("Temporizador (Regressivo)", self)
        mode_menu.set_trailing_check(act_timer, self.mode == "timer")
        act_timer.triggered.connect(lambda: self.mode_changed.emit("timer"))
        mode_menu.addAction(act_timer)

        act_stopwatch = QAction("Cronômetro", self)
        mode_menu.set_trailing_check(act_stopwatch, self.mode == "stopwatch")
        act_stopwatch.triggered.connect(lambda: self.mode_changed.emit("stopwatch"))
        mode_menu.addAction(act_stopwatch)
        menu.addMenu(mode_menu)

        menu.addSeparator()

        # 4. Redefinir tamanho
        act_reset_size = QAction("Redefinir tamanho padrão", self)
        act_reset_size.triggered.connect(self._reset_default_size)
        menu.addAction(act_reset_size)

        menu.addSeparator()

        # 6. Fechar Widget
        act_close = QAction("Fechar widget", self)
        act_close.triggered.connect(self.close_requested.emit)
        menu.addAction(act_close)

        menu.exec(event.globalPos())

    def _toggle_remember_position(self, checked: bool):
        if checked:
            config_manager.set_timer_position_remembered(True, self.x(), self.y())
        else:
            config_manager.set_timer_position_remembered(False)

    def _toggle_smart_hover(self, checked: bool):
        config_manager.set_timer_smart_hover_enabled(checked)
        self.update()

    def _reset_default_size(self):
        from app.core.screen_metrics import get_auto_timer_size
        auto_w, auto_h = get_auto_timer_size(widget=self)
        self.resize(auto_w, auto_h)
        config_manager.save_timer_size(auto_w, auto_h)
        self.update()
        config_manager.save_timer_size(self.DEFAULT_SIZE, self.DEFAULT_SIZE)
        self.update()
