"""Hub: página Música. Extraído de `pages.py` (mesmo código, só em arquivo próprio)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.hub.components.collapsible_section import skin_and_theme_block, skin_supports_themes
from app.hub.components.help_badge import HelpBadge
from app.core.screen_metrics import SCALE_PCT_MAX, SCALE_PCT_MIN, pct_to_scale, scale_to_pct
from app.hub.components.scale_card import ScaleCard
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.components.responsive_grid import ResponsiveCardGrid
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.core.preview_card import PreviewCard
from app.widgets.music.skins import init_music_skin_specs
from app.widgets.music.skins.stack_theme import loader as music_theme_loader
from app.widgets.music.skins.stack_theme_specs import make_theme_spec as make_music_theme_spec
from app.hub.base_page import BaseHubPage


_SCALE_UNSET = object()


class MusicPage(BaseHubPage):
    """Página detalhada de configuração do Music Widget."""

    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(
            title=t("music_title"),
            subtitle=t("music_subtitle"),
            theme=theme,
            parent=parent,
        )
        self.bridge = get_service_bridge()
        self._build_ui()
        # Mantém a seleção do Hub sincronizada com trocas feitas pelo menu do widget
        self.bridge.music_skin_changed.connect(self._sync_selected_skin)

    def _build_ui(self):
        # "?" discreto ao lado do título: aviso sobre YouTube Music no Firefox (estado e progresso atrasados)
        idx = self.content_layout.indexOf(self.lbl_title)
        self.content_layout.removeWidget(self.lbl_title)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(self.lbl_title)
        self.web_help = HelpBadge(t("music_web_compat_help"), theme=self._theme)
        title_row.addWidget(self.web_help, alignment=Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch()
        self.content_layout.insertLayout(idx, title_row)

        # 1. Card de Posição na Tela
        pos_card = QFrame()
        pos_card.setProperty("class", "HubCard")
        pos_layout = QHBoxLayout(pos_card)
        pos_layout.setContentsMargins(18, 14, 18, 14)

        pos_info = QVBoxLayout()
        pos_info.setSpacing(3)
        self.t_pos = QLabel(t("music_pos_title"))
        self.t_pos.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.s_pos = QLabel(t("music_pos_sub"))
        self.s_pos.setWordWrap(True)
        self.s_pos.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        pos_info.addWidget(self.t_pos)
        pos_info.addWidget(self.s_pos)
        pos_layout.addLayout(pos_info, stretch=1)
        pos_layout.setAlignment(pos_info, Qt.AlignmentFlag.AlignVCenter)

        self.pos_picker = PositionPicker(current_pos="br", theme=self._theme, parent=pos_card)
        self.pos_picker.position_changed.connect(self._on_pos_changed)
        pos_layout.addWidget(self.pos_picker)
        self.content_layout.addWidget(pos_card)

        # 2. Card de Skins Disponíveis
        skin_card = QFrame()
        self.skins_card = skin_card
        skin_card.setProperty("class", "HubCard")
        sk_layout = QVBoxLayout(skin_card)
        sk_layout.setContentsMargins(22, 20, 22, 22)
        sk_layout.setSpacing(0)

        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        self.sk_header = QLabel(t("music_style_title"))
        self.sk_header.setStyleSheet("font-size: 14.5px; font-weight: 600;")
        self.sk_desc = QLabel(t("music_style_sub"))
        self.sk_desc.setWordWrap(True)
        self.sk_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        if not bool(t("music_style_sub")):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
            self.sk_desc.hide()
        header_layout.addWidget(self.sk_header)
        header_layout.addWidget(self.sk_desc)
        sk_layout.addLayout(header_layout)

        sk_layout.addSpacing(18)

        self._skin_grid = ResponsiveCardGrid(min_card_width=150, spacing=16, parent=skin_card)
        self._skin_cards: dict[str, PreviewCard] = {}
        active_skin = self.bridge.music_controller.active_skin_name
        music_specs = init_music_skin_specs()

        for spec in music_specs:
            card = PreviewCard(
                spec=spec,
                theme=self._theme,
                is_selected=(spec.id == active_skin),
                show_active_toggle=True,
                is_active_in_menu=config_manager.is_skin_active(spec.id),
                before_toggle_callback=self._can_toggle_skin,
                parent=self._skin_grid,
            )
            card.clicked.connect(self._on_skin_selected)
            card.active_toggled.connect(self._on_skin_active_toggled)
            self._skin_cards[spec.id] = card
            self._skin_grid.add_card(card)

        sk_layout.addWidget(self._skin_grid)

        # 2b. Card de Tema visual da Capa Empilhada (escolher aplica no widget e torna a Capa Empilhada a skin em uso)
        self.theme_picker = ThemeGalleryCard(
            music_theme_loader,
            "music",
            make_music_theme_spec,
            self.bridge.apply_music_theme,
            self._theme,
            appliers=self.bridge.theme_appliers(),
            parent=self,
            subtitle_key="theme_picker_sub_music",
            default_title_key="theme_default_music",
        )
        # Os temas valem só para a Capa Empilhada: nas outras skins a galeria recolhe (animada), como no Timer
        skin_block, self.theme_section = skin_and_theme_block(
            skin_card, self.theme_picker, self.content_layout.spacing(),
            skin_supports_themes(music_specs, active_skin))
        self.content_layout.addWidget(skin_block)
        self.bridge.music_skin_changed.connect(self._on_active_music_skin_changed)

        # 3. Card de Tamanho e Escala (depois de escolher a skin)
        self.scale_card = ScaleCard("music_scale_title", "music_scale_sub", self._theme, SCALE_PCT_MIN, SCALE_PCT_MAX, self)
        self.scale_card.auto_clicked.connect(lambda: self.bridge.set_music_scale(None))
        self.scale_card.live_changed.connect(lambda pct: self.bridge.apply_music_scale_live(pct_to_scale(pct)))
        self.scale_card.committed.connect(lambda pct: self.bridge.set_music_scale(pct_to_scale(pct)))
        self.content_layout.addWidget(self.scale_card)

        self.update_scale_selection()
        self.bridge.music_scale_changed.connect(self.update_scale_selection)

        # 3. Card de Comportamento
        behav_card = QFrame()
        behav_card.setProperty("class", "HubCard")
        b_layout = QVBoxLayout(behav_card)
        b_layout.setContentsMargins(18, 14, 18, 14)
        b_layout.setSpacing(12)

        row1 = QHBoxLayout()
        info1 = QVBoxLayout()
        info1.setSpacing(2)
        self.l1_title = QLabel(t("music_auto_launch_title"))
        self.l1_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.l1_sub = QLabel(t("music_auto_launch_sub"))
        self.l1_sub.setWordWrap(True)
        self.l1_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info1.addWidget(self.l1_title)
        info1.addWidget(self.l1_sub)
        self.sw_auto_launch = PillSwitch(
            checked=config_manager.is_auto_launch_enabled(),
            theme=self._theme,
        )
        self.sw_auto_launch.toggled.connect(self._on_auto_launch_toggled)
        row1.addLayout(info1, stretch=1)
        row1.addWidget(self.sw_auto_launch)
        b_layout.addLayout(row1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setProperty("class", "HubDivider")
        b_layout.addWidget(sep)

        row2 = QHBoxLayout()
        info2 = QVBoxLayout()
        info2.setSpacing(2)
        self.l2_title = QLabel(t("music_auto_hide_title"))
        self.l2_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.l2_sub = QLabel(t("music_auto_hide_sub"))
        self.l2_sub.setWordWrap(True)
        self.l2_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info2.addWidget(self.l2_title)
        info2.addWidget(self.l2_sub)
        self.sw_auto_hide = PillSwitch(
            checked=config_manager.is_auto_hide_enabled(),
            theme=self._theme,
        )
        self.sw_auto_hide.toggled.connect(self._on_auto_hide_toggled)
        row2.addLayout(info2, stretch=1)
        row2.addWidget(self.sw_auto_hide)
        b_layout.addLayout(row2)

        sep_wheel = QFrame()
        sep_wheel.setFrameShape(QFrame.Shape.HLine)
        sep_wheel.setProperty("class", "HubDivider")
        b_layout.addWidget(sep_wheel)

        row3 = QHBoxLayout()
        info3 = QVBoxLayout()
        info3.setSpacing(2)
        self.l3_title = QLabel(t("music_wheel_volume_title"))
        self.l3_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.l3_sub = QLabel(t("music_wheel_volume_sub"))
        self.l3_sub.setWordWrap(True)
        self.l3_sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info3.addWidget(self.l3_title)
        info3.addWidget(self.l3_sub)
        self.sw_wheel_volume = PillSwitch(
            checked=config_manager.is_music_wheel_volume_enabled(),
            theme=self._theme,
        )
        self.sw_wheel_volume.toggled.connect(config_manager.set_music_wheel_volume_enabled)
        row3.addLayout(info3, stretch=1)
        row3.addWidget(self.sw_wheel_volume)
        b_layout.addLayout(row3)

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
        self.sw_desktop = PillSwitch(checked=self.bridge.music_controller.is_desktop_mode(), theme=self._theme)
        self.sw_desktop.toggled.connect(self.bridge.music_controller.set_desktop_mode)
        self.bridge.music_controller.desktop_mode_changed.connect(self._sync_desktop)
        row_desktop.addLayout(info_desktop, stretch=1)
        row_desktop.addWidget(self.sw_desktop)
        b_layout.addLayout(row_desktop)

        self.content_layout.addWidget(behav_card)

        # 4. Card de Atalho de Teclado
        hk_card = QFrame()
        hk_card.setProperty("class", "HubCard")
        hk_layout = QHBoxLayout(hk_card)
        hk_layout.setContentsMargins(18, 14, 18, 14)

        hk_info = QVBoxLayout()
        hk_info.setSpacing(3)
        self.hk_title = QLabel(t("music_hotkey_title"))
        self.hk_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.hk_desc = QLabel(t("music_hotkey_sub"))
        self.hk_desc.setWordWrap(True)
        self.hk_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        hk_info.addWidget(self.hk_title)
        hk_info.addWidget(self.hk_desc)
        hk_layout.addLayout(hk_info, stretch=1)
        hk_layout.setAlignment(hk_info, Qt.AlignmentFlag.AlignVCenter)

        self.hk_picker = ShortcutPicker(
            current_shortcut=config_manager.get_music_hotkey("Win+Alt+M"),
            default_shortcut="Win+Alt+M",
            theme=self._theme,
            parent=hk_card,
        )
        self.hk_picker.shortcut_changed.connect(self._on_hotkey_changed)
        hk_layout.addWidget(self.hk_picker)
        self.content_layout.addWidget(hk_card)

        self.content_layout.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_scale_selection()

    def update_scale_selection(self, scale: object = _SCALE_UNSET):
        """
        Reflete o tamanho do widget no cartão. O sinal traz ora a escala efetiva (quadro a quadro, do widget), ora a
        preferência; a verdade do modo automático está sempre na configuração.
        """
        if not hasattr(self, "scale_card"):
            return
        skin = getattr(self.bridge.music_controller, "skin", None)
        effective = skin.scale if skin is not None else config_manager.get_effective_music_scale()
        self.scale_card.set_state(config_manager.is_music_scale_auto(), scale_to_pct(effective))

    def _on_hotkey_changed(self, new_shortcut: str):
        self.bridge.update_music_hotkey(new_shortcut)

    def _on_pos_changed(self, pos_key: str):
        self.bridge.move_music_to_screen_position(pos_key)

    def _on_active_music_skin_changed(self, skin_key: str):
        """Mostra a galeria de temas só enquanto a skin ativa os aceita (o tema escolhido continua guardado)."""
        canon = "capa_empilhada" if skin_key in ("stacked", "capaEmpilhada") else skin_key
        self.theme_section.set_open(skin_supports_themes(init_music_skin_specs(), canon))

    def _sync_selected_skin(self, skin_key: str):
        canon = "capa_empilhada" if skin_key in ("stacked", "capaEmpilhada") else skin_key
        for k, card in getattr(self, "_skin_cards", {}).items():
            card.set_selected(k == canon)

    def _can_toggle_skin(self, skin_key: str, target_active: bool) -> bool:
        """Impede desativar a última skin ativa (mínimo de 1 no menu rápido)."""
        if target_active:
            return True
        return len([k for k in config_manager.get_active_widget_skins() if k != skin_key]) >= 1

    def _on_skin_active_toggled(self, skin_key: str, active: bool):
        card = self._skin_cards.get(skin_key)
        if not self.bridge.set_music_skin_active(skin_key, active):
            if card is not None:
                card.set_active_in_menu(not active)
            return
        # O fallback pode ter trocado a skin em uso; a seleção chega por music_skin_changed

    def _on_skin_selected(self, skin_key: str):
        card = self._skin_cards.get(skin_key)
        if card is not None and not card.is_active_in_menu():
            # Escolher uma skin desativada a torna disponível no menu rápido
            if self.bridge.set_music_skin_active(skin_key, True):
                card.set_active_in_menu(True)
        self.bridge.set_music_skin(skin_key)
        for k, c in self._skin_cards.items():
            c.set_selected(k == skin_key)

    def _sync_desktop(self, enabled: bool):
        """O widget mudou de camada por outro caminho (menu dele, ou o grupo ancorado): a chave acompanha."""
        if hasattr(self, "sw_desktop") and self.sw_desktop.isChecked() != enabled:
            self.sw_desktop.blockSignals(True)
            self.sw_desktop.set_checked(enabled, animated=True)
            self.sw_desktop.blockSignals(False)

    def _on_auto_launch_toggled(self, checked: bool):
        self.bridge.set_music_auto_launch(checked)

    def _on_auto_hide_toggled(self, checked: bool):
        self.bridge.set_music_auto_hide(checked)

    def retranslate_ui(self):
        self.set_header(t("music_title"), t("music_subtitle"))
        if hasattr(self, "web_help"):
            self.web_help.set_text(t("music_web_compat_help"))
        if hasattr(self, "t_pos"):
            self.t_pos.setText(t("music_pos_title"))
        if hasattr(self, "s_pos"):
            self.s_pos.setText(t("music_pos_sub"))
        if hasattr(self, "scale_card"):
            self.scale_card.retranslate()
        if hasattr(self, "sk_header"):
            self.sk_header.setText(t("music_style_title"))
        if hasattr(self, "sk_desc"):
            txt = t("music_style_sub")
            self.sk_desc.setText(txt)
            self.sk_desc.setVisible(bool(txt))
        if hasattr(self, "l1_title"):
            self.l1_title.setText(t("music_auto_launch_title"))
        if hasattr(self, "l1_sub"):
            self.l1_sub.setText(t("music_auto_launch_sub"))
        if hasattr(self, "l2_title"):
            self.l2_title.setText(t("music_auto_hide_title"))
        if hasattr(self, "l2_sub"):
            self.l2_sub.setText(t("music_auto_hide_sub"))
        if hasattr(self, "l3_title"):
            self.l3_title.setText(t("music_wheel_volume_title"))
        if hasattr(self, "l3_sub"):
            self.l3_sub.setText(t("music_wheel_volume_sub"))
        if hasattr(self, "ld_title"):
            self.ld_title.setText(t("weather_opt_desktop_title"))
        if hasattr(self, "ld_sub"):
            self.ld_sub.setText(t("weather_opt_desktop_sub"))
        if hasattr(self, "hk_title"):
            self.hk_title.setText(t("music_hotkey_title"))
        if hasattr(self, "hk_desc"):
            self.hk_desc.setText(t("music_hotkey_sub"))
        if hasattr(self, "hk_picker"):
            self.hk_picker.retranslate_ui()
        if hasattr(self, "theme_picker"):
            self.theme_picker.retranslate_ui()
        skin_translations = {
            "vinyl": (t("skin_vinyl_title"), t("skin_vinyl_sub")),
            "fullcover": (t("skin_fullcover_title"), t("skin_fullcover_sub")),
            "ripple": (t("skin_ripple_title"), t("skin_ripple_sub")),
            "capa_empilhada": (t("skin_stacked_title"), t("skin_stacked_sub")),
        }
        if hasattr(self, "_skin_cards"):
            for s_id, card in self._skin_cards.items():
                if s_id in skin_translations:
                    tr_title, tr_sub = skin_translations[s_id]
                    card._spec.title = tr_title
                    card._spec.subtitle = tr_sub
                    card._invalidate_cache()
                    card.update()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        self.pos_picker.set_theme(theme)
        self.scale_card.set_theme(theme)
        if hasattr(self, "web_help"):
            self.web_help.set_theme(theme)
        if hasattr(self, "sw_auto_launch"):
            self.sw_auto_launch.set_theme(theme)
        if hasattr(self, "sw_auto_hide"):
            self.sw_auto_hide.set_theme(theme)
        if hasattr(self, "sw_wheel_volume"):
            self.sw_wheel_volume.set_theme(theme)
        if hasattr(self, "sw_desktop"):
            self.sw_desktop.set_theme(theme)
        if hasattr(self, "hk_picker"):
            self.hk_picker.set_theme(theme)
        if hasattr(self, "theme_picker"):
            self.theme_picker.set_theme(theme)
        if hasattr(self, "_skin_cards"):
            for card in self._skin_cards.values():
                card.set_theme(theme)

    def focus_skins(self):
        """Rola a página diretamente para a seção de skins (usado pelo menu de contexto do Music Widget)."""
        if hasattr(self, "skins_card"):
            self.scroll_to_widget(self.skins_card)
