"""Testes da localização do Windows (WinRT) + geocodificação reversa (Nominatim) + fallback silencioso para IP."""

import copy
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.services import weather_service as ws


def _wait_for(predicate, timeout_s: float = 2.0) -> bool:
    end = time.time() + timeout_s
    while time.time() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


_SAMPLE_FORECAST = {
    "elevation": 820.0,
    "current": {"temperature_2m": 22.5, "weather_code": 1, "is_day": 1},
    "daily": {
        "time": ["2026-11-26", "2026-11-27", "2026-11-28", "2026-11-29", "2026-11-30"],
        "weather_code": [1, 2, 3, 61, 0],
        "temperature_2m_max": [26.0, 27.0, 24.0, 21.0, 25.0],
        "temperature_2m_min": [15.0, 16.0, 14.0, 13.0, 14.0],
    },
}


class TestNominatimReverseAndRounding(unittest.TestCase):
    def test_round_coords_to_two_decimals(self):
        self.assertEqual(ws.round_coords(-22.9519123, -46.5419876), (-22.95, -46.54))

    def test_nominatim_reverse_url_sends_rounded_coords(self):
        url = ws.nominatim_reverse_url(-22.9519123, -46.5419876, "pt")
        self.assertIn("lat=-22.95", url)
        self.assertIn("lon=-46.54", url)
        self.assertNotIn("9519", url)
        self.assertNotIn("5419", url)

    def test_parse_nominatim_reverse_city_town_village_municipality(self):
        for field_name, city_name in (
            ("city", "Bragança Paulista"),
            ("town", "Joanópolis"),
            ("village", "Monte Verde"),
            ("municipality", "Extrema"),
        ):
            data = {"address": {field_name: city_name, "state": "São Paulo", "country": "Brasil"}}
            place = ws.parse_nominatim_reverse(data, -22.9519, -46.5419)
            self.assertIsNotNone(place)
            self.assertEqual(place.name, city_name)
            self.assertEqual((place.lat, place.lon), (-22.95, -46.54))
            self.assertEqual(place.detail, "São Paulo, Brasil")

    def test_parse_nominatim_reverse_rejects_empty_or_error(self):
        self.assertIsNone(ws.parse_nominatim_reverse({"error": "Unable to geocode"}, -22.95, -46.54))
        self.assertIsNone(ws.parse_nominatim_reverse({"address": {}}, -22.95, -46.54))


class TestWindowsLocationOptInAndFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._saved = copy.deepcopy(config_manager._data)
        self._orig_save = config_manager._save
        config_manager._save = lambda: None
        config_manager._data["weather_widget"] = {
            "cities": [{"kind": ws.AUTO}],
            "current_city": 0,
            "cache_by_city": {},
            "auto_location": None,
            "auto_location_at": 0.0,
            "windows_location_consent": None,
            "auto_location_source": None,
        }

    def tearDown(self):
        config_manager._data = self._saved
        config_manager._save = self._orig_save

    def test_no_consent_never_calls_windows_location(self):
        svc = ws.WeatherService()
        called_win = []
        reports = []
        svc.reports_ready.connect(reports.append)

        def fake_get(url):
            if url == ws.IP_LOCATION_URL:
                return {"city": "São Paulo", "latitude": -23.55, "longitude": -46.63, "region": "SP", "country_name": "Brasil"}
            return _SAMPLE_FORECAST

        with patch.object(ws, "_request_windows_location", side_effect=lambda p, cb: (called_win.append(1), cb(None))), \
             patch.object(ws, "_http_get_json", side_effect=fake_get), \
             patch.object(ws, "_metar_get_json", return_value=[]):
            svc.refresh(force=True)
            self.assertTrue(_wait_for(lambda: bool(reports)))

        self.assertEqual(called_win, [])
        self.assertEqual(svc.auto_place().name, "São Paulo")
        self.assertEqual(svc.auto_location_source(), ws.AUTO_SOURCE_IP)

    def test_consent_uses_windows_location_and_stores_rounded_coords(self):
        config_manager._data["weather_widget"]["windows_location_consent"] = True
        svc = ws.WeatherService()
        reports = []
        svc.reports_ready.connect(reports.append)
        seen_urls = []

        def fake_get(url):
            seen_urls.append(url)
            if url.startswith(ws.NOMINATIM_REVERSE_URL):
                return {"address": {"city": "Bragança Paulista", "state": "São Paulo", "country": "Brasil"}}
            return _SAMPLE_FORECAST

        with patch.object(ws, "_request_windows_location", side_effect=lambda p, cb: cb((-22.95, -46.54))), \
             patch.object(ws, "_nominatim_throttle", return_value=None), \
             patch.object(ws, "_http_get_json", side_effect=fake_get), \
             patch.object(ws, "_metar_get_json", return_value=[]):
            svc.refresh(force=True)
            self.assertTrue(_wait_for(lambda: bool(reports)))

        place = svc.auto_place()
        self.assertEqual(place.name, "Bragança Paulista")
        self.assertEqual((place.lat, place.lon), (-22.95, -46.54))
        self.assertEqual(svc.auto_location_source(), ws.AUTO_SOURCE_WINDOWS)
        self.assertFalse(svc.windows_location_failed())
        self.assertTrue(any(u.startswith(ws.NOMINATIM_REVERSE_URL) for u in seen_urls))

    def test_windows_location_denied_falls_back_quietly_to_ip_and_flags_hint(self):
        config_manager._data["weather_widget"]["windows_location_consent"] = True
        svc = ws.WeatherService()
        reports = []
        svc.reports_ready.connect(reports.append)

        def fake_get(url):
            if url == ws.IP_LOCATION_URL:
                return {"city": "São Paulo", "latitude": -23.55, "longitude": -46.63, "region": "SP", "country_name": "Brasil"}
            return _SAMPLE_FORECAST

        with patch.object(ws, "_request_windows_location", side_effect=lambda p, cb: cb(None)), \
             patch.object(ws, "_http_get_json", side_effect=fake_get), \
             patch.object(ws, "_metar_get_json", return_value=[]):
            svc.refresh(force=True)
            self.assertTrue(_wait_for(lambda: bool(reports)))

        self.assertEqual(svc.auto_place().name, "São Paulo")
        self.assertEqual(svc.auto_location_source(), ws.AUTO_SOURCE_IP)
        self.assertTrue(svc.windows_location_failed())


if __name__ == "__main__":
    unittest.main()
