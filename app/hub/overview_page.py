"""Hub: página Visão geral. Extraído de `pages.py` (mesmo código, só em arquivo próprio)."""

from dataclasses import replace
from functools import partial
from typing import List
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.hub.components.help_badge import HelpBadge
from app.hub.components.tab_pill import ChipGroup
from app.hub.components.widget_card import WidgetCard
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.widgets.music.skins import init_music_skin_specs
from app.widgets.keylock_osd import KEYLOCK_SPEC, keylock_mock_state
from app.widgets.timer import init_timer_spec, init_timer_skin_specs
from app.widgets.volume_mixer import init_volume_spec
from app.widgets.performance import init_performance_skin_specs
from app.widgets.storage import init_storage_spec
from app.widgets.battery import init_battery_spec
from app.widgets.weather import init_weather_skin_specs
from app.hub.base_page import BaseHubPage
from app.hub.ui_tokens import CARD_MARGINS, CHIP_GAP, ROWS_GAP


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
        self._build_anchor_card()
        self._build_skin_switch_card()

    def _build_skin_switch_card(self):
        """Troca de skin: um efeito para todos os widgets (app/core/skin_switch.py)."""
        from app.core import skin_switch

        card, lay = self._card(vertical=True)
        lay.setSpacing(ROWS_GAP)
        self.skin_switch_card = card
        lay.addLayout(self._info("skin_switch_title", "skin_switch_sub", title_px=14, help_key="skin_switch_help"))

        def pick(key):
            config_manager.set_skin_switch_effect(key)
            self._skin_switch_group.set_selected(key)

        self._skin_switch_group = ChipGroup([(k, t(f"skin_switch_{k}")) for k in skin_switch.EFFECTS], pick,
                                            self._theme, selected=skin_switch.current_effect())
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._skin_switch_group)
        row.addStretch()
        lay.addLayout(row)
        self.content_layout.insertWidget(self.content_layout.count() - 1, card)   # antes do espaçador final

    # Ancoragem de widgets: estilo da rede e efeito ao juntar (o resto é fixo; ver app/core/anchor_manager.py)
    _ANCHOR_NET_CHIPS = (("dots", "anchor_net_dots"), ("lines", "anchor_net_lines"), ("both", "anchor_net_both"))
    _ANCHOR_BOOM_CHIPS = (("ring", "anchor_boom_ring"), ("sweep", "anchor_boom_sweep"))

    def _build_anchor_card(self):
        from app.core.anchor_manager import boom_style, net_style

        card = QFrame()
        card.setProperty("class", "HubCard")
        self.anchor_card = card
        lay = QVBoxLayout(card)
        lay.setContentsMargins(*CARD_MARGINS)
        lay.setSpacing(ROWS_GAP)

        self.t_anchor = QLabel(t("anchor_card_title"))
        self.t_anchor.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.anchor_help = HelpBadge(t("anchor_card_help"), theme=self._theme)
        anchor_title_row = QHBoxLayout()
        anchor_title_row.setContentsMargins(2, 0, 0, 0)
        anchor_title_row.setSpacing(6)
        anchor_title_row.addWidget(self.t_anchor)
        anchor_title_row.addWidget(self.anchor_help, alignment=Qt.AlignmentFlag.AlignVCenter)
        anchor_title_row.addStretch()
        self.s_anchor = QLabel(t("anchor_card_sub"))
        self.s_anchor.setWordWrap(True)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addLayout(anchor_title_row)
        head.addWidget(self.s_anchor)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._anchor_bento_cells: list[QFrame] = []

        def bento_cell(title_key, chips, selected, on_pick, col_idx):
            cell = QFrame()
            cell.setObjectName("BentoCell")
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(10)
            title = QLabel(t(title_key))
            cl.addWidget(title)
            cl.addStretch()
            group = ChipGroup([(k, t(i)) for k, i in chips], on_pick, self._theme, selected=selected, segmented=True)
            cl.addWidget(group)
            self._anchor_bento_cells.append(cell)
            grid.addWidget(cell, 0, col_idx)
            return title, group

        def pick_net(key):
            config_manager.set_anchor("net_style", key)
            self._anchor_net_group.set_selected(key)

        def pick_boom(key):
            config_manager.set_anchor("boom", key)
            self._anchor_boom_group.set_selected(key)

        self.t_anchor_net, self._anchor_net_group = bento_cell(
            "anchor_net_title", self._ANCHOR_NET_CHIPS, net_style(), pick_net, 0)
        self.t_anchor_boom, self._anchor_boom_group = bento_cell(
            "anchor_boom_title", self._ANCHOR_BOOM_CHIPS, boom_style(), pick_boom, 1)
        lay.addLayout(grid)

        self._style_anchor_card(self._theme)
        self.content_layout.insertWidget(self.content_layout.count() - 1, card)   # antes do espaçador final

    def _style_anchor_card(self, theme: HubTheme):
        self.s_anchor.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px; padding-left: 2px;")
        cell_css = (
            f"QFrame#BentoCell {{ background-color: {theme.panel2}; "
            f"border: 1px solid {theme.line}; border-radius: 12px; }}"
        )
        for cell in getattr(self, "_anchor_bento_cells", ()):
            cell.setStyleSheet(cell_css)
        for lbl in (self.t_anchor_net, self.t_anchor_boom):
            lbl.setStyleSheet(f"font-size: 12.5px; font-weight: 600; color: {theme.body}; background: transparent;")
        if hasattr(self, "anchor_help"):
            self.anchor_help.set_theme(theme)

    def _retranslate_anchor_card(self):
        self.t_anchor.setText(t("anchor_card_title"))
        self.s_anchor.setText(t("anchor_card_sub"))
        if hasattr(self, "anchor_help"):
            self.anchor_help.set_text(t("anchor_card_help"))
        self.t_anchor_net.setText(t("anchor_net_title"))
        self.t_anchor_boom.setText(t("anchor_boom_title"))
        for group, chips in ((self._anchor_net_group, self._ANCHOR_NET_CHIPS),
                             (self._anchor_boom_group, self._ANCHOR_BOOM_CHIPS)):
            for key, i18n_key in chips:
                group.button(key).setText(t(i18n_key))

    def _build_tools(self):
        tools_layout = QHBoxLayout()
        tools_layout.setSpacing(CHIP_GAP)

        # Campo de busca em tempo real
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchInput")
        self.search_box.setPlaceholderText(t("overview_search_placeholder"))
        self.search_box.textChanged.connect(self._on_search_changed)
        tools_layout.addWidget(self.search_box, stretch=1)

        # Chips de filtro de categoria
        self._filter_group = ChipGroup(
            [(k, t(i)) for k, i in [("All", "overview_filter_all"), ("Widget", "overview_filter_widget"),
                                    ("Flyout", "overview_filter_flyout")]],
            self._set_filter, self._theme, selected="All")
        self._filter_chips = self._filter_group.buttons
        tools_layout.addWidget(self._filter_group)

        self.content_layout.addLayout(tools_layout)

    def _build_gallery(self):
        self.grid_container = QWidget()
        # Sem isso a grade recebe a altura sobrando da janela e distribui entre as linhas: cards gigantes em tela em pé
        self.grid_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
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

        # 2. Caps / Lock Keys OSD Card (Sistema Flyout temporário) - miniatura do tema ativo
        self._flyout_specs: dict[str, tuple] = {}   # container -> (chave do tema ativo, spec, rótulo)
        keys_spec, keys_label = self._active_flyout_spec("keylock")
        self.keys_card = WidgetCard(
            widget_id="keys_osd",
            name=t("overview_card_keys"),
            category="Flyout",
            skin_label=keys_label,
            spec=keys_spec,
            is_active=self.bridge.is_keylock_enabled(),
            theme=self._theme,
        )
        self.keys_card.toggled.connect(self._on_card_toggled)
        self.keys_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.keys_card)

        # 3. Volume Mixer Card (Sistema Flyout temporário / retrátil) - miniatura do tema ativo
        vol_spec, vol_label = self._active_flyout_spec("mixer")
        self.vol_card = WidgetCard(
            widget_id="vol_mixer",
            name=t("overview_card_volume"),
            category="Flyout",
            skin_label=vol_label,
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
        skin_label = timer_spec.title if timer_spec else t("theme_default_timer")

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

        # 5. Weather Widget Card
        weather_spec = self._active_weather_spec()
        self.weather_card = WidgetCard(
            widget_id="weather",
            name=t("overview_card_weather"),
            category="Widget",
            skin_label=weather_spec.title,
            spec=weather_spec,
            is_active=self.bridge.is_weather_enabled(),
            theme=self._theme,
        )
        self.weather_card.toggled.connect(self._on_card_toggled)
        self.weather_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.weather_card)

        # 6. Performance Widget Card
        perf_spec = self._active_performance_spec()
        self.performance_card = WidgetCard(
            widget_id="performance",
            name=t("overview_card_performance"),
            category="Widget",
            skin_label=perf_spec.title,
            spec=perf_spec,
            is_active=self.bridge.is_performance_enabled(),
            theme=self._theme,
        )
        self.performance_card.toggled.connect(self._on_card_toggled)
        self.performance_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.performance_card)

        # 7. Storage Widget Card
        storage_spec = init_storage_spec()
        self.storage_card = WidgetCard(
            widget_id="storage",
            name=t("overview_card_storage"),
            category="Widget",
            skin_label=t("storage_skin_label"),
            spec=storage_spec,
            is_active=self.bridge.is_storage_enabled(),
            theme=self._theme,
        )
        self.storage_card.toggled.connect(self._on_card_toggled)
        self.storage_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.storage_card)

        # 8. Battery Widget Card
        self.battery_card = WidgetCard(
            widget_id="battery",
            name=t("overview_card_battery"),
            category="Widget",
            skin_label=t("battery_skin_label"),
            spec=init_battery_spec(),
            is_active=self.bridge.is_battery_enabled(),
            theme=self._theme,
        )
        # Cor do anel trocada na página de Baterias: a miniatura repinta (com a mesma aparência do Hub)
        self.bridge.battery_controller.ring_color_changed.connect(lambda: self.battery_card.set_theme(self._theme))
        self.battery_card.toggled.connect(self._on_card_toggled)
        self.battery_card.customize.connect(self.customize_requested.emit)
        self._cards.append(self.battery_card)

        self.bridge.status_changed.connect(self._on_bridge_status_changed)
        self.bridge.weather_skin_changed.connect(self._on_weather_skin_changed)
        self.bridge.performance_skin_changed.connect(self._on_performance_skin_changed)
        self.bridge.music_skin_changed.connect(self._on_music_skin_changed)
        self.bridge.timer_skin_changed.connect(self._on_timer_skin_changed)

        self._refresh_grid()
        self.content_layout.addWidget(self.grid_container)
        self.content_layout.addStretch()

    def _refresh_grid(self):
        # Tira do layout sem desparentar: setParent(None) num widget visível o vira janela solta por um instante.
        for i in reversed(range(self.grid_layout.count())):
            self.grid_layout.takeAt(i)

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
            card.show()
        shown = set(map(id, filtered))
        for card in self._cards:
            if id(card) not in shown:
                card.hide()   # continua filho da grade, só fora do layout

    def _set_filter(self, category: str):
        self._current_filter = category
        self._filter_group.set_selected(category)
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
        elif widget_id == "weather":
            self.bridge.set_weather_enabled(is_active)
        elif widget_id == "performance":
            self.bridge.set_performance_enabled(is_active)
        elif widget_id == "storage":
            self.bridge.set_storage_enabled(is_active)
        elif widget_id == "battery":
            self.bridge.set_battery_enabled(is_active)

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
            self.keys_card.retranslate_ui(name=t("overview_card_keys"), skin_label=self._active_flyout_spec("keylock")[1])
        if hasattr(self, "vol_card"):
            self.vol_card.retranslate_ui(name=t("overview_card_volume"), skin_label=self._active_flyout_spec("mixer")[1])
        if hasattr(self, "timer_card"):
            self.timer_card.retranslate_ui(name=t("overview_card_timer"), skin_label=t("theme_default_timer"))
        if hasattr(self, "weather_card"):
            self._on_weather_skin_changed(self.bridge.weather_controller.active_skin_name)
            self.weather_card.retranslate_ui(name=t("overview_card_weather"), skin_label=self.weather_card.skin_label)
        if hasattr(self, "performance_card"):
            self._on_performance_skin_changed(self.bridge.performance_controller.active_skin_name)
            self.performance_card.retranslate_ui(name=t("overview_card_performance"), skin_label=self.performance_card.skin_label)
        if hasattr(self, "storage_card"):
            self.storage_card.retranslate_ui(name=t("overview_card_storage"), skin_label=t("storage_skin_label"))
        if hasattr(self, "battery_card"):
            self.battery_card.retranslate_ui(name=t("overview_card_battery"), skin_label=t("battery_skin_label"))
        if hasattr(self, "anchor_card"):
            self._retranslate_anchor_card()
        if hasattr(self, "skin_switch_card"):
            for lbl, key in self._texts:
                lbl.setText(t(key))
            for badge, key in self._help_badges:
                badge.set_text(t(key))
            from app.core.skin_switch import EFFECTS
            for key in EFFECTS:
                self._skin_switch_group.button(key).setText(t(f"skin_switch_{key}"))
        self._refresh_grid()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        self._filter_group.set_theme(theme)
        for card in self._cards:
            card.set_theme(theme)
        if hasattr(self, "anchor_card"):
            self._anchor_net_group.set_theme(theme)
            self._anchor_boom_group.set_theme(theme)
            self._style_anchor_card(theme)
        if hasattr(self, "skin_switch_card"):
            self._skin_switch_group.set_theme(theme)
            for sub in self._subs:
                sub.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
            for badge, _key in self._help_badges:
                badge.set_theme(theme)

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

    def _active_performance_spec(self):
        specs = init_performance_skin_specs()
        active = self.bridge.performance_controller.active_skin_name
        return next((s for s in specs if s.id == active), specs[0])

    def _on_performance_skin_changed(self, _skin_key: str):
        if hasattr(self, "performance_card"):
            spec = self._active_performance_spec()
            self.performance_card.set_spec(spec, spec.title)

    def _active_weather_spec(self):
        specs = init_weather_skin_specs()
        active = self.bridge.weather_controller.active_skin_name
        return next((s for s in specs if s.id == active), specs[0])

    def _on_weather_skin_changed(self, _skin_key: str):
        if hasattr(self, "weather_card"):
            spec = self._active_weather_spec()
            self.weather_card.set_spec(spec, spec.title)

    def _active_flyout_spec(self, container: str) -> tuple:
        """(spec, rótulo) do tema em uso no flyout ("keylock"/"mixer"). O Padrão usa a miniatura original do
        flyout; um tema da pasta usa a mesma miniatura da galeria de temas. A spec só é recriada quando o tema
        ativo (ou o arquivo dele) muda, para a miniatura não ser redesenhada à toa."""
        from app.core.theme_loader import DEFAULT_ID, localized_theme_name
        from app.hub.components.theme_gallery import _loader_for

        loader = _loader_for(container)
        names = {th.id: th.name for th in loader.list_themes()}
        active = loader.active_id()
        if active not in names:   # escolha salva que sumiu: o flyout usa o padrão
            active = DEFAULT_ID
        if active == DEFAULT_ID:
            default = loader.default   # o visual "Windows" segue o modo do Windows: outro objeto = outra miniatura
            key = (DEFAULT_ID, id(default))
        else:
            theme_obj = loader.theme_for(active)
            key = (active, id(theme_obj), names[active])

        cached = self._flyout_specs.get(container)
        if cached is None or cached[0] != key:
            if active == DEFAULT_ID:
                # Spec nova a cada modo do Windows (o estado de exemplo leva o tema), para o cartão repintar
                if container == "keylock":
                    spec = replace(KEYLOCK_SPEC, mock_state=partial(keylock_mock_state, default))
                else:
                    spec = replace(init_volume_spec(), mock_state=lambda th=default: th)
                label_key = "overview_card_keys_skin" if container == "keylock" else "overview_card_volume_skin"
                cached = (key, spec, label_key)
            else:
                if container == "keylock":
                    from app.widgets.keylock_osd.theme_specs import make_theme_spec
                else:
                    from app.widgets.volume_mixer.theme_specs import make_theme_spec
                title = names[active] or t("theme_custom")
                cached = (key, make_theme_spec(active, title, theme_obj), title)
            self._flyout_specs[container] = cached
        _key, spec, label = cached
        if active == DEFAULT_ID:
            label = t(label)   # rótulo traduzido na hora (muda com o idioma)
        else:
            label = localized_theme_name(active, label)
        return spec, label

    def refresh_flyout_cards(self):
        for container, card in (("keylock", getattr(self, "keys_card", None)),
                                ("mixer", getattr(self, "vol_card", None))):
            if card is None:
                continue
            spec, label = self._active_flyout_spec(container)
            if card._spec is not spec:
                card.set_spec(spec, label)
            elif card.skin_label != label:
                card.retranslate_ui(skin_label=label)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_flyout_cards()
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
