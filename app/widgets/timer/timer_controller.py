import datetime
import time
from typing import Optional, Type
from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtWidgets import QApplication

from app.core.alarm_sound import play_alarm, stop_alarm
from app.core.config_manager import config_manager
from app.core.frame_clock import FrameTimer
from app.core.refresh_rate import refresh_interval_ms
from app.core.widget_animator import AnimatedVisibilityMixin, swap_skin_windows
from app.widgets.timer.alarm_rules import default_alarm_time, next_alarm, normalize_alarm_time
from app.widgets.timer.duration_rules import MIN_RUN_SECONDS, normalize_duration
from app.widgets.timer.skins.base_skin import BaseTimerSkin
from app.widgets.timer.skins import timer_skin_classes
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
from app.widgets.timer.time_layout import is_compact


class TimerWidgetController(AnimatedVisibilityMixin, QObject):
    """
    Controlador central do Timer Widget:
    - Motor de contagem de alta precisão via monotonic `time.perf_counter()`
    - Suporta modo Temporizador (contagem regressiva), Cronômetro (progressiva) e Alarme (contagem até um horário)
    - Gerencia skins intercambiáveis preservando estado e posicionamento
    - Senta no topo da tela por padrão ou restaura a posição favorita salva
    - Efeito de aviso sonoro e pulso luminoso visual ao concluir contagem
    """

    MODES = ("timer", "stopwatch", "alarm")
    TICK_MS = 100   # segundos inteiros na tela (Temporizador, Alarme e Cronômetro a partir de 1 h)

    status_changed = Signal(bool)
    configure_requested = Signal()   # "Configurar" no menu do widget
    skin_changed = Signal(str)
    time_updated = Signal(float, bool, str)  # current_seconds, is_running, mode
    desktop_mode_changed = Signal(bool)      # o widget foi (ou saiu) para a área de trabalho: o Hub acompanha
    remember_position_changed = Signal(bool)
    smart_hover_changed = Signal(bool)

    @staticmethod
    def available_skins() -> dict[str, Type[BaseTimerSkin]]:
        """Skins disponíveis agora (a Padrão e os pacotes de skin em disco); relido a cada chamada."""
        return timer_skin_classes()

    def __init__(self, skin_name: Optional[str] = None):
        super().__init__()

        # Estado da contagem
        self.is_running: bool = False
        self.mode: str = config_manager.get_timer_mode("timer")
        if self.mode not in self.MODES:
            self.mode = "timer"
        self.target_duration: float = float(config_manager.get_timer_duration(300))
        saved_alarm = config_manager.get_timer_alarm_time()
        self.alarm_time: int = saved_alarm if saved_alarm is not None else default_alarm_time(datetime.datetime.now())
        self.alarm_finished: bool = False            # o alarme tocou ("CONCLUÍDO") até a próxima ação
        self._alarm_deadline: Optional[float] = None  # instante (time.time) em que o alarme armado toca
        self.current_seconds: float = self._idle_seconds()
        self._last_tick_time: float = 0.0

        # Ticker periódico preciso
        self._ticker = FrameTimer(self)   # no compasso da tela: os centésimos do Cronômetro andam sem tropeço
        self._ticker.setInterval(self.TICK_MS)
        self._ticker.timeout.connect(self._on_tick)

        # Pulso visual de alarme
        self._alarm_pulse_count = 0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(220)
        self._pulse_timer.timeout.connect(self._step_alarm_pulse)

        # Inicializa a skin
        self.skin: Optional[BaseTimerSkin] = None
        saved_skin = config_manager.get_timer_active_skin("windows")
        initial_skin = skin_name or saved_skin
        if initial_skin not in self.available_skins():
            initial_skin = "windows"
        self.active_skin_name = initial_skin

        self.set_skin(initial_skin)

    def set_skin(self, skin_name: str):
        skin_cls = self.available_skins().get(skin_name, WindowsTimerSkin)
        self.active_skin_name = skin_name
        config_manager.set_timer_active_skin(skin_name)

        old_skin = self.skin
        old_pos = None
        was_visible = False
        saved_size = config_manager.get_timer_saved_size()

        if old_skin is not None:
            old_pos = old_skin.square_origin()   # o quadrado não muda de lugar ao trocar de skin ou de tema
            was_visible = self._is_shown()   # saindo (fade-out em curso) conta como escondido
            old_skin.animator.settle()
            try:
                old_skin.play_pause_clicked.disconnect(self.toggle_play_pause)
                old_skin.reset_clicked.disconnect(self.reset)
                old_skin.duration_changed.disconnect(self.set_duration)
                old_skin.alarm_time_changed.disconnect(self.set_alarm_time)
                old_skin.mode_changed.disconnect(self.set_mode)
                old_skin.close_requested.disconnect(self.on_skin_closed)
                old_skin.configure_requested.disconnect(self.configure_requested.emit)
                old_skin.skin_switch_requested.disconnect(self.set_skin)
                old_skin.desktop_mode_changed.disconnect(self.set_desktop_mode)
                old_skin.remember_position_changed.disconnect(self.remember_position_changed.emit)
                old_skin.smart_hover_changed.disconnect(self.smart_hover_changed.emit)
            except Exception:
                pass

        self.skin = skin_cls(width=saved_size[0], height=saved_size[1])
        self.skin.play_pause_clicked.connect(self.toggle_play_pause)
        self.skin.reset_clicked.connect(self.reset)
        self.skin.duration_changed.connect(self.set_duration)
        self.skin.alarm_time_changed.connect(self.set_alarm_time)
        self.skin.mode_changed.connect(self.set_mode)
        self.skin.close_requested.connect(self.on_skin_closed)
        self.skin.configure_requested.connect(self.configure_requested.emit)
        self.skin.skin_switch_requested.connect(self.set_skin)
        self.skin.desktop_mode_changed.connect(self.set_desktop_mode)   # a skin nova já nasce na camada gravada
        self.skin.remember_position_changed.connect(self.remember_position_changed.emit)
        self.skin.smart_hover_changed.connect(self.smart_hover_changed.emit)

        self._sync_skin()

        if old_pos is not None:
            self.skin.move_square_to(old_pos.x(), old_pos.y())
            if config_manager.is_timer_position_remembered():
                config_manager.save_timer_position(old_pos.x(), old_pos.y())
        else:
            self.restore_or_place_at_top()

        swap_skin_windows(old_skin, self.skin, was_visible)

        self.skin_changed.emit(skin_name)

    def set_desktop_mode(self, enabled: bool):
        """"Fixar na área de trabalho" (menu do widget ou Hub): aplica com a onda de pontos, grava e avisa o Hub."""
        config_manager.set_widget_desktop_mode("timer_widget", bool(enabled))
        if self.skin:
            self.skin.set_desktop_mode(enabled)
        self.desktop_mode_changed.emit(bool(enabled))

    def is_desktop_mode(self) -> bool:
        return bool(self.skin.desktop_mode_target()) if self.skin else False

    def restore_or_place_at_top(self):
        """
        Posicionamento padrão:
        - Se 'Lembrar posição' estiver ativo e houver posição válida, posiciona lá.
        - Por padrão, senta centralizado no topo da tela com margem elegante de 28px.
        """
        if not self.skin:
            return

        if config_manager.is_timer_position_remembered():
            pos = config_manager.get_timer_saved_position()
            side = self.skin.square_side()
            if pos is not None and self._is_position_on_screen(pos[0], pos[1], side, side):
                self.skin.move_square_to(pos[0], pos[1])
                return

        self.place_at_screen_top()

    def place_at_screen_top(self):
        """Centraliza o widget no topo da tela primária disponível."""
        app = QApplication.instance()
        if app and app.primaryScreen() and self.skin:
            geo = app.primaryScreen().availableGeometry()
            x = geo.x() + (geo.width() - self.skin.square_side()) // 2
            y = geo.y() + 28
            self.skin.move_square_to(x, y)

    def _is_position_on_screen(self, x: int, y: int, w: int, h: int) -> bool:
        app = QApplication.instance()
        if not app:
            return True
        widget_rect = QRect(x, y, max(1, w), max(1, h))
        for screen in app.screens():
            inter = screen.geometry().intersected(widget_rect)
            if inter.width() >= min(w, 50) and inter.height() >= min(h, 50):
                return True
        return False

    # --- Controles de Operação (Play / Pause / Reset / Config) ---

    def toggle_play_pause(self):
        if self.is_running:
            self.pause()
        else:
            self.play()

    def can_start(self) -> bool:
        """O temporizador só inicia com 10 s ou mais (00:00:00 é válido, mas não conta)."""
        return self.mode != "timer" or self.target_duration >= MIN_RUN_SECONDS

    def play(self):
        if not self.can_start():
            return
        # Se for modo temporizador e já estiver zerado, reinicia com a duração alvo
        if self.mode == "timer" and self.current_seconds <= 0:
            self.current_seconds = self.target_duration
        if self.mode == "alarm":
            # Arma para a próxima vez em que o relógio marcar o horário (hoje, ou amanhã se já passou)
            self._alarm_deadline = next_alarm(datetime.datetime.now(), self.alarm_time).timestamp()
            self.current_seconds = max(0.0, self._alarm_deadline - time.time())
            self.alarm_finished = False

        self.is_running = True
        self._last_tick_time = time.perf_counter()
        self._ticker.setInterval(self._tick_interval())
        self._ticker.start()
        self._stop_alarm_pulse()
        self._sync_skin()
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def pause(self):
        self.is_running = False
        self._ticker.stop()
        if self.mode == "alarm":
            # Pausar um alarme é desarmá-lo: o widget volta a mostrar o horário configurado
            self._alarm_deadline = None
            if not self.alarm_finished:
                self.current_seconds = float(self.alarm_time)
        self._sync_skin()
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def reset(self):
        self.pause()
        self._stop_alarm_pulse()
        if self.mode == "timer":
            # Reiniciar zera o relógio (00:00:00); a duração antiga não volta
            self.target_duration = 0.0
            config_manager.set_timer_duration(0)
        if self.mode == "alarm":
            # Como no Temporizador: reiniciar desarma e zera o horário (00:00:00)
            self.alarm_time = 0
            config_manager.set_timer_alarm_time(0)
        self.alarm_finished = False
        self.current_seconds = 0.0

        if self.skin:
            self.skin.target_duration = self.target_duration
        self._sync_skin()
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def set_duration(self, seconds: int):
        self.target_duration = float(normalize_duration(seconds))
        config_manager.set_timer_duration(int(self.target_duration))
        if not self.is_running and self.mode == "timer":
            self.current_seconds = self.target_duration
        if self.skin:
            self.skin.target_duration = self.target_duration
        self._sync_skin()
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def set_alarm_time(self, seconds: int):
        """Horário do modo Alarme (ajustado no widget). Com o alarme armado, a contagem já mira o horário novo."""
        self.alarm_time = normalize_alarm_time(seconds)
        config_manager.set_timer_alarm_time(self.alarm_time)
        self.alarm_finished = False
        if self.mode == "alarm":
            if self.is_running:
                self._alarm_deadline = next_alarm(datetime.datetime.now(), self.alarm_time).timestamp()
                self.current_seconds = max(0.0, self._alarm_deadline - time.time())
            else:
                self.current_seconds = float(self.alarm_time)
        self._sync_skin()
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def set_mode(self, mode: str):
        if mode in self.MODES:
            self.pause()
            self._stop_alarm_pulse()
            self.mode = mode
            config_manager.set_timer_mode(mode)
            self.alarm_finished = False
            self.current_seconds = self._idle_seconds()

            if self.skin:
                self.skin.mode = mode
            self._sync_skin()
            self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def _idle_seconds(self) -> float:
        """O que o widget mostra parado: a duração (Temporizador), zero (Cronômetro) ou o horário (Alarme)."""
        if self.mode == "timer":
            return self.target_duration
        if self.mode == "alarm":
            return float(self.alarm_time)
        return 0.0

    def _sync_skin(self):
        if self.skin:
            self.skin.alarm_time = self.alarm_time
            self.skin.alarm_finished = self.alarm_finished
            self.skin.set_time_state(self.current_seconds, self.is_running, self.mode)

    # --- Motor de Contagem Monotônica ---

    def _tick_interval(self) -> int:
        """Um tique por quadro enquanto o Cronômetro mostra centésimos; 100 ms quando só há segundos inteiros."""
        return refresh_interval_ms() if is_compact(self.mode, self.current_seconds) else self.TICK_MS

    def _on_tick(self):
        if not self.is_running:
            return

        now = time.perf_counter()
        dt = now - self._last_tick_time
        self._last_tick_time = now

        if self.mode == "stopwatch":
            self.current_seconds += dt
            self._ticker.setInterval(self._tick_interval())   # passou de 1 h: os centésimos saem, volta a 100 ms
        elif self.mode == "alarm":
            # Pelo relógio do sistema, não por acumulação: certo mesmo depois de o PC dormir
            remaining = (self._alarm_deadline or 0.0) - time.time()
            if remaining <= 0.0:
                self.current_seconds = 0.0
                self.alarm_finished = True
                self.pause()
                self._trigger_alarm_finish()
            else:
                self.current_seconds = remaining
        else:
            self.current_seconds -= dt
            if self.current_seconds <= 0.0:
                self.current_seconds = 0.0
                self.pause()
                self._trigger_alarm_finish()

        self._sync_skin()
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def _trigger_alarm_finish(self):
        """Ao zerar a contagem regressiva, toca o som (se ligado no Hub) e inicia o pulso luminoso."""
        if config_manager.is_timer_alarm_sound_enabled():
            play_alarm()

        self._alarm_pulse_count = 8
        self._pulse_timer.start()

    def _step_alarm_pulse(self):
        if not self.skin:
            self._pulse_timer.stop()
            return

        if self._alarm_pulse_count > 0:
            if hasattr(self.skin, "is_alarm_pulsing"):
                self.skin.is_alarm_pulsing = not self.skin.is_alarm_pulsing
                self.skin.update()
            self._alarm_pulse_count -= 1
        else:
            self._stop_alarm_pulse()

    def _stop_alarm_pulse(self):
        self._pulse_timer.stop()
        stop_alarm()   # iniciar ou reiniciar o Timer também silencia o som que ainda estiver tocando
        if self.skin and hasattr(self.skin, "is_alarm_pulsing"):
            self.skin.is_alarm_pulsing = False
            self.skin.update()

    # --- Ciclo de Vida ---

    def start(self):
        self.show()

    def show(self):
        if self.skin:
            if not self.skin.animator.is_animating():   # no meio de surgir/sumir a janela já está no lugar: não mexe
                self.restore_or_place_at_top()
            self._animate_show()
            self.status_changed.emit(True)

    def hide(self):
        if self.skin:
            self._animate_hide()
            self.status_changed.emit(False)

    def on_skin_closed(self):
        self.hide()
        config_manager.set_timer_enabled(False)

    def update_theme(self, theme=None):
        if self.skin:
            self.skin.update_theme(theme)
