import time
from typing import Optional, Type
from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.widgets.timer.duration_rules import MIN_RUN_SECONDS, normalize_duration
from app.widgets.timer.skins.base_skin import BaseTimerSkin
from app.widgets.timer.skins.windows_skin import WindowsTimerSkin


class TimerWidgetController(QObject):
    """
    Controlador central do Timer Widget:
    - Motor de contagem de alta precisão via monotonic `time.perf_counter()`
    - Suporta modo Temporizador (contagem regressiva) e Cronômetro (progressiva)
    - Gerencia skins intercambiáveis preservando estado e posicionamento
    - Senta no topo da tela por padrão ou restaura a posição favorita salva
    - Efeito de aviso sonoro e pulso luminoso visual ao concluir contagem
    """

    status_changed = Signal(bool)
    skin_changed = Signal(str)
    time_updated = Signal(float, bool, str)  # current_seconds, is_running, mode

    AVAILABLE_SKINS: dict[str, Type[BaseTimerSkin]] = {
        "windows": WindowsTimerSkin,
    }

    def __init__(self, skin_name: Optional[str] = None):
        super().__init__()

        # Estado da contagem
        self.is_running: bool = False
        self.mode: str = config_manager.get_timer_mode("timer")
        self.target_duration: float = float(config_manager.get_timer_duration(300))
        self.current_seconds: float = self.target_duration if self.mode == "timer" else 0.0
        self._last_tick_time: float = 0.0

        # Ticker periódico preciso
        self._ticker = QTimer(self)
        self._ticker.setInterval(100)
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
        if initial_skin not in self.AVAILABLE_SKINS:
            initial_skin = "windows"
        self.active_skin_name = initial_skin

        self.set_skin(initial_skin)

    def set_skin(self, skin_name: str):
        skin_cls = self.AVAILABLE_SKINS.get(skin_name, WindowsTimerSkin)
        self.active_skin_name = skin_name
        config_manager.set_timer_active_skin(skin_name)

        old_pos = None
        was_visible = False
        saved_size = config_manager.get_timer_saved_size()

        if self.skin is not None:
            old_pos = self.skin.pos()
            was_visible = self.skin.isVisible()
            try:
                self.skin.play_pause_clicked.disconnect(self.toggle_play_pause)
                self.skin.reset_clicked.disconnect(self.reset)
                self.skin.duration_changed.disconnect(self.set_duration)
                self.skin.mode_changed.disconnect(self.set_mode)
                self.skin.close_requested.disconnect(self.on_skin_closed)
                self.skin.skin_switch_requested.disconnect(self.set_skin)
            except Exception:
                pass
            self.skin.close()
            self.skin.deleteLater()

        self.skin = skin_cls(width=saved_size[0], height=saved_size[1])
        self.skin.play_pause_clicked.connect(self.toggle_play_pause)
        self.skin.reset_clicked.connect(self.reset)
        self.skin.duration_changed.connect(self.set_duration)
        self.skin.mode_changed.connect(self.set_mode)
        self.skin.close_requested.connect(self.on_skin_closed)
        self.skin.skin_switch_requested.connect(self.set_skin)

        self.skin.set_time_state(self.current_seconds, self.is_running, self.mode)

        if old_pos is not None:
            self.skin.move(old_pos)
            if config_manager.is_timer_position_remembered():
                config_manager.save_timer_position(old_pos.x(), old_pos.y())
        else:
            self.restore_or_place_at_top()

        if was_visible:
            self.skin.show()

        self.skin_changed.emit(skin_name)

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
            if pos is not None and self._is_position_on_screen(pos[0], pos[1], self.skin.width(), self.skin.height()):
                self.skin.move(pos[0], pos[1])
                return

        self.place_at_screen_top()

    def place_at_screen_top(self):
        """Centraliza o widget no topo da tela primária disponível."""
        app = QApplication.instance()
        if app and app.primaryScreen() and self.skin:
            geo = app.primaryScreen().availableGeometry()
            x = geo.x() + (geo.width() - self.skin.width()) // 2
            y = geo.y() + 28
            self.skin.move(x, y)

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

        self.is_running = True
        self._last_tick_time = time.perf_counter()
        self._ticker.start()
        self._stop_alarm_pulse()
        if self.skin:
            self.skin.set_time_state(self.current_seconds, self.is_running, self.mode)
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def pause(self):
        self.is_running = False
        self._ticker.stop()
        if self.skin:
            self.skin.set_time_state(self.current_seconds, self.is_running, self.mode)
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def reset(self):
        self.pause()
        self._stop_alarm_pulse()
        if self.mode == "timer":
            self.current_seconds = self.target_duration
        else:
            self.current_seconds = 0.0

        if self.skin:
            self.skin.set_time_state(self.current_seconds, self.is_running, self.mode)
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def set_duration(self, seconds: int):
        self.target_duration = float(normalize_duration(seconds))
        config_manager.set_timer_duration(int(self.target_duration))
        if not self.is_running and self.mode == "timer":
            self.current_seconds = self.target_duration
        if self.skin:
            self.skin.target_duration = self.target_duration
            self.skin.set_time_state(self.current_seconds, self.is_running, self.mode)
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def set_mode(self, mode: str):
        if mode in ("timer", "stopwatch"):
            self.pause()
            self.mode = mode
            config_manager.set_timer_mode(mode)
            if mode == "timer":
                self.current_seconds = self.target_duration
            else:
                self.current_seconds = 0.0

            if self.skin:
                self.skin.mode = mode
                self.skin.set_time_state(self.current_seconds, self.is_running, self.mode)
            self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    # --- Motor de Contagem Monotônica ---

    def _on_tick(self):
        if not self.is_running:
            return

        now = time.perf_counter()
        dt = now - self._last_tick_time
        self._last_tick_time = now

        if self.mode == "stopwatch":
            self.current_seconds += dt
        else:
            self.current_seconds -= dt
            if self.current_seconds <= 0.0:
                self.current_seconds = 0.0
                self.pause()
                self._trigger_alarm_finish()

        if self.skin:
            self.skin.set_time_state(self.current_seconds, self.is_running, self.mode)
        self.time_updated.emit(self.current_seconds, self.is_running, self.mode)

    def _trigger_alarm_finish(self):
        """Ao zerar a contagem regressiva, emite alerta sonoro e inicia pulso luminoso."""
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

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
        if self.skin and hasattr(self.skin, "is_alarm_pulsing"):
            self.skin.is_alarm_pulsing = False
            self.skin.update()

    # --- Ciclo de Vida ---

    def start(self):
        if config_manager.is_timer_enabled():
            self.show()

    def show(self):
        if self.skin:
            self.restore_or_place_at_top()
            self.skin.show()
            self.status_changed.emit(True)

    def hide(self):
        if self.skin:
            self.skin.hide()
            self.status_changed.emit(False)

    def on_skin_closed(self):
        self.hide()
        config_manager.set_timer_enabled(False)

    def update_theme(self, theme=None):
        if self.skin:
            self.skin.update_theme(theme)
