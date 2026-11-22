"""Testes unitários para o Storage Widget e para a skin Nothing Hourly do Weather Widget."""

import os
from unittest import mock

import pytest
from PySide6.QtCore import QEvent, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])

from app.core.refresh_rate import MAX_HZ, refresh_interval_ms
from app.services.storage_service import (
    DriveUsage,
    FolderUsage,
    StorageSnapshot,
    compute_snapshot,
    scan_folder_usage,
)
from app.services.weather_service import HourForecast, WeatherReport, DayForecast, parse_forecast
from app.widgets.storage.card_painter import paint_storage_card
from app.widgets.storage.card_state import CARD_W, COMPACT_H, StorageState
from app.widgets.storage.specs import init_storage_spec, paint_storage
from app.widgets.storage.storage_card import StorageCard
from app.widgets.weather import font_skins
from app.widgets.weather.specs import mock_state as weather_mock_state, paint_weather
from app.widgets.weather.weather_controller import build_hours


# --- Feature 1: Weather Nothing Hourly ---


def test_midnight_skin_registered():
    ids = [s.id for s in font_skins.discover()]
    assert font_skins.NOTHING_DOT_SKIN in ids
    assert font_skins.MIDNIGHT_SKIN in ids
    assert font_skins.is_nothing_skin(font_skins.NOTHING_DOT_SKIN) is True
    assert font_skins.is_nothing_skin(font_skins.MIDNIGHT_SKIN) is False
    assert font_skins.is_nothing_skin(font_skins.DEFAULT_SKIN) is False
    assert font_skins.skin_by_id("nothing_hourly").id == font_skins.MIDNIGHT_SKIN


def test_parse_forecast_extracts_hourly_and_preserves_compat():
    times = [f"2026-11-20T{h:02d}:00" for h in range(24)]
    data = {
        "current": {"time": "2026-11-20T13:00", "temperature_2m": 24.2, "weather_code": 0, "is_day": 1},
        "daily": {
            "time": ["2026-11-20"],
            "weather_code": [0],
            "temperature_2m_max": [28.0],
            "temperature_2m_min": [17.0],
            "temperature_2m_mean": [22.0],
        },
        "hourly": {
            "time": times,
            "weather_code": [0 if 6 <= h < 19 else 1 for h in range(24)],
            "temperature_2m": [17.0 + (h % 12) for h in range(24)],
            "is_day": [1 if 6 <= h < 19 else 0 for h in range(24)],
        },
    }
    rep = parse_forecast(data, "São Paulo", 100.0)
    assert len(rep.hours) == 24
    assert rep.current_time == "2026-11-20T13:00"

    slots = build_hours(rep, "c")
    assert len(slots) == 5
    assert [s.short for s in slots[1:]] == ["16h", "19h", "22h", "01h"] or slots[1].short == "16h"
    assert slots[0].hi == 28 and slots[0].lo == 17

    # Roundtrip cache serialization
    restored = WeatherReport.from_dict(rep.to_dict())
    assert restored is not None
    assert len(restored.hours) == 24

    # Backward compatibility when old cache lacks `hours`
    old_dict = rep.to_dict()
    old_dict.pop("hours")
    old_dict.pop("current_time")
    old_rep = WeatherReport.from_dict(old_dict)
    assert old_rep is not None and old_rep.hours == []
    fallback_slots = build_hours(old_rep, "c")
    assert len(fallback_slots) == 5


def test_midnight_preview_renders(qapp):
    st = weather_mock_state(skin_id=font_skins.MIDNIGHT_SKIN)
    assert len(st.days) == 5
    assert st.days[1].short == "16h"
    img = QImage(320, 280, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    paint_weather(p, QRectF(0, 0, 320, 280), st)
    p.end()


# --- Feature 2: Storage Service & Widget ---


def test_scan_folder_usage_counts_files_and_skips_missing(tmp_path):
    sub = tmp_path / "roms"
    sub.mkdir()
    (tmp_path / "a.bin").write_bytes(b"x" * 1024)
    (sub / "b.bin").write_bytes(b"y" * 2048)

    size_b, count, ok = scan_folder_usage(str(tmp_path))
    assert ok is True
    assert size_b == 3072
    assert count == 2

    miss_b, miss_c, miss_ok = scan_folder_usage(str(tmp_path / "does_not_exist"))
    assert miss_ok is False and miss_b == 0 and miss_c == 0


def test_compute_snapshot_groups_by_drive(tmp_path):
    f1 = tmp_path / "Downloads"
    f2 = tmp_path / "Emulators"
    f1.mkdir()
    f2.mkdir()
    (f1 / "file1.bin").write_bytes(b"0" * 4096)
    (f2 / "rom.nsp").write_bytes(b"1" * 8192)

    snap = compute_snapshot([
        {"name": "Downloads", "path": str(f1)},
        {"name": "Emulators", "path": str(f2)},
    ])
    assert len(snap.drives) == 1
    assert len(snap.drives[0].folders) == 2
    assert snap.drives[0].total_bytes > 0
    # Sorted biggest -> smallest (Emulators 8192B before Downloads 4096B)
    assert [f.name for f in snap.drives[0].folders] == ["Emulators", "Downloads"]
    restored = StorageSnapshot.from_dict(snap.to_dict())
    assert restored is not None
    assert restored.drives[0].folders[0].name == "Emulators"


def test_game_library_scanner_steam_and_epic(tmp_path):
    import json
    from app.services.game_library_scanner import scan_epic_libraries, scan_steam_libraries

    # Steam library with 2 ACF manifests
    steam_root = tmp_path / "Steam"
    steamapps = steam_root / "steamapps"
    (steamapps / "common").mkdir(parents=True)
    (steamapps / "appmanifest_100.acf").write_text('"AppState"\n{\n\t"SizeOnDisk"\t\t"5000000000"\n}\n', encoding="utf-8")
    (steamapps / "appmanifest_200.acf").write_text('"AppState"\n{\n\t"SizeOnDisk"\t\t"3000000000"\n}\n', encoding="utf-8")

    steam_libs = scan_steam_libraries(str(steam_root))
    assert len(steam_libs) == 1
    assert steam_libs[0].store == "Steam"
    assert steam_libs[0].size_bytes == 8_000_000_000
    assert steam_libs[0].game_count == 2

    # Epic manifests dir (1 complete + 1 incomplete ignored)
    epic_manifests = tmp_path / "EpicManifests"
    epic_manifests.mkdir()
    game_dir = tmp_path / "EpicGames" / "Hades"
    game_dir.mkdir(parents=True)
    (epic_manifests / "hades.item").write_text(json.dumps({
        "InstallLocation": str(game_dir),
        "InstallSize": 12_000_000_000,
        "bIsIncompleteInstall": False,
    }), encoding="utf-8")
    (epic_manifests / "partial.item").write_text(json.dumps({
        "InstallLocation": str(game_dir),
        "InstallSize": 9_000_000_000,
        "bIsIncompleteInstall": True,
    }), encoding="utf-8")

    epic_libs = scan_epic_libraries(str(epic_manifests))
    assert len(epic_libs) == 1
    assert epic_libs[0].store == "Epic Games"
    assert epic_libs[0].size_bytes == 12_000_000_000
    assert epic_libs[0].game_count == 1


def test_storage_state_spring_expand_collapse_and_no_anim():
    gb = 1024 ** 3
    snap = StorageSnapshot(drives=[
        DriveUsage(
            drive="D:",
            label="Secondary SSD (D:)",
            total_bytes=int(931 * gb),
            used_bytes=int(640 * gb),
            folders=[
                FolderUsage("Emulators", "D:\\Emulators", "D:", int(312 * gb), 1000),
                FolderUsage("Videos", "D:\\Videos", "D:", int(118 * gb), 90),
                FolderUsage("Downloads", "D:\\Downloads", "D:", int(64 * gb), 400),
                FolderUsage("Mods", "D:\\Mods", "D:", int(48 * gb), 5000),
            ],
        )
    ])

    # Animated expansion moves smoothly and settles
    st = StorageState(animated=True, always_expanded=False)
    st.apply_snapshot(snap, animate=False)
    assert st.card_h.x == pytest.approx(COMPACT_H)

    assert st.set_expanded(True, animate=True) is True
    target_h = st.target_card_height()
    assert target_h > COMPACT_H
    assert st.busy() is True

    # Step 1 frame -> in-flight (did not jump immediately)
    st.step(1 / 120.0)
    assert COMPACT_H < st.card_h.x < target_h

    # Step to settle
    for _ in range(240):
        st.step(1 / 120.0)
    assert st.card_h.x == pytest.approx(target_h, abs=0.5)
    assert st.busy() is False

    # Always expanded blocks collapse
    st.set_always_expanded(True, animate=False)
    assert st.set_expanded(False, animate=True) is False
    assert st.expanded is True

    # Non-animated mode snaps immediately
    st_fast = StorageState(animated=False, always_expanded=False)
    st_fast.apply_snapshot(snap, animate=False)
    st_fast.set_expanded(True, animate=True)
    assert st_fast.card_h.x == pytest.approx(st_fast.target_card_height())
    assert st_fast.busy() is False


def test_storage_card_paint_outside_collapse_and_240hz_cap(qapp):
    card = StorageCard(scale=1.0, desktop_mode=False, always_expanded=False)
    assert card.card_size() == (int(CARD_W), int(COMPACT_H))

    # Paint dark, light & true_dark (OLED) and verify palette surfaces match HubTheme
    from app.hub.theme import THEME_DARK, THEME_LIGHT, THEME_TRUE_DARK
    from app.widgets.storage.card_painter import (
        PALETTE_DARK,
        PALETTE_LIGHT,
        PALETTE_TRUE_DARK,
        resolve_storage_palette,
    )
    from app.widgets.storage.storage_card import card_theme, invalidate_card_theme

    assert PALETTE_LIGHT.surface.name().lower() == THEME_LIGHT.panel.lower()
    assert PALETTE_DARK.surface.name().lower() == THEME_DARK.bg.lower()
    assert PALETTE_TRUE_DARK.surface.name().lower() == THEME_TRUE_DARK.bg.lower()
    assert resolve_storage_palette(theme=THEME_LIGHT) == PALETTE_LIGHT
    assert resolve_storage_palette(theme=THEME_DARK) == PALETTE_DARK
    assert resolve_storage_palette(theme=THEME_TRUE_DARK) == PALETTE_TRUE_DARK

    for mode_pref, expected_mode in (("light", "light"), ("dark", "dark"), ("true_dark", "true_dark")):
        with mock.patch("app.widgets.storage.storage_card.config_manager.get_hub_theme", return_value=mode_pref):
            invalidate_card_theme()
            assert card_theme() == expected_mode

    with mock.patch("app.widgets.storage.storage_card.config_manager.get_hub_theme", return_value="system"), \
         mock.patch("app.hub.theme.get_windows_system_theme", return_value="dark"):
        invalidate_card_theme()
        assert card_theme() == "dark"

    img = QImage(320, 320, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    paint_storage(p, QRectF(0, 0, 320, 320), theme=THEME_DARK)
    paint_storage(p, QRectF(0, 0, 320, 320), theme=THEME_TRUE_DARK)
    paint_storage_card(p, QRectF(0, 0, 300, 262), card.state, light=True)
    p.end()

    # Spec registered
    spec = init_storage_spec()
    assert spec.id == "storage"

    # Refresh rate cap at 240 Hz -> 4 ms
    fake_screen = mock.Mock()
    fake_screen.refreshRate.return_value = 360.0
    with mock.patch.object(card, "screen", return_value=fake_screen):
        assert refresh_interval_ms(card) == max(4, int(round(1000.0 / MAX_HZ)))

    # Outside deactivate collapses when always_expanded=False
    card.show()
    card.set_expanded(True)
    assert card.state.expanded is True
    card.eventFilter(card, QEvent(QEvent.Type.ApplicationDeactivate))
    assert card.state.expanded is False

    # Always expanded stays open on deactivate
    card.set_always_expanded(True)
    assert card.state.expanded is True
    card.eventFilter(card, QEvent(QEvent.Type.ApplicationDeactivate))
    assert card.state.expanded is True

    # Clicking chevron still works after a prior drag (`_dragged` left True by FloatingCard)
    card.set_always_expanded(False)
    card.set_expanded(False)
    card._dragged = True
    card._drag_offset = None
    from app.widgets.storage.card_painter import EXPAND_BTN_RECT
    assert card._on_card_press(EXPAND_BTN_RECT.center()) is True
    assert card._on_card_release(EXPAND_BTN_RECT.center()) is True
    assert card.state.expanded is True
    assert card._on_card_press(EXPAND_BTN_RECT.center()) is True
    assert card._on_card_release(EXPAND_BTN_RECT.center()) is True
    assert card.state.expanded is False

    # Context menu builds cleanly with FluentMusicMenu + ActionBarItem
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from app.ui_components.fluent_menu import FluentMusicMenu

    with mock.patch.object(FluentMusicMenu, "exec", return_value=None) as m_exec:
        card.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20)))
        assert m_exec.called
    card.close()


def test_storage_page_and_hub_startup(qapp):
    from app.hub.storage_page import StoragePage
    from app.hub.theme import THEME_DARK, THEME_LIGHT

    page = StoragePage(theme=THEME_DARK)
    page.set_theme(THEME_LIGHT)
    page.retranslate_ui()
    page._sync_size()
    page._sync_always_expanded(True)
    page._sync_always_expanded(False)
    page.close()


def test_anchor_inherits_target_group_gap():
    from app.core import anchor_geometry as geo
    from app.core.anchor_manager import AnchorManager, Group

    g_target = Group(geo.Join("weather", "performance", "x", 0, 0.0, 24.0))
    g_single = Group("storage")
    g_other = Group(geo.Join("music", "timer", "y", 0, 0.0, 4.0))

    # Single widget attaching to a group inherits target's 24 px gap
    assert AnchorManager._inherited_gap(g_single, g_target) == pytest.approx(24.0)
    # Group attaching to a single widget keeps its own 24 px gap
    assert AnchorManager._inherited_gap(g_target, g_single) == pytest.approx(24.0)
    # Group attaching to another group inherits target's 24 px gap
    assert AnchorManager._inherited_gap(g_other, g_target) == pytest.approx(24.0)
    # Two single widgets inherit align_prefs.gap when set, otherwise default GAP
    with mock.patch("app.core.anchor_manager.config_manager.get_anchor", return_value={"gap": 4}):
        assert AnchorManager._inherited_gap(g_single, Group("music")) == pytest.approx(4.0)
    with mock.patch("app.core.anchor_manager.config_manager.get_anchor", return_value=None):
        assert AnchorManager._inherited_gap(g_single, Group("music")) == pytest.approx(geo.GAP)


def test_metar_observation_altitude_and_fallbacks():
    from app.services import weather_service as ws

    # WMO mapping from METAR wxString & cover
    assert ws.metar_to_wmo_code(None, "FEW", 80) == 1
    assert ws.metar_to_wmo_code(None, "SCT", 80) == 2
    assert ws.metar_to_wmo_code(None, "OVC", 0) == 3
    assert ws.metar_to_wmo_code(None, "CLR", 61) == 0
    assert ws.metar_to_wmo_code("-RA", "OVC", 0) == 61
    assert ws.metar_to_wmo_code("+TSRA", "BKN", 0) == 95
    assert ws.metar_to_wmo_code("FG", "OVC", 0) == 45

    # Nearest METAR filtering (ignores stale and too-far stations)
    now = 1_795_378_000.0
    stations = [
        {"icaoId": "FAR1", "lat": -20.0, "lon": -46.5, "temp": 33, "obsTime": now - 300},
        {"icaoId": "OLD1", "lat": -22.95, "lon": -46.54, "temp": 18, "obsTime": now - 7200},
        {"icaoId": "SBGR", "lat": -23.432, "lon": -46.469, "elev": 745, "temp": 30, "cover": "FEW", "obsTime": now - 600},
    ]
    nearest = ws.pick_nearest_metar(stations, -22.9519, -46.5419, now)
    assert nearest is not None and nearest["icaoId"] == "SBGR"

    # Altitude lapse-rate adjustment (30°C at 745m -> 29.4°C at 841m) + high/low clamp
    rep = WeatherReport(
        place="Bragança Paulista",
        current_temp=22.3,
        current_code=80,
        is_day=True,
        days=[DayForecast("2026-11-22", 80, 28.0, 20.0, 24.0)],
    )
    ws.apply_metar_observation(rep, nearest, city_elev=841.0)
    assert rep.current_temp == pytest.approx(29.4, abs=0.1)
    assert rep.current_code == 1
    assert rep.days[0].t_max == pytest.approx(29.4, abs=0.1)

    # Nominatim fallback parser
    nom = ws.parse_nominatim([
        {"lat": "-22.9519", "lon": "-46.5419", "address": {"municipality": "Bragança Paulista", "state": "São Paulo", "country": "Brasil"}},
    ])
    assert len(nom) == 1
    assert nom[0].name == "Bragança Paulista"
    assert "São Paulo" in nom[0].detail

    # ipwho.is fallback parser
    ipw = ws.parse_ipwho_location({"success": True, "city": "Campinas", "latitude": -22.9, "longitude": -47.06, "region": "São Paulo", "country": "Brazil"})
    assert ipw is not None and ipw.name == "Campinas"
    assert ws.parse_ipwho_location({"success": False}) is None



