"""
StorageWidgetController - liga StorageService (background) ao StorageCard (janela flutuante).

- Carrega o último cache imediatamente ao iniciar para abrir o cartão já desenhado.
- Inicia a varredura e o watcher somente quando o widget está visível (custo zero fechado).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from app.core.config_manager import config_manager
from app.core.i18n import i18n
from app.core.widget_animator import AnimatedVisibilityMixin, animations_enabled
from app.services.storage_service import StorageService, StorageSnapshot
from app.ui_components.floating_card import (
    MAX_SCALE,
    MIN_SCALE,
    SCREEN_MARGIN,
    is_rect_on_screen,
    place_card_default,
    restore_card_position,
)
from app.widgets.storage.storage_card import StorageCard


class StorageWidgetController(AnimatedVisibilityMixin, QObject):
    status_changed = Signal(bool)
    configure_requested = Signal()   # "Configurar" no menu do widget
    scale_changed = Signal(float)
    desktop_mode_changed = Signal(bool)
    remember_position_changed = Signal(bool)
    always_expanded_changed = Signal(bool)

    def __init__(self, service: Optional[StorageService] = None):
        super().__init__()
        self.service = service or StorageService(self)
        self.service.snapshot_ready.connect(self._on_snapshot)
        self.service.busy_changed.connect(self._on_busy)

        always_exp = bool(config_manager.get_storage("always_expanded", False))
        self.skin = StorageCard(
            scale=float(config_manager.get_storage("scale", 1.0) or 1.0),
            desktop_mode=bool(config_manager.get_storage("desktop_mode", False)),
            always_expanded=always_exp,
        )
        self.skin.scale_auto = bool(config_manager.get_storage("scale_auto", False))
        if self.skin.scale_auto:
            self.skin.set_scale(self.skin.auto_scale_target())

        self.skin.desktop_mode_changed.connect(self.set_desktop_mode)
        self.skin.remember_position_changed.connect(self.set_remember_position)
        self.skin.close_requested.connect(self.on_skin_closed)
        self.skin.configure_requested.connect(self.configure_requested.emit)
        self.skin.scale_changed.connect(self.set_scale)
        self.skin.refresh_requested.connect(lambda: self.service.refresh(force=True))
        self.skin.always_expanded_changed.connect(self.set_always_expanded)

        cached = self.service.cached_snapshot()
        if cached is not None:
            self.skin.state.apply_snapshot(cached, animate=False)
            self.skin._sync_card_height()

        i18n.language_changed.connect(lambda _lang: self.skin.update())

    # --- Dados ---

    def _on_snapshot(self, snap: StorageSnapshot):
        self.skin.state.animated = animations_enabled()
        self.skin.state.apply_snapshot(snap, animate=self.skin.isVisible())
        if not self.skin.state.animated:
            self.skin._sync_card_height()
        self.skin._last_tick = self.skin.now()
        self.skin.kick()
        self.skin.update()

    def _on_busy(self, busy: bool):
        self.skin.state.scanning = bool(busy)
        self.skin.update()

    # --- Opções ---

    def set_always_expanded(self, enabled: bool):
        enabled = bool(enabled)
        config_manager.set_storage("always_expanded", enabled)
        self.skin.set_always_expanded(enabled)
        self.always_expanded_changed.emit(enabled)

    def set_scan_games(self, enabled: bool):
        config_manager.set_storage("scan_games", bool(enabled))
        if self.is_shown():
            self.service.refresh(force=True)

    def set_scale(self, scale: float | None):
        auto = scale is None
        config_manager.set_storage("scale_auto", auto)
        self.skin.scale_auto = auto
        target = self.skin.auto_scale_target() if auto else max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        self.skin.animate_scale_to(target)
        config_manager.set_storage("scale", round(target, 3))
        self.scale_changed.emit(target)

    def apply_scale_live(self, scale: float):
        self.skin.stop_scale_animation()
        self.skin.set_scale(scale)

    def is_scale_auto(self) -> bool:
        return bool(self.skin.scale_auto)

    def set_desktop_mode(self, enabled: bool):
        config_manager.set_storage("desktop_mode", bool(enabled))
        self.skin.set_desktop_mode(enabled)
        self.desktop_mode_changed.emit(bool(enabled))

    def set_remember_position(self, enabled: bool):
        enabled = bool(enabled)
        config_manager.set_storage("remember_position", enabled)
        if enabled:
            origin = self.skin.card_origin()
            config_manager.set_storage("position", [origin.x(), origin.y()])
        self.remember_position_changed.emit(enabled)

    # --- Posição ---

    def restore_or_place(self):
        restore_card_position(
            self.skin,
            bool(config_manager.get_storage("remember_position", False)),
            config_manager.get_storage("position", None),
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
        self.service.start()
        self.status_changed.emit(True)

    def hide(self):
        self.service.stop()
        self.skin.forget_show_desktop()
        self._animate_hide()
        self.status_changed.emit(False)

    def on_skin_closed(self):
        self.hide()
        config_manager.set_storage("enabled", False)

    def stop(self):
        self.service.stop()
