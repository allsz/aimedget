"""
Weather Widget: condições WMO, leitura das respostas da Open-Meteo/ipapi, conversão de unidade, animações do cartão
(dígitos, troca de texto, morph do dia, pílula), serviço com rede falsa e o controller nos estados sem dados.
Nada aqui toca a rede: o conftest desliga `_http_get_json`, e os testes que precisam de respostas trocam por dados fixos.
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.i18n import TRANSLATIONS
from app.services import weather_service as ws
from app.widgets.weather import conditions as cond
from app.widgets.weather import motion as mo
from app.widgets.weather.card_painter import paint_card, tab_at, tab_rect
from app.widgets.weather.icons import ICONS
from app.widgets.weather.card_state import PAST, CardState, DayView, DigitGroup, TextMorph, TextSwap

FORECAST = {
    "current": {"temperature_2m": 23.6, "weather_code": 0, "is_day": 0},
    "daily": {
        "time": ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"],
        "weather_code": [0, 3, 61, 95, 71],
        "temperature_2m_max": [26.0, 21.0, 18.0, 17.0, 2.0],
        "temperature_2m_min": [17.0, 14.0, 12.0, 11.0, -3.0],
        "temperature_2m_mean": [21.0, 18.6, None, 14.0, -0.4],
    },
}


def _wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestConditions(unittest.TestCase):
    def test_wmo_mapping(self):
        self.assertEqual(cond.condition_from_wmo(0), cond.SUNNY)
        self.assertEqual(cond.condition_from_wmo(0, is_day=False), cond.CLEAR_NIGHT)
        self.assertEqual(cond.condition_from_wmo(2), cond.PARTLY_CLOUDY)
        self.assertEqual(cond.condition_from_wmo(45), cond.FOG)
        self.assertEqual(cond.condition_from_wmo(53), cond.LIGHT_RAIN)
        self.assertEqual(cond.condition_from_wmo(63), cond.RAIN)
        self.assertEqual(cond.condition_from_wmo(82), cond.HEAVY_RAIN)
        self.assertEqual(cond.condition_from_wmo(99), cond.THUNDERSTORM)
        self.assertEqual(cond.condition_from_wmo(75), cond.SNOW)
        self.assertEqual(cond.condition_from_wmo(12345), cond.CLOUDY)
        self.assertEqual(cond.condition_from_wmo(None), cond.CLOUDY)

    def test_every_condition_has_scene_tab_icon_and_names(self):
        for key in cond.ALL_CONDITIONS:
            self.assertIn(key, cond.SCENES)
            self.assertIn(key, cond.TAB_ICON)
            for lang in ("pt", "en"):
                self.assertIn(f"weather_cond_{cond.name_key(key)}", TRANSLATIONS[lang])

    def test_every_condition_has_a_night_version(self):
        night = {cond.PARTLY_CLOUDY: cond.PARTLY_CLOUDY_NIGHT, cond.CLOUDY: cond.CLOUDY_NIGHT, cond.FOG: cond.FOG_NIGHT,
                 cond.LIGHT_RAIN: cond.LIGHT_RAIN_NIGHT, cond.RAIN: cond.RAIN_NIGHT,
                 cond.HEAVY_RAIN: cond.HEAVY_RAIN_NIGHT, cond.THUNDERSTORM: cond.THUNDERSTORM_NIGHT,
                 cond.SNOW: cond.SNOW_NIGHT}
        codes = {cond.PARTLY_CLOUDY: 2, cond.CLOUDY: 3, cond.FOG: 45, cond.LIGHT_RAIN: 53, cond.RAIN: 63,
                 cond.HEAVY_RAIN: 65, cond.THUNDERSTORM: 95, cond.SNOW: 73}
        for day, ngt in night.items():
            self.assertEqual(cond.condition_from_wmo(codes[day], True), day)
            self.assertEqual(cond.condition_from_wmo(codes[day], False), ngt)
            self.assertTrue(cond.is_night(ngt))
            self.assertFalse(cond.is_night(day))
            self.assertEqual(cond.name_key(ngt), day)
            # o céu da noite é mais escuro que o do dia
            lum = lambda c: sum(int(c[i:i + 2], 16) for i in (1, 3, 5))
            self.assertLess(lum(cond.scene_for(ngt).sky[0][1]), lum(cond.scene_for(day).sky[0][1]))
        # o que importa para Gurupi à meia-noite: parcialmente nublado de noite não mostra o sol
        self.assertEqual(cond.scene_for(cond.PARTLY_CLOUDY_NIGHT).icon, "partly_night")
        self.assertEqual(cond.TAB_ICON[cond.PARTLY_CLOUDY_NIGHT], "partly_night")
        self.assertIn("partly_night", ICONS)

    def test_rain_intensity_grows(self):
        light, rain, heavy = (cond.scene_for(k) for k in (cond.LIGHT_RAIN, cond.RAIN, cond.HEAVY_RAIN))
        self.assertLess(light.rain, rain.rain)
        self.assertLess(rain.rain, heavy.rain)
        self.assertLess(heavy.rain_ms, light.rain_ms)


def _hours(date: str, codes: list) -> dict:
    """Bloco `hourly` de um dia: 24 códigos, da 0 h às 23 h."""
    return {"time": [f"{date}T{h:02d}:00" for h in range(24)], "weather_code": codes}


# Gurupi, 20/11/2026 (Open-Meteo): o código diário veio 95 (tempestade) por UMA hora de trovoada às 23 h; o dia foi
# nublado com garoa.
GURUPI_TODAY = [3, 3, 3, 2, 2, 3, 3, 3, 51, 51, 3, 55, 51, 3, 0, 1, 3, 3, 3, 3, 51, 51, 3, 95]


class TestDayCondition(unittest.TestCase):
    def _code(self, codes, fallback=95):
        return ws.representative_code([(h, c) for h, c in enumerate(codes)], fallback)

    def test_one_late_storm_hour_does_not_make_the_whole_day_a_storm(self):
        self.assertEqual(self._code(GURUPI_TODAY), 51)              # garoa, não tempestade

    def test_storm_shows_when_it_covers_two_daytime_hours(self):
        codes = [3] * 24
        codes[13] = codes[14] = 95
        self.assertEqual(self._code(codes), 95)
        codes[14] = 3
        self.assertEqual(self._code(codes, fallback=95), 3)         # uma hora só: o dia é nublado

    def test_rain_needs_three_daytime_hours_and_keeps_its_intensity(self):
        codes = [1] * 24
        for h in (9, 10):
            codes[h] = 63
        self.assertEqual(self._code(codes), 1)                      # 2 horas de chuva: o céu manda
        codes[11] = 63
        self.assertEqual(self._code(codes), 63)
        codes[22] = codes[23] = 65                                  # chuva forte de noite não conta
        self.assertEqual(self._code(codes), 63)

    def test_snow_fog_and_sky(self):
        self.assertEqual(self._code([73] * 24), 73)
        self.assertEqual(self._code([45] * 12 + [0] * 12), 45)
        self.assertEqual(self._code([0] * 7 + [2] * 3 + [0] * 14), 0)     # 9 horas limpas x 3 parciais: limpo
        self.assertEqual(self._code([0] * 7 + [2] * 6 + [0] * 11), 2)     # 6 x 6: o empate fica com o mais nublado

    def test_missing_hours_fall_back_to_the_daily_code(self):
        self.assertEqual(ws.representative_code([], 61), 61)
        self.assertEqual(ws.representative_code([(20, 0), (21, 0)], 61), 61)

    def test_parse_uses_the_hours_when_they_come(self):
        data = json.loads(json.dumps(FORECAST))
        data["daily"]["weather_code"][0] = 95
        data["hourly"] = _hours("2026-11-16", GURUPI_TODAY)
        report = ws.parse_forecast(data, "Gurupi", 1.0)
        self.assertEqual(report.days[0].code, 51)
        self.assertEqual(report.days[1].code, 3)                    # sem horas desse dia: o código diário
        self.assertIn("hourly=weather_code", ws.forecast_url(-11.7, -49.0))
        self.assertIn("hourly=weather_code", ws.forecast_url_multi([ws.Place("A", 1.0, 2.0)]))


class TestParsing(unittest.TestCase):
    def test_parse_forecast(self):
        report = ws.parse_forecast(FORECAST, "Lisboa", 100.0)
        self.assertEqual(report.place, "Lisboa")
        self.assertEqual(len(report.days), 5)
        self.assertFalse(report.is_day)
        self.assertAlmostEqual(report.days[2].t_mean, 15.0)   # média ausente: (máx + mín) / 2
        self.assertEqual(ws.WeatherReport.from_dict(report.to_dict()), report)

    def test_cache_rejects_garbage(self):
        self.assertIsNone(ws.WeatherReport.from_dict({"place": "x"}))
        self.assertIsNone(ws.WeatherReport.from_dict({"place": "x", "current_temp": 1, "current_code": 0,
                                                      "is_day": True, "days": []}))

    def test_geocode_and_ip(self):
        places = ws.parse_geocode({"results": [
            {"name": "Porto", "latitude": 41.1, "longitude": -8.6, "admin1": "Porto", "country": "Portugal"},
            {"name": "sem coordenadas"},
        ]})
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0].detail, "Porto, Portugal")
        self.assertEqual(ws.parse_geocode({}), [])
        ip = ws.parse_ip_location({"city": "Recife", "latitude": -8.05, "longitude": -34.9, "country_name": "Brazil"})
        self.assertEqual(ip.name, "Recife")
        self.assertIsNone(ws.parse_ip_location({"error": True, "reason": "RateLimited"}))

    def test_units(self):
        self.assertEqual(ws.to_unit(0, "c"), 0)
        self.assertEqual(ws.to_unit(0, "f"), 32)
        self.assertEqual(ws.to_unit(-40, "f"), -40)
        self.assertEqual(ws.to_unit(21.6, "c"), 22)

    def test_forecast_url(self):
        url = ws.forecast_url(-23.55, -46.63)
        self.assertIn("latitude=-23.5500", url)
        self.assertIn("forecast_days=5", url)


class TestMotion(unittest.TestCase):
    def test_bezier_endpoints_and_overshoot(self):
        for ease in (mo.EASE_SMOOTH_OUT, mo.EASE_IN_OUT, mo.EASE_DIGIT):
            self.assertEqual(ease(0.0), 0.0)
            self.assertEqual(ease(1.0), 1.0)
        self.assertAlmostEqual(mo.EASE_IN_OUT(0.5), 0.5, places=3)
        self.assertGreater(max(mo.EASE_DIGIT(x / 50) for x in range(51)), 1.0)   # passa do alvo e volta

    def test_flash_keyframes(self):
        self.assertEqual(mo.keyframes(0.5, mo.FLASH_FRAMES), 0.0)
        self.assertAlmostEqual(mo.keyframes(0.88, mo.FLASH_FRAMES), 0.4)


class TestCardAnimations(unittest.TestCase):
    def test_digits_only_changed_chars_animate_with_stagger(self):
        g = DigitGroup("24")
        g.set("26", 10.0)
        self.assertEqual(g.starts[0], PAST)                            # o "2" igual não anima
        self.assertAlmostEqual(g.starts[1], 10.0 + 2 * mo.DIGIT_STAGGER)   # último caractere: 2x o escalonamento
        dy, alpha = g.char_state(1, 10.0)
        self.assertEqual(alpha, 0.0)
        self.assertGreater(dy, 0.0)
        self.assertEqual(g.char_state(1, 11.0), (0.0, 1.0))

    def test_text_swap_exits_then_enters(self):
        s = TextSwap("Sunny")
        s.set("Cloudy", 5.0)
        text, dy, _ = s.state(5.05)
        self.assertEqual(text, "Sunny")
        self.assertLess(dy, 0)
        text, dy, alpha = s.state(5.0 + 2 * mo.TEXT_SWAP_DUR)
        self.assertEqual((text, dy, alpha), ("Cloudy", 0.0, 1.0))

    def test_morph_keeps_common_parts(self):
        m = TextMorph("Monday")
        m.set("Sunday", 0.0)
        self.assertEqual(m.parts(), ("", "Mo", "Su", "nday"))
        m = TextMorph("Terça")
        m.set("Quarta", 0.0)
        self.assertEqual(m.parts(), ("", "Terç", "Quart", "a"))

    def test_select_moves_pill_and_ignores_same_day(self):
        days = [DayView("Mon", "Monday", c, 20 + i, 25, 15) for i, c in enumerate(cond.ALL_CONDITIONS[:5])]
        st = CardState()
        st.set_days("X", days, {}, PAST, animate=False)
        self.assertFalse(st.select(0, {}, 1.0))
        self.assertTrue(st.select(3, {}, 1.0))
        self.assertAlmostEqual(st.pill_position(1.0), 0.0)
        self.assertAlmostEqual(st.pill_position(2.0), 3.0)
        self.assertEqual(st.sky.current, days[3].condition)
        self.assertTrue(st.transitions_busy(1.1))
        self.assertFalse(st.transitions_busy(5.0))

    def test_tab_hit_testing(self):
        for i in range(5):
            self.assertEqual(tab_at(tab_rect(i).center()), i)
        self.assertEqual(tab_at(tab_rect(0).topLeft() - tab_rect(0).topLeft() * 2), -1)


class TestPainting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_every_condition_and_message_paints(self):
        from app.widgets.weather.specs import mock_state
        img = QImage(320, 280, QImage.Format.Format_ARGB32_Premultiplied)
        for key in cond.ALL_CONDITIONS:
            st = mock_state()
            st.animated = True
            st.preview_condition(key, {}, 0.0)
            img.fill(QColor(0, 0, 0, 0))
            p = QPainter(img)
            paint_card(p, QRectF(10, 10, 300, 262), st, 0.3)   # no meio da troca (fundo e ícone em fade cruzado)
            p.end()
            self.assertNotEqual(img.pixelColor(150, 140).alpha(), 0, key)
        st = mock_state()
        st.set_message("weather_offline", "detail")
        p = QPainter(img)
        paint_card(p, QRectF(10, 10, 300, 262), st, 1.0)
        p.end()


class TestForecastTabsSwap(unittest.TestCase):
    """Trocar de cidade anima o ícone e o nome de cada aba (em onda); sem mudança, as abas ficam paradas."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_day_to_night_swaps_sky_and_icon_with_motion(self):
        st = CardState()
        st.set_days("Gurupi", self._days([cond.PARTLY_CLOUDY] * 5), {}, PAST, animate=False)
        st.set_days("Gurupi", self._days([cond.PARTLY_CLOUDY_NIGHT] + [cond.PARTLY_CLOUDY] * 4), {}, 10.0,
                    animate=True)
        self.assertTrue(st.transitions_busy(10.05))          # anima, não pula
        self.assertEqual(st.icon.current, "partly_night")
        self.assertEqual(st.icon.previous, "partly")
        self.assertFalse(st.transitions_busy(20.0))          # termina limpo
        st.set_days("Gurupi", self._days([cond.PARTLY_CLOUDY] * 5), {}, 30.0, animate=False)   # sem animações
        self.assertFalse(st.transitions_busy(30.0))
        self.assertEqual(st.icon.current, "partly")

    def _days(self, conds, names=("Mon", "Tue", "Wed", "Thu", "Fri")):
        return [DayView(n, n + "day", c, 20, 25, 15) for n, c in zip(names, conds)]

    def _state(self):
        st = CardState()
        st.set_days("Lisboa", self._days([cond.CLEAR_NIGHT] * 5), {}, PAST, animate=False)
        return st

    def test_city_switch_animates_every_tab_in_a_wave(self):
        st = self._state()
        st.set_days("Recife", self._days([cond.RAIN] + [cond.CLEAR_NIGHT] * 4), {}, 10.0, animate=True)
        self.assertTrue(st.transitions_busy(10.05))
        swaps = [st.tab_swap(i, 10.05) for i in range(5)]
        self.assertTrue(all(sw is not None for sw in swaps))                  # inclusive as que não mudaram
        self.assertEqual(swaps[0][0][1], cond.TAB_ICON[cond.CLEAR_NIGHT])     # a aba 0 lembra o ícone anterior
        self.assertGreater(swaps[0][1], swaps[4][1])                           # da esquerda para a direita
        st.set_days("Lisboa", self._days([cond.CLEAR_NIGHT] * 5), {}, 20.0, animate=True, direction=-1)
        self.assertLess(st.tab_swap(0, 20.05)[1], st.tab_swap(4, 20.05)[1])   # voltando: da direita para a esquerda
        self.assertTrue(all(st.tab_swap(i, 21.0) is None for i in range(5)))
        self.assertFalse(st.transitions_busy(21.0))

    def test_same_city_refresh_only_moves_changed_tabs(self):
        st = self._state()
        st.set_days("Lisboa", self._days([cond.CLEAR_NIGHT, cond.SNOW] + [cond.CLEAR_NIGHT] * 3), {}, 10.0, True)
        self.assertIsNone(st.tab_swap(0, 10.1))
        self.assertIsNotNone(st.tab_swap(1, 10.1))

    def test_no_animation_when_static(self):
        st = self._state()
        st.set_days("Recife", self._days([cond.RAIN] * 5), {}, PAST, animate=False)
        self.assertTrue(all(st.tab_swap(i, 0.0) is None for i in range(5)))

    def test_tabs_paint_moving_then_settle_on_final_frame(self):
        def frame(st, now):
            img = QImage(320, 280, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor(0, 0, 0, 0))
            p = QPainter(img)
            paint_card(p, QRectF(10, 10, 300, 262), st, now)
            p.end()
            return img.copy(10, 200, 300, 72)   # faixa das abas

        st = self._state()
        st.set_days("Recife", self._days([cond.RAIN] * 5), {}, 10.0, animate=True)
        still = CardState()
        still.set_days("Recife", self._days([cond.RAIN] * 5), {}, PAST, animate=False)
        self.assertNotEqual(frame(st, 10.12), frame(still, 10.12))   # no meio: ícones/nomes em movimento
        self.assertEqual(frame(st, 12.0), frame(still, 12.0))        # no fim: igual ao estado parado


class TestTextStaysStillOnClick(unittest.TestCase):
    """Clicar num dia não pode mexer no texto que não muda (o nome da cidade "pulava" a cada clique)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _frame(self, dpr: float, origin: float, busy: bool) -> QImage:
        from app.widgets.weather.specs import mock_state
        st = mock_state()
        st.animated = False
        st.place = "Bragança Paulista"
        if busy:
            st.press_t0 = 100.0   # "troca em curso" sem mudar nada visível
        img = QImage(int(340 * dpr), int(300 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        paint_card(p, QRectF(origin, origin, 300, 262), st, 100.05, cache={})
        p.end()
        return img

    def test_place_name_identical_idle_and_during_click(self):
        for dpr, origin in ((1.0, 18.0), (1.25, 18.0), (1.5, 18.0), (1.25, 21.6)):
            a, b = self._frame(dpr, origin, False), self._frame(dpr, origin, True)
            x0, y0 = int((origin + 20) * dpr), int((origin + 20) * dpr)
            x1, y1 = int((origin + 240) * dpr), int((origin + 46) * dpr)
            same = all(a.pixel(x, y) == b.pixel(x, y) for x in range(x0, x1, 2) for y in range(y0, y1, 2))
            self.assertTrue(same, f"dpr={dpr} origin={origin}")


class TestServiceAndController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._saved = dict(config_manager._data.get("weather_widget", {}))
        self._http = ws._http_get_json
        self._orig_save = config_manager._save
        config_manager._save = lambda *a, **k: None   # os testes não escrevem no settings.json do usuário
        config_manager._data["weather_widget"] = {}

    def tearDown(self):
        ws._http_get_json = self._http
        config_manager._data["weather_widget"] = self._saved
        config_manager._save = self._orig_save

    @staticmethod
    def _set_cities(*places):
        config_manager._data["weather_widget"]["cities"] = [
            {"kind": "auto"} if pl == "auto" else {"kind": "place", "name": pl.name, "lat": pl.lat, "lon": pl.lon,
                                                   "detail": pl.detail}
            for pl in places
        ]

    def test_refresh_all_cities_in_one_request(self):
        urls = []
        second = json.loads(json.dumps(FORECAST))
        second["current"]["temperature_2m"] = 10.0

        def fake(url):
            urls.append(url)
            return [FORECAST, second]

        ws._http_get_json = fake
        self._set_cities(ws.Place("Lisboa", 38.7, -9.1), ws.Place("Porto", 41.1, -8.6))
        svc = ws.WeatherService()
        got = []
        svc.reports_ready.connect(got.append)
        svc.refresh(force=True)
        self.assertTrue(_wait_for(lambda: got))
        self.assertEqual(len(urls), 1)                                 # uma requisição para as duas cidades
        self.assertIn("latitude=38.7000%2C41.1000", urls[0])
        self.assertTrue(all("ipapi" not in u for u in urls))           # sem "minha localização": nada de IP
        reports = got[0]
        self.assertEqual(sorted(r.place for r in reports.values()), ["Lisboa", "Porto"])
        self.assertEqual(len(svc.cached_reports()), 2)

    def test_forecast_model_defaults_to_auto_and_updates_url(self):
        self.assertNotIn("models=", ws.forecast_url(-22.95, -46.54, "auto"))
        self.assertIn("models=icon_seamless", ws.forecast_url(-22.95, -46.54, "icon"))
        self.assertIn("models=ecmwf_ifs025", ws.forecast_url(-22.95, -46.54, "ecmwf"))
        self.assertIn("models=gfs_seamless", ws.forecast_url(-22.95, -46.54, "gfs"))

        urls = []
        ws._http_get_json = lambda url: (urls.append(url), FORECAST)[1]
        self._set_cities(ws.Place("Bragança Paulista", -22.95, -46.54))
        svc = ws.WeatherService()
        self.assertEqual(svc.forecast_model(), "auto")

        got = []
        svc.reports_ready.connect(got.append)
        svc.set_forecast_model("icon")
        self.assertEqual(svc.forecast_model(), "icon")
        self.assertTrue(_wait_for(lambda: got))
        self.assertTrue(urls and "models=icon_seamless" in urls[-1])
        self.assertFalse(svc.is_stale())

    def test_city_list_rules(self):
        self._set_cities()
        svc = ws.WeatherService()
        svc.refresh = lambda *a, **k: None   # só a lista; sem consulta
        places = [ws.Place(f"C{i}", 10.0 + i, 20.0 + i) for i in range(6)]
        for pl in places[:4]:
            self.assertEqual(svc.add_place(pl), "ok")
        self.assertEqual(svc.add_place(places[0]), "duplicate")
        self.assertEqual(svc.add_auto(), "ok")                        # "minha localização" ocupa uma vaga
        self.assertEqual(svc.add_auto(), "duplicate")
        self.assertEqual(svc.add_place(places[5]), "full")            # mais de 5: não
        self.assertEqual(svc.city_count(), ws.MAX_CITIES)

        svc.set_current_index(2)                                       # vendo C2
        svc.move_city(2, 0)
        self.assertEqual(svc.city_name(svc.current_city()), "C2")      # reordenar não troca a cidade vista
        svc.remove_city(1)                                             # remove uma antes da vista? (C0 está em 1)
        self.assertEqual(svc.city_name(svc.current_city()), "C2")
        svc.remove_city(0)                                             # remove a própria cidade vista
        self.assertEqual(svc.current_index(), 0)

    def test_migrates_single_city_settings(self):
        w = config_manager._data["weather_widget"]
        w["location_mode"] = "manual"
        w["location"] = {"name": "Lisboa", "lat": 38.7, "lon": -9.1, "detail": ""}
        w["cache"] = ws.parse_forecast(FORECAST, "Lisboa", time.time()).to_dict()
        svc = ws.WeatherService()
        self.assertEqual([c["name"] for c in svc.cities()], ["Lisboa"])
        self.assertIsNotNone(svc.cached_report())                     # a previsão salva veio junto

    def test_auto_without_network_fails_offline(self):
        svc = ws.WeatherService()
        failures = []
        svc.failed.connect(failures.append)
        svc.refresh(force=True)
        self.assertTrue(_wait_for(lambda: failures))
        self.assertEqual(failures[0], ws.FAIL_OFFLINE)

    def test_manual_without_city_asks_for_one(self):
        config_manager._data["weather_widget"]["location_mode"] = "manual"
        svc = ws.WeatherService()
        failures = []
        svc.failed.connect(failures.append)
        svc.refresh(force=True)
        self.assertTrue(_wait_for(lambda: failures))
        self.assertEqual(failures[0], ws.FAIL_NO_LOCATION)

    def _controller_with(self, names):
        from app.widgets.weather.weather_controller import WeatherWidgetController
        places = [ws.Place(n, 10.0 + i, 20.0 + i) for i, n in enumerate(names)]
        self._set_cities(*places)
        ctrl = WeatherWidgetController()
        ctrl.service.refresh = lambda *a, **k: None
        reports = {}
        for i, pl in enumerate(places):
            data = json.loads(json.dumps(FORECAST))
            data["current"]["temperature_2m"] = 10.0 + i
            reports[ws.city_key({"kind": "place", "lat": pl.lat, "lon": pl.lon})] = ws.parse_forecast(
                data, pl.name, time.time())
        return ctrl, reports

    def test_controller_states(self):
        from app.widgets.weather.weather_controller import build_days
        ctrl, reports = self._controller_with(["Lisboa"])
        self.assertEqual(ctrl.skin.state.message, "weather_loading")   # sem cache: carregando
        self.assertEqual(len(ctrl.skin.state.days), 5)                 # abas com os nomes dos dias

        ctrl._on_reports(reports)
        st = ctrl.skin.state
        self.assertIsNone(st.message)
        self.assertEqual(st.days[0].condition, cond.CLEAR_NIGHT)   # hoje à noite
        self.assertEqual(st.days[0].temp, 10)
        self.assertEqual(st.days[3].condition, cond.THUNDERSTORM)
        self.assertEqual(st.city_count, 1)                          # uma cidade: sem pontos
        ctrl._on_failed(ws.FAIL_OFFLINE)                            # falha com previsão na tela: mantém a previsão
        self.assertIsNone(st.message)

        ctrl.set_units("f")
        self.assertEqual(st.days[4].hi, 36)
        report = next(iter(reports.values()))
        self.assertEqual(build_days(report, "c")[1].temp, 21)       # amanhã: a máxima do dia (não a média)
        ctrl.select_day(2)
        self.assertEqual(st.selected, 2)
        ctrl.skin.close()
        ctrl.skin.deleteLater()

    def test_city_switch_loops_and_keeps_day(self):
        ctrl, reports = self._controller_with(["A", "B", "C"])
        ctrl._on_reports(reports)
        st = ctrl.skin.state
        self.assertEqual(ctrl.skin.city_names, ["A", "B", "C"])
        ctrl.select_day(3)
        ctrl.step_city(1)
        self.assertEqual((st.place_text.new, st.selected, st.city_index), ("B", 3, 1))   # mesmo dia na outra cidade
        self.assertEqual(st.days[0].temp, 11)
        ctrl.step_city(1)
        ctrl.step_city(1)
        self.assertEqual((st.place_text.new, st.city_index), ("A", 0))                  # da última volta à primeira
        ctrl.step_city(-1)
        self.assertEqual((st.place_text.new, st.city_index), ("C", 2))                  # e ao contrário
        self.assertEqual(config_manager.get_weather("current_city"), 2)                 # última vista fica salva
        ctrl.select_city(1)
        self.assertEqual(st.place_text.new, "B")
        self.assertEqual(st.place_text.direction, -1)                                    # voltou na lista
        ctrl.skin.close()
        ctrl.skin.deleteLater()

    def test_reopen_goes_back_to_today(self):
        ctrl, reports = self._controller_with(["A", "B"])
        ctrl._on_reports(reports)
        ctrl.select_day(4)
        ctrl.show()   # estava fechado: reabre em hoje, na cidade vista por último
        self.assertEqual(ctrl.skin.state.selected, 0)
        ctrl.skin.forget_show_desktop()
        ctrl.skin.close()
        ctrl.skin.deleteLater()

    def test_wheel_switches_city_once_per_gesture_and_ctrl_resizes(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        ctrl, reports = self._controller_with(["A", "B", "C"])
        ctrl._on_reports(reports)
        card = ctrl.skin
        steps, scales = [], []
        card.city_step.connect(steps.append)
        card.scale_changed.connect(scales.append)

        def wheel(dy, mods=Qt.KeyboardModifier.NoModifier):
            ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                             mods, Qt.ScrollPhase.NoScrollPhase, False)
            card.wheelEvent(ev)

        wheel(-120)   # para baixo: próxima
        wheel(-120)   # logo em seguida: ignorado (pausa entre passos)
        self.assertEqual(steps, [1])
        card._last_city_step = 0.0
        wheel(120)    # para cima: anterior
        self.assertEqual(steps, [1, -1])
        start = card.scale()
        wheel(120, Qt.KeyboardModifier.ControlModifier)
        self.assertAlmostEqual(scales[-1], round(start + 0.05, 3))
        self.assertEqual(steps, [1, -1])   # Ctrl+roda não troca de cidade
        card.close()
        card.deleteLater()


class TestCityList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _pump(self, sec):
        end = time.time() + sec
        while time.time() < end:
            QCoreApplication.processEvents()
            time.sleep(0.005)

    def _list(self):
        from app.hub.components.city_list import CityList
        from app.hub.theme import THEME_DARK
        cl = CityList(THEME_DARK)
        cl.set_items([("a", "A", "x"), ("b", "B", ""), ("c", "C", "z")])
        cl.resize(320, 260)
        cl.show()
        QCoreApplication.processEvents()
        return cl

    def test_reorder_by_dragging(self):
        cl = self._list()
        moved = []
        cl.moved.connect(lambda a, b: moved.append((a, b)))
        row = cl._rows[0]
        self.assertTrue(cl._begin_drag(row))
        for _ in range(2):   # arrasta a primeira para baixo, passando do meio das vizinhas
            cl._drag_to(cl.mapToGlobal(cl.rect().bottomLeft()))
        cl._end_drag()
        self.assertEqual(moved, [(0, 2)])
        cl.close()

    def test_drag_lifts_slides_and_settles(self):
        cl = self._list()
        a, b, c = cl._rows
        self.assertTrue(cl._begin_drag(a, a.mapToGlobal(a.rect().center())))
        self.assertTrue(cl.is_reordering())
        r = cl._reorder
        self._pump(0.15)
        self.assertGreater(r.lift.x, 0.8)                         # levantou
        b_start = r.y[b].x
        cl._drag_to(a.mapToGlobal(a.rect().center()) + QPoint(0, b.height() + 4))
        self.assertEqual(cl._rows, [b, a, c])
        self.assertLess(r.y[b].t, b_start)                       # a vizinha tem um novo alvo acima...
        self._pump(0.03)
        self.assertGreater(r.y[b].x, r.y[b].t)                    # ...e vai até ele deslizando, não pula
        cl._end_drag()
        self._pump(0.8)
        self.assertFalse(cl.is_reordering())                      # assentou e limpou a camada
        for row in (a, b, c):
            self.assertIsNone(row.card.graphicsEffect())
        cl.close()

    def test_drag_without_animations_is_instant(self):
        from app.hub.components import city_list as mod
        orig = mod.animations_enabled
        mod.animations_enabled = lambda: False
        try:
            cl = self._list()
            a = cl._rows[0]
            self.assertTrue(cl._begin_drag(a))
            self.assertFalse(cl.is_reordering())
            cl._end_drag()
            cl.close()
        finally:
            mod.animations_enabled = orig

    def test_unchanged_items_keep_their_rows(self):
        cl = self._list()
        before = list(cl._rows)
        cl.set_items([("a", "A", "x"), ("b", "B2", ""), ("c", "C", "z")])   # só um texto mudou
        self.assertEqual(cl._rows, before)
        self.assertEqual(cl._rows[1].lbl_name.text(), "B2")
        self.assertFalse(cl.is_animating())
        cl.close()

    def test_remove_click_confirms_then_leaves(self):
        from app.hub.components import city_list as mod
        cl = self._list()
        removed = []
        cl.removed.connect(removed.append)
        survivors = [cl._rows[0], cl._rows[2]]
        row = cl._rows[1]
        btn = row.btn_remove
        btn.click()
        self.assertEqual(removed, [1])                    # avisa já no clique (contador e busca atualizam na hora)
        self.assertEqual(cl.count(), 2)
        self.assertTrue(cl.is_animating())
        self._pump(mod.SQUASH_S + mod.CHECK_DRAW_DELAY_S + mod.CHECK_DRAW_S + 0.15)
        self.assertAlmostEqual(btn.w, mod.BTN_H, delta=1.0)           # virou um círculo de 28
        self.assertEqual((btn.color_f, btn.glyph_f), (1.0, 0.0))      # na cor de destaque, sem o ✕
        self.assertAlmostEqual(btn.check_f, 1.0, places=2)            # check desenhado
        self.assertTrue(row.isVisible() and row.card.isVisible())     # ainda na pausa, antes de sair
        self._pump(mod.PAUSE_S + mod.FADE_S + 1.0)
        self.assertFalse(cl.is_animating())
        self.assertNotIn(row, cl._rows + cl._leaving)
        self.assertEqual(cl._rows, survivors)                         # as outras linhas são as mesmas
        cl.close()

    def test_new_item_unfolds_in(self):
        from app.hub.components import city_list as mod
        cl = self._list()
        cl.set_items([("a", "A", "x"), ("b", "B", ""), ("c", "C", "z"), ("d", "D", "w")])
        row = cl._rows[-1]
        self.assertIsNotNone(row.graphicsEffect())                    # começa invisível e desfocada
        self.assertLess(row.height(), 5)
        self._pump(mod.RISE_DELAY_S + mod.RISE_S + 0.2)
        self.assertIsNone(row.graphicsEffect())
        self.assertIsNone(row.card.graphicsEffect())
        self.assertGreater(row.height(), 20)
        cl.close()

    def test_without_windows_animations_everything_is_instant(self):
        from app.hub.components import city_list as mod
        orig = mod.animations_enabled
        mod.animations_enabled = lambda: False
        try:
            cl = self._list()
            cl._rows[0].btn_remove.click()
            self.assertEqual(cl.count(), 2)
            self.assertFalse(cl.is_animating())
            cl.set_items([("b", "B", ""), ("c", "C", "z"), ("d", "D", "")])
            self.assertFalse(cl.is_animating())
            self.assertEqual(cl.count(), 3)
            cl.close()
        finally:
            mod.animations_enabled = orig


class TestAddCityNoStrayWindow(unittest.TestCase):
    """Clicar num resultado da busca não pode abrir uma janela solta (o botão clicado aparecia fora do Hub)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._saved = dict(config_manager._data.get("weather_widget", {}))
        self._orig_save = config_manager._save
        self._orig_refresh = ws.WeatherService.refresh
        config_manager._save = lambda *a, **k: None
        ws.WeatherService.refresh = lambda self, force=False: None
        config_manager._data["weather_widget"] = {"cities": [
            {"kind": "place", "name": "Lisboa", "lat": 38.7, "lon": -9.1, "detail": "Lisboa, Portugal"}]}

    def tearDown(self):
        ws.WeatherService.refresh = self._orig_refresh
        config_manager._data["weather_widget"] = self._saved
        config_manager._save = self._orig_save

    def test_clicking_a_result_opens_no_window(self):
        from app.hub.weather_page import WeatherPage
        page = WeatherPage()
        page.resize(800, 900)
        page.show()
        QCoreApplication.processEvents()
        page._last_query_places = [ws.Place("Recife", -8.05, -34.9, "Pernambuco, Brasil")]
        page._show_results(page._last_query_places)
        QCoreApplication.processEvents()
        before = {id(w) for w in self.app.topLevelWidgets() if w.isVisible()}
        page._result_buttons[0].click()
        stray = []
        end = time.time() + 0.6
        while time.time() < end:
            QCoreApplication.processEvents()
            stray += [type(w).__name__ for w in self.app.topLevelWidgets() if w.isVisible() and id(w) not in before]
            time.sleep(0.005)
        self.assertEqual(stray, [])
        self.assertEqual(page.service.city_count(), 2)
        page.close()


class TestCitiesCardNoJitter(TestAddCityNoStrayWindow):
    """
    Adicionar/remover cidade: a altura do cartão "Cidades" só anda num sentido durante a animação. Antes, o botão
    "Adicionar minha localização" e os resultados da busca sumiam/voltavam na hora enquanto a linha ainda abria ou
    saía, e o cartão encolhia e crescia de novo (Referências Visuais/bugs/animation_jitters.mp4).
    """

    def _page(self):
        from app.hub.weather_page import WeatherPage
        page = WeatherPage()
        page.resize(800, 1400)
        page.show()
        self._pump(0.1)
        return page

    def _pump(self, sec):
        end = time.time() + sec
        while time.time() < end:
            QCoreApplication.processEvents()
            time.sleep(0.004)

    def _heights(self, page, sec):
        card = page.city_list.parentWidget()
        out = [card.height()]
        end = time.time() + sec
        while time.time() < end:
            QCoreApplication.processEvents()
            out.append(card.height())
            time.sleep(0.004)
        return out

    def assertOneWay(self, heights, tol=1):
        up = all(b >= a - tol for a, b in zip(heights, heights[1:]))
        down = all(b <= a + tol for a, b in zip(heights, heights[1:]))
        self.assertTrue(up or down, f"a altura foi e voltou: {sorted(set(heights))} ({heights[:3]}..{heights[-3:]})")
        self.assertNotEqual(heights[0], heights[-1])

    def test_add_my_location_grows_without_dip(self):
        page = self._page()
        self.assertTrue(page.fold_auto.isVisible())
        page._on_add_auto()
        self.assertOneWay(self._heights(page, 0.7))
        self.assertFalse(page.fold_auto.isVisible())
        page.close()

    def test_remove_brings_button_back_without_bump(self):
        config_manager._data["weather_widget"]["cities"].append({"kind": "auto"})
        page = self._page()
        self.assertFalse(page.fold_auto.isVisible())
        page.city_list._rows[1].btn_remove.click()
        self.assertFalse(page.fold_auto.isVisible() and page.fold_auto.height() > 0)   # ainda não: a linha está lá
        self.assertOneWay(self._heights(page, 1.8))
        self.assertTrue(page.fold_auto.isVisible())
        self.assertEqual(page.city_list.count(), 1)
        page.close()

    def test_add_from_search_folds_results_with_the_new_row(self):
        page = self._page()
        page._last_query_places = [ws.Place(n, -8.0 - i, -34.9, "Brasil") for i, n in enumerate(("Recife", "Olinda", "Natal"))]
        page._show_results(page._last_query_places)
        self._pump(0.1)
        page._result_buttons[0].click()
        self.assertOneWay(self._heights(page, 0.7))
        self.assertFalse(page.fold_results.isVisible())
        self.assertEqual(page._result_buttons, [])
        page.close()

    def test_instant_without_animations(self):
        from app.hub.components import city_list as mod
        orig = mod.animations_enabled
        mod.animations_enabled = lambda: False
        try:
            page = self._page()
            page._on_add_auto()
            self.assertFalse(page.fold_auto.isVisible())
            self.assertFalse(page.fold_auto.is_animating())
            page.city_list._rows[1].btn_remove.click()
            self.assertTrue(page.fold_auto.isVisible())
            self.assertFalse(page.fold_auto.is_animating())
            page.close()
        finally:
            mod.animations_enabled = orig


class TestDotWave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_wave_values_from_prototype(self):
        self.assertEqual((mo.WAVE_DUR, mo.WAVE_GAP, mo.WAVE_BAND), (0.750, 5.0, 0.35))

    def test_wave_moves_from_top_left_to_bottom_right(self):
        from app.widgets.weather.card_painter import paint_dot_wave
        img = QImage(300, 262, QImage.Format.Format_ARGB32_Premultiplied)

        def lit(progress, x, y):
            img.fill(QColor(0, 0, 0, 0))
            p = QPainter(img)
            paint_dot_wave(p, QRectF(0, 0, 300, 262), progress)
            p.end()
            # algum ponto aceso num quadrado 12x12 em volta de (x, y)
            return any(img.pixelColor(x + dx, y + dy).alpha() > 0 for dx in range(-6, 6) for dy in range(-6, 6))

        # A frente acelera e desacelera (cúbica), como no protótipo
        self.assertTrue(lit(0.35, 30, 30))      # começo: canto superior esquerdo
        self.assertFalse(lit(0.35, 270, 235))
        self.assertTrue(lit(0.65, 270, 235))    # fim: canto inferior direito
        self.assertFalse(lit(0.65, 30, 30))
        self.assertFalse(lit(0.0, 150, 130))   # antes e depois da onda: nada
        self.assertFalse(lit(1.0, 150, 130))


@unittest.skipUnless(sys.platform == "win32", "ordem Z do Windows")
class TestShowDesktopGuard(unittest.TestCase):
    """Fixado, o cartão volta para logo acima do desktop quando sai do lugar (o que o Win+D faz), como o Rainmeter."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from app.core import desktop_layer
        if not desktop_layer.desktop_host():
            self.skipTest("sem janela de desktop (sessão sem Explorer)")
        self._saved = dict(config_manager._data.get("weather_widget", {}))
        self._orig_save = config_manager._save
        config_manager._save = lambda *a, **k: None
        config_manager._data["weather_widget"] = {"desktop_mode": True}
        from app.widgets.weather.weather_card import WeatherCard
        self.card = WeatherCard(desktop_mode=True)

    def tearDown(self):
        self.card.close()
        self.card.deleteLater()
        QCoreApplication.processEvents()
        config_manager._data["weather_widget"] = self._saved
        config_manager._save = self._orig_save

    def _pump(self, sec=0.3):
        end = time.time() + sec
        while time.time() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)

    def test_guard_runs_only_while_pinned_and_visible(self):
        guard = self.card.pin_guard()
        self.assertFalse(guard.is_running())
        self.card.show()
        self._pump(0.2)
        self.assertTrue(guard.is_running())
        self.card.hide()
        self.assertFalse(guard.is_running())

    def test_card_left_above_an_app_goes_back_down(self):
        """Depois de voltar do Win+D o cartão pode ficar por cima dos apps: o vigia o devolve ao nível do desktop."""
        import ctypes
        from PySide6.QtWidgets import QWidget
        from app.core import desktop_layer
        self.card.show()
        self._pump(0.3)
        hwnd = int(self.card.winId())
        self.assertTrue(desktop_layer.z_order_above_desktop(hwnd))
        self.assertFalse(desktop_layer.needs_replace(hwnd))

        other = QWidget()
        other.setGeometry(100, 100, 200, 150)
        other.show()
        self._pump(0.2)
        # Põe o app logo ABAIXO do cartão: cartão, app, desktop — o cartão "por cima de um app"
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos(int(other.winId()), hwnd, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        self.assertTrue(desktop_layer.needs_replace(hwnd))

        guard = self.card.pin_guard()
        before = guard.replacements
        self._pump(0.6)   # a checagem de 250 ms resolve sozinha
        self.assertGreater(guard.replacements, before)
        self.assertTrue(desktop_layer.z_order_above_desktop(hwnd))
        self.assertFalse(desktop_layer.needs_replace(hwnd))
        other.close()


@unittest.skipUnless(sys.platform == "win32", "Win+D é do Windows")
class TestUnpinnedShowDesktop(unittest.TestCase):
    """Sem fixar, o cartão some com o Win+D (como as janelas) e volta depois; fechado no meio, fica fechado."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._saved = dict(config_manager._data.get("weather_widget", {}))
        self._orig_save = config_manager._save
        config_manager._save = lambda *a, **k: None
        config_manager._data["weather_widget"] = {}
        from app.widgets.weather.weather_controller import WeatherWidgetController
        self.ctrl = WeatherWidgetController()
        self.ctrl.service.refresh = lambda *a, **k: None

    def tearDown(self):
        self.ctrl.skin.forget_show_desktop()
        self.ctrl.skin.close()
        self.ctrl.skin.deleteLater()
        QCoreApplication.processEvents()
        config_manager._data["weather_widget"] = self._saved
        config_manager._save = self._orig_save

    def _pump(self, sec=0.4):
        end = time.time() + sec
        while time.time() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)

    def test_hides_and_comes_back(self):
        from app.core.show_desktop_watcher import show_desktop_watcher
        card = self.ctrl.skin
        self.ctrl.show()
        self._pump()
        self.assertTrue(show_desktop_watcher().is_running())
        card._on_show_desktop(True)
        self._pump()
        self.assertFalse(card.isVisible())
        self.assertTrue(card.is_suspended_by_show_desktop())
        self.assertTrue(show_desktop_watcher().is_running())   # continua escutando para saber quando voltar
        card._on_show_desktop(False)
        self._pump()
        self.assertTrue(card.isVisible())
        self.assertFalse(card.is_suspended_by_show_desktop())

    def test_closed_during_show_desktop_stays_closed(self):
        card = self.ctrl.skin
        self.ctrl.show()
        self._pump()
        card._on_show_desktop(True)
        self._pump()
        self.ctrl.hide()
        card._on_show_desktop(False)
        self._pump()
        self.assertFalse(card.isVisible())

    def test_pinned_card_ignores_show_desktop(self):
        card = self.ctrl.skin
        self.ctrl.set_desktop_mode(True)
        self.ctrl.show()
        self._pump(1.0)
        card._on_show_desktop(True)   # fixado não escuta, mas mesmo se o sinal chegar não esconde
        self._pump()
        self.assertTrue(card.isVisible())


class _HideWatcher(QObject):
    def __init__(self, sink: list):
        super().__init__()
        self.sink = sink

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Hide:
            self.sink.append(obj)
        return False


class TestResizeAndDesktopLayer(unittest.TestCase):
    """Arrastar o canto redimensiona e salva; "Fixar na área de trabalho" deixa a janela logo acima do desktop."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self._saved = dict(config_manager._data.get("weather_widget", {}))
        self._orig_save = config_manager._save
        config_manager._save = lambda *a, **k: None
        config_manager._data["weather_widget"] = {}
        from app.widgets.weather.weather_controller import WeatherWidgetController
        self.ctrl = WeatherWidgetController()
        self.ctrl.service.refresh = lambda *a, **k: None

    def tearDown(self):
        self.ctrl.skin.close()
        self.ctrl.skin.deleteLater()
        QCoreApplication.processEvents()
        config_manager._data["weather_widget"] = self._saved
        config_manager._save = self._orig_save

    def _pump(self, sec=0.2):
        end = time.time() + sec
        while time.time() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)

    def test_drag_corner_resizes_and_saves(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        card = self.ctrl.skin
        card.show()
        self._pump()
        r = card.card_rect()
        grip = QPoint(int(r.right() - 6), int(r.bottom() - 6))
        origin = card.card_origin()
        QTest.mousePress(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)
        QTest.mouseMove(card, grip + QPoint(60, 60))
        expected = 1.0 + (60 / 300 + 60 / 262) / 2
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip + QPoint(60, 60))
        self.assertAlmostEqual(card.scale(), expected, places=2)
        self.assertAlmostEqual(config_manager.get_weather("scale"), expected, places=2)
        self.assertEqual(card.card_origin(), origin)   # cresce a partir do canto superior esquerdo

    def test_grip_is_not_the_friday_tab(self):
        card = self.ctrl.skin
        self.assertTrue(card._on_grip(QPointF(296, 258)))
        self.assertFalse(card._on_grip(tab_rect(4).center()))
        self.assertFalse(card._on_grip(QPointF(150, 100)))

    @unittest.skipUnless(sys.platform == "win32", "ordem Z do Windows")
    def test_desktop_mode_keeps_card_under_other_windows(self):
        from PySide6.QtWidgets import QWidget
        from app.core import desktop_layer
        if not desktop_layer.desktop_host():
            self.skipTest("sem janela de desktop (sessão sem Explorer)")
        card = self.ctrl.skin
        card.show()
        self._pump(0.3)
        hwnd = int(card.winId())
        import ctypes
        self.assertTrue(ctypes.windll.user32.GetWindowLongW(hwnd, -20) & 0x8, "começa sempre no topo")

        hidden = []
        watcher = _HideWatcher(hidden)
        card.installEventFilter(watcher)   # registra qualquer Hide durante a troca
        self.ctrl.set_desktop_mode(True)
        self.assertTrue(config_manager.get_weather("desktop_mode"))
        if card.wave_progress(card.now()) is not None:   # com efeitos ligados: a troca espera o meio da onda
            self.assertTrue(ctypes.windll.user32.GetWindowLongW(hwnd, -20) & 0x8, "ainda no topo no início da onda")
        self._pump(1.0)
        self.assertIsNone(card.wave_progress(card.now()))
        # Mesma janela nativa, nunca escondida: é o que tirava o quadro preto ao trocar de modo
        self.assertEqual(int(card.winId()), hwnd)
        self.assertEqual(hidden, [])
        self.assertTrue(desktop_layer.z_order_above_desktop(hwnd))

        other = QWidget()
        other.setGeometry(card.geometry())
        other.show()
        other.raise_()
        self._pump(0.2)
        card.raise_()
        card.activateWindow()   # clicar/ativar o cartão não pode trazê-lo para a frente
        self._pump(0.3)
        self.assertTrue(desktop_layer.z_order_above_desktop(hwnd))
        other.close()

        self.ctrl.set_desktop_mode(False)   # volta a ser "sempre no topo"
        self._pump(1.0)
        self.assertEqual(int(card.winId()), hwnd)
        self.assertEqual(hidden, [])
        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        self.assertTrue(ex_style & 0x8, "WS_EX_TOPMOST")
        card.removeEventFilter(watcher)


if __name__ == "__main__":
    unittest.main()
