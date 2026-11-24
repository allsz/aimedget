"""
Página do Performance Widget no Hub: posição, tamanho, comportamento (lembrar posição, fixar no desktop,
exibir ao iniciar, abrir agora) e atalho de teclado.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.preview_card import PreviewCard
from app.hub.components.collapsible_section import skin_and_theme_block
from app.hub.components.help_badge import HelpBadge
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.components.responsive_grid import ResponsiveCardGrid
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.scale_card import ScaleCard
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.core.screen_metrics import SCALE_PCT_MAX, SCALE_PCT_MIN
from app.hub.pages import BaseHubPage
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.services.fps_service import fps_capability_status, perf_log_users_group_name, request_fps_permission
from app.widgets.performance import init_performance_skin_specs
from app.widgets.performance.card_state import SKIN_NOTHING_DOT
from app.widgets.performance.theme import loader as perf_theme_loader
from app.widgets.performance.theme_specs import make_theme_spec as make_perf_theme_spec
from app.hub.ui_tokens import INLINE_GAP, ROWS_GAP


class PerformancePage(BaseHubPage):
    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(title=t("perf_title"), subtitle=t("perf_subtitle"), theme=theme, parent=parent)
        self.bridge = get_service_bridge()
        self.controller = self.bridge.performance_controller
        self._fps_perm_requested = False
        self._build_ui()
        self.bridge.performance_skin_changed.connect(self._sync_skin_selection)

    def _build_ui(self):
        # 1. Posição
        card, row = self._card()
        pos_info = self._info("weather_pos_title", "weather_pos_sub", 14)
        row.addLayout(pos_info, stretch=1)
        row.setAlignment(pos_info, Qt.AlignmentFlag.AlignVCenter)
        self.pos_picker = PositionPicker(current_pos="tr", theme=self._theme, parent=card)
        self.pos_picker.position_changed.connect(self.bridge.move_performance_to_screen_position)
        row.addWidget(self.pos_picker)
        self.content_layout.addWidget(card)

        # 2. Estilo (skins do cartão de desempenho)
        card, col = self._card(vertical=True)
        col.setContentsMargins(22, 20, 22, 22)
        col.addLayout(self._info("perf_style_title", "perf_style_sub", 14.5))
        col.addSpacing(18)
        self._skin_grid = ResponsiveCardGrid(min_card_width=150, spacing=16, parent=card)
        self._skin_cards: dict[str, PreviewCard] = {}
        for spec in init_performance_skin_specs():
            pc = PreviewCard(
                spec=spec,
                theme=self._theme,
                is_selected=(spec.id == self.controller.active_skin_name),
                parent=self._skin_grid,
            )
            pc.clicked.connect(self.bridge.set_performance_skin)
            self._skin_cards[spec.id] = pc
            self._skin_grid.add_card(pc)
        col.addWidget(self._skin_grid)
        self.theme_picker = ThemeGalleryCard(
            perf_theme_loader,
            "performance",
            make_perf_theme_spec,
            self.bridge.apply_performance_theme,
            self._theme,
            appliers=self.bridge.theme_appliers(),
            parent=self,
            subtitle_key="theme_picker_sub_performance",
            default_title_key="theme_default_nothing",
        )
        skin_block, self.theme_section = skin_and_theme_block(
            card,
            self.theme_picker,
            self.content_layout.spacing(),
            self.controller.active_skin_name == SKIN_NOTHING_DOT,
        )
        self.content_layout.addWidget(skin_block)

        # 2b. Tamanho (depois de escolher a skin)
        self.scale_card = ScaleCard("weather_size_title", "weather_size_sub", self._theme, SCALE_PCT_MIN, SCALE_PCT_MAX, self)
        self.scale_card.auto_clicked.connect(lambda: self.controller.set_scale(None))
        self.scale_card.live_changed.connect(lambda pct: self.controller.apply_scale_live(pct / 100.0))
        self.scale_card.committed.connect(lambda pct: self.controller.set_scale(pct / 100.0))
        self.content_layout.addWidget(self.scale_card)
        self.controller.skin.scale_applied.connect(lambda _s: self._sync_size())   # acompanha a animação quadro a quadro
        self.controller.scale_changed.connect(lambda _s: self._sync_size())
        self._sync_size()

        # 3. Contador de FPS (opcional, somente em jogos)
        card, col = self._card(vertical=True)
        col.setSpacing(ROWS_GAP)
        fps_row = QHBoxLayout()
        fps_row.setSpacing(16)
        fps_info = QVBoxLayout()
        fps_info.setSpacing(3)
        fps_title_row = QHBoxLayout()
        fps_title_row.setContentsMargins(0, 0, 0, 0)
        fps_title_row.setSpacing(6)
        lbl_fps_title = QLabel(t("perf_fps_title"))
        lbl_fps_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self._texts.append((lbl_fps_title, "perf_fps_title"))
        self.fps_help = HelpBadge(t("perf_fps_help"), theme=self._theme)
        fps_title_row.addWidget(lbl_fps_title)
        fps_title_row.addWidget(self.fps_help, alignment=Qt.AlignmentFlag.AlignVCenter)
        fps_title_row.addStretch()
        lbl_fps_sub = QLabel(t("perf_fps_sub"))
        lbl_fps_sub.setWordWrap(True)
        lbl_fps_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        self._texts.append((lbl_fps_sub, "perf_fps_sub"))
        self._subs.append(lbl_fps_sub)
        fps_info.addLayout(fps_title_row)
        fps_info.addWidget(lbl_fps_sub)
        fps_row.addLayout(fps_info, stretch=1)
        fps_row.setAlignment(fps_info, Qt.AlignmentFlag.AlignVCenter)
        self.sw_fps = PillSwitch(
            checked=bool(config_manager.get_performance("fps_enabled", False)),
            theme=self._theme,
        )
        self.sw_fps.toggled.connect(self.controller.set_fps_enabled)
        fps_row.addWidget(self.sw_fps, alignment=Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(fps_row)
        self.controller.fps_enabled_changed.connect(self._sync_fps)

        col.addWidget(self._divider())

        fps_foot = QHBoxLayout()
        fps_foot.setSpacing(INLINE_GAP)
        self.lbl_fps_status = QLabel()
        self.lbl_fps_status.setWordWrap(True)
        self.lbl_fps_status.setStyleSheet(f"color: {self._theme.mute}; font-size: 12px;")
        self._subs.append(self.lbl_fps_status)
        fps_foot.addWidget(self.lbl_fps_status, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.btn_grant_fps = self._chip(t("perf_fps_grant_btn"), self._on_grant_fps_clicked)
        fps_foot.addWidget(self.btn_grant_fps, alignment=Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(fps_foot)
        self.content_layout.addWidget(card)
        self._refresh_fps_status()

        # 4. Comportamento
        card, col = self._card(vertical=True)
        col.setSpacing(ROWS_GAP)
        self.sw_remember = self._switch_row(
            col,
            "weather_opt_remember_title",
            "weather_opt_remember_sub",
            bool(config_manager.get_performance("remember_position", False)),
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
            bool(config_manager.get_performance("show_on_startup", False)),
            lambda v: config_manager.set_performance("show_on_startup", bool(v)),
        )
        col.addWidget(self._divider())
        row = QHBoxLayout()
        show_info = self._info("weather_opt_show_title", "weather_opt_show_sub")
        row.addLayout(show_info, stretch=1)
        row.setAlignment(show_info, Qt.AlignmentFlag.AlignVCenter)
        self.btn_show = self._chip(t("weather_opt_show_btn"), self._on_show_clicked)
        row.addWidget(self.btn_show, alignment=Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(row)
        self.content_layout.addWidget(card)

        # 4. Atalho
        card, row = self._card()
        hk_info = self._info("perf_hotkey_title", "perf_hotkey_sub", 14)
        row.addLayout(hk_info, stretch=1)
        row.setAlignment(hk_info, Qt.AlignmentFlag.AlignVCenter)
        self.hk_picker = ShortcutPicker(
            current_shortcut=config_manager.get_performance("hotkey", "Win+Alt+P"),
            default_shortcut="Win+Alt+P",
            theme=self._theme,
            parent=card,
        )
        self.hk_picker.shortcut_changed.connect(self.bridge.update_performance_hotkey)
        row.addWidget(self.hk_picker)
        self.content_layout.addWidget(card)

        self.content_layout.addStretch()

    def _sync_size(self):
        """Chip Automático e polegar seguem o cartão (inclusive enquanto ele anima até o tamanho novo)."""
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

    def _sync_fps(self, enabled: bool):
        if self.sw_fps.isChecked() != enabled:
            self.sw_fps.blockSignals(True)
            self.sw_fps.set_checked(enabled, animated=False)
            self.sw_fps.blockSignals(False)

    def _refresh_fps_status(self):
        status = fps_capability_status()
        if status == "ready":
            self.lbl_fps_status.setText(t("perf_fps_status_ready"))
            self.btn_grant_fps.hide()
        elif status == "missing_binary":
            self.lbl_fps_status.setText(t("perf_fps_status_missing"))
            self.btn_grant_fps.hide()
        elif self._fps_perm_requested:
            self.lbl_fps_status.setText(t("perf_fps_status_relogin"))
            self.btn_grant_fps.hide()
        else:
            self.lbl_fps_status.setText(t("perf_fps_status_perm", group=perf_log_users_group_name()))
            self.btn_grant_fps.show()

    def _on_grant_fps_clicked(self):
        if request_fps_permission():
            self._fps_perm_requested = True
            self._refresh_fps_status()

    def _on_show_clicked(self):
        self.bridge.set_performance_enabled(True)
        self.controller.skin.raise_()
        self.controller.skin.activateWindow()

    def _sync_skin_selection(self, skin_id: str):
        for key, card in getattr(self, "_skin_cards", {}).items():
            card.set_selected(key == skin_id)
        if hasattr(self, "theme_section"):
            self.theme_section.set_open(skin_id == SKIN_NOTHING_DOT)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_skin_selection(self.controller.active_skin_name)
        self._sync_size()
        self._sync_desktop(self.controller.skin.is_desktop_mode())
        self._sync_remember(bool(config_manager.get_performance("remember_position", False)))
        self._sync_fps(bool(config_manager.get_performance("fps_enabled", False)))
        self._refresh_fps_status()

    def retranslate_ui(self):
        self.set_header(t("perf_title"), t("perf_subtitle"))
        for label, key in self._texts:
            txt = t(key)
            label.setText(txt)
            if label in self._subs:
                label.setVisible(bool(txt))
        if hasattr(self, "_skin_cards") and "fluent" in self._skin_cards:
            card = self._skin_cards["fluent"]
            card._spec.title = t("perf_skin_label")
            card._invalidate_cache()
            card.update()
        self.scale_card.retranslate()
        if hasattr(self, "theme_picker"):
            self.theme_picker.retranslate_ui()
        self.btn_show.setText(t("weather_opt_show_btn"))
        self.btn_grant_fps.setText(t("perf_fps_grant_btn"))
        self.fps_help.set_text(t("perf_fps_help"))
        self._refresh_fps_status()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        for sub in self._subs:
            px = "12px" if sub is self.lbl_fps_status else "12.5px"
            sub.setStyleSheet(f"color: {theme.mute}; font-size: {px};")
        for card in getattr(self, "_skin_cards", {}).values():
            card.set_theme(theme)
        for w in (self.scale_card, self.theme_picker, self.pos_picker, self.hk_picker, self.fps_help, self.sw_fps, self.sw_remember, self.sw_desktop, self.sw_startup):
            if hasattr(w, "set_theme"):
                w.set_theme(theme)
