"""
Página do Weather Widget no Hub: posição, tamanho, estilo (fonte), cidades (até 5), unidade, comportamento e
atalho. Separada de pages.py, que já passa do tamanho de um arquivo legível.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from app.core.config_manager import config_manager
from app.core.i18n import i18n, t
from app.core.preview_card import PreviewCard
from app.hub.components.city_list import CityList
from app.hub.components.fold import Fold
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.components.responsive_grid import ResponsiveCardGrid
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.tab_pill import ChipGroup
from app.hub.pages import BaseHubPage
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.widgets.weather import init_weather_skin_specs
from app.services.weather_service import MAX_CITIES, city_key
from app.widgets.weather.weather_card import SCALES

SEARCH_DEBOUNCE_MS = 450
MAX_RESULTS = 6
CITY_GAP = 10   # espaço entre os itens do cartão de cidades


class WeatherPage(BaseHubPage):
    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(title=t("weather_title"), subtitle=t("weather_subtitle"), theme=theme, parent=parent)
        self.bridge = get_service_bridge()
        self.controller = self.bridge.weather_controller
        self.service = self.controller.service
        self._texts: list = []      # (QLabel, chave i18n)
        self._subs: list = []       # legendas cinzas (a cor muda com o tema)
        self._result_buttons: list = []
        self._build_ui()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._run_search)
        self.service.search_results.connect(self._on_search_results)
        self.service.reports_ready.connect(lambda _r: self._refresh_cities())   # nome do automático pode chegar agora
        self.service.cities_changed.connect(self._on_cities_changed)
        self.bridge.weather_skin_changed.connect(self._sync_skin_selection)

    # --- Construção ---

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

    @staticmethod
    def _set_selected(btn: QPushButton, selected: bool):
        btn.setProperty("selected", "true" if selected else "false")
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _build_ui(self):
        # 1. Posição
        card, row = self._card()
        row.addLayout(self._info("weather_pos_title", "weather_pos_sub", 14), stretch=1)
        self.pos_picker = PositionPicker(current_pos="tr", theme=self._theme, parent=card)
        self.pos_picker.position_changed.connect(self.bridge.move_weather_to_screen_position)
        row.addWidget(self.pos_picker)
        self.content_layout.addWidget(card)

        # 1b. Tamanho (os mesmos tamanhos do menu; arrastar o canto dá qualquer valor entre eles)
        card, row = self._card()
        row.addLayout(self._info("weather_size_title", "weather_size_sub", 14), stretch=1)
        self._size_group = ChipGroup([(v, f"{int(round(v * 100))}%") for v in SCALES], self.controller.set_scale,
                                     self._theme, parent=card)
        row.addWidget(self._size_group)
        self.content_layout.addWidget(card)
        self.controller.scale_changed.connect(lambda _s: self._sync_size())
        self._sync_size()

        # 2. Estilo (uma skin por fonte)
        card, col = self._card(vertical=True)
        col.setContentsMargins(22, 20, 22, 22)
        col.addLayout(self._info("weather_style_title", "weather_style_sub", 14.5))
        col.addSpacing(18)
        self._skin_grid = ResponsiveCardGrid(min_card_width=150, spacing=16, parent=card)
        self._skin_cards: dict = {}
        for spec in init_weather_skin_specs():
            pc = PreviewCard(spec=spec, theme=self._theme, is_selected=spec.id == self.controller.active_skin_name,
                             parent=self._skin_grid)
            pc.clicked.connect(self.bridge.set_weather_skin)
            self._skin_cards[spec.id] = pc
            self._skin_grid.add_card(pc)
        col.addWidget(self._skin_grid)
        self.content_layout.addWidget(card)

        # 3. Cidades (até 5, na ordem do cartão; a roda do mouse troca entre elas)
        # Tudo o que aparece/some aqui fica num Fold que abre/fecha junto com as linhas da lista (sem o cartão
        # encolher e crescer de novo). O espaço entre os itens fica dentro de cada Fold, para fechar junto.
        card, col = self._card(vertical=True)
        self.cities_card = card
        col.setSpacing(0)
        head = QHBoxLayout()
        head.addLayout(self._info("weather_cities_title", "weather_cities_sub", 14), stretch=1)
        self.lbl_count = QLabel()
        self.lbl_count.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px; font-weight: 600;")
        head.addWidget(self.lbl_count, alignment=Qt.AlignmentFlag.AlignTop)
        col.addLayout(head)
        self.lbl_empty = QLabel(t("weather_cities_empty"))
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        self._subs.append(self.lbl_empty)
        self.fold_empty = Fold(self.lbl_empty, gap=CITY_GAP)
        col.addWidget(self.fold_empty)
        col.addSpacing(CITY_GAP)
        self.city_list = CityList(self._theme, card)
        self.city_list.moved.connect(self.service.move_city)
        self.city_list.removed.connect(self.service.remove_city)
        col.addWidget(self.city_list)
        self.btn_add_auto = self._chip(t("weather_add_my_location"), self._on_add_auto)
        self.fold_auto = Fold(self.btn_add_auto, gap=CITY_GAP, align=Qt.AlignmentFlag.AlignLeft)
        col.addWidget(self.fold_auto)
        col.addSpacing(CITY_GAP)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchInput")
        self.search_box.textChanged.connect(lambda _txt: self._search_timer.start())
        self.search_box.returnPressed.connect(self._run_search)
        col.addWidget(self.search_box)
        self.lbl_search_status = QLabel()
        self.lbl_search_status.setWordWrap(True)
        self.lbl_search_status.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        self._subs.append(self.lbl_search_status)
        self.fold_status = Fold(self.lbl_search_status, gap=CITY_GAP)
        self.fold_status.set_open(False)
        col.addWidget(self.fold_status)
        self.results_box = QWidget()
        self.results_layout = QVBoxLayout(self.results_box)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(6)
        self.fold_results = Fold(self.results_box, gap=CITY_GAP)
        self.fold_results.set_open(False)
        col.addWidget(self.fold_results)
        self.content_layout.addWidget(card)
        self._last_query_places: list = []
        self._refresh_cities()

        # 4. Unidade
        card, row = self._card()
        row.addLayout(self._info("weather_units_title", "weather_units_sub", 14), stretch=1)
        self._unit_group = ChipGroup([("c", "°C"), ("f", "°F")], self._on_unit, self._theme, parent=card)
        row.addWidget(self._unit_group)
        self._sync_units(animated=False)
        self.content_layout.addWidget(card)

        # 5. Comportamento
        card, col = self._card(vertical=True)
        col.setSpacing(12)
        self.sw_remember = self._switch_row(col, "weather_opt_remember_title", "weather_opt_remember_sub",
                                            bool(config_manager.get_weather("remember_position", False)),
                                            self.controller.set_remember_position)
        self.controller.remember_position_changed.connect(self._sync_remember)
        col.addWidget(self._divider())
        self.sw_desktop = self._switch_row(col, "weather_opt_desktop_title", "weather_opt_desktop_sub",
                                           self.controller.skin.is_desktop_mode(), self.controller.set_desktop_mode)
        self.controller.desktop_mode_changed.connect(self._sync_desktop)
        col.addWidget(self._divider())
        self.sw_startup = self._switch_row(col, "weather_opt_startup_title", "weather_opt_startup_sub",
                                           bool(config_manager.get_weather("show_on_startup", False)),
                                           lambda v: config_manager.set_weather("show_on_startup", bool(v)))
        col.addWidget(self._divider())
        row = QHBoxLayout()
        row.addLayout(self._info("weather_opt_show_title", "weather_opt_show_sub"), stretch=1)
        self.btn_show = self._chip(t("weather_opt_show_btn"), self._on_show_clicked)
        row.addWidget(self.btn_show)
        col.addLayout(row)
        self.content_layout.addWidget(card)

        # 6. Atalho
        card, row = self._card()
        row.addLayout(self._info("weather_hotkey_title", "weather_hotkey_sub", 14), stretch=1)
        self.hk_picker = ShortcutPicker(
            current_shortcut=config_manager.get_weather("hotkey", "Win+Alt+W"),
            default_shortcut="Win+Alt+W",
            theme=self._theme,
            parent=card,
        )
        self.hk_picker.shortcut_changed.connect(self.bridge.update_weather_hotkey)
        row.addWidget(self.hk_picker)
        self.content_layout.addWidget(card)

        self.content_layout.addStretch()

    def _switch_row(self, col: QVBoxLayout, title_key: str, sub_key: str, checked: bool, on_toggle) -> PillSwitch:
        row = QHBoxLayout()
        row.addLayout(self._info(title_key, sub_key), stretch=1)
        sw = PillSwitch(checked=checked, theme=self._theme)
        sw.toggled.connect(on_toggle)
        row.addWidget(sw)
        col.addLayout(row)
        return sw

    # --- Cidades ---

    def _refresh_cities(self):
        """Lista, contador, botão de "minha localização" e o estado da busca (desligada com 5 cidades). A lista só
        anima o que mudou: a cidade nova entra, a removida sai."""
        cities = self.service.cities()
        items = []
        for c in cities:
            if c.get("kind") == "auto":
                auto_name = self.service.city_name(c)
                detail = t("weather_my_location_detail") + (f" · {auto_name}" if auto_name else "")
                items.append((city_key(c), t("weather_my_location"), detail))
            else:
                items.append((city_key(c), str(c.get("name", "")), str(c.get("detail", ""))))
        self.city_list.set_items(items)
        # Os vizinhos abrem/fecham no ritmo da linha que entra/sai (na hora se nada anima)
        follow = self.city_list.follow_current_change()
        self.fold_empty.set_open(not cities, follow)
        self.lbl_count.setText(t("weather_cities_count", n=len(cities), max=MAX_CITIES))
        full = not self.service.can_add()
        self.fold_auto.set_open(not self.service.has_auto() and not full, follow)
        self.search_box.setEnabled(not full)
        self.search_box.setPlaceholderText(t("weather_cities_full") if full else t("weather_loc_search_placeholder"))
        if full:
            self.search_box.blockSignals(True)
            self.search_box.clear()
            self.search_box.blockSignals(False)
            self._close_results(follow)
            self.fold_status.set_open(False, follow)
        elif self._last_query_places:
            self._show_results(self._last_query_places)   # "já adicionada" acompanha a lista

    def _on_add_auto(self):
        if self.service.add_auto() == "ok":
            self._refresh_cities()

    def _run_search(self):
        self._search_timer.stop()
        query = self.search_box.text().strip()
        if len(query) < 2:
            self._last_query_places = []
            self._clear_results()
            self.fold_status.set_open(False)
            return
        self.lbl_search_status.setText(t("weather_loc_searching"))
        self.fold_status.set_open(True)
        self.service.search(query, i18n.current_language)

    def _on_search_results(self, query: str, places: list):
        if query != self.search_box.text().strip():
            return   # resposta de uma busca antiga
        self._last_query_places = list(places[:MAX_RESULTS])
        if not places:
            self._clear_results()
            self.lbl_search_status.setText(t("weather_loc_no_results"))
            self.fold_status.set_open(len(query) >= 2)
            return
        self.fold_status.set_open(False)
        self._show_results(self._last_query_places)

    def _show_results(self, places: list):
        self._drop_result_buttons()
        for place in places:
            text = f"{place.name} — {place.detail}" if place.detail else place.name
            already = self.service.contains_place(place)
            if already:
                text += f"  ·  {t('weather_city_already')}"
            btn = self._chip(text, lambda checked=False, pl=place: self._on_place_chosen(pl))
            btn.setStyleSheet("text-align: left; padding-left: 12px;")
            btn.setEnabled(not already)
            self.results_layout.addWidget(btn)
            self._result_buttons.append(btn)
        self.fold_results.set_open(bool(self._result_buttons))

    def _clear_results(self):
        self._close_results(None)

    def _close_results(self, follow=None):
        """Fecha a lista de resultados (acompanhando a linha nova, se houver) e só então apaga os botões."""
        self.fold_results.set_open(False, follow, on_done=self._drop_result_buttons)

    def _drop_result_buttons(self):
        # Esconde e apaga no lugar. Não usar setParent(None): o botão recém-clicado (ainda no meio do clique) virava
        # uma janela solta por um instante, fora do Hub, e a tela "pulava".
        for btn in self._result_buttons:
            btn.hide()
            self.results_layout.removeWidget(btn)
            btn.deleteLater()
        self._result_buttons = []

    def _on_place_chosen(self, place):
        if self.service.add_place(place) != "ok":
            return
        # A lista já recebeu a linha nova (cities_changed): os resultados fecham enquanto ela abre
        self._last_query_places = []
        self._refresh_cities()
        follow = self.city_list.follow_current_change()
        self._close_results(follow)
        self.fold_status.set_open(False, follow)
        self.search_box.blockSignals(True)
        self.search_box.clear()
        self.search_box.blockSignals(False)

    # --- Unidade, skin, comportamento ---

    def _on_unit(self, unit: str):
        self.controller.set_units(unit)
        self._sync_units()

    def _sync_units(self, animated: bool = True):
        self._unit_group.set_selected(self.controller.units(), animated=animated)

    def _sync_size(self, animated: bool = True):
        scale = self.controller.skin.scale()
        # tamanho arrastado: nenhum chip marcado (a pílula some)
        match = next((v for v in SCALES if abs(scale - v) < 0.01), None)
        self._size_group.set_selected(match, animated=animated)

    def _sync_desktop(self, enabled: bool):
        if self.sw_desktop.isChecked() != enabled:
            self.sw_desktop.blockSignals(True)
            self.sw_desktop.set_checked(enabled, animated=False)
            self.sw_desktop.blockSignals(False)

    def _sync_skin_selection(self, skin_id: str):
        for key, card in self._skin_cards.items():
            card.set_selected(key == skin_id)

    def _sync_remember(self, enabled: bool):
        if self.sw_remember.isChecked() != enabled:
            self.sw_remember.blockSignals(True)
            self.sw_remember.set_checked(enabled, animated=False)
            self.sw_remember.blockSignals(False)

    def _on_show_clicked(self):
        self.bridge.set_weather_enabled(True)
        self.controller.skin.raise_()
        self.controller.skin.activateWindow()

    # --- Hub ---

    def _on_cities_changed(self):
        if self.city_list._drag_row is None:   # no meio de um arraste a lista já está na ordem nova
            self._refresh_cities()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_skin_selection(self.controller.active_skin_name)
        self._sync_units()
        self._refresh_cities()
        self._sync_remember(bool(config_manager.get_weather("remember_position", False)))

    def retranslate_ui(self):
        self.set_header(t("weather_title"), t("weather_subtitle"))
        for label, key in self._texts:
            label.setText(t(key))
        self.btn_add_auto.setText(t("weather_add_my_location"))
        self.btn_show.setText(t("weather_opt_show_btn"))
        self.lbl_empty.setText(t("weather_cities_empty"))
        self._refresh_cities()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        for sub in self._subs:
            sub.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        for card in self._skin_cards.values():
            card.set_theme(theme)
        self.city_list.set_theme(theme)
        self.lbl_count.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px; font-weight: 600;")
        for w in (self._size_group, self._unit_group, self.pos_picker, self.hk_picker, self.sw_remember, self.sw_desktop, self.sw_startup):
            if hasattr(w, "set_theme"):
                w.set_theme(theme)

    def focus_cities(self):
        """Rola a página diretamente para a seção de cidades e foca a busca (menu de contexto do Weather Widget)."""
        if hasattr(self, "cities_card"):
            self.scroll_to_widget(self.cities_card, focus_widget=self.search_box)
