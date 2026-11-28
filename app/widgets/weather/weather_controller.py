"""
WeatherWidgetController - liga o WeatherService (dados) ao WeatherCard (janela).

- Converte a previsão em dias para o cartão (°C/°F, nomes no idioma do app, condição de cada dia).
- Mostrar/esconder com o mesmo surgir/sumir dos outros widgets (AnimatedVisibilityMixin).
- Consulta a rede só com o widget na tela: ao aparecer (se a previsão salva estiver velha) e a cada 30 min.
- Sem dados: o cartão mostra "Carregando", "Sem conexão" ou "Escolha uma cidade"; com uma previsão salva, ela
  continua na tela mesmo se a atualização falhar.
"""

import datetime
import time
from typing import Optional

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.i18n import i18n, t
from app.core.widget_animator import AnimatedVisibilityMixin, animations_enabled
from app.services.weather_service import (
    FAIL_NO_LOCATION, FORECAST_DAYS, REFRESH_S, WeatherReport, WeatherService, city_key, to_unit,
)
from app.widgets.weather import conditions as cond
from app.widgets.weather import font_skins
from app.widgets.weather.card_state import MSG_LOADING, MSG_NO_LOCATION, MSG_OFFLINE, PAST, DayView
from app.ui_components.floating_card import MAX_SCALE, MIN_SCALE, is_rect_on_screen, place_card_default, restore_card_position
from app.widgets.weather.weather_card import WeatherCard

SCREEN_MARGIN = 24


def weekday_labels() -> tuple:
    """(curtos, completos) de segunda a domingo no idioma atual."""
    return ([t(f"weather_wd_short_{i}") for i in range(7)], [t(f"weather_wd_{i}") for i in range(7)])


def condition_names() -> dict:
    return {key: t(f"weather_cond_{cond.name_key(key)}") for key in cond.ALL_CONDITIONS}


def build_days(report: WeatherReport, unit: str) -> list:
    """
    Dias para o cartão: hoje usa a temperatura e a condição de agora; os seguintes, a máxima (como os apps de
    previsão mostram; a média ficava bem abaixo do que se espera ver) e a condição que domina o dia.
    """
    short, full = weekday_labels()
    days = []
    for i, d in enumerate(report.days[:FORECAST_DAYS]):
        try:
            wd = datetime.date.fromisoformat(d.date).weekday()
        except ValueError:
            wd = (datetime.date.today().weekday() + i) % 7
        if i == 0:
            condition = cond.condition_from_wmo(report.current_code, report.is_day)
            temp = report.current_temp
        else:
            condition = cond.condition_from_wmo(d.code, True)
            temp = d.t_max
        days.append(DayView(short[wd], full[wd], condition, to_unit(temp, unit),
                            to_unit(d.t_max, unit), to_unit(d.t_min, unit)))
    return days


def build_hours(report: WeatherReport, unit: str) -> list:
    """
    Horas do dia para a skin Nothing Hourly: Agora + 4 horários espaçados de 3 em 3 horas (+3h, +6h, +9h, +12h).
    Mantém a máxima/mínima de hoje; se o cache antigo ainda não trouxe `hours`, sintetiza os horários sem quebrar.
    """
    now_lbl = t("weather_now")
    today_hi = to_unit(report.days[0].t_max, unit) if report.days else to_unit(report.current_temp, unit)
    today_lo = to_unit(report.days[0].t_min, unit) if report.days else to_unit(report.current_temp, unit)
    now_cond = cond.condition_from_wmo(report.current_code, report.is_day)
    slots = [DayView(now_lbl, now_lbl, now_cond, to_unit(report.current_temp, unit), today_hi, today_lo)]

    start_idx = -1
    if report.hours:
        ref = report.current_time[:13] if len(report.current_time) >= 13 else datetime.datetime.now().strftime("%Y-%m-%dT%H")
        for idx, h in enumerate(report.hours):
            if h.time[:13] >= ref:
                start_idx = idx
                break
        if start_idx < 0:
            start_idx = 0

    base_hour = datetime.datetime.now().hour
    if len(report.current_time) >= 13:
        try:
            base_hour = int(report.current_time[11:13])
        except ValueError:
            pass

    for step in (3, 6, 9, 12):
        idx = start_idx + step if start_idx >= 0 else -1
        if 0 <= idx < len(report.hours):
            h = report.hours[idx]
            hh = h.time[11:13]
            slots.append(DayView(
                f"{hh}h", f"{hh}:00",
                cond.condition_from_wmo(h.code, h.is_day),
                to_unit(h.temp, unit), today_hi, today_lo,
            ))
        else:
            hh = (base_hour + step) % 24
            is_day = 6 <= hh < 19
            slots.append(DayView(
                f"{hh:02d}h", f"{hh:02d}:00",
                cond.condition_from_wmo(report.current_code, is_day),
                to_unit(report.current_temp, unit), today_hi, today_lo,
            ))
    return slots


def placeholder_days() -> list:
    """Abas sem dados: só os nomes dos próximos 5 dias (o cartão desenha sem ícones e apagadas)."""
    short, full = weekday_labels()
    today = datetime.date.today().weekday()
    return [DayView(short[(today + i) % 7], full[(today + i) % 7], cond.CLOUDY, 0, 0, 0) for i in range(5)]


def placeholder_hours() -> list:
    """Abas sem dados para a skin Nothing Hourly: Agora + próximos 4 horários de 3 em 3h."""
    now_lbl = t("weather_now")
    base_hour = datetime.datetime.now().hour
    slots = [DayView(now_lbl, now_lbl, cond.CLOUDY, 0, 0, 0)]
    for step in (3, 6, 9, 12):
        hh = (base_hour + step) % 24
        slots.append(DayView(f"{hh:02d}h", f"{hh:02d}:00", cond.CLOUDY, 0, 0, 0))
    return slots


class WeatherWidgetController(AnimatedVisibilityMixin, QObject):
    status_changed = Signal(bool)
    configure_requested = Signal()   # "Configurar" no menu do widget
    skin_changed = Signal(str)
    scale_changed = Signal(float)
    desktop_mode_changed = Signal(bool)
    remember_position_changed = Signal(bool)
    units_changed = Signal(str)
    forecast_mode_changed = Signal(str)

    manage_cities_requested = Signal()   # "Gerenciar cidades…" no menu do cartão

    def __init__(self, service: Optional[WeatherService] = None):
        super().__init__()
        self.service = service or WeatherService(self)
        self.service.reports_ready.connect(self._on_reports)
        self.service.failed.connect(self._on_failed)
        self.service.busy_changed.connect(self._on_busy_changed)
        self.service.cities_changed.connect(self._on_cities_changed)

        self.skin = WeatherCard(scale=float(config_manager.get_weather("scale", 1.0) or 1.0),
                                desktop_mode=bool(config_manager.get_weather("desktop_mode", False)))
        self.skin.scale_auto = bool(config_manager.get_weather("scale_auto", False))
        if self.skin.scale_auto:
            self.skin.set_scale(self.skin.auto_scale_target())
        self.skin.desktop_mode_changed.connect(self.set_desktop_mode)
        self.skin.remember_position_changed.connect(self.set_remember_position)
        self.skin.close_requested.connect(self.on_skin_closed)
        self.skin.configure_requested.connect(self.configure_requested.emit)
        self.skin.refresh_requested.connect(lambda: self.service.refresh(force=True))
        self.skin.units_changed.connect(self.set_units)
        self.skin.forecast_mode_changed.connect(self.set_forecast_mode)
        self.skin.scale_changed.connect(self.set_scale)
        self.skin.day_selected.connect(self.select_day)
        self.skin.city_step.connect(self.step_city)
        self.skin.city_selected.connect(self.select_city)
        self.skin.manage_cities_requested.connect(self.manage_cities_requested.emit)

        self.active_skin_name = font_skins.DEFAULT_SKIN
        self.set_skin(config_manager.get_weather("skin", font_skins.DEFAULT_SKIN), save=False)

        self._reports: dict = self.service.cached_reports()   # chave da cidade -> WeatherReport
        self._failure: Optional[str] = None
        self._apply_report(animate=False)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_S * 1000)
        self._refresh_timer.timeout.connect(lambda: self.service.refresh())

        i18n.language_changed.connect(lambda _lang: self._apply_report(animate=False))

    # --- Dados -> cartão ---

    def units(self) -> str:
        return "f" if config_manager.get_weather("units", "c") == "f" else "c"

    def forecast_mode(self) -> str:
        return "hourly" if config_manager.get_weather("forecast_mode", "daily") == "hourly" else "daily"

    def city_display_names(self) -> list:
        """Nomes da lista na ordem do cartão; o automático ainda sem local aparece como "Minha localização"."""
        return [self.service.city_name(c) or t("weather_my_location") for c in self.service.cities()]

    @property
    def _report(self) -> Optional[WeatherReport]:
        """Previsão da cidade que está no cartão."""
        entry = self.service.current_city()
        return self._reports.get(city_key(entry)) if entry else None

    def _apply_report(self, animate: bool = True, direction: int = 1):
        state = self.skin.state
        now = self.skin.now() if animate and state.animated else PAST
        names = self.city_display_names()
        index = self.service.current_index()
        self.skin.city_names = names
        state.set_city(index, len(names), now)
        report = self._report
        hourly_mode = self.forecast_mode() == "hourly"
        if report is not None:
            place = names[index] if names else report.place
            slots = build_hours(report, self.units()) if hourly_mode else build_days(report, self.units())
            state.set_days(place, slots, condition_names(), now,
                           animate=now != PAST, direction=direction)
        else:
            state.days = placeholder_hours() if hourly_mode else placeholder_days()
            state.set_place(names[index] if names else "", now, direction)
            if not names or self._failure == FAIL_NO_LOCATION:
                state.set_message(MSG_NO_LOCATION, t("weather_no_location_detail"))
            elif self._failure:
                state.set_message(MSG_OFFLINE, t("weather_offline_detail"))
            else:
                state.set_message(MSG_LOADING)
        self.skin.kick()

    def _on_reports(self, reports: dict):
        self._reports.update(reports)
        keys = {city_key(c) for c in self.service.cities()}
        self._reports = {k: r for k, r in self._reports.items() if k in keys}
        self._failure = None
        self._apply_report(animate=True)

    def _on_failed(self, reason: str):
        self._failure = reason
        if self._report is None:   # com previsão salva, ela continua na tela mesmo sem rede
            self._apply_report(animate=False)

    def _on_busy_changed(self, busy: bool):
        if busy and self._report is None:
            self._failure = None
            self._apply_report(animate=False)

    def _on_cities_changed(self):
        keys = {city_key(c) for c in self.service.cities()}
        self._reports = {k: r for k, r in self.service.cached_reports().items() if k in keys}
        self._apply_report(animate=True)

    # --- Cidades ---

    def step_city(self, delta: int):
        """Próxima/anterior (roda, ↑/↓). A lista dá a volta; o dia escolhido continua o mesmo."""
        n = self.service.city_count()
        if n < 2:
            return
        self.service.set_current_index((self.service.current_index() + delta) % n)
        self._apply_report(animate=True, direction=1 if delta > 0 else -1)

    def select_city(self, index: int):
        current = self.service.current_index()
        if index == current or not 0 <= index < self.service.city_count():
            return
        self.service.set_current_index(index)
        self._apply_report(animate=True, direction=1 if index > current else -1)

    # --- Ações do cartão ---

    def select_day(self, index: int):
        state = self.skin.state
        now = self.skin.now() if state.animated else PAST
        if state.select(index, condition_names(), now):
            self.skin.kick()

    def set_units(self, unit: str):
        u = "f" if unit == "f" else "c"
        config_manager.set_weather("units", u)
        self._apply_report(animate=True)
        self.units_changed.emit(u)

    def set_forecast_mode(self, mode: str):
        m = "hourly" if mode == "hourly" else "daily"
        if m == self.forecast_mode():
            return
        config_manager.set_weather("forecast_mode", m)
        self._apply_report(animate=True)
        if m == "hourly" and self.is_shown() and self._report is not None and not self._report.hours:
            self.service.refresh(force=True)
        self.forecast_mode_changed.emit(m)

    def set_scale(self, scale: float | None):
        """Tamanho do cartão (menu, Hub ou arraste do canto), com movimento; None = automático (segue a tela)."""
        auto = scale is None
        config_manager.set_weather("scale_auto", auto)
        self.skin.scale_auto = auto
        target = self.skin.auto_scale_target() if auto else max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        self.skin.animate_scale_to(target)
        config_manager.set_weather("scale", round(target, 3))
        self.scale_changed.emit(target)

    def apply_scale_live(self, scale: float):
        """Arraste do controle de tamanho no Hub: aplica na hora (o ponteiro já é o movimento), sem gravar."""
        self.skin.stop_scale_animation()
        self.skin.set_scale(scale)

    def is_scale_auto(self) -> bool:
        return bool(self.skin.scale_auto)

    def set_desktop_mode(self, enabled: bool):
        """Fixar na área de trabalho: o cartão fica no nível do desktop e qualquer janela o cobre."""
        config_manager.set_weather("desktop_mode", bool(enabled))
        self.skin.set_desktop_mode(enabled)
        self.desktop_mode_changed.emit(bool(enabled))

    def set_remember_position(self, enabled: bool):
        enabled = bool(enabled)
        config_manager.set_weather("remember_position", enabled)
        if enabled:
            origin = self.skin.card_origin()
            config_manager.set_weather("position", [origin.x(), origin.y()])
        self.remember_position_changed.emit(enabled)

    def set_skin(self, skin_id: str, save: bool = True):
        skin = font_skins.skin_by_id(skin_id)
        changed = (skin.id != self.active_skin_name) or (skin.family != self.skin.state.font_family)
        if changed:
            self.skin.begin_skin_switch()   # efeito escolhido no Hub (app/core/skin_switch.py)
        self.active_skin_name = skin.id
        self.skin.state.skin_id = skin.id
        self.skin.state.font_family = skin.family
        if save:
            config_manager.set_weather("skin", skin.id)
        self.skin.update()
        self.skin_changed.emit(skin.id)

    @staticmethod
    def available_skins() -> dict:
        return {s.id: s for s in font_skins.discover()}

    # --- Posição ---

    def restore_or_place(self):
        restore_card_position(
            self.skin,
            bool(config_manager.get_weather("remember_position", False)),
            config_manager.get_weather("position", None),
            margin=SCREEN_MARGIN,
        )

    def place_default(self):
        """Canto superior direito da tela principal."""
        place_card_default(self.skin, margin=SCREEN_MARGIN)

    @staticmethod
    def _on_screen(x: int, y: int, w: int, h: int) -> bool:
        return is_rect_on_screen(x, y, w, h)

    # --- Ciclo de vida ---

    def start(self):
        self.show()

    def show(self):
        self.skin.forget_show_desktop()   # aberto pelo usuário: deixa de ser "escondido pelo Win+D"
        if not self.skin.animator.is_animating():
            self.restore_or_place()
        self.skin.state.animated = animations_enabled()
        if not self.skin.isVisible():   # reaberto: volta para hoje (na cidade vista por último)
            self.skin.state.selected = 0
            self.skin.state.pill_from = 0.0
            self._apply_report(animate=False)
        self._animate_show()
        self._refresh_timer.start()
        self.service.refresh()   # só consulta se a previsão salva estiver velha
        self.status_changed.emit(True)

    def hide(self):
        self._refresh_timer.stop()
        self.skin.forget_show_desktop()
        self._animate_hide()
        self.status_changed.emit(False)

    def on_skin_closed(self):
        self.hide()
        config_manager.set_weather("enabled", False)

    def report_age_s(self) -> Optional[float]:
        return None if self._report is None else time.time() - self._report.fetched_at
