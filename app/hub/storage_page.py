"""
Página do Storage Widget no Hub: posição, tamanho, pastas monitoradas, comportamento (sempre expandido,
lembrar posição, fixar no desktop, exibir ao iniciar, abrir agora) e atalho de teclado.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.screen_metrics import SCALE_PCT_MAX, SCALE_PCT_MIN
from app.hub.components.city_list import CityList
from app.hub.components.fold import Fold
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.components.scale_card import ScaleCard
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.pages import BaseHubPage
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.services.storage_service import MAX_FOLDERS, drive_of


class StoragePage(BaseHubPage):
    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(title=t("storage_title"), subtitle=t("storage_subtitle"), theme=theme, parent=parent)
        self.bridge = get_service_bridge()
        self.controller = self.bridge.storage_controller
        self.service = self.controller.service
        self._texts: list[tuple[QLabel, str]] = []
        self._subs: list[QLabel] = []
        self._build_ui()
        self.service.folders_changed.connect(self._on_folders_changed)
        self.controller.always_expanded_changed.connect(self._sync_always_expanded)

    def _card(self, vertical: bool = False):
        card = QFrame()
        card.setProperty("class", "HubCard")
        layout = QVBoxLayout(card) if vertical else QHBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        return card, layout

    def _info(self, title_key: str, sub_key: str, title_px: float = 13.5) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel(t(title_key))
        title.setStyleSheet(f"font-size: {title_px}px; font-weight: 600;")
        sub_txt = t(sub_key)
        sub = QLabel(sub_txt)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        if not bool(sub_txt):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
            sub.hide()
        box.addWidget(title)
        box.addWidget(sub)
        self._texts += [(title, title_key), (sub, sub_key)]
        self._subs.append(sub)
        return box

    def _divider(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setProperty("class", "HubDivider")
        return sep

    def _chip(self, text: str, on_click) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("class", "Chip")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(on_click)
        return btn

    def _switch_row(self, col: QVBoxLayout, title_key: str, sub_key: str, checked: bool, on_toggle) -> PillSwitch:
        row = QHBoxLayout()
        row.addLayout(self._info(title_key, sub_key), stretch=1)
        sw = PillSwitch(checked=checked, theme=self._theme)
        sw.toggled.connect(on_toggle)
        row.addWidget(sw)
        col.addLayout(row)
        return sw

    def _build_ui(self):
        # 1. Posição
        card, row = self._card()
        pos_info = self._info("weather_pos_title", "weather_pos_sub", 14)
        row.addLayout(pos_info, stretch=1)
        row.setAlignment(pos_info, Qt.AlignmentFlag.AlignVCenter)
        self.pos_picker = PositionPicker(current_pos="tr", theme=self._theme, parent=card)
        self.pos_picker.position_changed.connect(self.bridge.move_storage_to_screen_position)
        row.addWidget(self.pos_picker)
        self.content_layout.addWidget(card)

        # 2. Tamanho
        self.scale_card = ScaleCard(
            "weather_size_title", "weather_size_sub", self._theme, SCALE_PCT_MIN, SCALE_PCT_MAX, self
        )
        self.scale_card.auto_clicked.connect(lambda: self.controller.set_scale(None))
        self.scale_card.live_changed.connect(lambda pct: self.controller.apply_scale_live(pct / 100.0))
        self.scale_card.committed.connect(lambda pct: self.controller.set_scale(pct / 100.0))
        self.content_layout.addWidget(self.scale_card)
        self.controller.skin.scale_applied.connect(lambda _s: self._sync_size())
        self.controller.scale_changed.connect(lambda _s: self._sync_size())
        self._sync_size()

        # 3. Pastas monitoradas (usa CityList + Fold para animação de entrada/saída sem tremor)
        self.folders_card, col = self._card(vertical=True)
        col.setSpacing(0)
        head_row = QHBoxLayout()
        head_row.addLayout(self._info("storage_folders_title", "storage_folders_sub", 14), stretch=1)
        self.btn_add_folder = self._chip(t("storage_add_folder"), self._on_add_folder)
        self.btn_restore_folders = self._chip(t("storage_restore_defaults"), self._on_restore_defaults)
        head_row.addWidget(self.btn_add_folder)
        head_row.addWidget(self.btn_restore_folders)
        col.addLayout(head_row)

        self.lbl_empty_folders = QLabel(t("storage_empty_hint"))
        self.lbl_empty_folders.setWordWrap(True)
        self.lbl_empty_folders.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        self._subs.append(self.lbl_empty_folders)
        self.fold_empty_folders = Fold(self.lbl_empty_folders, gap=10)
        col.addWidget(self.fold_empty_folders)
        col.addSpacing(10)

        self.folder_list = CityList(self._theme, self.folders_card)
        self.folder_list.moved.connect(self.service.move_folder)
        self.folder_list.removed.connect(self._on_remove_folder_at)
        col.addWidget(self.folder_list)
        self.content_layout.addWidget(self.folders_card)
        self._rebuild_folder_list()

        # 4. Comportamento
        card, col = self._card(vertical=True)
        col.setSpacing(12)

        self.sw_scan_games = self._switch_row(
            col,
            "storage_scan_games_title",
            "storage_scan_games_sub",
            bool(config_manager.get_storage("scan_games", True)),
            self.controller.set_scan_games,
        )
        col.addWidget(self._divider())

        self.sw_always_expanded = self._switch_row(
            col,
            "storage_always_expanded_title",
            "storage_always_expanded_sub",
            bool(config_manager.get_storage("always_expanded", False)),
            self.controller.set_always_expanded,
        )
        col.addWidget(self._divider())

        self.sw_remember = self._switch_row(
            col,
            "weather_opt_remember_title",
            "weather_opt_remember_sub",
            bool(config_manager.get_storage("remember_position", False)),
            self.controller.set_remember_position,
        )
        self.controller.remember_position_changed.connect(self._sync_remember)
        col.addWidget(self._divider())

        self.sw_desktop = self._switch_row(
            col,
            "weather_opt_desktop_title",
            "weather_opt_desktop_sub",
            self.controller.skin.is_desktop_mode(),
            self.controller.set_desktop_mode,
        )
        self.controller.desktop_mode_changed.connect(self._sync_desktop)
        col.addWidget(self._divider())

        self.sw_startup = self._switch_row(
            col,
            "weather_opt_startup_title",
            "weather_opt_startup_sub",
            bool(config_manager.get_storage("show_on_startup", False)),
            lambda on: config_manager.set_storage("show_on_startup", bool(on)),
        )
        col.addWidget(self._divider())

        show_row = QHBoxLayout()
        show_info = self._info("weather_opt_show_title", "weather_opt_show_sub")
        show_row.addLayout(show_info, stretch=1)
        show_row.setAlignment(show_info, Qt.AlignmentFlag.AlignVCenter)
        self.btn_show = self._chip(t("weather_opt_show_btn"), self._on_show_clicked)
        show_row.addWidget(self.btn_show, alignment=Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(show_row)
        self.content_layout.addWidget(card)

        # 5. Atalho de teclado
        card, row = self._card()
        hk_info = self._info("perf_hotkey_title", "perf_hotkey_sub", 14)
        row.addLayout(hk_info, stretch=1)
        row.setAlignment(hk_info, Qt.AlignmentFlag.AlignVCenter)
        self.hk_picker = ShortcutPicker(
            current_shortcut=config_manager.get_storage("hotkey", "Win+Alt+S"),
            default_shortcut="Win+Alt+S",
            theme=self._theme,
            parent=card,
        )
        self.hk_picker.shortcut_changed.connect(self.bridge.set_storage_hotkey)
        row.addWidget(self.hk_picker)
        self.content_layout.addWidget(card)

        self.content_layout.addStretch()

    # --- Pastas ---

    def _on_folders_changed(self):
        if self.folder_list._drag_row is None:
            self._rebuild_folder_list()

    def _on_remove_folder_at(self, index: int):
        folders = self.service.folders()
        if 0 <= index < len(folders):
            self.service.remove_folder(folders[index]["path"])

    def _rebuild_folder_list(self):
        folders = self.service.folders()
        items = [
            (f["path"].lower(), f["name"], f"{drive_of(f['path'])} · {f['path']}")
            for f in folders
        ]
        self.folder_list.set_items(items)
        follow = self.folder_list.follow_current_change()
        self.fold_empty_folders.set_open(not folders, follow)
        self.btn_add_folder.setEnabled(len(folders) < MAX_FOLDERS)

    def _on_add_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, t("storage_pick_folder_title"))
        if chosen:
            self.service.add_folder(chosen)

    def _on_restore_defaults(self):
        self.service.restore_defaults()

    def _on_show_clicked(self):
        self.bridge.set_storage_enabled(True)
        self.controller.skin.raise_()
        self.controller.skin.activateWindow()

    # --- Sincronização ---

    def _sync_size(self):
        pct = max(SCALE_PCT_MIN, min(SCALE_PCT_MAX, int(round(self.controller.skin.scale() * 100))))
        self.scale_card.set_state(self.controller.is_scale_auto(), pct)

    def _sync_desktop(self, enabled: bool):
        if self.sw_desktop.isChecked() != enabled:
            self.sw_desktop.blockSignals(True)
            self.sw_desktop.set_checked(enabled, animated=False)
            self.sw_desktop.blockSignals(False)

    def _sync_remember(self, enabled: bool):
        if self.sw_remember.isChecked() != enabled:
            self.sw_remember.blockSignals(True)
            self.sw_remember.set_checked(enabled, animated=False)
            self.sw_remember.blockSignals(False)

    def _sync_always_expanded(self, enabled: bool):
        if self.sw_always_expanded.isChecked() != enabled:
            self.sw_always_expanded.blockSignals(True)
            self.sw_always_expanded.set_checked(enabled, animated=False)
            self.sw_always_expanded.blockSignals(False)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_size()
        self._sync_desktop(self.controller.skin.is_desktop_mode())
        self._sync_remember(bool(config_manager.get_storage("remember_position", False)))
        self._sync_always_expanded(bool(config_manager.get_storage("always_expanded", False)))

    # --- Tema & idioma ---

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        for sub in self._subs:
            sub.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        self.folder_list.set_theme(theme)
        for w in (
            self.scale_card,
            self.pos_picker,
            self.hk_picker,
            self.sw_scan_games,
            self.sw_always_expanded,
            self.sw_remember,
            self.sw_desktop,
            self.sw_startup,
        ):
            if hasattr(w, "set_theme"):
                w.set_theme(theme)

    def retranslate_ui(self):
        self.set_header(t("storage_title"), t("storage_subtitle"))
        for lbl, key in self._texts:
            txt = t(key)
            lbl.setText(txt)
            if lbl in self._subs:
                lbl.setVisible(bool(txt))
        self.scale_card.retranslate()
        self.btn_add_folder.setText(t("storage_add_folder"))
        self.btn_restore_folders.setText(t("storage_restore_defaults"))
        self.lbl_empty_folders.setText(t("storage_empty_hint"))
        self.btn_show.setText(t("weather_opt_show_btn"))
        self._rebuild_folder_list()
