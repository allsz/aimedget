"""Hub: página Volume. Extraído de `pages.py` (mesmo código, só em arquivo próprio)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.widgets.volume_mixer.theme_specs import make_theme_spec as make_mixer_theme_spec
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.widgets.volume_mixer.theme import loader as mixer_theme_loader
from app.hub.base_page import BaseHubPage


class VolumePage(BaseHubPage):
    """Página de configuração do Mixer de Volume."""

    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(
            title=t("volume_title"),
            subtitle=t("volume_subtitle"),
            theme=theme,
            parent=parent,
        )
        self.bridge = get_service_bridge()
        self._build_ui()

    def _build_ui(self):
        # Card de Teste do Flyout
        test_card = QFrame()
        test_card.setProperty("class", "HubCard")
        t_layout = QHBoxLayout(test_card)
        t_layout.setContentsMargins(18, 14, 18, 14)

        t_info = QVBoxLayout()
        t_info.setSpacing(3)
        self.t_title = QLabel(t("volume_test_title"))
        self.t_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.t_desc = QLabel(t("volume_test_sub"))
        self.t_desc.setWordWrap(True)
        self.t_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        t_info.addWidget(self.t_title)
        t_info.addWidget(self.t_desc)
        t_layout.addLayout(t_info, stretch=1)

        self.btn_test = QPushButton(t("volume_test_btn"))
        self.btn_test.setProperty("class", "Chip")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.clicked.connect(self.bridge.trigger_test_volume)
        t_layout.addWidget(self.btn_test)

        self.content_layout.addWidget(test_card)

        # Card de Posição na tela (compartilhada com o Caps/Num Lock)
        self._add_osd_position_card("mixer", "volume_pos_sub",self.bridge.trigger_test_volume)

        # Card de Tema visual (mostra o flyout ao escolher, para ver o resultado)
        self.theme_picker = ThemeGalleryCard(
            mixer_theme_loader,
            "mixer",
            make_mixer_theme_spec,
            self.bridge.trigger_test_volume,
            self._theme,
            appliers=self.bridge.theme_appliers(),
            parent=self,
        )
        self.content_layout.addWidget(self.theme_picker)

        # Card de Atalho de Teclado
        hk_card = QFrame()
        hk_card.setProperty("class", "HubCard")
        hk_layout = QHBoxLayout(hk_card)
        hk_layout.setContentsMargins(18, 14, 18, 14)

        hk_info = QVBoxLayout()
        hk_info.setSpacing(3)
        self.hk_title = QLabel(t("volume_hotkey_title"))
        self.hk_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.hk_desc = QLabel(t("volume_hotkey_sub"))
        self.hk_desc.setWordWrap(True)
        self.hk_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        hk_info.addWidget(self.hk_title)
        hk_info.addWidget(self.hk_desc)
        hk_layout.addLayout(hk_info, stretch=1)

        self.hk_picker = ShortcutPicker(
            current_shortcut=config_manager.get_volume_hotkey("Win+Alt+V"),
            default_shortcut="Win+Alt+V",
            theme=self._theme,
            parent=hk_card,
        )
        self.hk_picker.shortcut_changed.connect(self._on_hotkey_changed)
        hk_layout.addWidget(self.hk_picker)
        self.content_layout.addWidget(hk_card)

        self.content_layout.addStretch()

    def _on_hotkey_changed(self, new_shortcut: str):
        self.bridge.update_volume_hotkey(new_shortcut)

    def retranslate_ui(self):
        if hasattr(self, "theme_picker"):
            self.theme_picker.retranslate_ui()
        self.set_header(t("volume_title"), t("volume_subtitle"))
        self._retranslate_osd_position_card()
        if hasattr(self, "t_title"):
            self.t_title.setText(t("volume_test_title"))
        if hasattr(self, "t_desc"):
            self.t_desc.setText(t("volume_test_sub"))
        if hasattr(self, "btn_test"):
            self.btn_test.setText(t("volume_test_btn"))
        if hasattr(self, "hk_title"):
            self.hk_title.setText(t("volume_hotkey_title"))
        if hasattr(self, "hk_desc"):
            self.hk_desc.setText(t("volume_hotkey_sub"))
        if hasattr(self, "hk_picker"):
            self.hk_picker.retranslate_ui()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        if hasattr(self, "hk_picker"):
            self.hk_picker.set_theme(theme)
        if hasattr(self, "theme_picker"):
            self.theme_picker.set_theme(theme)
