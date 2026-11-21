"""
WeatherService - previsão do tempo para o Weather Widget (zero código de UI).

- Previsão: Open-Meteo (gratuita, sem chave nem conta). Sempre em °C; a conversão para °F é feita na hora de mostrar,
  então trocar a unidade não precisa de outra consulta.
- Local: cidade escolhida no Hub (busca pela geocodificação da Open-Meteo) ou automático pelo IP (ipapi.co).
- Rede numa thread daemon (o app fecha sem esperar uma consulta lenta); os sinais chegam na thread da UI.
- A última previsão fica salva nas configurações: o widget abre já desenhado, mesmo sem internet.
- Nada é consultado enquanto o widget está fechado: quem chama `refresh()` é o controller, ao mostrar o widget e a
  cada `REFRESH_S` enquanto ele está na tela.
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from app.core.config_manager import config_manager
from app.core.version import __version__

logger = logging.getLogger(__name__)

FORECAST_DAYS = 5
REFRESH_S = 30 * 60            # previsão "velha" depois de 30 min
AUTO_PLACE_TTL_S = 12 * 60 * 60   # o local pelo IP é refeito no máximo a cada 12 h
HTTP_TIMEOUT_S = 15   # uma requisição pode trazer até 5 cidades (houve resposta lenta com 8 s)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
IP_LOCATION_URL = "https://ipapi.co/json/"

# Motivos de falha (o widget mostra um texto para cada)
FAIL_OFFLINE = "offline"
FAIL_NO_LOCATION = "no_location"

MAX_CITIES = 5
AUTO = "auto"   # entrada da lista "Minha localização"

# Modelos de previsão disponíveis na Open-Meteo (padrão "auto" = best_match da API)
FORECAST_MODEL_AUTO = "auto"
FORECAST_MODELS: dict[str, Optional[str]] = {
    "auto": None,
    "icon": "icon_seamless",
    "ecmwf": "ecmwf_ifs025",
    "gfs": "gfs_seamless",
}


def normalize_forecast_model(model: object) -> str:
    return model if isinstance(model, str) and model in FORECAST_MODELS else FORECAST_MODEL_AUTO


# --- Modelo ---

@dataclass
class Place:
    name: str
    lat: float
    lon: float
    detail: str = ""   # estado/país, para distinguir cidades homônimas na busca

    @classmethod
    def from_dict(cls, d) -> Optional["Place"]:
        try:
            return cls(str(d["name"]), float(d["lat"]), float(d["lon"]), str(d.get("detail", "")))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class DayForecast:
    date: str          # ISO (aaaa-mm-dd) no fuso do local
    code: int          # WMO
    t_max: float
    t_min: float
    t_mean: float


@dataclass
class HourForecast:
    time: str          # ISO (aaaa-mm-ddTHH:MM) no fuso do local
    code: int          # WMO
    temp: float
    is_day: bool = True


@dataclass
class WeatherReport:
    place: str
    current_temp: float
    current_code: int
    is_day: bool
    days: list = field(default_factory=list)   # list[DayForecast]
    fetched_at: float = 0.0
    hours: list = field(default_factory=list)  # list[HourForecast]
    current_time: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> Optional["WeatherReport"]:
        try:
            days = [DayForecast(str(x["date"]), int(x["code"]), float(x["t_max"]), float(x["t_min"]),
                                float(x["t_mean"])) for x in d["days"]]
            if not days:
                return None
            hours = []
            for x in d.get("hours") or []:
                try:
                    hours.append(HourForecast(
                        str(x["time"]), int(x["code"]), float(x["temp"]), bool(x.get("is_day", True)),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
            return cls(str(d["place"]), float(d["current_temp"]), int(d["current_code"]), bool(d["is_day"]),
                       days, float(d.get("fetched_at", 0.0)), hours, str(d.get("current_time", "")))
        except (KeyError, TypeError, ValueError):
            return None


def to_unit(celsius: float, unit: str) -> int:
    """Temperatura arredondada na unidade pedida ('c' ou 'f')."""
    value = celsius * 9.0 / 5.0 + 32.0 if unit == "f" else celsius
    return int(round(value))


# --- Condição do dia a partir das horas (pura) ---

# O `weather_code` DIÁRIO da Open-Meteo é a pior hora do dia: uma só hora de trovoada (mesmo às 23 h) marca o dia
# inteiro como tempestade. Para o ícone da aba usamos o tempo que domina as horas do dia.
DAY_HOURS = range(7, 19)       # 7 h às 18 h, no fuso do local (a resposta vem com timezone=auto)
STORM_MIN_HOURS = 2            # trovoada aparece se cobre pelo menos 2 horas do dia
WET_MIN_HOURS = 3              # chuva/neve/garoa aparecem se cobrem pelo menos 3 das 12 horas do dia
FOG_MIN_HOURS = 4


def _is_storm(c: int) -> bool:
    return c >= 95


def _is_snow(c: int) -> bool:
    return 71 <= c <= 77 or c in (85, 86)


def _is_wet(c: int) -> bool:
    return 51 <= c <= 67 or 80 <= c <= 82


def _most_common(codes: list) -> int:
    """O código mais frequente; no empate, o mais "forte" (maior código WMO dentro do grupo)."""
    counts = {}
    for c in codes:
        counts[c] = counts.get(c, 0) + 1
    return max(counts, key=lambda c: (counts[c], c))


def representative_code(hours: list, fallback: int) -> int:
    """
    Código WMO que representa o dia, a partir de (hora, código) das 24 horas dele. Ordem de prioridade: trovoada,
    neve, chuva/garoa (o tipo mais frequente entre essas horas), neblina e, por fim, o céu (limpo a nublado) que mais
    aparece. Sem horas suficientes, fica o código diário da API.
    """
    day = [c for h, c in hours if h in DAY_HOURS]
    if len(day) < len(DAY_HOURS) // 2:
        return fallback
    storm = [c for c in day if _is_storm(c)]
    if len(storm) >= STORM_MIN_HOURS:
        return _most_common(storm)
    snow = [c for c in day if _is_snow(c)]
    if len(snow) >= WET_MIN_HOURS:
        return _most_common(snow)
    wet = [c for c in day if _is_wet(c) or _is_storm(c)]
    if len(wet) >= WET_MIN_HOURS:
        return _most_common([c for c in wet if _is_wet(c)] or wet)
    fog = [c for c in day if c in (45, 48)]
    if len(fog) >= FOG_MIN_HOURS:
        return _most_common(fog)
    sky = [c for c in day if c <= 3]
    return _most_common(sky) if sky else fallback


def _hours_by_date(hourly) -> dict:
    """aaaa-mm-dd -> [(hora, código)] a partir do bloco `hourly` da resposta (vazio se não veio)."""
    out = {}
    if not isinstance(hourly, dict):
        return out
    for stamp, code in zip(hourly.get("time") or [], hourly.get("weather_code") or []):
        if code is None or not isinstance(stamp, str) or len(stamp) < 13:
            continue
        try:
            out.setdefault(stamp[:10], []).append((int(stamp[11:13]), int(code)))
        except ValueError:
            continue
    return out


def _parse_hourly_slots(hourly) -> list:
    """Extrai list[HourForecast] do bloco `hourly` quando temperatura e código estão presentes."""
    if not isinstance(hourly, dict):
        return []
    times = hourly.get("time") or []
    codes = hourly.get("weather_code") or []
    temps = hourly.get("temperature_2m") or []
    is_days = hourly.get("is_day") or []
    if not temps:
        return []
    out = []
    for i, (stamp, code, temp) in enumerate(zip(times, codes, temps)):
        if code is None or temp is None or not isinstance(stamp, str) or len(stamp) < 16:
            continue
        day_flag = bool(is_days[i]) if i < len(is_days) and is_days[i] is not None else (6 <= int(stamp[11:13]) < 19)
        try:
            out.append(HourForecast(stamp[:16], int(code), float(temp), day_flag))
        except ValueError:
            continue
    return out


# --- URLs e leitura das respostas (puras, testadas sem rede) ---

def forecast_url(lat: float, lon: float, model: str = FORECAST_MODEL_AUTO) -> str:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,temperature_2m_mean",
        "hourly": "weather_code,temperature_2m,is_day",
        "timezone": "auto",
        "forecast_days": FORECAST_DAYS,
    }
    api_model = FORECAST_MODELS[normalize_forecast_model(model)]
    if api_model:
        params["models"] = api_model
    return f"{FORECAST_URL}?{urllib.parse.urlencode(params)}"


def forecast_url_multi(places: list, model: str = FORECAST_MODEL_AUTO) -> str:
    """Uma requisição para várias cidades: a Open-Meteo aceita latitudes e longitudes separadas por vírgula e
    devolve uma lista de previsões, cada uma no fuso da sua cidade (conferido na API em 2026-11)."""
    params = {
        "latitude": ",".join(f"{pl.lat:.4f}" for pl in places),
        "longitude": ",".join(f"{pl.lon:.4f}" for pl in places),
        "current": "temperature_2m,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,temperature_2m_mean",
        "hourly": "weather_code,temperature_2m,is_day",
        "timezone": "auto",
        "forecast_days": FORECAST_DAYS,
    }
    api_model = FORECAST_MODELS[normalize_forecast_model(model)]
    if api_model:
        params["models"] = api_model
    return f"{FORECAST_URL}?{urllib.parse.urlencode(params)}"


def parse_forecast_multi(data, names: list, now: float) -> list:
    """Lista de WeatherReport na ordem pedida (com uma cidade só a API devolve um objeto, não uma lista)."""
    items = data if isinstance(data, list) else [data]
    if len(items) != len(names):
        raise ValueError("resposta com número de cidades diferente do pedido")
    return [parse_forecast(item, name, now) for item, name in zip(items, names)]


def city_key(entry: dict) -> str:
    """Identidade de uma cidade da lista (a mesma cidade adicionada duas vezes tem a mesma chave)."""
    if entry.get("kind") == AUTO:
        return AUTO
    return f"{float(entry['lat']):.2f},{float(entry['lon']):.2f}"


def _place_entry(place: Place) -> dict:
    return {"kind": "place", **asdict(place)}


def _valid_city(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("kind") == AUTO:
        return True
    return entry.get("kind") == "place" and Place.from_dict(entry) is not None


def geocode_url(query: str, language: str = "pt") -> str:
    q = urllib.parse.urlencode({"name": query.strip(), "count": 6, "language": language, "format": "json"})
    return f"{GEOCODE_URL}?{q}"


def parse_forecast(data: dict, place_name: str, now: float) -> WeatherReport:
    current = data["current"]
    daily = data["daily"]
    means = daily.get("temperature_2m_mean") or []
    hours = _hours_by_date(data.get("hourly"))
    days = []
    for i, date in enumerate(daily["time"][:FORECAST_DAYS]):
        t_max = float(daily["temperature_2m_max"][i])
        t_min = float(daily["temperature_2m_min"][i])
        mean = means[i] if i < len(means) and means[i] is not None else (t_max + t_min) / 2.0
        code = representative_code(hours.get(str(date), []), int(daily["weather_code"][i]))
        days.append(DayForecast(str(date), code, t_max, t_min, float(mean)))
    if not days:
        raise ValueError("previsão sem dias")
    return WeatherReport(
        place=place_name,
        current_temp=float(current["temperature_2m"]),
        current_code=int(current["weather_code"]),
        is_day=bool(current.get("is_day", 1)),
        days=days,
        fetched_at=now,
        hours=_parse_hourly_slots(data.get("hourly")),
        current_time=str(current.get("time", "")),
    )


def parse_geocode(data: dict) -> list:
    places = []
    for r in (data or {}).get("results") or []:
        try:
            detail = ", ".join(x for x in (r.get("admin1"), r.get("country")) if x)
            places.append(Place(str(r["name"]), float(r["latitude"]), float(r["longitude"]), detail))
        except (KeyError, TypeError, ValueError):
            continue
    return places


def parse_ip_location(data: dict) -> Optional[Place]:
    try:
        if data.get("error"):
            return None
        detail = ", ".join(x for x in (data.get("region"), data.get("country_name")) if x)
        return Place(str(data["city"]), float(data["latitude"]), float(data["longitude"]), detail)
    except (KeyError, TypeError, ValueError):
        return None


def _http_get_json(url: str) -> dict:
    """GET que devolve JSON. Os testes trocam esta função para nunca tocar a rede."""
    req = urllib.request.Request(url, headers={"User-Agent": f"Aimedget-App/{__version__}"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


# --- Serviço ---

class _Relay(QObject):
    """Leva o resultado da thread de rede para a thread da UI (o sinal emitido fora dela vira chamada enfileirada)."""
    done = Signal(object, object)   # (callback, resultado)


class WeatherService(QObject):
    reports_ready = Signal(object)  # {chave da cidade: WeatherReport}
    cities_changed = Signal()
    failed = Signal(str)            # FAIL_OFFLINE / FAIL_NO_LOCATION
    search_results = Signal(str, list)   # (busca, list[Place])
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._relay = _Relay()
        self._relay.done.connect(lambda cb, result: cb(result))
        self._busy = False
        self._pending = False   # pediram outra consulta enquanto a atual rodava (ex.: trocou a cidade)
        self._search_seq = 0

    # --- Cidades (até MAX_CITIES, na ordem do cartão) ---
    # Configuração "cities": [{"kind": "auto"} | {"kind": "place", name, lat, lon, detail}], "current_city": índice
    # da última vista, "cache_by_city": {chave: previsão}. "auto" = local pela conexão (ocupa uma das vagas).

    @staticmethod
    def cities() -> list:
        """Lista de cidades. Na primeira vez, migra a escolha antiga (um local só) para a lista."""
        raw = config_manager.get_weather("cities", None)
        if isinstance(raw, list):
            return [c for c in raw if _valid_city(c)][:MAX_CITIES]
        migrated = []
        if config_manager.get_weather("location_mode", "auto") == "manual":
            place = Place.from_dict(config_manager.get_weather("location", None) or {})
            if place is not None:
                migrated.append(_place_entry(place))
        else:
            migrated.append({"kind": AUTO})
        old_cache = config_manager.get_weather("cache", None)
        if migrated and isinstance(old_cache, dict):
            config_manager.set_weather("cache_by_city", {city_key(migrated[0]): old_cache})
        config_manager.set_weather("cities", migrated)
        return migrated

    def city_count(self) -> int:
        return len(self.cities())

    def current_index(self) -> int:
        n = self.city_count()
        try:
            i = int(config_manager.get_weather("current_city", 0) or 0)
        except (TypeError, ValueError):
            i = 0
        return max(0, min(i, n - 1)) if n else 0

    def set_current_index(self, index: int):
        n = self.city_count()
        if n:
            config_manager.set_weather("current_city", int(index) % n)

    def current_city(self) -> Optional[dict]:
        cities = self.cities()
        return cities[self.current_index()] if cities else None

    def city_name(self, entry: Optional[dict]) -> str:
        """Nome para mostrar; "" para o automático ainda sem local conhecido (a UI escreve "Minha localização")."""
        if not entry:
            return ""
        if entry.get("kind") == AUTO:
            auto = self.auto_place()
            return auto.name if auto else ""
        return str(entry.get("name", ""))

    def has_auto(self) -> bool:
        return any(c.get("kind") == AUTO for c in self.cities())

    def can_add(self) -> bool:
        return self.city_count() < MAX_CITIES

    def contains_place(self, place: Place) -> bool:
        key = city_key(_place_entry(place))
        return any(city_key(c) == key for c in self.cities())

    def add_place(self, place: Place) -> str:
        """Adiciona no fim da lista. Devolve "ok", "full" (já são 5) ou "duplicate"."""
        if self.contains_place(place):
            return "duplicate"
        if not self.can_add():
            return "full"
        self._save_cities(self.cities() + [_place_entry(place)])
        self.refresh(force=True)
        return "ok"

    def add_auto(self) -> str:
        if self.has_auto():
            return "duplicate"
        if not self.can_add():
            return "full"
        self._save_cities(self.cities() + [{"kind": AUTO}])
        self.refresh(force=True)
        return "ok"

    def remove_city(self, index: int):
        cities = self.cities()
        if not 0 <= index < len(cities):
            return
        current = self.current_index()
        del cities[index]
        if index < current or current >= len(cities):   # a cidade vista continua a mesma (ou a anterior)
            current = max(0, current - 1)
        config_manager.set_weather("current_city", current)
        self._save_cities(cities)

    def move_city(self, src: int, dst: int):
        """Reordena (arrastar no Hub). A cidade vista no cartão continua a mesma."""
        cities = self.cities()
        if not (0 <= src < len(cities) and 0 <= dst < len(cities)) or src == dst:
            return
        viewing = city_key(cities[self.current_index()])
        cities.insert(dst, cities.pop(src))
        config_manager.set_weather("current_city", next(i for i, c in enumerate(cities) if city_key(c) == viewing))
        self._save_cities(cities)

    def _save_cities(self, cities: list):
        config_manager.set_weather("cities", cities[:MAX_CITIES])
        self.cities_changed.emit()

    # --- Previsões salvas ---

    @staticmethod
    def auto_place() -> Optional[Place]:
        return Place.from_dict(config_manager.get_weather("auto_location", None) or {})

    def cached_reports(self) -> dict:
        """chave da cidade -> WeatherReport (só as cidades da lista)."""
        data = config_manager.get_weather("cache_by_city", None) or {}
        reports = {}
        for c in self.cities():
            report = WeatherReport.from_dict(data.get(city_key(c))) if isinstance(data, dict) else None
            if report is not None:
                reports[city_key(c)] = report
        return reports

    def cached_report(self, key: Optional[str] = None) -> Optional[WeatherReport]:
        if key is None:
            entry = self.current_city()
            key = city_key(entry) if entry else None
        return self.cached_reports().get(key) if key else None

    def is_stale(self, now: Optional[float] = None) -> bool:
        """Velha se alguma cidade da lista não tem previsão ou tem uma de mais de 30 min."""
        now = time.time() if now is None else now
        cities = self.cities()
        reports = self.cached_reports()
        return any(
            city_key(c) not in reports or not (0 <= now - reports[city_key(c)].fetched_at < REFRESH_S) for c in cities
        )

    def is_busy(self) -> bool:
        return self._busy

    def forecast_model(self) -> str:
        return normalize_forecast_model(config_manager.get_weather("forecast_model", FORECAST_MODEL_AUTO))

    def set_forecast_model(self, model: str) -> None:
        normalized = normalize_forecast_model(model)
        if normalized == self.forecast_model():
            return
        config_manager.set_weather("forecast_model", normalized)
        self.refresh(force=True)

    # --- Consulta (uma requisição para todas as cidades) ---

    def refresh(self, force: bool = False):
        """Busca a previsão de todas as cidades numa requisição só, se alguma estiver velha (ou sempre, com `force`)."""
        cities = self.cities()
        if not cities:
            self.failed.emit(FAIL_NO_LOCATION)
            return
        if not force and not self.is_stale():
            return
        if self._busy:
            self._pending = self._pending or force
            return

        auto = self.auto_place()
        auto_at = float(config_manager.get_weather("auto_location_at", 0.0) or 0.0)
        need_ip = any(c.get("kind") == AUTO for c in cities) and (
            auto is None or not (0 <= time.time() - auto_at < AUTO_PLACE_TTL_S))

        model = self.forecast_model()

        def work():
            new_auto = None
            if need_ip:
                try:
                    new_auto = parse_ip_location(_http_get_json(IP_LOCATION_URL))
                except Exception as e:   # sem rede ou serviço fora: tenta com o local que já tinha
                    logger.info("Local pelo IP indisponível: %s", e)
            auto_now = new_auto or auto
            targets = []   # (chave, Place)
            for c in cities:
                if c.get("kind") == AUTO:
                    if auto_now is not None:
                        targets.append((AUTO, auto_now))
                else:
                    targets.append((city_key(c), Place.from_dict(c)))
            if not targets:   # só o automático, e o IP não respondeu: quase sempre sem rede
                return ("fail", FAIL_OFFLINE, new_auto)
            try:
                data = _http_get_json(forecast_url_multi([pl for _k, pl in targets], model=model))
                reports = parse_forecast_multi(data, [pl.name for _k, pl in targets], time.time())
            except Exception as e:
                logger.info("Previsão indisponível: %s", e)
                return ("fail", FAIL_OFFLINE, new_auto)
            return ("ok", {k: r for (k, _pl), r in zip(targets, reports)}, new_auto)

        self._set_busy(True)
        self._run(work, self._on_refresh_done)

    def search(self, query: str, language: str = "pt"):
        """Busca cidades pelo nome; responde por `search_results` (só a busca mais recente é entregue)."""
        query = (query or "").strip()
        self._search_seq += 1
        seq = self._search_seq
        if len(query) < 2:
            self.search_results.emit(query, [])
            return

        def work():
            try:
                return parse_geocode(_http_get_json(geocode_url(query, language)))
            except Exception as e:
                logger.info("Busca de cidade falhou: %s", e)
                return []

        def done(places):
            if seq == self._search_seq:
                self.search_results.emit(query, places)

        self._run(work, done)

    # --- Internos ---

    def _run(self, work: Callable, callback: Callable):
        relay = self._relay

        def target():
            try:
                result = work()
            except Exception as e:   # nunca deixa a thread morrer sem responder
                logger.warning("Erro inesperado no WeatherService: %s", e)
                result = ("fail", FAIL_OFFLINE, None) if callback == self._on_refresh_done else []
            relay.done.emit(callback, result)

        threading.Thread(target=target, name="aimedget-weather", daemon=True).start()

    def _on_refresh_done(self, result):
        status, payload, new_auto = result
        if new_auto is not None:
            config_manager.set_weather("auto_location", asdict(new_auto))
            config_manager.set_weather("auto_location_at", time.time())
        if status == "ok":
            keys = {city_key(c) for c in self.cities()}
            cache = config_manager.get_weather("cache_by_city", None) or {}
            cache = {k: v for k, v in cache.items() if k in keys} if isinstance(cache, dict) else {}
            cache.update({k: r.to_dict() for k, r in payload.items()})
            config_manager.set_weather("cache_by_city", cache)
            self.reports_ready.emit(payload)
        else:
            self.failed.emit(payload)
        self._set_busy(False)
        if self._pending:
            self._pending = False
            self.refresh(force=True)

    def _set_busy(self, busy: bool):
        if self._busy != busy:
            self._busy = busy
            self.busy_changed.emit(busy)
