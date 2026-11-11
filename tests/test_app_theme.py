"""Tema embutido "Aimedget": os flyouts herdam modo e cor de destaque do app."""

from dataclasses import replace

import pytest

from app.core import theme_loader
from app.core.app_theme import keylock_theme_from_hub, mixer_theme_from_hub
from app.core.theme_loader import APP_ID, DEFAULT_ID
from app.hub.theme import THEME_DARK, THEME_LIGHT, THEME_TRUE_DARK, contrast_ratio, with_accent
from app.widgets.keylock_osd import theme as keylock_theme
from app.widgets.volume_mixer import theme as mixer_theme


def _hex(color) -> str:
    return color.name()


def test_light_and_dark_backgrounds_follow_the_app():
    assert _hex(mixer_theme_from_hub(THEME_LIGHT).card_bg) == THEME_LIGHT.panel.lower()
    assert _hex(mixer_theme_from_hub(THEME_DARK).card_bg) == THEME_DARK.panel.lower()
    assert _hex(keylock_theme_from_hub(THEME_LIGHT).card_bg) == THEME_LIGHT.panel.lower()
    assert _hex(keylock_theme_from_hub(THEME_TRUE_DARK).card_bg) == THEME_TRUE_DARK.panel.lower()


@pytest.mark.parametrize("base", [THEME_LIGHT, THEME_DARK, THEME_TRUE_DARK])
def test_accent_drives_sliders_switch_and_lock_bar(base):
    hub = with_accent(base, "#2E7D32")
    mixer = mixer_theme_from_hub(hub)
    keys = keylock_theme_from_hub(hub)
    accent = hub.accent.lower()
    assert _hex(mixer.accent) == _hex(mixer.thumb) == _hex(mixer.switch_on) == accent
    assert _hex(keys.on_color) == accent
    assert _hex(mixer.on_accent) == hub.ink.lower()


@pytest.mark.parametrize("base", [THEME_LIGHT, THEME_DARK, THEME_TRUE_DARK])
def test_text_is_readable_on_cards(base):
    mixer = mixer_theme_from_hub(base)
    assert contrast_ratio(_hex(mixer.text), _hex(mixer.card_bg)) >= 4.5
    # O âmbar de fábrica do modo claro (branco sobre #E58A18) é uma escolha do Hub; aqui vale o acento ajustado
    fitted = mixer_theme_from_hub(with_accent(base, "#2E7D32"))
    assert contrast_ratio(_hex(fitted.on_accent), _hex(fitted.accent)) >= 4.5
    keys = keylock_theme_from_hub(base)
    assert contrast_ratio(_hex(keys.text), _hex(keys.card_bg)) >= 4.5


def test_same_hub_theme_gives_same_object_and_change_gives_new_one():
    assert mixer_theme_from_hub(THEME_DARK) is mixer_theme_from_hub(replace(THEME_DARK))
    assert mixer_theme_from_hub(THEME_DARK) is not mixer_theme_from_hub(THEME_LIGHT)


def test_only_colors_are_inherited():
    default = mixer_theme.DEFAULT_THEME
    inherited = mixer_theme_from_hub(THEME_LIGHT)
    assert (inherited.radius, inherited.shadow, inherited.background, inherited.stickers) == \
           (default.radius, default.shadow, default.background, default.stickers)
    kdefault = keylock_theme.DEFAULT_THEME
    kinherited = keylock_theme_from_hub(THEME_LIGHT)
    assert (kinherited.radius, kinherited.scale, kinherited.size) == (kdefault.radius, kdefault.scale, kdefault.size)


@pytest.mark.parametrize("module", [mixer_theme, keylock_theme])
def test_loader_offers_app_theme_and_uses_it_on_fresh_install(module, monkeypatch, tmp_path):
    monkeypatch.setattr(theme_loader.config_manager, "get_theme_choice", lambda _c: None)
    monkeypatch.setattr(module.loader, "themes_dir", lambda: str(tmp_path))
    assert [t.id for t in module.loader.list_themes()][:2] == [APP_ID, DEFAULT_ID]
    assert module.loader.active_id() == APP_ID
    assert module.loader.is_builtin(APP_ID) and module.loader.is_builtin(DEFAULT_ID)
    assert module.loader.load() is module.loader.theme_for(APP_ID)


@pytest.mark.parametrize("module", [mixer_theme, keylock_theme])
def test_explicit_default_choice_is_kept(module, monkeypatch, tmp_path):
    monkeypatch.setattr(theme_loader.config_manager, "get_theme_choice", lambda _c: DEFAULT_ID)
    monkeypatch.setattr(module.loader, "themes_dir", lambda: str(tmp_path))
    assert module.loader.active_id() == DEFAULT_ID
    assert module.loader.load() is module.DEFAULT_THEME


def test_loader_follows_app_mode_change(monkeypatch, tmp_path):
    monkeypatch.setattr(theme_loader.config_manager, "get_theme_choice", lambda _c: APP_ID)
    monkeypatch.setattr(mixer_theme.loader, "themes_dir", lambda: str(tmp_path))
    import app.core.app_theme as app_theme
    monkeypatch.setattr(app_theme, "current_hub_theme", lambda: THEME_LIGHT)
    light = mixer_theme.loader.load()
    monkeypatch.setattr(app_theme, "current_hub_theme", lambda: THEME_DARK)
    dark = mixer_theme.loader.load()
    assert light is not dark and light.card_bg != dark.card_bg
