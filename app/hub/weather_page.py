"""
Página do Weather Widget no Hub: posição, tamanho, estilo (fonte), cidades (até 5), unidade, comportamento e
atalho. Separada de pages.py, que já passa do tamanho de um arquivo legível.
"""

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.core.config_manager import config_manager
from app.core.i18n import i18n, t
from app.core.preview_card import PreviewCard
from app.hub.components.city_list import CityList
from app.hub.components.collapsible_section import skin_and_theme_block
from app.hub.components.fold import Fold
from app.hub.components.help_badge import HelpBadge
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.components.responsive_grid import ResponsiveCardGrid
from app.hub.components.shortcut_picker import ShortcutPicker
from app.hub.components.scale_card import ScaleCard
from app.hub.components.tab_pill import ChipGroup
from app.hub.components.theme_gallery import ThemeGalleryCard
from app.core.screen_metrics import SCALE_PCT_MAX, SCALE_PCT_MIN
from app.hub.pages import BaseHubPage
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.widgets.weather import font_skins, init_weather_skin_specs
from app.widgets.weather.theme import loader as weather_theme_loader
from app.widgets.weather.theme_specs import make_theme_spec as make_weather_theme_spec
from app.services.weather_service import MAX_CITIES, city_key

SEARCH_DEBOUNCE_MS = 450
MAX_RESULTS = 6
CITY_GAP = 10   # espaço entre os itens do cartão de cidades

_SOURCE_OPTIONS = (
    ("auto", "weather_model_auto", "weather_model_auto_origin"),
    ("icon", None, "weather_model_icon_origin"),
    ("ecmwf", None, "weather_model_ecmwf_origin"),
    ("gfs", None, "weather_model_gfs_origin"),
)


class _SourceOptionButton(QPushButton):
    """Botão de 2 linhas (nome do modelo + origem) dentro da bandeja segmentada."""

    def __init__(self, key: str, title_key: str | None, origin_key: str, theme: HubTheme, parent=None):
        super().__init__(parent)
        self.key = key
        self._title_key = title_key
        self._origin_key = origin_key
        self._theme = theme
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(48)

        col = QVBoxLayout(self)
        col.setContentsMargins(8, 7, 8, 7)
        col.setSpacing(2)
        self._lbl_name = QLabel(t(title_key) if title_key else key.upper(), self)
        self._lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._lbl_origin = QLabel(t(origin_key), self)
        self._lbl_origin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_origin.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        col.addWidget(self._lbl_name)
        col.addWidget(self._lbl_origin)
        self._apply_style()

    def sizeHint(self) -> QSize:
        lay = self.layout()
        sh = lay.sizeHint() if lay is not None else super().sizeHint()
        return QSize(max(80, sh.width()), max(48, sh.height()))

    def set_selected(self, selected: bool):
        if self._selected != bool(selected):
            self._selected = bool(selected)
            self._apply_style()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._apply_style()

    def retranslate_ui(self):
        if self._title_key:
            self._lbl_name.setText(t(self._title_key))
        self._lbl_origin.setText(t(self._origin_key))

    def _apply_style(self):
        t_ = self._theme
        if self._selected:
            bg = t_.panel2 if t_.is_dark else t_.panel
            border = t_.line
            name_col = t_.text
            origin_col = t_.accent
        else:
            bg = "transparent"
            border = "transparent"
            name_col = t_.body
            origin_col = t_.mute
        hover_bg = t_.hover if not self._selected else bg
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; border: 1px solid {border}; border-radius: 6px; padding: 0px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; }}"
        )
        self._lbl_name.setStyleSheet(f"font-size: 12.5px; font-weight: 600; color: {name_col}; background: transparent; border: none;")
        self._lbl_origin.setStyleSheet(f"font-size: 10.5px; font-weight: 500; color: {origin_col}; background: transparent; border: none;")


class _ForecastSourceTray(QFrame):
    """Bandeja segmentada de 4 colunas com nome do modelo e origem (Automático, ICON, ECMWF, GFS)."""

    def __init__(self, on_pick, theme: HubTheme, parent=None):
        super().__init__(parent)
        self.setObjectName("SourceTray")
        self._theme = theme
        self._buttons: dict[str, _SourceOptionButton] = {}

        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(4)
        for key, title_key, origin_key in _SOURCE_OPTIONS:
            btn = _SourceOptionButton(key, title_key, origin_key, theme, self)
            btn.clicked.connect(lambda _c=False, k=key: on_pick(k))
            self._buttons[key] = btn
            row.addWidget(btn, stretch=1)
        self._apply_style()

    def set_selected(self, key: str):
        for k, btn in self._buttons.items():
            btn.set_selected(k == key)

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._apply_style()
        for btn in self._buttons.values():
            btn.set_theme(theme)

    def retranslate_ui(self):
        for btn in self._buttons.values():
            btn.retranslate_ui()

    def _apply_style(self):
        t_ = self._theme
        self.setStyleSheet(
            f"QFrame#SourceTray {{ background-color: {t_.bg}; border: 1px solid {t_.line}; border-radius: 9px; }}"
        )


class WeatherPage(BaseHubPage):
    def __init__(self, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(title=t("weather_title"), subtitle=t("weather_subtitle"), theme=theme, parent=parent)
        self.bridge = get_service_bridge()
        self.controller = self.bridge.weather_controller
        self.service = self.controller.service
        self._texts: list = []      # (QLabel, chave i18n)
        self._subs: list = []       # legendas cinzas (a cor muda com o tema)
        self._help_badges: list = []
        self._bento_cells: list[QFrame] = []
        self._bento_titles: list[tuple[QLabel, str]] = []
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

    def _info(self, title_key: str, sub_key: str, title_px: float = 13.5, help_key: str | None = None) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel(t(title_key))
        title.setStyleSheet(f"font-size: {title_px}px; font-weight: 600;")
        if help_key:
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(6)
            title_row.addWidget(title)
            badge = HelpBadge(t(help_key), theme=self._theme)
            title_row.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)
            title_row.addStretch()
            box.addLayout(title_row)
            self._help_badges.append((badge, help_key))
        else:
            box.addWidget(title)
        sub_txt = t(sub_key)
        sub = QLabel(sub_txt)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        if not bool(sub_txt):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
            sub.hide()
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
        pos_info = self._info("weather_pos_title", "weather_pos_sub", 14)
        row.addLayout(pos_info, stretch=1)
        row.setAlignment(pos_info, Qt.AlignmentFlag.AlignVCenter)
        self.pos_picker = PositionPicker(current_pos="tr", theme=self._theme, parent=card)
        self.pos_picker.position_changed.connect(self.bridge.move_weather_to_screen_position)
        row.addWidget(self.pos_picker)
        self.content_layout.addWidget(card)

        # 2. Estilo (uma skin por fonte)
        card, col = self._card(vertical=True)
        col.setContentsMargins(22, 20, 22, 22)
        col.addLayout(self._info("weather_style_title", "weather_style_sub", 14.5, help_key="weather_style_help"))
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
        self.theme_picker = ThemeGalleryCard(
            weather_theme_loader,
            "weather",
            make_weather_theme_spec,
            self.bridge.apply_weather_theme,
            self._theme,
            appliers=self.bridge.theme_appliers(),
            parent=self,
            subtitle_key="theme_picker_sub_weather",
            default_title_key="theme_default_timer",
        )
        skin_block, self.theme_section = skin_and_theme_block(
            card,
            self.theme_picker,
            self.content_layout.spacing(),
            font_skins.is_nothing_skin(self.controller.active_skin_name),
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

        # 3. Cidades (até 5, na ordem do cartão; a roda do mouse troca entre elas)
        # Tudo o que aparece/some aqui fica num Fold que abre/fecha junto com as linhas da lista (sem o cartão
        # encolher e crescer de novo). O espaço entre os itens fica dentro de cada Fold, para fechar junto.
        card, col = self._card(vertical=True)
        self.cities_card = card
        col.setSpacing(0)
        head = QHBoxLayout()
        head.addLayout(self._info("weather_cities_title", "weather_cities_sub", 14, help_key="weather_cities_help"), stretch=1)
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

        # 3b. Previsão (Bento 2+1: Exibição, Temperatura, Fonte dos dados)
        self.content_layout.addWidget(self._build_forecast_bento())
        self.controller.forecast_mode_changed.connect(lambda _m: self._sync_forecast_mode())
        self.controller.units_changed.connect(lambda _u: self._sync_units())
        self._sync_units(animated=False)
        self._sync_model(animated=False)

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
        show_info = self._info("weather_opt_show_title", "weather_opt_show_sub")
        row.addLayout(show_info, stretch=1)
        row.setAlignment(show_info, Qt.AlignmentFlag.AlignVCenter)
        self.btn_show = self._chip(t("weather_opt_show_btn"), self._on_show_clicked)
        row.addWidget(self.btn_show, alignment=Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(row)
        self.content_layout.addWidget(card)

        # 6. Atalho
        card, row = self._card()
        hk_info = self._info("weather_hotkey_title", "weather_hotkey_sub", 14)
        row.addLayout(hk_info, stretch=1)
        row.setAlignment(hk_info, Qt.AlignmentFlag.AlignVCenter)
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

    def _bento_cell(self, title_key: str, help_key: str = "") -> tuple[QFrame, QVBoxLayout]:
        cell = QFrame()
        cell.setObjectName("BentoCell")
        col = QVBoxLayout(cell)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(6)
        lbl = QLabel(t(title_key))
        head.addWidget(lbl)
        if help_key:
            badge = HelpBadge(t(help_key), self._theme, cell)
            self._help_badges.append((badge, help_key))
            head.addWidget(badge)
        head.addStretch()
        col.addLayout(head)
        self._bento_cells.append(cell)
        self._bento_titles.append((lbl, title_key))
        return cell, col

    def _build_forecast_bento(self) -> QFrame:
        card, outer = self._card(vertical=True)
        outer.setSpacing(12)
        header = QLabel(t("weather_mode_title"))
        header.setStyleSheet("font-size: 14px; font-weight: 600;")
        self._texts.append((header, "weather_mode_title"))
        outer.addWidget(header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        c_mode, l_mode = self._bento_cell("weather_display_title")
        self._forecast_group = ChipGroup(
            [("daily", t("weather_mode_daily")), ("hourly", t("weather_mode_hourly"))],
            self._on_forecast_mode,
            self._theme,
            selected=self.controller.forecast_mode(),
            parent=c_mode,
            segmented=True,
        )
        l_mode.addWidget(self._forecast_group)
        grid.addWidget(c_mode, 0, 0)

        c_unit, l_unit = self._bento_cell("weather_units_title")
        self._unit_group = ChipGroup(
            [("c", "°C"), ("f", "°F")],
            self._on_unit,
            self._theme,
            parent=c_unit,
            segmented=True,
        )
        l_unit.addWidget(self._unit_group)
        grid.addWidget(c_unit, 0, 1)

        c_src, l_src = self._bento_cell("weather_model_title", help_key="weather_model_help")
        self._model_tray = _ForecastSourceTray(self._on_model, self._theme, parent=c_src)
        l_src.addWidget(self._model_tray)
        grid.addWidget(c_src, 1, 0, 1, 2)

        outer.addLayout(grid)
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

    def _on_forecast_mode(self, mode: str):
        self.controller.set_forecast_mode(mode)

    def _sync_forecast_mode(self, animated: bool = True):
        self._forecast_group.set_selected(self.controller.forecast_mode(), animated=animated)

    def _on_unit(self, unit: str):
        self.controller.set_units(unit)
        self._sync_units()

    def _sync_units(self, animated: bool = True):
        self._unit_group.set_selected(self.controller.units(), animated=animated)

    def _on_model(self, model: str):
        self.service.set_forecast_model(model)
        self._sync_model()

    def _sync_model(self, animated: bool = True):
        self._model_tray.set_selected(self.service.forecast_model())

    def _sync_size(self):
        """Chip Automático e polegar seguem o cartão (inclusive enquanto ele anima até o tamanho novo)."""
        pct = max(SCALE_PCT_MIN, min(SCALE_PCT_MAX, int(round(self.controller.skin.scale() * 100))))
        self.scale_card.set_state(self.controller.is_scale_auto(), pct)

    def _sync_desktop(self, enabled: bool):
        if self.sw_desktop.isChecked() != enabled:
            self.sw_desktop.blockSignals(True)
            self.sw_desktop.set_checked(enabled, animated=False)
            self.sw_desktop.blockSignals(False)

    def _sync_skin_selection(self, skin_id: str):
        for key, card in self._skin_cards.items():
            card.set_selected(key == skin_id)
        if hasattr(self, "theme_section"):
            self.theme_section.set_open(font_skins.is_nothing_skin(skin_id))

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
        self._sync_forecast_mode(animated=False)
        self._sync_units()
        self._sync_model(animated=False)
        self._refresh_cities()
        self._sync_remember(bool(config_manager.get_weather("remember_position", False)))

    def retranslate_ui(self):
        self.set_header(t("weather_title"), t("weather_subtitle"))
        for label, key in self._texts:
            txt = t(key)
            label.setText(txt)
            if label in self._subs:
                label.setVisible(bool(txt))
        for badge, key in self._help_badges:
            badge.set_text(t(key))
        self.scale_card.retranslate()
        if hasattr(self, "theme_picker"):
            self.theme_picker.retranslate_ui()
        self._forecast_group.button("daily").setText(t("weather_mode_daily"))
        self._forecast_group.button("hourly").setText(t("weather_mode_hourly"))
        for lbl, key in self._bento_titles:
            lbl.setText(t(key))
        self._model_tray.retranslate_ui()
        self.btn_add_auto.setText(t("weather_add_my_location"))
        self.btn_show.setText(t("weather_opt_show_btn"))
        self.lbl_empty.setText(t("weather_cities_empty"))
        self._refresh_cities()

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        for sub in self._subs:
            sub.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        for badge, _key in self._help_badges:
            badge.set_theme(theme)
        for card in self._skin_cards.values():
            card.set_theme(theme)
        self.city_list.set_theme(theme)
        self.lbl_count.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px; font-weight: 600;")
        self._style_bento(theme)
        for w in (self.scale_card, self.theme_picker, self._forecast_group, self._unit_group, self._model_tray, self.pos_picker, self.hk_picker, self.sw_remember, self.sw_desktop, self.sw_startup):
            if hasattr(w, "set_theme"):
                w.set_theme(theme)

    def focus_cities(self):
        """Rola a página diretamente para a seção de cidades e foca a busca (menu de contexto do Weather Widget)."""
        if hasattr(self, "cities_card"):
            self.scroll_to_widget(self.cities_card, focus_widget=self.search_box)
