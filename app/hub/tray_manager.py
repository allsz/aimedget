"""
AimedgetTrayIcon - Ícone na bandeja do sistema (System Tray) para o Aimedget.
Permite abrir/ocultar a janela do Hub, alternar widgets e encerrar o aplicativo por completo.
"""

from typing import Callable, Optional
from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app.core.i18n import t
from app.hub.hub_icon import create_aimedget_icon
from app.hub.service_bridge import get_service_bridge
from app.ui_components.fluent_menu import FluentMusicMenu


class AimedgetTrayIcon(QSystemTrayIcon):
    open_hub_requested = Signal()

    def __init__(self, on_open_hub: Optional[Callable[[], None]] = None,
                 on_quit: Optional[Callable[[], None]] = None, parent=None):
        super().__init__(parent)
        # Encerrar: o Hub passa o encerramento completo (hub_window.quit_app); sem ele, sai direto do loop
        self._on_quit = on_quit or (lambda: QApplication.exit(0))
        self.setIcon(create_aimedget_icon(32))
        self.setToolTip("Aimedget Suite")

        if on_open_hub:
            self.open_hub_requested.connect(on_open_hub)

        self._menu = None
        self._build_menu()
        self.activated.connect(self._on_activated)

    def _build_menu(self):
        bridge = get_service_bridge()
        self._menu = FluentMusicMenu()

        # 1. Abrir Aimedget Hub
        self.act_open = QAction(t("tray_open_hub"), self)
        self.act_open.triggered.connect(self.open_hub_requested.emit)
        self._menu.addAction(self.act_open)

        self._menu.addSeparator()

        # 2. Toggle rápido do Vinyl Music Widget
        self.act_music = QAction(t("tray_music_widget"), self)
        self.act_music.setCheckable(True)
        self.act_music.setChecked(bridge.is_music_widget_enabled())
        self.act_music.toggled.connect(bridge.set_music_widget_enabled)
        self._menu.addAction(self.act_music)

        # 3. Toggle rápido do Caps Lock Flyout
        self.act_keys = QAction(t("tray_keys_flyout"), self)
        self.act_keys.setCheckable(True)
        self.act_keys.setChecked(bridge.is_keylock_enabled())
        self.act_keys.toggled.connect(bridge.set_keylock_enabled)
        self._menu.addAction(self.act_keys)

        # 4. Toggle rápido do Volume Mixer
        self.act_vol = QAction(t("tray_vol_mixer"), self)
        self.act_vol.setCheckable(True)
        self.act_vol.setChecked(bridge.is_volume_mixer_enabled())
        self.act_vol.toggled.connect(bridge.set_volume_mixer_enabled)
        self._menu.addAction(self.act_vol)

        self._menu.addSeparator()

        # 5. Sair do aplicativo
        self.act_exit = QAction(t("tray_quit"), self)
        self.act_exit.triggered.connect(lambda: self._on_quit())
        self._menu.addAction(self.act_exit)

        self.setContextMenu(self._menu)

    def retranslate_ui(self):
        if hasattr(self, "act_open"):
            self.act_open.setText(t("tray_open_hub"))
        if hasattr(self, "act_music"):
            self.act_music.setText(t("tray_music_widget"))
        if hasattr(self, "act_keys"):
            self.act_keys.setText(t("tray_keys_flyout"))
        if hasattr(self, "act_vol"):
            self.act_vol.setText(t("tray_vol_mixer"))
        if hasattr(self, "act_exit"):
            self.act_exit.setText(t("tray_quit"))

    def update_theme(self, theme):
        """Atualiza a paleta de cores do menu do Tray em tempo real."""
        if self._menu:
            self._menu.set_theme(theme)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        # Um ou dois cliques no ícone do tray abre o Hub
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_hub_requested.emit()
