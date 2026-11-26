"""Hub: página Timer. Extraído de `pages.py` (mesmo código, só em arquivo próprio)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from app.core.config_manager import config_manager
from app.core.screen_metrics import SCALE_PCT_MAX, SCALE_PCT_MIN
from app.core.i18n import i18n, t
from app.core.skin_packs import discover as discover_skin_packs
from app.core.theme_loader import APP_ID, APP_NAME, DEFAULT_ID
from app.hub.components.collapsible_section import skin_and_theme_block, skin_supports_themes
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.components.scale_card import ScaleCard
from app.hub.components.responsive_grid import ResponsiveCardGrid
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.core.preview_card import PreviewCard
from app.widgets.timer.theme import (
    DEFAULT_THEME as TIMER_DEFAULT_THEME,
    app_timer_theme,
    loader as timer_theme_loader,
    nothing_loader as nothing_timer_theme_loader,
)
from app.widgets.timer.theme_specs import (
    make_nothing_theme_spec,
    make_theme_spec as make_timer_theme_spec,
)
from app.widgets.timer import init_timer_skin_specs
from app.hub.base_page import BaseHubPage
from app.hub.ui_tokens import CARD_MARGINS, ROWS_GAP


class _NothingTimerThemeCard(QFrame):
    """Galeria enxuta de cor de destaque da skin Nothing Dot: apenas Nothing Red e Aimedget (cor do app)."""

    def __init__(self, on_applied, theme: HubTheme, parent=None):
        super().__init__(parent)
        self.setProperty("class", "HubCard")
        self._on_applied = on_applied
        self._theme = theme
        self._cards: dict[str, PreviewCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 22)
        outer.setSpacing(16)

        self._title = QLabel(t("theme_picker_title"))
        self._title.setStyleSheet("font-size: 14.5px; font-weight: 600;")
        outer.addWidget(self._title)

        self._grid = ResponsiveCardGrid(min_card_width=150, spacing=16, parent=self)
        outer.addWidget(self._grid)

        active = nothing_timer_theme_loader.active_id()
        for tid, title, th in (
            (DEFAULT_ID, t("theme_default_nothing"), TIMER_DEFAULT_THEME),
            (APP_ID, APP_NAME, app_timer_theme()),
        ):
            spec = make_nothing_theme_spec(tid, title, th)
            card = PreviewCard(spec=spec, theme=self._theme, is_selected=(tid == active), parent=self._grid)
            card.clicked.connect(self._on_pick)
            self._cards[tid] = card
            self._grid.add_card(card)

    def _on_pick(self, tid: str):
        nothing_timer_theme_loader.set_active(tid)
        for k, card in self._cards.items():
            card.set_selected(k == tid)
        self._on_applied()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        for card in self._cards.values():
            card.set_theme(theme)

    def retranslate_ui(self):
        self._title.setText(t("theme_picker_title"))
        card = self._cards.get(DEFAULT_ID)
        if card is not None:
            card._spec.title = t("theme_default_nothing")
            card._invalidate_cache()
            card.update()


class TimerPage(BaseHubPage):
    """Página detalhada de configuração do Timer Widget."""

    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(
            title=t("timer_title"),
            subtitle=t("timer_subtitle"),
            theme=theme,
            parent=parent,
        )
        self.bridge = get_service_bridge()
        self._build_ui()

    def _build_ui(self):
        # 1. Card de Posição na Tela
        pos_card = QFrame()
        pos_card.setProperty("class", "HubCard")
        pos_layout = QHBoxLayout(pos_card)
        pos_layout.setContentsMargins(*CARD_MARGINS)

        pos_info = QVBoxLayout()
        pos_info.setSpacing(3)
        self.t_pos = QLabel(t("timer_pos_title"))
        self.t_pos.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.s_pos = QLabel(t("timer_pos_sub"))
        self.s_pos.setWordWrap(True)
        self.s_pos.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        pos_info.addWidget(self.t_pos)
        pos_info.addWidget(self.s_pos)
        pos_layout.addLayout(pos_info, stretch=1)
        pos_layout.setAlignment(pos_info, Qt.AlignmentFlag.AlignVCenter)

        self.pos_picker = PositionPicker(current_pos="tc", theme=self._theme, parent=pos_card)
        self.pos_picker.position_changed.connect(self._on_pos_changed)
        pos_layout.addWidget(self.pos_picker)
        self.content_layout.addWidget(pos_card)

        # 2. Card de Skins & Estilos
        skin_card = QFrame()
        skin_card.setProperty("class", "HubCard")
        sk_layout = QVBoxLayout(skin_card)
        sk_layout.setContentsMargins(22, 20, 22, 22)
        sk_layout.setSpacing(0)

        # Header com proximidade intencional (4px)
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        self.sk_header = QLabel(t("timer_style_title"))
        self.sk_header.setStyleSheet("font-size: 14.5px; font-weight: 600;")
        self.sk_desc = QLabel(t("timer_style_sub"))
        self.sk_desc.setWordWrap(True)
        self.sk_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        if not bool(t("timer_style_sub")):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
            self.sk_desc.hide()
        header_layout.addWidget(self.sk_header)
        header_layout.addWidget(self.sk_desc)
        sk_layout.addLayout(header_layout)

        # Respiro generoso entre o cabeçalho e a galeria de miniaturas
        sk_layout.addSpacing(18)

        self._skin_grid = ResponsiveCardGrid(min_card_width=150, spacing=16, parent=skin_card)
        self._skin_cards: dict[str, PreviewCard] = {}
        active_skin = self.bridge.timer_controller.active_skin_name
        timer_specs = init_timer_skin_specs()

        for spec in timer_specs:
            card = PreviewCard(
                spec=spec,
                theme=self._theme,
                is_selected=(spec.id == active_skin),
                parent=self._skin_grid,
            )
            card.clicked.connect(self._on_skin_selected)
            self._skin_cards[spec.id] = card
            self._skin_grid.add_card(card)

        sk_layout.addWidget(self._skin_grid)

        # 3. Card de Tema visual (skin Windows tem a galeria completa; Nothing Dot tem só Nothing Red + Aimedget)
        self.theme_picker = ThemeGalleryCard(
            timer_theme_loader,
            "timer",
            make_timer_theme_spec,
            self.bridge.apply_timer_theme,
            self._theme,
            appliers=self.bridge.theme_appliers(),
            parent=self,
            subtitle_key="theme_picker_sub_timer",
            default_title_key="theme_default_timer",
        )
        self.nothing_theme_picker = _NothingTimerThemeCard(
            self.bridge.apply_timer_theme,
            self._theme,
            parent=self,
        )
        theme_host = QWidget(self)
        th_lay = QVBoxLayout(theme_host)
        th_lay.setContentsMargins(0, 0, 0, 0)
        th_lay.setSpacing(0)
        th_lay.addWidget(self.theme_picker)
        th_lay.addWidget(self.nothing_theme_picker)
        self._sync_theme_picker_kind(active_skin)

        # Skins + temas num bloco só: a galeria recolhe (animada) quando a skin escolhida não aceita temas
        skin_block, self.theme_section = skin_and_theme_block(
            skin_card, theme_host, self.content_layout.spacing(), self._active_skin_supports_themes())
        self.content_layout.addWidget(skin_block)
        self.bridge.timer_skin_changed.connect(self._on_active_timer_skin_changed)

        # 3b. Tamanho, depois do Estilo, como no Desempenho (% do lado padrão; a alça do canto continua valendo)
        controller = self.bridge.timer_controller
        self.scale_card = ScaleCard(
            "weather_size_title", "weather_size_sub", self._theme, SCALE_PCT_MIN, SCALE_PCT_MAX, self
        )
        self.scale_card.auto_clicked.connect(lambda: controller.set_scale(None))
        self.scale_card.live_changed.connect(lambda pct: controller.apply_scale_live(pct / 100.0))
        self.scale_card.committed.connect(lambda pct: controller.set_scale(pct / 100.0))
        self.content_layout.addWidget(self.scale_card)
        controller.scale_applied.connect(lambda _s: self._sync_size())   # acompanha a animação quadro a quadro
        controller.scale_changed.connect(lambda _s: self._sync_size())
        controller.skin_changed.connect(lambda _n: self._sync_size())
        self._sync_size()

        # 4. Card de Comportamento & Ações
        behav_card = QFrame()
        behav_card.setProperty("class", "HubCard")
        b_layout = QVBoxLayout(behav_card)
        b_layout.setContentsMargins(*CARD_MARGINS)
        b_layout.setSpacing(ROWS_GAP)

        # Linha 1: Lembrar posição
        row1 = QHBoxLayout()
        info1 = QVBoxLayout()
        info1.setSpacing(2)
        self.l1_title = QLabel(t("timer_opt_remember_title"))
        self.l1_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.l1_sub = QLabel(t("timer_opt_remember_sub"))
        self.l1_sub.setWordWrap(True)
        self.l1_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info1.addWidget(self.l1_title)
        info1.addWidget(self.l1_sub)
        self.sw_remember = PillSwitch(
            checked=config_manager.is_timer_position_remembered(),
            theme=self._theme,
        )
        self.sw_remember.toggled.connect(self._on_remember_toggled)
        self.bridge.timer_controller.remember_position_changed.connect(self._sync_remember)
        row1.addLayout(info1, stretch=1)
        row1.addWidget(self.sw_remember)
        b_layout.addLayout(row1)

        # "Fixar na área de trabalho": o mesmo dos outros widgets (num grupo ancorado, todos vão juntos)
        sep_desktop = QFrame()
        sep_desktop.setFrameShape(QFrame.Shape.HLine)
        sep_desktop.setProperty("class", "HubDivider")
        b_layout.addWidget(sep_desktop)
        row_desktop = QHBoxLayout()
        info_desktop = QVBoxLayout()
        info_desktop.setSpacing(2)
        self.ld_title = QLabel(t("weather_opt_desktop_title"))
        self.ld_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.ld_sub = QLabel(t("weather_opt_desktop_sub"))
        self.ld_sub.setWordWrap(True)
        self.ld_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_desktop.addWidget(self.ld_title)
        info_desktop.addWidget(self.ld_sub)
        self.sw_desktop = PillSwitch(checked=self.bridge.timer_controller.is_desktop_mode(), theme=self._theme)
        self.sw_desktop.toggled.connect(self.bridge.timer_controller.set_desktop_mode)
        self.bridge.timer_controller.desktop_mode_changed.connect(self._sync_desktop)
        row_desktop.addLayout(info_desktop, stretch=1)
        row_desktop.addWidget(self.sw_desktop)
        b_layout.addLayout(row_desktop)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setProperty("class", "HubDivider")
        b_layout.addWidget(sep1)

        # Linha 2a: Exibir ao iniciar
        row_start = QHBoxLayout()
        info_start = QVBoxLayout()
        info_start.setSpacing(2)
        self.lst_title = QLabel(t("timer_opt_startup_title"))
        self.lst_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.lst_sub = QLabel(t("timer_opt_startup_sub"))
        self.lst_sub.setWordWrap(True)
        self.lst_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_start.addWidget(self.lst_title)
        info_start.addWidget(self.lst_sub)
        self.sw_startup = PillSwitch(
            checked=config_manager.is_timer_show_on_startup(),
            theme=self._theme,
        )
        self.sw_startup.toggled.connect(config_manager.set_timer_show_on_startup)
        row_start.addLayout(info_start, stretch=1)
        row_start.addWidget(self.sw_startup)
        b_layout.addLayout(row_start)

        sep_start = QFrame()
        sep_start.setFrameShape(QFrame.Shape.HLine)
        sep_start.setProperty("class", "HubDivider")
        b_layout.addWidget(sep_start)

        # Linha 2b: Scroll nos dígitos
        row_smart = QHBoxLayout()
        info_smart = QVBoxLayout()
        info_smart.setSpacing(2)
        self.ls_title = QLabel(t("timer_opt_smart_hover_title"))
        self.ls_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.ls_sub = QLabel(t("timer_opt_smart_hover_sub"))
        self.ls_sub.setWordWrap(True)
        self.ls_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_smart.addWidget(self.ls_title)
        info_smart.addWidget(self.ls_sub)
        self.sw_smart_hover = PillSwitch(
            checked=config_manager.is_timer_smart_hover_enabled(),
            theme=self._theme,
        )
        self.sw_smart_hover.toggled.connect(self._on_smart_hover_toggled)
        self.bridge.timer_controller.smart_hover_changed.connect(self._sync_smart_hover)
        row_smart.addLayout(info_smart, stretch=1)
        row_smart.addWidget(self.sw_smart_hover)
        b_layout.addLayout(row_smart)

        sep_alarm = QFrame()
        sep_alarm.setFrameShape(QFrame.Shape.HLine)
        sep_alarm.setProperty("class", "HubDivider")
        b_layout.addWidget(sep_alarm)

        # Linha 2c: Som ao terminar
        row_alarm = QHBoxLayout()
        info_alarm = QVBoxLayout()
        info_alarm.setSpacing(2)
        self.la_title = QLabel(t("timer_opt_alarm_title"))
        self.la_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.la_sub = QLabel(t("timer_opt_alarm_sub"))
        self.la_sub.setWordWrap(True)
        self.la_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        if not bool(t("timer_opt_alarm_sub")):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
            self.la_sub.hide()
        info_alarm.addWidget(self.la_title)
        info_alarm.addWidget(self.la_sub)
        self.sw_alarm = PillSwitch(
            checked=config_manager.is_timer_alarm_sound_enabled(),
            theme=self._theme,
        )
        self.sw_alarm.toggled.connect(config_manager.set_timer_alarm_sound_enabled)
        row_alarm.addLayout(info_alarm, stretch=1)
        row_alarm.setAlignment(info_alarm, Qt.AlignmentFlag.AlignVCenter)
        row_alarm.addWidget(self.sw_alarm, alignment=Qt.AlignmentFlag.AlignVCenter)
        b_layout.addLayout(row_alarm)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setProperty("class", "HubDivider")
        b_layout.addWidget(sep2)

        # Linha 3: Testar / Exibir no desktop
        row2 = QHBoxLayout()
        info2 = QVBoxLayout()
        info2.setSpacing(2)
        self.l2_title = QLabel(t("timer_opt_show_title"))
        self.l2_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.l2_sub = QLabel(t("timer_opt_show_sub"))
        self.l2_sub.setWordWrap(True)
        self.l2_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        if not bool(t("timer_opt_show_sub")):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
            self.l2_sub.hide()
        info2.addWidget(self.l2_title)
        info2.addWidget(self.l2_sub)

        self.btn_show = QPushButton(t("timer_opt_show_btn"))
        self.btn_show.setProperty("class", "Chip")
        self.btn_show.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show.clicked.connect(self._on_show_timer_clicked)

        row2.addLayout(info2, stretch=1)
        row2.setAlignment(info2, Qt.AlignmentFlag.AlignVCenter)
        row2.addWidget(self.btn_show, alignment=Qt.AlignmentFlag.AlignVCenter)
        b_layout.addLayout(row2)

        self.content_layout.addWidget(behav_card)

        # 5. Card de Atalho de Teclado
        hk_card = QFrame()
        hk_card.setProperty("class", "HubCard")
        hk_layout = QHBoxLayout(hk_card)
        hk_layout.setContentsMargins(*CARD_MARGINS)

        hk_info = QVBoxLayout()
        hk_info.setSpacing(3)
        self.hk_title = QLabel(t("timer_hotkey_title"))
        self.hk_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.hk_desc = QLabel(t("timer_hotkey_sub"))
        self.hk_desc.setWordWrap(True)
        self.hk_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        hk_info.addWidget(self.hk_title)
        hk_info.addWidget(self.hk_desc)
        hk_layout.addLayout(hk_info, stretch=1)

        self.hk_picker = ShortcutPicker(
            current_shortcut=config_manager.get_timer_hotkey("Win+Alt+T"),
            default_shortcut="Win+Alt+T",
            theme=self._theme,
            parent=hk_card,
        )
        self.hk_picker.shortcut_changed.connect(self._on_hotkey_changed)
        hk_layout.addWidget(self.hk_picker)
        self.content_layout.addWidget(hk_card)

        self.content_layout.addStretch()

    def _on_hotkey_changed(self, new_shortcut: str):
        self.bridge.update_timer_hotkey(new_shortcut)

    def _on_pos_changed(self, pos_key: str):
        self.bridge.move_timer_to_screen_position(pos_key)

    def _on_remember_toggled(self, checked: bool):
        if self.bridge.timer_controller.skin:
            pos = self.bridge.timer_controller.skin.pos()
            config_manager.set_timer_position_remembered(checked, pos.x(), pos.y())
        else:
            config_manager.set_timer_position_remembered(checked)

    def _sync_desktop(self, enabled: bool):
        """O widget mudou de camada por outro caminho (menu dele, ou o grupo ancorado): a chave acompanha."""
        if hasattr(self, "sw_desktop") and self.sw_desktop.isChecked() != enabled:
            self.sw_desktop.blockSignals(True)
            self.sw_desktop.set_checked(enabled, animated=True)
            self.sw_desktop.blockSignals(False)

    def _on_smart_hover_toggled(self, checked: bool):
        config_manager.set_timer_smart_hover_enabled(checked)
        if self.bridge.timer_controller.skin:
            self.bridge.timer_controller.skin.update()

    def _on_show_timer_clicked(self):
        self.bridge.set_timer_enabled(True)
        if self.bridge.timer_controller.skin:
            self.bridge.timer_controller.skin.raise_()
            self.bridge.timer_controller.skin.activateWindow()

    def _active_skin_supports_themes(self, skin_key: str | None = None) -> bool:
        """A skin ativa aceita temas visuais? (Skins com arte própria, vindas de pacotes, não aceitam.)"""
        return skin_supports_themes(init_timer_skin_specs(), skin_key or self.bridge.timer_controller.active_skin_name)

    def _sync_theme_picker_kind(self, skin_key: str):
        is_nothing = (skin_key == "nothing_dot")
        self.theme_picker.setVisible(not is_nothing)
        self.nothing_theme_picker.setVisible(is_nothing)

    def _on_active_timer_skin_changed(self, skin_key: str):
        """Mostra a galeria de temas certa para a skin ativa (Windows ou Nothing Dot)."""
        self._sync_theme_picker_kind(skin_key)
        self.theme_section.set_open(self._active_skin_supports_themes(skin_key))

    def _on_skin_selected(self, skin_key: str):
        if skin_key in self.bridge.timer_controller.available_skins():
            self.bridge.set_timer_skin(skin_key)
            if hasattr(self, "_skin_cards"):
                for k, card in self._skin_cards.items():
                    card.set_selected(k == skin_key)

    def _sync_remember(self, enabled: bool):
        if self.sw_remember.isChecked() != enabled:
            self.sw_remember.blockSignals(True)
            self.sw_remember.set_checked(enabled, animated=False)
            self.sw_remember.blockSignals(False)

    def _sync_smart_hover(self, enabled: bool):
        if self.sw_smart_hover.isChecked() != enabled:
            self.sw_smart_hover.blockSignals(True)
            self.sw_smart_hover.set_checked(enabled, animated=False)
            self.sw_smart_hover.blockSignals(False)

    def _sync_size(self):
        """Chip Automático e polegar seguem o widget (inclusive enquanto ele anima até o tamanho novo)."""
        controller = self.bridge.timer_controller
        pct = max(SCALE_PCT_MIN, min(SCALE_PCT_MAX, int(round(controller.scale() * 100))))
        self.scale_card.set_state(controller.is_scale_auto(), pct)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_size()
        self._sync_remember(config_manager.is_timer_position_remembered())
        self._sync_smart_hover(config_manager.is_timer_smart_hover_enabled())
        if hasattr(self, "_skin_cards"):
            active_skin = self.bridge.timer_controller.active_skin_name
            for k, card in self._skin_cards.items():
                card.set_selected(k == active_skin)

    def retranslate_ui(self):
        self.set_header(t("timer_title"), t("timer_subtitle"))
        self.scale_card.retranslate()
        if hasattr(self, "t_pos"):
            self.t_pos.setText(t("timer_pos_title"))
        if hasattr(self, "s_pos"):
            self.s_pos.setText(t("timer_pos_sub"))
        if hasattr(self, "sk_header"):
            self.sk_header.setText(t("timer_style_title"))
        if hasattr(self, "sk_desc"):
            txt = t("timer_style_sub")
            self.sk_desc.setText(txt)
            self.sk_desc.setVisible(bool(txt))
        if hasattr(self, "l1_title"):
            self.l1_title.setText(t("timer_opt_remember_title"))
        if hasattr(self, "l1_sub"):
            self.l1_sub.setText(t("timer_opt_remember_sub"))
        if hasattr(self, "ld_title"):
            self.ld_title.setText(t("weather_opt_desktop_title"))
        if hasattr(self, "ld_sub"):
            self.ld_sub.setText(t("weather_opt_desktop_sub"))
        if hasattr(self, "lst_title"):
            self.lst_title.setText(t("timer_opt_startup_title"))
        if hasattr(self, "lst_sub"):
            self.lst_sub.setText(t("timer_opt_startup_sub"))
        if hasattr(self, "la_title"):
            self.la_title.setText(t("timer_opt_alarm_title"))
        if hasattr(self, "la_sub"):
            txt = t("timer_opt_alarm_sub")
            self.la_sub.setText(txt)
            self.la_sub.setVisible(bool(txt))
        if hasattr(self, "ls_title"):
            self.ls_title.setText(t("timer_opt_smart_hover_title"))
        if hasattr(self, "ls_sub"):
            self.ls_sub.setText(t("timer_opt_smart_hover_sub"))
        if hasattr(self, "l2_title"):
            self.l2_title.setText(t("timer_opt_show_title"))
        if hasattr(self, "l2_sub"):
            txt = t("timer_opt_show_sub")
            self.l2_sub.setText(txt)
            self.l2_sub.setVisible(bool(txt))
        if hasattr(self, "btn_show"):
            self.btn_show.setText(t("timer_opt_show_btn"))
        if hasattr(self, "hk_title"):
            self.hk_title.setText(t("timer_hotkey_title"))
        if hasattr(self, "hk_desc"):
            self.hk_desc.setText(t("timer_hotkey_sub"))
        if hasattr(self, "hk_picker"):
            self.hk_picker.retranslate_ui()
        if hasattr(self, "theme_picker"):
            self.theme_picker.retranslate_ui()
        if hasattr(self, "nothing_theme_picker"):
            self.nothing_theme_picker.retranslate_ui()
        # O título e o subtítulo da skin ficam na spec (criada na inicialização): refaz no idioma novo
        timer_skin_texts = {
            "windows": (t("theme_default_timer"), t("skin_windows_sub")),
            "nothing_dot": ("Nothing Dot", t("skin_nothing_dot_timer_sub")),
            "focus_ring": (t("skin_focus_ring_title"), t("skin_focus_ring_timer_sub")),
        }
        for pack in discover_skin_packs("timer"):
            timer_skin_texts[pack.id] = pack.texts(i18n.current_language)
        if hasattr(self, "_skin_cards"):
            for s_id, card in self._skin_cards.items():
                if s_id in timer_skin_texts:
                    card._spec.title, card._spec.subtitle = timer_skin_texts[s_id]
                    card._invalidate_cache()
                    card.update()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        self.pos_picker.set_theme(theme)
        self.scale_card.set_theme(theme)
        self.sw_remember.set_theme(theme)
        self.sw_desktop.set_theme(theme)
        self.sw_smart_hover.set_theme(theme)
        self.sw_alarm.set_theme(theme)
        self.sw_startup.set_theme(theme)
        if hasattr(self, "hk_picker"):
            self.hk_picker.set_theme(theme)
        if hasattr(self, "theme_picker"):
            self.theme_picker.set_theme(theme)
        if hasattr(self, "nothing_theme_picker"):
            self.nothing_theme_picker.set_theme(theme)
        if hasattr(self, "_skin_cards"):
            for card in self._skin_cards.values():
                card.set_theme(theme)
