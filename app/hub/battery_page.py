"""
Página do Battery Widget no Hub: posição, aparência (bento 2×2: centro do anel, nome, textos visíveis, última linha),
tamanho, comportamento (lembrar posição, fixar no desktop, exibir ao iniciar, abrir agora), atalho e dispositivos.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.hub.components.help_badge import HelpBadge
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.tab_pill import Blend, ChipGroup
from app.hub.pages import BaseHubPage
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.widgets.battery import layout as lay
from app.widgets.battery.card_state import (
    FACE_BOTH,
    FACE_HOVER,
    FACE_ICON,
    FACE_PERCENT,
    LABEL_NAME,
    LABEL_TYPE,
    SHOW_ALL,
    SHOW_HEADER,
    SHOW_NAMES,
    SHOW_NONE,
)

# Células segmentadas do bento 2×2: (chave da opção, título, [(valor, rótulo)])
SEGMENTED_CHOICES = (
    ("face", "battery_opt_face_title",
     ((FACE_HOVER, "battery_face_hover_short"), (FACE_ICON, "battery_face_icon"),
      (FACE_PERCENT, "battery_face_percent_short"), (FACE_BOTH, "battery_face_both_short"))),
    ("label", "battery_opt_label_title",
     ((LABEL_NAME, "battery_label_name_short"), (LABEL_TYPE, "battery_label_type"))),
    ("odd", "battery_opt_odd_title",
     ((lay.ODD_CENTER, "battery_odd_center"), (lay.ODD_LEFT, "battery_odd_left"))),
)


def _show_flags(show: str) -> tuple[bool, bool]:
    """(mostrar_titulo, mostrar_nomes) a partir da opção `show`."""
    return show in (SHOW_ALL, SHOW_HEADER), show in (SHOW_ALL, SHOW_NAMES)


def _flags_to_show(show_title: bool, show_names: bool) -> str:
    if show_title and show_names:
        return SHOW_ALL
    if show_title:
        return SHOW_HEADER
    if show_names:
        return SHOW_NAMES
    return SHOW_NONE


class BatteryPage(BaseHubPage):
    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(title=t("battery_title"), subtitle=t("battery_subtitle"), theme=theme, parent=parent)
        self.bridge = get_service_bridge()
        self.controller = self.bridge.battery_controller
        self._texts: list[tuple[QLabel, str]] = []
        self._subs: list[QLabel] = []
        self._groups: dict[str, ChipGroup] = {}
        self._bento_cells: list[QFrame] = []
        self._bento_titles: list[tuple[QLabel, str]] = []
        self._build_ui()
        self.controller.options_changed.connect(lambda _o: self._sync_options())

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
        sub = QLabel(t(sub_key))
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        sub.setVisible(bool(t(sub_key)))
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

    def _bento_cell(self, title_key: str) -> tuple[QFrame, QVBoxLayout]:
        cell = QFrame()
        cell.setObjectName("BentoCell")
        lay_c = QVBoxLayout(cell)
        lay_c.setContentsMargins(14, 12, 14, 12)
        lay_c.setSpacing(10)
        lbl = QLabel(t(title_key))
        lbl.setStyleSheet(f"font-size: 12.5px; font-weight: 600; color: {self._theme.body}; background: transparent;")
        lay_c.addWidget(lbl)
        self._bento_cells.append(cell)
        self._bento_titles.append((lbl, title_key))
        return cell, lay_c

    def _build_appearance_bento(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "HubCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 11)
        grid.setColumnStretch(1, 10)

        # Linha 0 (largura total): Centro do anel
        c_face, l_face = self._bento_cell("battery_opt_face_title")
        g_face = ChipGroup(
            [(v, t(k)) for v, k in SEGMENTED_CHOICES[0][2]],
            lambda v: self.controller.set_option("face", v),
            self._theme,
            selected=self.controller.options.face,
            segmented=True,
        )
        l_face.addStretch()
        l_face.addWidget(g_face)
        self._groups["face"] = g_face
        grid.addWidget(c_face, 0, 0, 1, 2)

        # Linhas 1–2, Coluna 1 (topo): Nome abaixo do anel (esmaece suavemente quando "Nomes" está desligado)
        self._label_cell, l_label = self._bento_cell("battery_opt_label_title")
        g_label = ChipGroup(
            [(v, t(k)) for v, k in SEGMENTED_CHOICES[1][2]],
            lambda v: self.controller.set_option("label", v),
            self._theme,
            selected=self.controller.options.label,
            segmented=True,
        )
        l_label.addStretch()
        l_label.addWidget(g_label)
        self._groups["label"] = g_label
        self._label_fx = QGraphicsOpacityEffect(self._label_cell)
        self._label_cell.setGraphicsEffect(self._label_fx)
        show_t, show_n = _show_flags(self.controller.options.show)
        self._label_dim = Blend(1.0 if show_n else 0.42, self._apply_label_dim, self)
        self._apply_label_dim()
        grid.addWidget(self._label_cell, 1, 1)

        # Linhas 1–2, Coluna 0 (ocupa 2 linhas): Textos visíveis — bandeja interna com 3 linhas + PillSwitch animado
        c_show, l_show = self._bento_cell("battery_opt_show_title")
        self._show_tray = QFrame()
        self._show_tray.setObjectName("ShowTray")
        tray_l = QVBoxLayout(self._show_tray)
        tray_l.setContentsMargins(0, 0, 0, 0)
        tray_l.setSpacing(0)

        row_t = QHBoxLayout()
        row_t.setContentsMargins(12, 8, 10, 8)
        self._lbl_show_title = QLabel(t("battery_show_title_lbl"))
        self._lbl_show_title.setStyleSheet("font-size: 12.5px; font-weight: 500; background: transparent;")
        self.sw_show_title = PillSwitch(checked=show_t, theme=self._theme)
        self.sw_show_title.toggled.connect(self._on_show_toggle)
        row_t.addWidget(self._lbl_show_title, stretch=1)
        row_t.addWidget(self.sw_show_title)
        tray_l.addLayout(row_t, stretch=1)

        self._show_sep = QFrame()
        self._show_sep.setFixedHeight(1)
        tray_l.addWidget(self._show_sep)

        row_n = QHBoxLayout()
        row_n.setContentsMargins(12, 8, 10, 8)
        self._lbl_show_names = QLabel(t("battery_show_names_lbl"))
        self._lbl_show_names.setStyleSheet("font-size: 12.5px; font-weight: 500; background: transparent;")
        self.sw_show_names = PillSwitch(checked=show_n, theme=self._theme)
        self.sw_show_names.toggled.connect(self._on_show_toggle)
        row_n.addWidget(self._lbl_show_names, stretch=1)
        row_n.addWidget(self.sw_show_names)
        tray_l.addLayout(row_n, stretch=1)

        # Terceira linha: "X dispositivos" (vive na linha do título; esmaece quando o título está desligado)
        self._count_sep = QFrame()
        self._count_sep.setFixedHeight(1)
        tray_l.addWidget(self._count_sep)
        self._count_row = QFrame()
        row_c = QHBoxLayout(self._count_row)
        row_c.setContentsMargins(12, 8, 10, 8)
        self._lbl_show_count = QLabel(t("battery_show_count_lbl"))
        self._lbl_show_count.setStyleSheet("font-size: 12.5px; font-weight: 500; background: transparent;")
        self.sw_show_count = PillSwitch(checked=self.controller.options.count, theme=self._theme)
        self.sw_show_count.toggled.connect(self.controller.set_show_count)
        row_c.addWidget(self._lbl_show_count, stretch=1)
        row_c.addWidget(self.sw_show_count)
        tray_l.addWidget(self._count_row, stretch=1)
        self._count_fx = QGraphicsOpacityEffect(self._count_row)
        self._count_row.setGraphicsEffect(self._count_fx)
        self._count_dim = Blend(1.0 if show_t else 0.42, self._apply_count_dim, self)
        self._apply_count_dim()

        l_show.addWidget(self._show_tray, stretch=1)
        grid.addWidget(c_show, 1, 0, 2, 1)

        # Linha 2, Coluna 1 (embaixo): Última linha (texto puro, sem ícone à esquerda)
        c_odd, l_odd = self._bento_cell("battery_opt_odd_title")
        g_odd = ChipGroup(
            [(v, t(k)) for v, k in SEGMENTED_CHOICES[2][2]],
            lambda v: self.controller.set_option("odd", v),
            self._theme,
            selected=self.controller.options.odd,
            segmented=True,
        )
        l_odd.addStretch()
        l_odd.addWidget(g_odd)
        self._groups["odd"] = g_odd
        grid.addWidget(c_odd, 2, 1)

        self._style_bento(self._theme)
        return card

    def _style_bento(self, theme: HubTheme):
        cell_css = (
            f"QFrame#BentoCell {{ background-color: {theme.panel2}; "
            f"border: 1px solid {theme.line}; border-radius: 12px; }}"
        )
        for c in self._bento_cells:
            c.setStyleSheet(cell_css)
        for lbl, _k in self._bento_titles:
            lbl.setStyleSheet(f"font-size: 12.5px; font-weight: 600; color: {theme.body}; background: transparent;")
        self._show_tray.setStyleSheet(
            f"QFrame#ShowTray {{ background-color: {theme.bg}; "
            f"border: 1px solid {theme.line}; border-radius: 10px; }}"
        )
        self._show_sep.setStyleSheet(f"background-color: {theme.line}; border: 0;")
        self._count_sep.setStyleSheet(f"background-color: {theme.line}; border: 0;")
        self._count_row.setStyleSheet("background: transparent;")
        for lbl in (self._lbl_show_title, self._lbl_show_names, self._lbl_show_count):
            lbl.setStyleSheet(f"font-size: 12.5px; font-weight: 500; color: {theme.text}; background: transparent;")

    def _apply_label_dim(self):
        self._label_fx.setOpacity(max(0.2, min(1.0, self._label_dim.value)))

    def _apply_count_dim(self):
        self._count_fx.setOpacity(max(0.2, min(1.0, self._count_dim.value)))

    def _on_show_toggle(self, _checked: bool):
        val = _flags_to_show(self.sw_show_title.isChecked(), self.sw_show_names.isChecked())
        self.controller.set_option("show", val)
        self._label_dim.set(1.0 if self.sw_show_names.isChecked() else 0.42, animated=self.isVisible())
        self._count_dim.set(1.0 if self.sw_show_title.isChecked() else 0.42, animated=self.isVisible())

    def _build_ui(self):
        # 1. Posição
        card, row = self._card()
        pos_info = self._info("weather_pos_title", "weather_pos_sub", 14)
        row.addLayout(pos_info, stretch=1)
        row.setAlignment(pos_info, Qt.AlignmentFlag.AlignVCenter)
        self.pos_picker = PositionPicker(current_pos="tr", theme=self._theme, parent=card)
        self.pos_picker.position_changed.connect(self.bridge.move_battery_to_screen_position)
        row.addWidget(self.pos_picker)
        self.content_layout.addWidget(card)

        # 2. Aparência (Bento 2×2)
        self.content_layout.addWidget(self._build_appearance_bento())

        # 3. Tamanho (livre: o canto do cartão decide)
        card, row = self._card()
        size_info = self._info("battery_size_title", "battery_size_sub", 14)
        row.addLayout(size_info, stretch=1)
        row.setAlignment(size_info, Qt.AlignmentFlag.AlignVCenter)
        self.btn_reset = self._chip(t("battery_reset_size"), self.controller.reset_size)
        row.addWidget(self.btn_reset, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.content_layout.addWidget(card)

        # 4. Comportamento
        card, col = self._card(vertical=True)
        col.setSpacing(12)
        self.sw_remember = self._switch_row(
            col, "weather_opt_remember_title", "weather_opt_remember_sub",
            bool(config_manager.get_battery("remember_position", False)), self.controller.set_remember_position)
        self.controller.remember_position_changed.connect(lambda on: self._sync_switch(self.sw_remember, on))
        col.addWidget(self._divider())
        self.sw_desktop = self._switch_row(
            col, "weather_opt_desktop_title", "weather_opt_desktop_sub",
            self.controller.skin.is_desktop_mode(), self.controller.set_desktop_mode)
        self.controller.desktop_mode_changed.connect(lambda on: self._sync_switch(self.sw_desktop, on))
        col.addWidget(self._divider())
        self.sw_startup = self._switch_row(
            col, "weather_opt_startup_title", "weather_opt_startup_sub",
            bool(config_manager.get_battery("show_on_startup", False)),
            lambda on: config_manager.set_battery("show_on_startup", bool(on)))
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
            current_shortcut=config_manager.get_battery("hotkey", "Win+Alt+B"),
            default_shortcut="Win+Alt+B",
            theme=self._theme,
            parent=card,
        )
        self.hk_picker.shortcut_changed.connect(self.bridge.set_battery_hotkey)
        row.addWidget(self.hk_picker)
        self.content_layout.addWidget(card)

        # 6. Dispositivos suportados
        card, row = self._card()
        row.addLayout(self._info("battery_sources_title", "battery_sources_sub", 14), stretch=1)
        self.sources_help = HelpBadge(t("battery_sources_help"), self._theme, card)
        row.addWidget(self.sources_help, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.content_layout.addWidget(card)

        self.content_layout.addStretch()

    def _on_show_clicked(self):
        self.bridge.set_battery_enabled(True)
        self.controller.skin.raise_()
        self.controller.skin.activateWindow()

    # --- Sincronização ---

    @staticmethod
    def _sync_switch(sw: PillSwitch, enabled: bool, animated: bool = False):
        if sw.isChecked() != enabled:
            sw.blockSignals(True)
            sw.set_checked(enabled, animated=animated)
            sw.blockSignals(False)

    def _sync_options(self):
        vis = self.isVisible()
        for key, group in self._groups.items():
            value = getattr(self.controller.options, key)
            if group.selected() != value:
                group.set_selected(value, animated=vis)
        show_t, show_n = _show_flags(self.controller.options.show)
        self._sync_switch(self.sw_show_title, show_t, animated=vis)
        self._sync_switch(self.sw_show_names, show_n, animated=vis)
        self._label_dim.set(1.0 if show_n else 0.42, animated=vis)
        self._sync_switch(self.sw_show_count, self.controller.options.count, animated=vis)
        self._count_dim.set(1.0 if show_t else 0.42, animated=vis)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_options()
        self._sync_switch(self.sw_desktop, self.controller.skin.is_desktop_mode())
        self._sync_switch(self.sw_remember, bool(config_manager.get_battery("remember_position", False)))

    # --- Tema & idioma ---

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        self._style_bento(theme)
        for sub in self._subs:
            sub.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        for w in (
            self.pos_picker,
            self.hk_picker,
            self.sw_show_title,
            self.sw_show_names,
            self.sw_show_count,
            self.sw_remember,
            self.sw_desktop,
            self.sw_startup,
            *self._groups.values(),
        ):
            if hasattr(w, "set_theme"):
                w.set_theme(theme)

    def retranslate_ui(self):
        self.set_header(t("battery_title"), t("battery_subtitle"))
        for lbl, key in self._texts:
            txt = t(key)
            lbl.setText(txt)
            if lbl in self._subs:
                lbl.setVisible(bool(txt))
        for lbl, key in self._bento_titles:
            lbl.setText(t(key))
        for key, _title, chips in SEGMENTED_CHOICES:
            group = self._groups[key]
            for value, label_key in chips:
                group.button(value).setText(t(label_key))
        self._lbl_show_title.setText(t("battery_show_title_lbl"))
        self._lbl_show_names.setText(t("battery_show_names_lbl"))
        self._lbl_show_count.setText(t("battery_show_count_lbl"))
        self.btn_reset.setText(t("battery_reset_size"))
        self.btn_show.setText(t("weather_opt_show_btn"))
