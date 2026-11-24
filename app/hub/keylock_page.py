"""Hub: página Lock Keys. Extraído de `pages.py` (mesmo código, só em arquivo próprio)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.hub.components.help_badge import HelpBadge
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.widgets.keylock_osd.theme_specs import make_theme_spec as make_keylock_theme_spec
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.widgets.keylock_osd.theme import loader as keylock_theme_loader
from app.hub.base_page import BaseHubPage
from app.hub.ui_tokens import CARD_MARGINS, ROWS_GAP


class LockKeysPage(BaseHubPage):
    """Página de configuração do Caps Lock e Num Lock OSD."""

    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(
            title=t("keys_title"),
            subtitle=t("keys_subtitle"),
            theme=theme,
            parent=parent,
        )
        self.bridge = get_service_bridge()
        self._build_ui()

    def _build_ui(self):
        # Card de Teste
        test_card = QFrame()
        test_card.setProperty("class", "HubCard")
        t_layout = QHBoxLayout(test_card)
        t_layout.setContentsMargins(*CARD_MARGINS)

        t_info = QVBoxLayout()
        t_info.setSpacing(3)
        self.t_title = QLabel(t("keys_test_title"))
        self.t_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.t_desc = QLabel(t("keys_test_sub"))
        self.t_desc.setWordWrap(True)
        self.t_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        # "?" discreto: aviso sobre indicadores de fabricantes que aparecem junto (ex.: Lenovo)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(self.t_title)
        self.oem_help = HelpBadge(t("keys_oem_osd_help"), theme=self._theme)
        title_row.addWidget(self.oem_help, alignment=Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch()
        t_info.addLayout(title_row)
        t_info.addWidget(self.t_desc)
        t_layout.addLayout(t_info, stretch=1)

        self.btn_test = QPushButton(t("keys_test_btn"))
        self.btn_test.setProperty("class", "Chip")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.clicked.connect(lambda: self.bridge.trigger_test_keylock("Caps Lock", True))
        t_layout.addWidget(self.btn_test)

        self.content_layout.addWidget(test_card)

        # Card de Posição na tela (compartilhada com o Mixer de Volume)
        self._add_osd_position_card("keylock", "keys_pos_sub",lambda: self.bridge.trigger_test_keylock("Caps Lock", True))

        # Card de Tema visual (mostra o flyout ao escolher, para ver o resultado)
        self.theme_picker = ThemeGalleryCard(
            keylock_theme_loader,
            "keylock",
            make_keylock_theme_spec,
            lambda: self.bridge.trigger_test_keylock("Caps Lock", True),
            self._theme,
            appliers=self.bridge.theme_appliers(),
            parent=self,
        )
        self.content_layout.addWidget(self.theme_picker)

        # Card de Opções
        card = QFrame()
        card.setProperty("class", "HubCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(*CARD_MARGINS)
        c_layout.setSpacing(ROWS_GAP)

        keys_opts = [
            ("keys_opt_caps_title", "keys_opt_caps_sub", "Caps Lock"),
            ("keys_opt_num_title", "keys_opt_num_sub", "Num Lock"),
        ]
        self._opt_labels = []
        self._key_switches: dict[str, PillSwitch] = {}

        for i, (name_key, desc_key, key_id) in enumerate(keys_opts):
            row = QHBoxLayout()
            info = QVBoxLayout()
            info.setSpacing(2)
            lbl_n = QLabel(t(name_key))
            lbl_n.setStyleSheet("font-size: 13.5px; font-weight: 600;")
            lbl_d = QLabel(t(desc_key))
            lbl_d.setWordWrap(True)
            lbl_d.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
            if not bool(t(desc_key)):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
                lbl_d.hide()
            info.addWidget(lbl_n)
            info.addWidget(lbl_d)
            self._opt_labels.append((lbl_n, name_key, lbl_d, desc_key))

            s = PillSwitch(checked=config_manager.is_keylock_key_enabled(key_id), theme=self._theme)
            s.toggled.connect(lambda checked, k=key_id: config_manager.set_keylock_key_enabled(k, checked))
            self._key_switches[key_id] = s
            row.addLayout(info, stretch=1)
            row.setAlignment(info, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(s, alignment=Qt.AlignmentFlag.AlignVCenter)
            c_layout.addLayout(row)

            if i < len(keys_opts) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setProperty("class", "HubDivider")
                c_layout.addWidget(sep)

        self.content_layout.addWidget(card)

        # Card de Atalho de Teclado
        hk_card = QFrame()
        hk_card.setProperty("class", "HubCard")
        hk_layout = QHBoxLayout(hk_card)
        hk_layout.setContentsMargins(*CARD_MARGINS)

        hk_info = QVBoxLayout()
        hk_info.setSpacing(3)
        self.hk_title = QLabel(t("keys_hotkey_title"))
        self.hk_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.hk_desc = QLabel(t("keys_hotkey_sub"))
        self.hk_desc.setWordWrap(True)
        self.hk_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        hk_info.addWidget(self.hk_title)
        hk_info.addWidget(self.hk_desc)
        hk_layout.addLayout(hk_info, stretch=1)

        self.hk_picker = ShortcutPicker(
            current_shortcut=config_manager.get_keylock_hotkey("Win+Alt+K"),
            default_shortcut="Win+Alt+K",
            theme=self._theme,
            parent=hk_card,
        )
        self.hk_picker.shortcut_changed.connect(self._on_hotkey_changed)
        hk_layout.addWidget(self.hk_picker)
        self.content_layout.addWidget(hk_card)

        self.content_layout.addStretch()

    def _on_hotkey_changed(self, new_shortcut: str):
        self.bridge.update_keylock_hotkey(new_shortcut)

    def retranslate_ui(self):
        if hasattr(self, "theme_picker"):
            self.theme_picker.retranslate_ui()
        self.set_header(t("keys_title"), t("keys_subtitle"))
        self._retranslate_osd_position_card()
        if hasattr(self, "t_title"):
            self.t_title.setText(t("keys_test_title"))
        if hasattr(self, "t_desc"):
            self.t_desc.setText(t("keys_test_sub"))
        if hasattr(self, "oem_help"):
            self.oem_help.set_text(t("keys_oem_osd_help"))
        if hasattr(self, "btn_test"):
            self.btn_test.setText(t("keys_test_btn"))
        if hasattr(self, "_opt_labels"):
            for lbl_n, name_key, lbl_d, desc_key in self._opt_labels:
                lbl_n.setText(t(name_key))
                txt = t(desc_key)
                lbl_d.setText(txt)
                lbl_d.setVisible(bool(txt))
        if hasattr(self, "hk_title"):
            self.hk_title.setText(t("keys_hotkey_title"))
        if hasattr(self, "hk_desc"):
            self.hk_desc.setText(t("keys_hotkey_sub"))
        if hasattr(self, "hk_picker"):
            self.hk_picker.retranslate_ui()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        for switch in self._key_switches.values():
            switch.set_theme(theme)   # senão o switch fica com o destaque de quando a página foi criada
        if hasattr(self, "hk_picker"):
            self.hk_picker.set_theme(theme)
        if hasattr(self, "theme_picker"):
            self.theme_picker.set_theme(theme)
        if hasattr(self, "oem_help"):
            self.oem_help.set_theme(theme)
