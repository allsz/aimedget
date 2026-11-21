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
    MAX_SCALE,
    MIN_SCALE,
    SCREEN_MARGIN,
    is_rect_on_screen,
    place_card_default,
    restore_card_position,
)
from app.widgets.performance.card_state import PERFORMANCE_SKINS, SKIN_FLUENT
from app.widgets.performance.performance_card import PerformanceCard


class PerformanceWidgetController(AnimatedVisibilityMixin, QObject):
    status_changed = Signal(bool)
    skin_changed = Signal(str)
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

        saved_skin = str(config_manager.get_performance("skin", SKIN_FLUENT) or SKIN_FLUENT)
        self.active_skin_name = saved_skin if saved_skin in PERFORMANCE_SKINS else SKIN_FLUENT

        self.skin = PerformanceCard(
            scale=float(config_manager.get_performance("scale", 1.0) or 1.0),
            desktop_mode=bool(config_manager.get_performance("desktop_mode", False)),
            selected_metric=str(config_manager.get_performance("selected_metric", "cpu") or "cpu"),
            fps_enabled=fps_on,
            metric_order=config_manager.get_performance("metric_order", None),
            skin_id=self.active_skin_name,
        )
        self.skin.scale_auto = bool(config_manager.get_performance("scale_auto", False))
        if self.skin.scale_auto:
            self.skin.set_scale(self.skin.auto_scale_target())
        self.skin.desktop_mode_changed.connect(self.set_desktop_mode)
        self.skin.remember_position_changed.connect(self.set_remember_position)
        self.skin.close_requested.connect(self.on_skin_closed)
        self.skin.scale_changed.connect(self.set_scale)
        self.skin.metric_selected.connect(self.select_metric)
        self.skin.metric_order_changed.connect(self.set_metric_order)
        self.skin.skin_switch_requested.connect(self.set_skin)

        i18n.language_changed.connect(lambda _lang: self.skin.update())

    # --- Dados ---

    def _on_snapshot(self, snap: PerformanceSnapshot):
        self.skin.state.push(snap)
        if self.skin.state.fps_enabled:
            self.fps_service.on_gpu_pids(dict(snap.pid_3d_gpu))
        self.skin.update()

    def _on_fps_reading(self, reading: FpsReading):
        self.skin.state.animated = animations_enabled()
        self.skin.state.push_fps(reading, now=self.skin.now())
        self.skin.kick()
        self.skin.update()

    # --- Ações ---

    def select_metric(self, metric: str):
        self.skin.state.animated = animations_enabled()
        if self.skin.state.select(metric, now=self.skin.now()):
            config_manager.set_performance("selected_metric", metric)
            self.skin.kick()
            self.metric_changed.emit(metric)

    def set_metric_order(self, order: list[str]):
        normalized = list(self.skin.state.set_metric_order(order))
        config_manager.set_performance("metric_order", normalized)
        self.skin.update()

    def set_skin(self, skin_id: str, save: bool = True):
        sid = skin_id if skin_id in PERFORMANCE_SKINS else SKIN_FLUENT
        if sid != self.active_skin_name:
            self.skin.begin_skin_crossfade()
        self.active_skin_name = sid
        self.skin.set_skin(sid)
        if save:
            config_manager.set_performance("skin", sid)
        self.skin_changed.emit(sid)

    def set_scale(self, scale: float | None):
        """Tamanho do cartão (menu, Hub ou arraste do canto), com movimento; None = automático (segue a tela)."""
        auto = scale is None
        config_manager.set_performance("scale_auto", auto)
        self.skin.scale_auto = auto
        target = self.skin.auto_scale_target() if auto else max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        self.skin.animate_scale_to(target)
        config_manager.set_performance("scale", round(target, 3))
        self.scale_changed.emit(target)

    def apply_scale_live(self, scale: float):
        """Arraste do controle de tamanho no Hub: aplica na hora (o ponteiro já é o movimento), sem gravar."""
        self.skin.stop_scale_animation()
        self.skin.set_scale(scale)

    def is_scale_auto(self) -> bool:
        return bool(self.skin.scale_auto)

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
