"""
BatteryWidgetController - liga o BatteryService (leitura em background) ao BatteryCard.

- A leitura só roda com o cartão na tela (custo zero fechado); ao abrir, mostra a última lista na hora.
- Opções (face, rótulo, o que mostrar, última linha ímpar), o formato livre (largura x altura, pelo canto) e a escala
  (controle de Tamanho do Hub) ficam em `battery_widget` na config.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.core.config_manager import config_manager
from app.core.i18n import i18n
from app.core.widget_animator import AnimatedVisibilityMixin
from app.services.battery.service import BatteryService
from app.services.battery.system_events import SystemEventFilter
from app.ui_components.floating_card import (
    MAX_SCALE, MIN_SCALE, SCREEN_MARGIN, is_rect_on_screen, place_card_default, restore_card_position,
)
from app.widgets.battery import layout as lay
from app.widgets.battery.battery_card import BatteryCard
from app.widgets.battery.card_state import FACES, LABELS, ODDS, SHOWS, Options

OPTION_VALUES = {"face": FACES, "label": LABELS, "show": SHOWS, "odd": ODDS}


def _saved_size() -> tuple[float, float]:
    raw = config_manager.get_battery("size", None)
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            pass
    return lay.DEFAULT_SIZE


class BatteryWidgetController(AnimatedVisibilityMixin, QObject):
    status_changed = Signal(bool)
    configure_requested = Signal()   # "Configurar" no menu do widget
    desktop_mode_changed = Signal(bool)
    remember_position_changed = Signal(bool)
    options_changed = Signal(object)          # Options
    size_changed = Signal(float, float)
    scale_changed = Signal(float)

    def __init__(self, service: Optional[BatteryService] = None):
        super().__init__()
        self.service = service or BatteryService(self)
        self.service.devices_updated.connect(self._on_devices)

        self.options = Options.from_config(config_manager.get_battery)
        self.skin = BatteryCard(
            desktop_mode=bool(config_manager.get_battery("desktop_mode", False)),
            size=_saved_size(),
            options=self.options,
            scale=float(config_manager.get_battery("scale", 1.0) or 1.0),
        )
        self.skin.scale_auto = bool(config_manager.get_battery("scale_auto", False))
        if self.skin.scale_auto:
            self.skin.set_scale(self.skin.auto_scale_target())
        self.skin.scale_changed.connect(self.set_scale)
        self.skin.desktop_mode_changed.connect(self.set_desktop_mode)
        self.skin.remember_position_changed.connect(self.set_remember_position)
        self.skin.close_requested.connect(self.on_skin_closed)
        self.skin.configure_requested.connect(self.configure_requested.emit)
        self.skin.option_requested.connect(self._on_option_requested)
        self.skin.size_committed.connect(self._on_size_committed)
        self.skin.refresh_requested.connect(self.service.refresh)
        # Dispositivo ligado/desligado ou PC acordou: lê na hora (com rajada), sem esperar o intervalo
        self._sys_filter = SystemEventFilter(self.service.notify_change)
        self._sys_filter_installed = False
        i18n.language_changed.connect(lambda _lang: self.skin.update())

    # --- Dados ---

    def _on_devices(self, devices: list):
        self.skin.set_devices(devices)

    # --- Opções ---

    def set_option(self, key: str, value: str):
        if key not in OPTION_VALUES or value not in OPTION_VALUES[key]:
            return
        if getattr(self.options, key) == value:
            return
        self.options = replace(self.options, **{key: value})
        config_manager.set_battery(key, value)
        self.skin.set_options(self.options)
        self.options_changed.emit(self.options)

    def set_show_count(self, enabled: bool):
        """Liga/desliga o "X dispositivos" ao lado do título."""
        enabled = bool(enabled)
        if self.options.count == enabled:
            return
        self.options = replace(self.options, count=enabled)
        config_manager.set_battery("count", enabled)
        self.skin.set_options(self.options)
        self.options_changed.emit(self.options)

    def _on_option_requested(self, key: str, value: str):
        if key == "count":
            self.set_show_count(value == "on")
        elif key == "size" and value == "reset":
            self.reset_size()
        else:
            self.set_option(key, value)

    def set_size(self, w: float, h: float):
        self.skin.set_base_size(w, h)
        self._on_size_committed(*self.skin.base_size())

    def reset_size(self):
        self.set_size(*lay.DEFAULT_SIZE)

    def _on_size_committed(self, w: float, h: float):
        config_manager.set_battery("size", [round(float(w), 1), round(float(h), 1)])
        self.size_changed.emit(float(w), float(h))

    # --- Escala (controle de Tamanho do Hub; o formato continua no canto do cartão) ---

    def set_scale(self, scale: float | None):
        auto = scale is None
        config_manager.set_battery("scale_auto", auto)
        self.skin.scale_auto = auto
        target = self.skin.auto_scale_target() if auto else max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        self.skin.animate_scale_to(target)
        config_manager.set_battery("scale", round(target, 3))
        self.scale_changed.emit(target)

    def apply_scale_live(self, scale: float):
        self.skin.stop_scale_animation()
        self.skin.set_scale(scale)

    def is_scale_auto(self) -> bool:
        return bool(self.skin.scale_auto)

    def set_desktop_mode(self, enabled: bool):
        config_manager.set_battery("desktop_mode", bool(enabled))
        self.skin.set_desktop_mode(enabled)
        self.desktop_mode_changed.emit(bool(enabled))

    def set_remember_position(self, enabled: bool):
        enabled = bool(enabled)
        config_manager.set_battery("remember_position", enabled)
        if enabled:
            origin = self.skin.card_origin()
            config_manager.set_battery("position", [origin.x(), origin.y()])
        self.remember_position_changed.emit(enabled)

    # --- Posição ---

    def restore_or_place(self):
        restore_card_position(
            self.skin,
            bool(config_manager.get_battery("remember_position", False)),
            config_manager.get_battery("position", None),
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
        if self.service.last_devices and not self.skin.state.order:
            self.skin.set_devices(self.service.last_devices)
        self._animate_show()
        self.service.start()
        self._install_sys_filter(True)
        self.status_changed.emit(True)

    def _install_sys_filter(self, on: bool):
        app = QCoreApplication.instance()
        if app is None or on == self._sys_filter_installed:
            return
        if on:
            app.installNativeEventFilter(self._sys_filter)
        else:
            app.removeNativeEventFilter(self._sys_filter)
        self._sys_filter_installed = on

    def hide(self):
        self._install_sys_filter(False)
        self.service.stop()
        self.skin.forget_show_desktop()
        self._animate_hide()
        self.status_changed.emit(False)

    def on_skin_closed(self):
        self.hide()
        config_manager.set_battery("enabled", False)

    def stop(self):
        self._install_sys_filter(False)
        self.service.stop()
