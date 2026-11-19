"""
PerformanceWidgetController - liga PerformanceService + FpsService (opcional) ao PerformanceCard.

- Inicia o sampler em 1 Hz apenas enquanto o widget está visível; ao esconder, para imediatamente (custo zero).
- Quando o contador de FPS está ativo, o FpsService só liga o PresentMon durante jogos 3D / Lossless Scaling.
"""

from typing import Optional

from PySide6.QtCore import QObject, Signal

from app.core.config_manager import config_manager
from app.core.i18n import i18n
from app.core.widget_animator import AnimatedVisibilityMixin, animations_enabled
from app.services.fps_service import FpsReading, FpsService
from app.services.performance_service import PerformanceService, PerformanceSnapshot
from app.ui_components.floating_card import (
    SCREEN_MARGIN,
    is_rect_on_screen,
    place_card_default,
    restore_card_position,
)
from app.widgets.performance.performance_card import PerformanceCard


class PerformanceWidgetController(AnimatedVisibilityMixin, QObject):
    status_changed = Signal(bool)
    scale_changed = Signal(float)
    desktop_mode_changed = Signal(bool)
    remember_position_changed = Signal(bool)
    fps_enabled_changed = Signal(bool)
    metric_changed = Signal(str)

    def __init__(
        self,
        service: Optional[PerformanceService] = None,
        fps_service: Optional[FpsService] = None,
    ):
        super().__init__()
        self.service = service or PerformanceService(self)
        self.service.snapshot_ready.connect(self._on_snapshot)

        self.fps_service = fps_service or FpsService(self)
        self.fps_service.reading_ready.connect(self._on_fps_reading)
        fps_on = bool(config_manager.get_performance("fps_enabled", False))
        self.fps_service.set_enabled(fps_on)

        self.skin = PerformanceCard(
            scale=float(config_manager.get_performance("scale", 1.0) or 1.0),
            desktop_mode=bool(config_manager.get_performance("desktop_mode", False)),
            selected_metric=str(config_manager.get_performance("selected_metric", "cpu") or "cpu"),
            fps_enabled=fps_on,
        )
        self.skin.desktop_mode_changed.connect(self.set_desktop_mode)
        self.skin.remember_position_changed.connect(self.set_remember_position)
        self.skin.close_requested.connect(self.on_skin_closed)
        self.skin.scale_changed.connect(self.set_scale)
        self.skin.metric_selected.connect(self.select_metric)

        i18n.language_changed.connect(lambda _lang: self.skin.update())

    # --- Dados ---

    def _on_snapshot(self, snap: PerformanceSnapshot):
        self.skin.state.push(snap)
        if self.skin.state.fps_enabled:
            self.fps_service.on_gpu_pids(dict(snap.pid_3d_gpu))
        self.skin.update()

    def _on_fps_reading(self, reading: FpsReading):
        self.skin.state.push_fps(reading)
        self.skin.update()

    # --- Ações ---

    def select_metric(self, metric: str):
        self.skin.state.animated = animations_enabled()
        if self.skin.state.select(metric, now=self.skin.now()):
            config_manager.set_performance("selected_metric", metric)
            self.skin.kick()
            self.metric_changed.emit(metric)

    def set_scale(self, scale: float):
        self.skin.set_scale(scale)
        config_manager.set_performance("scale", round(self.skin.scale(), 3))
        self.scale_changed.emit(self.skin.scale())

    def set_desktop_mode(self, enabled: bool):
        config_manager.set_performance("desktop_mode", bool(enabled))
        self.skin.set_desktop_mode(enabled)
        self.desktop_mode_changed.emit(bool(enabled))

    def set_remember_position(self, enabled: bool):
        enabled = bool(enabled)
        config_manager.set_performance("remember_position", enabled)
        if enabled:
            origin = self.skin.card_origin()
            config_manager.set_performance("position", [origin.x(), origin.y()])
        self.remember_position_changed.emit(enabled)

    def set_fps_enabled(self, enabled: bool):
        enabled = bool(enabled)
        config_manager.set_performance("fps_enabled", enabled)
        self.skin.state.set_fps_enabled(enabled)
        self.fps_service.set_enabled(enabled)
        self.skin.update()
        self.fps_enabled_changed.emit(enabled)

    # --- Posição ---

    def restore_or_place(self):
        restore_card_position(
            self.skin,
            bool(config_manager.get_performance("remember_position", False)),
            config_manager.get_performance("position", None),
            margin=SCREEN_MARGIN,
        )

    def place_default(self):
        place_card_default(self.skin, margin=SCREEN_MARGIN)

    @staticmethod
    def _on_screen(x: int, y: int, w: int, h: int) -> bool:
        return is_rect_on_screen(x, y, w, h)

    # --- Ciclo de vida ---

    def start(self):
        self.show()

    def show(self):
        self.skin.forget_show_desktop()
        if not self.skin.animator.is_animating():
            self.restore_or_place()
        self._animate_show()
        self.fps_service.set_widget_visible(True)
        self.service.start()
        self.status_changed.emit(True)

    def hide(self):
        self.service.stop()
        self.fps_service.set_widget_visible(False)
        self.skin.forget_show_desktop()
        self._animate_hide()
        self.status_changed.emit(False)

    def on_skin_closed(self):
        self.hide()
        config_manager.set_performance("enabled", False)

    def stop(self):
        self.service.stop()
        self.fps_service.stop()
