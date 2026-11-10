"""
Páginas de conteúdo do Aimedget Hub revisadas com a skill Impeccable:
- Tipografia unificada Inter (tamanhos padronizados: 22px títulos, 13.5px legendas, 13px rótulos).
- Pesos contidos (Regular 400 / SemiBold 600) eliminando os tags <b> e contrastes berrantes.
- Paleta orgânica Notion / Linear.
"""

from typing import List, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.version import __version__
from app.services.updater_service import UpdateInfo, updater_service
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.components.responsive_grid import ResponsiveCardGrid
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.widgets.keylock_osd.theme_specs import make_theme_spec as make_keylock_theme_spec
from app.widgets.volume_mixer.theme_specs import make_theme_spec as make_mixer_theme_spec
from app.hub.components.widget_card import WidgetCard
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.core.preview_card import PreviewCard
from app.widgets.music.skins import init_music_skin_specs
from app.widgets.keylock_osd import KEYLOCK_SPEC
from app.widgets.keylock_osd.theme import loader as keylock_theme_loader
from app.widgets.volume_mixer.theme import loader as mixer_theme_loader
from app.widgets.timer import init_timer_spec, init_timer_skin_specs
from app.widgets.volume_mixer import init_volume_spec


class HubScrollArea(QScrollArea):
    """QScrollArea com contenção estrita de viewport: nunca rola horizontalmente nem deixa conteúdo vazar."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.widget()
        if w:
            vw = self.viewport().width()
            if vw > 100:
                w.setFixedWidth(vw)


class BaseHubPage(QWidget):
    """Página base com estrutura padronizada, espaçamento arejado e rolagem suave."""

    def __init__(self, title: str, subtitle: str, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self._theme = theme

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = HubScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(32, 28, 36, 32)
        self.content_layout.setSpacing(18)

        # Header padronizado
        self.lbl_title = QLabel(title)
        self.lbl_title.setProperty("class", "SectionTitle")
        self.content_layout.addWidget(self.lbl_title)

        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setProperty("class", "SectionSubtitle")
        self.lbl_sub.setWordWrap(True)
        self.content_layout.addWidget(self.lbl_sub)

        self.scroll.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll)

    def set_header(self, title: str, subtitle: str):
        self.lbl_title.setText(title)
        self.lbl_sub.setText(subtitle)

    def retranslate_ui(self):
        pass

    def set_theme(self, theme: HubTheme):
        self._theme = theme


class OverviewPage(BaseHubPage):
    """Página 'Customization' com visão geral dos módulos, widgets e flyouts."""

    customize_requested = Signal(str)

    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(
            title=t("overview_title"),
            subtitle=t("overview_subtitle"),
            theme=theme,
            parent=parent,
        )
        self.bridge = get_service_bridge()
        self._cards: List[WidgetCard] = []
        self._current_filter: str = "All"
        self._search_query: str = ""

        self._build_tools()
        self._build_gallery()

    def _build_tools(self):
        tools_layout = QHBoxLayout()
        tools_layout.setSpacing(8)

        # Campo de busca em tempo real
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchInput")
        self.search_box.setPlaceholderText(t("overview_search_placeholder"))
        self.search_box.textChanged.connect(self._on_search_changed)
        tools_layout.addWidget(self.search_box, stretch=1)

        # Chips de filtro de categoria
        self._filter_chips: dict[str, QPushButton] = {}
        for cat_key, i18n_key in [("All", "overview_filter_all"), ("Widget", "overview_filter_widget"), ("Flyout", "overview_filter_flyout")]:
            chip = QPushButton(t(i18n_key))
            chip.setProperty("class", "Chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            if cat_key == "All":
                chip.setProperty("selected", "true")
            chip.clicked.connect(lambda checked=False, c=cat_key: self._set_filter(c))
            self._filter_chips[cat_key] = chip
            tools_layout.addWidget(chip)

        self.content_layout.addLayout(tools_layout)

    def _build_gallery(self):
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 4, 0, 0)
        self.grid_layout.setSpacing(14)

        # 1. Music Player Card (Desktop Widget fixo) - Miniatura dinâmica da skin ativa
        active_skin = self.bridge.music_controller.active_skin_name
        music_specs = init_music_skin_specs()
        music_spec = next((s for s in music_specs if s.id == active_skin), music_specs[0] if music_specs else None)
        skin_titles = {
            "vinyl": t("skin_vinyl_title"),
            "fullcover": t("skin_fullcover_title"),
            "ripple": t("skin_ripple_title"),
            "capa_empilhada": t("skin_stacked_title"),
        }
        skin_label = skin_titles.get(active_skin, music_spec.title if music_spec else "Music Player")

        self.music_card = WidgetCard(
            widget_id="music_vinyl",
            name=t("overview_card_music"),
            category="Widget",
            skin_label=skin_label,
            spec=music_spec,
            is_active=self.bridge.is_music_widget_enabled(),
            theme=self._theme,
        )
        self.music_card.toggled.connect(self._on_card_toggled)
        self.music_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.music_card)

        # 2. Caps / Lock Keys OSD Card (Sistema Flyout temporário)
        self.keys_card = WidgetCard(
            widget_id="keys_osd",
            name=t("overview_card_keys"),
            category="Flyout",
            skin_label=t("overview_card_keys_skin"),
            spec=KEYLOCK_SPEC,
            is_active=self.bridge.is_keylock_enabled(),
            theme=self._theme,
        )
        self.keys_card.toggled.connect(self._on_card_toggled)
        self.keys_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.keys_card)

        # 3. Volume Mixer Card (Sistema Flyout temporário / retrátil)
        vol_spec = init_volume_spec()
        self.vol_card = WidgetCard(
            widget_id="vol_mixer",
            name=t("overview_card_volume"),
            category="Flyout",
            skin_label=t("overview_card_volume_skin"),
            spec=vol_spec,
            is_active=self.bridge.is_volume_mixer_enabled(),
            theme=self._theme,
        )
        self.vol_card.toggled.connect(self._on_card_toggled)
        self.vol_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.vol_card)

        # 4. Timer & Focus Widget Card (Desktop Widget flutuante)
        active_timer_skin = self.bridge.timer_controller.active_skin_name
        timer_specs = init_timer_skin_specs()
        timer_spec = next((s for s in timer_specs if s.id == active_timer_skin), timer_specs[0] if timer_specs else init_timer_spec())
        skin_label = timer_spec.title if timer_spec else "Aimedget Style"

        self.timer_card = WidgetCard(
            widget_id="timer",
            name=t("overview_card_timer"),
            category="Widget",
            skin_label=skin_label,
            spec=timer_spec,
            is_active=self.bridge.is_timer_enabled(),
            theme=self._theme,
        )
        self.timer_card.toggled.connect(self._on_card_toggled)
        self.timer_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.timer_card)

        self.bridge.status_changed.connect(self._on_bridge_status_changed)
        self.bridge.music_skin_changed.connect(self._on_music_skin_changed)
        self.bridge.timer_skin_changed.connect(self._on_timer_skin_changed)

        self._refresh_grid()
        self.content_layout.addWidget(self.grid_container)
        self.content_layout.addStretch()

    def _refresh_grid(self):
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.takeAt(i)
            if item.widget():
                item.widget().setParent(None)

        filtered = []
        for card in self._cards:
            match_cat = (self._current_filter == "All") or (card.category == self._current_filter)
            q = self._search_query.lower()
            match_search = (
                not q
                or (q in card.widget_name.lower())
                or (q in card.category.lower())
                or (q in card.skin_label.lower())
            )
            if match_cat and match_search:
                filtered.append(card)

        cols = 2
        for idx, card in enumerate(filtered):
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(card, r, c)

    def _set_filter(self, category: str):
        self._current_filter = category
        for cat, chip in self._filter_chips.items():
            chip.setProperty("selected", "true" if cat == category else "false")
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        self._refresh_grid()

    def _on_search_changed(self, text: str):
        self._search_query = text.strip()
        self._refresh_grid()

    def _on_card_toggled(self, widget_id: str, is_active: bool):
        if widget_id == "music_vinyl":
            self.bridge.set_music_widget_enabled(is_active)
        elif widget_id == "keys_osd":
            self.bridge.set_keylock_enabled(is_active)
        elif widget_id == "vol_mixer":
            self.bridge.set_volume_mixer_enabled(is_active)
        elif widget_id == "timer":
            self.bridge.set_timer_enabled(is_active)

    def _on_bridge_status_changed(self, widget_id: str, is_active: bool):
        for card in self._cards:
            if card.widget_id == widget_id:
                if card.switch.isChecked() != is_active:
                    card.switch.setChecked(is_active)
                break

    def retranslate_ui(self):
        self.set_header(t("overview_title"), t("overview_subtitle"))
        self.search_box.setPlaceholderText(t("overview_search_placeholder"))
        for cat_key, i18n_key in [("All", "overview_filter_all"), ("Widget", "overview_filter_widget"), ("Flyout", "overview_filter_flyout")]:
            if cat_key in self._filter_chips:
                self._filter_chips[cat_key].setText(t(i18n_key))
        if hasattr(self, "music_card"):
            active_skin = self.bridge.music_controller.active_skin_name
            skin_titles = {
                "vinyl": t("skin_vinyl_title"),
                "fullcover": t("skin_fullcover_title"),
                "ripple": t("skin_ripple_title"),
                "capa_empilhada": t("skin_stacked_title"),
            }
            skin_label = skin_titles.get(active_skin, "Music Player")
            self.music_card.retranslate_ui(name=t("overview_card_music"), skin_label=skin_label)
        if hasattr(self, "keys_card"):
            self.keys_card.retranslate_ui(name=t("overview_card_keys"), skin_label=t("overview_card_keys_skin"))
        if hasattr(self, "vol_card"):
            self.vol_card.retranslate_ui(name=t("overview_card_volume"), skin_label=t("overview_card_volume_skin"))
        if hasattr(self, "timer_card"):
            self.timer_card.retranslate_ui(name=t("overview_card_timer"))
        self._refresh_grid()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        for card in self._cards:
            card.set_theme(theme)

    def _on_music_skin_changed(self, skin_key: str):
        music_specs = init_music_skin_specs()
        spec = next((s for s in music_specs if s.id == skin_key), None)
        if spec and hasattr(self, "music_card"):
            self.music_card.set_spec(spec, spec.title)

    def _on_timer_skin_changed(self, skin_key: str):
        timer_specs = init_timer_skin_specs()
        spec = next((s for s in timer_specs if s.id == skin_key), None)
        if spec and hasattr(self, "timer_card"):
            self.timer_card.set_spec(spec, spec.title)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "music_card"):
            active_skin = self.bridge.music_controller.active_skin_name
            music_specs = init_music_skin_specs()
            spec = next((s for s in music_specs if s.id == active_skin), None)
            if spec:
                self.music_card.set_spec(spec, spec.title)

        if hasattr(self, "timer_card"):
            active_timer_skin = self.bridge.timer_controller.active_skin_name
            timer_specs = init_timer_skin_specs()
            spec = next((s for s in timer_specs if s.id == active_timer_skin), None)
            if spec:
                self.timer_card.set_spec(spec, spec.title)


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

        self.pos_picker = PositionPicker(current_pos="br", theme=self._theme, parent=pos_card)
        self.pos_picker.position_changed.connect(self._on_pos_changed)
        pos_layout.addWidget(self.pos_picker)
        self.content_layout.addWidget(pos_card)

        # 2. Card de Tamanho e Escala Proporcional
        scale_card = QFrame()
        scale_card.setProperty("class", "HubCard")
        scale_layout = QHBoxLayout(scale_card)
        scale_layout.setContentsMargins(18, 14, 18, 14)

        scale_info = QVBoxLayout()
        scale_info.setSpacing(3)
        self.t_scale = QLabel(t("music_scale_title"))
        self.t_scale.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.s_scale = QLabel(t("music_scale_sub"))
        self.s_scale.setWordWrap(True)
        self.s_scale.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        scale_info.addWidget(self.t_scale)
        scale_info.addWidget(self.s_scale)
        scale_layout.addLayout(scale_info, stretch=1)

        scale_buttons_layout = QHBoxLayout()
        scale_buttons_layout.setSpacing(6)
        self._scale_chips: dict[str, QPushButton] = {}

        self._scale_options = [
            ("auto", t("music_scale_auto")),
            ("0.375", "75%"),
            ("0.50", "100%"),
            ("0.625", "125%"),
            ("0.75", "150%"),
        ]

        for opt_key, opt_label in self._scale_options:
            btn = QPushButton(opt_label)
            btn.setProperty("class", "Chip")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=opt_key: self._on_scale_selected(k))
            self._scale_chips[opt_key] = btn
            scale_buttons_layout.addWidget(btn)

        scale_layout.addLayout(scale_buttons_layout)
        self.content_layout.addWidget(scale_card)

        self.update_scale_selection()
        self.bridge.music_scale_changed.connect(self.update_scale_selection)

        # 3. Card de Skins Disponíveis
        skin_card = QFrame()
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
        self.content_layout.addWidget(skin_card)

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
        Atualiza o estado visual dos chips de seleção de escala.
        Se a escala for customizada pelo usuário (não-auto e diferente dos presets fixos),
        nenhum dos chips de escala deve aparecer selecionado.
        """
        if not hasattr(self, "_scale_chips") or not self._scale_chips:
            return

        if scale is _SCALE_UNSET:
            curr_scale = config_manager.get_music_scale()
        else:
            curr_scale = scale

        is_auto = (curr_scale is None)

        matching_key = None
        if is_auto:
            matching_key = "auto"
        else:
            for opt_key, _ in self._scale_options:
                if opt_key == "auto":
                    continue
                try:
                    if abs(float(opt_key) - float(curr_scale)) < 0.005:
                        matching_key = opt_key
                        break
                except (ValueError, TypeError):
                    continue

        for k, btn in self._scale_chips.items():
            is_sel = (k == matching_key)
            btn.setProperty("selected", "true" if is_sel else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_scale_selected(self, opt_key: str):
        if opt_key == "auto":
            self.bridge.set_music_scale(None)
        else:
            try:
                scale_val = float(opt_key)
                self.bridge.set_music_scale(scale_val)
            except ValueError:
                return

    def _on_hotkey_changed(self, new_shortcut: str):
        self.bridge.update_music_hotkey(new_shortcut)

    def _on_pos_changed(self, pos_key: str):
        self.bridge.move_music_to_screen_position(pos_key)

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

    def _on_auto_launch_toggled(self, checked: bool):
        self.bridge.set_music_auto_launch(checked)

    def _on_auto_hide_toggled(self, checked: bool):
        self.bridge.set_music_auto_hide(checked)

    def retranslate_ui(self):
        self.set_header(t("music_title"), t("music_subtitle"))
        if hasattr(self, "t_pos"):
            self.t_pos.setText(t("music_pos_title"))
        if hasattr(self, "s_pos"):
            self.s_pos.setText(t("music_pos_sub"))
        if hasattr(self, "t_scale"):
            self.t_scale.setText(t("music_scale_title"))
        if hasattr(self, "s_scale"):
            self.s_scale.setText(t("music_scale_sub"))
        if hasattr(self, "_scale_chips") and "auto" in self._scale_chips:
            self._scale_chips["auto"].setText(t("music_scale_auto"))
        if hasattr(self, "sk_header"):
            self.sk_header.setText(t("music_style_title"))
        if hasattr(self, "sk_desc"):
            self.sk_desc.setText(t("music_style_sub"))
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
        if hasattr(self, "hk_title"):
            self.hk_title.setText(t("music_hotkey_title"))
        if hasattr(self, "hk_desc"):
            self.hk_desc.setText(t("music_hotkey_sub"))
        if hasattr(self, "hk_picker"):
            self.hk_picker.retranslate_ui()
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
        if hasattr(self, "s_scale"):
            self.s_scale.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        if hasattr(self, "sw_auto_launch"):
            self.sw_auto_launch.set_theme(theme)
        if hasattr(self, "sw_auto_hide"):
            self.sw_auto_hide.set_theme(theme)
        if hasattr(self, "sw_wheel_volume"):
            self.sw_wheel_volume.set_theme(theme)
        if hasattr(self, "hk_picker"):
            self.hk_picker.set_theme(theme)
        if hasattr(self, "_skin_cards"):
            for card in self._skin_cards.values():
                card.set_theme(theme)


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
        t_layout.setContentsMargins(18, 14, 18, 14)

        t_info = QVBoxLayout()
        t_info.setSpacing(3)
        self.t_title = QLabel(t("keys_test_title"))
        self.t_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.t_desc = QLabel(t("keys_test_sub"))
        self.t_desc.setWordWrap(True)
        self.t_desc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        t_info.addWidget(self.t_title)
        t_info.addWidget(self.t_desc)
        t_layout.addLayout(t_info, stretch=1)

        self.btn_test = QPushButton(t("keys_test_btn"))
        self.btn_test.setProperty("class", "Chip")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.clicked.connect(lambda: self.bridge.trigger_test_keylock("Caps Lock", True))
        t_layout.addWidget(self.btn_test)

        self.content_layout.addWidget(test_card)

        # Card de Tema visual (mostra o flyout ao escolher, para ver o resultado)
        self.theme_picker = ThemeGalleryCard(
            keylock_theme_loader,
            "keylock",
            make_keylock_theme_spec,
            lambda: self.bridge.trigger_test_keylock("Caps Lock", True),
            self._theme,
            appliers={
                "keylock": lambda: self.bridge.trigger_test_keylock("Caps Lock", True),
                "mixer": self.bridge.trigger_test_volume,
            },
            parent=self,
        )
        self.content_layout.addWidget(self.theme_picker)

        # Card de Opções
        card = QFrame()
        card.setProperty("class", "HubCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(18, 14, 18, 14)
        c_layout.setSpacing(12)

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
            info.addWidget(lbl_n)
            info.addWidget(lbl_d)
            self._opt_labels.append((lbl_n, name_key, lbl_d, desc_key))

            s = PillSwitch(checked=config_manager.is_keylock_key_enabled(key_id), theme=self._theme)
            s.toggled.connect(lambda checked, k=key_id: config_manager.set_keylock_key_enabled(k, checked))
            self._key_switches[key_id] = s
            row.addLayout(info, stretch=1)
            row.addWidget(s)
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
        hk_layout.setContentsMargins(18, 14, 18, 14)

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
        if hasattr(self, "t_title"):
            self.t_title.setText(t("keys_test_title"))
        if hasattr(self, "t_desc"):
            self.t_desc.setText(t("keys_test_sub"))
        if hasattr(self, "btn_test"):
            self.btn_test.setText(t("keys_test_btn"))
        if hasattr(self, "_opt_labels"):
            for lbl_n, name_key, lbl_d, desc_key in self._opt_labels:
                lbl_n.setText(t(name_key))
                lbl_d.setText(t(desc_key))
        if hasattr(self, "hk_title"):
            self.hk_title.setText(t("keys_hotkey_title"))
        if hasattr(self, "hk_desc"):
            self.hk_desc.setText(t("keys_hotkey_sub"))
        if hasattr(self, "hk_picker"):
            self.hk_picker.retranslate_ui()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        if hasattr(self, "hk_picker"):
            self.hk_picker.set_theme(theme)
        if hasattr(self, "theme_picker"):
            self.theme_picker.set_theme(theme)


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

        # Card de Tema visual (mostra o flyout ao escolher, para ver o resultado)
        self.theme_picker = ThemeGalleryCard(
            mixer_theme_loader,
            "mixer",
            make_mixer_theme_spec,
            self.bridge.trigger_test_volume,
            self._theme,
            appliers={
                "keylock": lambda: self.bridge.trigger_test_keylock("Caps Lock", True),
                "mixer": self.bridge.trigger_test_volume,
            },
            parent=self,
        )
        self.content_layout.addWidget(self.theme_picker)

        # Card de Configurações
        card = QFrame()
        card.setProperty("class", "HubCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(18, 14, 18, 14)
        c_layout.setSpacing(12)

        row = QHBoxLayout()
        info = QVBoxLayout()
        info.setSpacing(2)
        self.lbl_m = QLabel(t("volume_opt_mixer_title"))
        self.lbl_m.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.lbl_d = QLabel(t("volume_opt_mixer_sub"))
        self.lbl_d.setWordWrap(True)
        self.lbl_d.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info.addWidget(self.lbl_m)
        info.addWidget(self.lbl_d)

        s = PillSwitch(checked=True, theme=self._theme)
        row.addLayout(info, stretch=1)
        row.addWidget(s)
        c_layout.addLayout(row)

        self.content_layout.addWidget(card)

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
        if hasattr(self, "t_title"):
            self.t_title.setText(t("volume_test_title"))
        if hasattr(self, "t_desc"):
            self.t_desc.setText(t("volume_test_sub"))
        if hasattr(self, "btn_test"):
            self.btn_test.setText(t("volume_test_btn"))
        if hasattr(self, "lbl_m"):
            self.lbl_m.setText(t("volume_opt_mixer_title"))
        if hasattr(self, "lbl_d"):
            self.lbl_d.setText(t("volume_opt_mixer_sub"))
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
        pos_layout.setContentsMargins(18, 14, 18, 14)

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

        self.content_layout.addWidget(skin_card)

        # 4. Card de Comportamento & Ações
        behav_card = QFrame()
        behav_card.setProperty("class", "HubCard")
        b_layout = QVBoxLayout(behav_card)
        b_layout.setContentsMargins(18, 14, 18, 14)
        b_layout.setSpacing(12)

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
        row1.addLayout(info1, stretch=1)
        row1.addWidget(self.sw_remember)
        b_layout.addLayout(row1)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setProperty("class", "HubDivider")
        b_layout.addWidget(sep1)

        # Linha 2: Hover Inteligente de Tempo
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
        row_smart.addLayout(info_smart, stretch=1)
        row_smart.addWidget(self.sw_smart_hover)
        b_layout.addLayout(row_smart)

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
        info2.addWidget(self.l2_title)
        info2.addWidget(self.l2_sub)

        self.btn_show = QPushButton(t("timer_opt_show_btn"))
        self.btn_show.setProperty("class", "Chip")
        self.btn_show.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show.clicked.connect(self._on_show_timer_clicked)

        row2.addLayout(info2, stretch=1)
        row2.addWidget(self.btn_show)
        b_layout.addLayout(row2)

        self.content_layout.addWidget(behav_card)

        # 5. Card de Atalho de Teclado
        hk_card = QFrame()
        hk_card.setProperty("class", "HubCard")
        hk_layout = QHBoxLayout(hk_card)
        hk_layout.setContentsMargins(18, 14, 18, 14)

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

    def _on_smart_hover_toggled(self, checked: bool):
        config_manager.set_timer_smart_hover_enabled(checked)
        if self.bridge.timer_controller.skin:
            self.bridge.timer_controller.skin.update()

    def _on_show_timer_clicked(self):
        self.bridge.set_timer_enabled(True)
        if self.bridge.timer_controller.skin:
            self.bridge.timer_controller.skin.raise_()
            self.bridge.timer_controller.skin.activateWindow()

    def _on_skin_selected(self, skin_key: str):
        if skin_key in self.bridge.timer_controller.AVAILABLE_SKINS:
            self.bridge.set_timer_skin(skin_key)
            if hasattr(self, "_skin_cards"):
                for k, card in self._skin_cards.items():
                    card.set_selected(k == skin_key)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "_skin_cards"):
            active_skin = self.bridge.timer_controller.active_skin_name
            for k, card in self._skin_cards.items():
                card.set_selected(k == active_skin)

    def retranslate_ui(self):
        self.set_header(t("timer_title"), t("timer_subtitle"))
        if hasattr(self, "t_pos"):
            self.t_pos.setText(t("timer_pos_title"))
        if hasattr(self, "s_pos"):
            self.s_pos.setText(t("timer_pos_sub"))
        if hasattr(self, "sk_header"):
            self.sk_header.setText(t("timer_style_title"))
        if hasattr(self, "sk_desc"):
            self.sk_desc.setText(t("timer_style_sub"))
        if hasattr(self, "l1_title"):
            self.l1_title.setText(t("timer_opt_remember_title"))
        if hasattr(self, "l1_sub"):
            self.l1_sub.setText(t("timer_opt_remember_sub"))
        if hasattr(self, "ls_title"):
            self.ls_title.setText(t("timer_opt_smart_hover_title"))
        if hasattr(self, "ls_sub"):
            self.ls_sub.setText(t("timer_opt_smart_hover_sub"))
        if hasattr(self, "l2_title"):
            self.l2_title.setText(t("timer_opt_show_title"))
        if hasattr(self, "l2_sub"):
            self.l2_sub.setText(t("timer_opt_show_sub"))
        if hasattr(self, "btn_show"):
            self.btn_show.setText(t("timer_opt_show_btn"))
        if hasattr(self, "hk_title"):
            self.hk_title.setText(t("timer_hotkey_title"))
        if hasattr(self, "hk_desc"):
            self.hk_desc.setText(t("timer_hotkey_sub"))
        if hasattr(self, "hk_picker"):
            self.hk_picker.retranslate_ui()
        timer_skin_subs = {
            "windows": t("skin_windows_sub"),
            "notion": t("skin_coming_soon"),
            "focus_wheel": t("skin_coming_soon"),
            "pomodoro_bars": t("skin_coming_soon"),
        }
        if hasattr(self, "_skin_cards"):
            for s_id, card in self._skin_cards.items():
                if s_id in timer_skin_subs:
                    card._spec.subtitle = timer_skin_subs[s_id]
                    card._invalidate_cache()
                    card.update()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        self.pos_picker.set_theme(theme)
        self.sw_remember.set_theme(theme)
        self.sw_smart_hover.set_theme(theme)
        if hasattr(self, "hk_picker"):
            self.hk_picker.set_theme(theme)
        if hasattr(self, "_skin_cards"):
            for card in self._skin_cards.values():
                card.set_theme(theme)


class GeneralPage(BaseHubPage):
    """Página de preferências gerais com seletores de aparência e idioma refinados."""

    def __init__(
        self,
        on_theme_change=None,
        on_language_change=None,
        current_pref: str = "system",
        current_lang: str | None = None,
        theme: HubTheme = THEME_LIGHT,
        parent=None,
    ):
        super().__init__(
            title=t("gen_title"),
            subtitle=t("gen_subtitle"),
            theme=theme,
            parent=parent,
        )
        self._on_theme_change = on_theme_change
        self._on_language_change = on_language_change
        self._current_pref = current_pref
        self._current_lang = current_lang or config_manager.get_language("pt")
        self._build_settings()

    def _build_settings(self):
        card = QFrame()
        card.setProperty("class", "HubCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(18, 14, 18, 14)
        c_layout.setSpacing(12)

        # Iniciar com o Windows
        row1 = QHBoxLayout()
        info1 = QVBoxLayout()
        info1.setSpacing(2)
        self.t1 = QLabel(t("gen_startup_title"))
        self.t1.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d1 = QLabel(t("gen_startup_sub"))
        self.d1.setWordWrap(True)
        self.d1.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info1.addWidget(self.t1)
        info1.addWidget(self.d1)
        self.s1 = PillSwitch(checked=config_manager.is_start_with_windows_enabled(), theme=self._theme)
        self.s1.toggled_value.connect(config_manager.set_start_with_windows_enabled)
        row1.addLayout(info1, stretch=1)
        row1.addWidget(self.s1)
        c_layout.addLayout(row1)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setProperty("class", "HubDivider")
        c_layout.addWidget(sep1)

        # Iniciar minimizado
        row_min = QHBoxLayout()
        info_min = QVBoxLayout()
        info_min.setSpacing(2)
        self.t_min = QLabel(t("gen_start_minimized_title"))
        self.t_min.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d_min = QLabel(t("gen_start_minimized_sub"))
        self.d_min.setWordWrap(True)
        self.d_min.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_min.addWidget(self.t_min)
        info_min.addWidget(self.d_min)
        self.s_min = PillSwitch(checked=config_manager.is_start_minimized_enabled(), theme=self._theme)
        self.s_min.toggled_value.connect(config_manager.set_start_minimized_enabled)
        row_min.addLayout(info_min, stretch=1)
        row_min.addWidget(self.s_min)
        c_layout.addLayout(row_min)

        sep_min = QFrame()
        sep_min.setFrameShape(QFrame.Shape.HLine)
        sep_min.setProperty("class", "HubDivider")
        c_layout.addWidget(sep_min)

        # Permanecer no Tray
        row2 = QHBoxLayout()
        info2 = QVBoxLayout()
        info2.setSpacing(2)
        self.t2 = QLabel(t("gen_tray_title"))
        self.t2.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d2 = QLabel(t("gen_tray_sub"))
        self.d2.setWordWrap(True)
        self.d2.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info2.addWidget(self.t2)
        info2.addWidget(self.d2)
        self.s2 = PillSwitch(checked=config_manager.is_keep_in_tray_enabled(), theme=self._theme)
        self.s2.toggled_value.connect(config_manager.set_keep_in_tray_enabled)
        row2.addLayout(info2, stretch=1)
        row2.addWidget(self.s2)
        c_layout.addLayout(row2)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setProperty("class", "HubDivider")
        c_layout.addWidget(sep2)

        # Modo de Aparência
        row3 = QHBoxLayout()
        info3 = QVBoxLayout()
        info3.setSpacing(2)
        self.t3 = QLabel(t("gen_theme_title"))
        self.t3.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d3 = QLabel(t("gen_theme_sub"))
        self.d3.setWordWrap(True)
        self.d3.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info3.addWidget(self.t3)
        info3.addWidget(self.d3)
        row3.addLayout(info3, stretch=1)

        theme_buttons_layout = QHBoxLayout()
        theme_buttons_layout.setSpacing(6)
        self._theme_chips: dict[str, QPushButton] = {}

        self._theme_modes = [
            ("light", "gen_theme_light"),
            ("dark", "gen_theme_dark"),
            ("true_dark", "gen_theme_true_dark"),
            ("system", "gen_theme_system"),
        ]
        for mode_key, i18n_key in self._theme_modes:
            btn = QPushButton(t(i18n_key))
            btn.setProperty("class", "Chip")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if mode_key == self._current_pref:
                btn.setProperty("selected", "true")
            btn.clicked.connect(lambda checked=False, m=mode_key: self._set_theme_mode(m))
            self._theme_chips[mode_key] = btn
            theme_buttons_layout.addWidget(btn)

        row3.addLayout(theme_buttons_layout)
        c_layout.addLayout(row3)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setProperty("class", "HubDivider")
        c_layout.addWidget(sep3)

        # Seletor de Idioma
        row4 = QHBoxLayout()
        info4 = QVBoxLayout()
        info4.setSpacing(2)
        self.t4 = QLabel(t("gen_language_title"))
        self.t4.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d4 = QLabel(t("gen_language_sub"))
        self.d4.setWordWrap(True)
        self.d4.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info4.addWidget(self.t4)
        info4.addWidget(self.d4)
        row4.addLayout(info4, stretch=1)

        lang_buttons_layout = QHBoxLayout()
        lang_buttons_layout.setSpacing(6)
        self._lang_chips: dict[str, QPushButton] = {}

        for lang_key, lang_label in [("pt", "Português"), ("en", "English")]:
            btn = QPushButton(lang_label)
            btn.setProperty("class", "Chip")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("selected", "true" if lang_key == self._current_lang else "false")
            btn.clicked.connect(lambda checked=False, lk=lang_key: self._set_language(lk))
            self._lang_chips[lang_key] = btn
            lang_buttons_layout.addWidget(btn)

        row4.addLayout(lang_buttons_layout)
        c_layout.addLayout(row4)

        self.content_layout.addWidget(card)

        # Card de Atualizações do Sistema
        self._pending_update_info: Optional[UpdateInfo] = None
        card_update = QFrame()
        card_update.setProperty("class", "HubCard")
        up_layout = QVBoxLayout(card_update)
        up_layout.setContentsMargins(18, 14, 18, 14)
        up_layout.setSpacing(10)

        row_up = QHBoxLayout()
        info_up = QVBoxLayout()
        info_up.setSpacing(2)
        self.t_update = QLabel(t("gen_updates_title"))
        self.t_update.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d_update = QLabel(t("gen_updates_installed").format(version=__version__))
        self.d_update.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_up.addWidget(self.t_update)
        info_up.addWidget(self.d_update)
        row_up.addLayout(info_up, stretch=1)

        self.btn_check_update = QPushButton(t("gen_updates_btn_check"))
        self.btn_check_update.setProperty("class", "Chip")
        self.btn_check_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_update.clicked.connect(self._check_for_updates)
        row_up.addWidget(self.btn_check_update)

        self.btn_apply_update = QPushButton(t("gen_updates_btn_download"))
        self.btn_apply_update.setProperty("class", "Chip")
        self.btn_apply_update.setProperty("selected", "true")
        self.btn_apply_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_update.setVisible(False)
        self.btn_apply_update.clicked.connect(self._apply_update)
        row_up.addWidget(self.btn_apply_update)

        up_layout.addLayout(row_up)

        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setWordWrap(True)
        self.lbl_update_status.setStyleSheet(f"color: {self._theme.mute}; font-size: 12px;")
        self.lbl_update_status.setVisible(False)
        up_layout.addWidget(self.lbl_update_status)

        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.setTextVisible(False)
        self.update_progress.setFixedHeight(6)
        self.update_progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {self._theme.line};
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: #FFA13D;
                border-radius: 3px;
            }}
        """)
        self.update_progress.setVisible(False)
        up_layout.addWidget(self.update_progress)

        self.content_layout.addWidget(card_update)
        self.content_layout.addStretch()

    def _check_for_updates(self):
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText(t("gen_updates_checking"))
        self.lbl_update_status.setVisible(True)
        self.lbl_update_status.setText(t("gen_updates_checking"))
        self._pending_update_info = None

        updater_service.check_for_updates(
            on_update_found=self._on_update_found,
            on_up_to_date=self._on_up_to_date,
            on_error=self._on_update_error,
        )

    def _on_update_found(self, info: UpdateInfo):
        self._pending_update_info = info
        self.btn_check_update.setVisible(False)
        self.btn_apply_update.setVisible(True)
        self.btn_apply_update.setEnabled(True)
        self.lbl_update_status.setVisible(True)
        self.lbl_update_status.setText(t("gen_updates_found").format(version=info.latest_version))

    def _on_up_to_date(self, current_ver: str):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(t("gen_updates_btn_check"))
        self.btn_apply_update.setVisible(False)
        self.lbl_update_status.setVisible(True)
        self.lbl_update_status.setText(t("gen_updates_up_to_date"))

    def _on_update_error(self, err_msg: str):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(t("gen_updates_btn_check"))
        self.lbl_update_status.setVisible(True)
        self.lbl_update_status.setText(f"{t('gen_updates_err')} ({err_msg})")

    def _apply_update(self):
        if not self._pending_update_info:
            return
        self.btn_apply_update.setEnabled(False)
        self.update_progress.setVisible(True)
        self.update_progress.setValue(0)
        self.lbl_update_status.setText(t("gen_updates_downloading").format(percent=0))

        updater_service.start_download(
            download_url=self._pending_update_info.download_url,
            on_progress=self._on_download_progress,
            on_finished=self._on_download_finished,
            on_error=self._on_download_error,
        )

    def _on_download_progress(self, percent: int):
        self.update_progress.setValue(percent)
        self.lbl_update_status.setText(t("gen_updates_downloading").format(percent=percent))

    def _on_download_finished(self, temp_path: str):
        self.lbl_update_status.setText(t("gen_updates_applying"))
        updater_service.apply_update_and_restart(temp_path)

    def _on_download_error(self, err_msg: str):
        self.update_progress.setVisible(False)
        self.btn_apply_update.setEnabled(True)
        self.lbl_update_status.setText(f"Falha no download: {err_msg}")

    def _set_theme_mode(self, mode: str):
        self._current_pref = mode
        for k, btn in self._theme_chips.items():
            btn.setProperty("selected", "true" if k == mode else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if self._on_theme_change:
            self._on_theme_change(mode)

    def _set_language(self, lang_code: str):
        if lang_code == self._current_lang:
            return
        self._current_lang = lang_code
        for k, btn in self._lang_chips.items():
            btn.setProperty("selected", "true" if k == lang_code else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        from app.core.i18n import i18n
        i18n.set_language(lang_code)
        if self._on_language_change:
            self._on_language_change(lang_code)

    def retranslate_ui(self):
        self.set_header(t("gen_title"), t("gen_subtitle"))
        if hasattr(self, "t1"):
            self.t1.setText(t("gen_startup_title"))
        if hasattr(self, "d1"):
            self.d1.setText(t("gen_startup_sub"))
        if hasattr(self, "t_min"):
            self.t_min.setText(t("gen_start_minimized_title"))
        if hasattr(self, "d_min"):
            self.d_min.setText(t("gen_start_minimized_sub"))
        if hasattr(self, "t2"):
            self.t2.setText(t("gen_tray_title"))
        if hasattr(self, "d2"):
            self.d2.setText(t("gen_tray_sub"))
        if hasattr(self, "t3"):
            self.t3.setText(t("gen_theme_title"))
        if hasattr(self, "d3"):
            self.d3.setText(t("gen_theme_sub"))
        if hasattr(self, "t4"):
            self.t4.setText(t("gen_language_title"))
        if hasattr(self, "d4"):
            self.d4.setText(t("gen_language_sub"))
        if hasattr(self, "_theme_modes"):
            for mode_key, i18n_key in self._theme_modes:
                if mode_key in self._theme_chips:
                    self._theme_chips[mode_key].setText(t(i18n_key))
        if hasattr(self, "_lang_chips"):
            from app.core.i18n import i18n
            self._current_lang = i18n.current_language
            for k, btn in self._lang_chips.items():
                btn.setProperty("selected", "true" if k == self._current_lang else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        if hasattr(self, "t_update"):
            self.t_update.setText(t("gen_updates_title"))
        if hasattr(self, "d_update"):
            self.d_update.setText(t("gen_updates_installed").format(version=__version__))
        if hasattr(self, "btn_check_update") and self.btn_check_update.isEnabled():
            self.btn_check_update.setText(t("gen_updates_btn_check"))
        if hasattr(self, "btn_apply_update"):
            self.btn_apply_update.setText(t("gen_updates_btn_download"))

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        if hasattr(self, "s1"):
            self.s1.set_theme(theme)
        if hasattr(self, "s_min"):
            self.s_min.set_theme(theme)
        if hasattr(self, "s2"):
            self.s2.set_theme(theme)
        if hasattr(self, "d_min"):
            self.d_min.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        if hasattr(self, "d_update"):
            self.d_update.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        if hasattr(self, "lbl_update_status"):
            self.lbl_update_status.setStyleSheet(f"color: {theme.mute}; font-size: 12px;")
        if hasattr(self, "update_progress"):
            self.update_progress.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {theme.line};
                    border-radius: 3px;
                    border: none;
                }}
                QProgressBar::chunk {{
                    background-color: #FFA13D;
                    border-radius: 3px;
                }}
            """)
        for btn in self._theme_chips.values():
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if hasattr(self, "_lang_chips"):
            for btn in self._lang_chips.values():
                btn.style().unpolish(btn)
                btn.style().polish(btn)
