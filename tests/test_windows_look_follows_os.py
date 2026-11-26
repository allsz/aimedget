"""O visual "Windows" dos flyouts de Caps/Num Lock e Volume segue o modo claro/escuro do WINDOWS, não o do app.

É a exceção: o resto (Hub, tema "Aimedget", Timer, cartões) segue o app. Com o app fixo em escuro e o Windows no claro,
esses dois flyouts ficam claros, e trocam ao vivo (com a dissolvência de modo) quando o Windows troca.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtWidgets import QApplication

from app.core import theme_crossfade as tc
from app.core.config_manager import config_manager
from app.core.theme_loader import APP_ID, DEFAULT_ID
from app.hub.theme import contrast_ratio
from app.widgets.keylock_osd import theme as kl_theme
from app.widgets.volume_mixer import theme as mx_theme

THEMES = [kl_theme, mx_theme]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def isolated():
    """Config num diretório temporário, com o visual "Windows" escolhido nos dois flyouts."""
    tmp = tempfile.TemporaryDirectory()
    old = (config_manager.config_dir, config_manager.config_path, config_manager._data.get("themes"))
    config_manager.config_dir = tmp.name
    config_manager.config_path = os.path.join(tmp.name, "settings.json")
    config_manager._data["themes"] = {"keylock": DEFAULT_ID, "mixer": DEFAULT_ID}
    for module in THEMES:
        module.loader.reset()
        module.loader._preview_cache.clear()
    yield
    config_manager.config_dir, config_manager.config_path = old[0], old[1]
    config_manager._data.pop("themes", None)
    if old[2] is not None:
        config_manager._data["themes"] = old[2]
    for module in THEMES:
        module.loader.reset()
    tmp.cleanup()


def _os(mode: str):
    return mock.patch("app.hub.theme.get_windows_system_theme", return_value=mode)


def _app(mode: str):
    return mock.patch.object(config_manager, "get_hub_theme", return_value=mode)


def _pump(seconds: float):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.005)


# --- Segue o Windows, não o app ---

@pytest.mark.parametrize("module", THEMES, ids=["keylock", "mixer"])
@pytest.mark.parametrize("app_mode", ["light", "dark", "true_dark", "system"])
def test_windows_look_follows_the_os_whatever_the_app_says(isolated, module, app_mode):
    with _app(app_mode):
        with _os("light"):
            assert module.default_theme() is module.LIGHT_DEFAULT_THEME
            assert module.load_user_theme() is module.LIGHT_DEFAULT_THEME
        with _os("dark"):
            assert module.default_theme() is module.DEFAULT_THEME
            assert module.load_user_theme() is module.DEFAULT_THEME


@pytest.mark.parametrize("module", THEMES, ids=["keylock", "mixer"])
def test_aimedget_theme_still_follows_the_app(isolated, module):
    """Só o visual "Windows" é a exceção: o "Aimedget" continua no modo do app."""
    module.loader.set_active(APP_ID)
    with _app("dark"), _os("light"):
        dark_card = module.load_user_theme().card_bg
    with _app("light"), _os("light"):
        light_card = module.load_user_theme().card_bg
    assert dark_card.lightness() < 128 < light_card.lightness()


@pytest.mark.parametrize("module", THEMES, ids=["keylock", "mixer"])
def test_folder_themes_do_not_change_with_the_os(isolated, module):
    folder = os.path.join(module.loader.themes_dir(), "neon")
    os.makedirs(folder)
    with open(os.path.join(folder, "theme.json"), "w", encoding="utf-8") as f:
        f.write('{"name": "Neon"}')
    module.loader.set_active("neon")
    with _app("dark"), _os("dark"):   # app fixo: com ele em "Sistema", o modo do app também mudaria
        dark = module.load_user_theme()
    with _app("dark"), _os("light"):
        light = module.load_user_theme()
    assert dark is light                                     # nem relido: o mesmo objeto
    assert dark.card_bg == module.DEFAULT_THEME.card_bg      # parte do visual original escuro, como sempre


def test_light_mixer_is_readable():
    th = mx_theme.LIGHT_DEFAULT_THEME
    assert contrast_ratio(th.text.name(), th.card_bg.name()) >= 4.5
    assert contrast_ratio(th.on_accent.name(), th.accent.name()) >= 4.5
    assert contrast_ratio(th.muted_text.name(), th.card_bg.name()) >= 3.0
    assert contrast_ratio(th.accent.name(), th.card_bg.name()) >= 3.0
    # mesmos tons da versão clara do Caps/Num Lock
    kl = kl_theme.LIGHT_DEFAULT_THEME
    assert (th.card_bg, th.border, th.text, th.accent) == (kl.card_bg, kl.border, kl.text, kl.on_color)


# --- Troca ao vivo nos flyouts (com movimento) ---

def _keylock_flyout(qapp):
    from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
    flyout = KeyLockFlyout()
    flyout.resize(200, 80)
    return flyout


def test_visible_keylock_crossfades_on_mode_switch(qapp):
    flyout = _keylock_flyout(qapp)
    flyout.theme = kl_theme.DEFAULT_THEME
    with mock.patch.object(tc, "animations_enabled", return_value=True):
        flyout.show()
        QApplication.processEvents()
        flyout.apply_mode_theme(kl_theme.LIGHT_DEFAULT_THEME)
        layer = flyout._theme_crossfade
        assert layer is not None and layer.is_running()        # anima, não pula
        assert layer._duration == pytest.approx(tc.MODE_DURATION_MS / 1000.0)
        assert layer._shrink == 0.0                             # troca de modo: sem encolher
        assert flyout.theme is kl_theme.LIGHT_DEFAULT_THEME
        _pump(tc.MODE_DURATION_MS / 1000.0 + 0.15)
        assert not layer.is_running()                           # termina limpo
    flyout.hide()
    flyout.deleteLater()


def test_keylock_without_animations_or_hidden_switches_at_once(qapp):
    flyout = _keylock_flyout(qapp)
    flyout.theme = kl_theme.DEFAULT_THEME
    flyout.apply_mode_theme(kl_theme.LIGHT_DEFAULT_THEME)       # escondido
    assert flyout.theme is kl_theme.LIGHT_DEFAULT_THEME
    with mock.patch.object(tc, "animations_enabled", return_value=False):
        flyout.show()
        QApplication.processEvents()
        flyout.apply_mode_theme(kl_theme.DEFAULT_THEME)
        assert getattr(flyout, "_theme_crossfade", None) is None
        assert flyout.theme is kl_theme.DEFAULT_THEME
    flyout.hide()
    flyout.deleteLater()


def test_visible_mixer_uses_the_mode_crossfade(qapp):
    from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout
    flyout = VolumeMixerFlyout()
    with mock.patch.object(tc, "animations_enabled", return_value=True):
        flyout.show()
        QApplication.processEvents()
        flyout._apply_theme(mx_theme.LIGHT_DEFAULT_THEME, mode_switch=True)
        layer = flyout._theme_crossfade
        assert layer is not None and layer.is_running()
        assert layer._duration == pytest.approx(tc.MODE_DURATION_MS / 1000.0)
        assert flyout.theme is mx_theme.LIGHT_DEFAULT_THEME
        _pump(tc.MODE_DURATION_MS / 1000.0 + 0.15)
        assert not layer.is_running()
    flyout.hide()
    flyout.deleteLater()


def test_bridge_hands_the_os_look_to_both_flyouts(isolated):
    from app.hub.service_bridge import HubServiceBridge
    got = {}
    bridge = SimpleNamespace(
        keylock_flyout=SimpleNamespace(apply_mode_theme=lambda th: got.setdefault("keylock", th)),
        volume_flyout=SimpleNamespace(_apply_theme=lambda th, mode_switch=False: got.setdefault("mixer", (th, mode_switch))),
    )
    with _app("dark"), _os("light"):
        HubServiceBridge.on_windows_mode_changed(bridge)
    assert got["keylock"] is kl_theme.LIGHT_DEFAULT_THEME
    assert got["mixer"] == (mx_theme.LIGHT_DEFAULT_THEME, True)


# --- Miniaturas da Visão geral ---

def test_overview_thumbnails_follow_the_os(qapp, isolated):
    from app.hub.pages import OverviewPage
    from app.hub.theme import THEME_DARK
    with _app("dark"), _os("dark"):
        page = OverviewPage(theme=THEME_DARK)
        assert page.keys_card._spec.mock_state().theme is kl_theme.DEFAULT_THEME
        assert page.vol_card._spec.mock_state() is mx_theme.DEFAULT_THEME
        before = page.keys_card._spec
        page.refresh_flyout_cards()
        assert page.keys_card._spec is before                    # nada mudou: não repinta à toa
    with _app("dark"), _os("light"):
        page.refresh_flyout_cards()
        assert page.keys_card._spec.mock_state().theme is kl_theme.LIGHT_DEFAULT_THEME
        assert page.vol_card._spec.mock_state() is mx_theme.LIGHT_DEFAULT_THEME
    page.deleteLater()
