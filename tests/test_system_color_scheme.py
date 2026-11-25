"""Troca de modo claro/escuro: o Hub segue o Windows ao vivo (modo "Sistema") e dissolve em 300 ms com curva in-out,
com a barra de título nativa mudando de cor junto (protótipo mockups/theme-mode-transition.html, variante C)."""

import sys
import time
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

from app.core import theme_crossfade as tc
from app.hub import hub_window
from app.hub.dwm_helper import mix_hex
from app.hub.theme import THEME_DARK, THEME_LIGHT


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _pump(seconds: float):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def _fake_window(preference: str, current):
    applied = []
    shell = QWidget()
    shell.resize(200, 120)
    win = SimpleNamespace(
        _theme_preference=preference,
        _current_theme=current,
        _current_theme_before_mode=current,
        _titlebar_hex=current.bg,
        shell=shell,
        _stop_wipe=lambda: None,
        winId=lambda: 0,
    )

    def _apply(theme, titlebar=True):
        win._current_theme = theme
        applied.append(theme)

    win._apply_theme = _apply
    win._switch_mode_animated = MethodType(hub_window.AimedgetHubWindow._switch_mode_animated, win)
    return win, applied


@pytest.fixture
def env(monkeypatch):
    notified, bars, frames = [], [], []
    monkeypatch.setattr(hub_window, "get_service_bridge", lambda: SimpleNamespace(on_theme_changed=notified.append))
    monkeypatch.setattr(hub_window, "resolve_theme", lambda _pref: THEME_LIGHT)   # o Windows acabou de ir para o claro
    monkeypatch.setattr(hub_window, "set_titlebar_colors", lambda _h, bg, _t: bars.append(bg))
    monkeypatch.setattr(hub_window, "set_dark_frame", lambda _h, dark: frames.append(dark))
    return SimpleNamespace(notified=notified, bars=bars, frames=frames)


# --- Seguir o Windows ---

def test_system_mode_follows_windows(qapp, env):
    with mock.patch.object(tc, "animations_enabled", return_value=False):
        win, applied = _fake_window("system", THEME_DARK)
        hub_window.AimedgetHubWindow._on_system_color_scheme_changed(win)
    assert applied == [THEME_LIGHT]
    assert env.notified == [THEME_LIGHT]   # widgets que seguem o app trocam juntos
    assert env.bars == [THEME_LIGHT.bg]    # sem animação: a barra vai direto à cor final
    assert env.frames == [False]


def test_manual_mode_ignores_windows(qapp, env):
    win, applied = _fake_window("dark", THEME_DARK)
    hub_window.AimedgetHubWindow._on_system_color_scheme_changed(win)
    assert applied == [] and env.notified == []


def test_same_theme_does_nothing(qapp, env):
    win, applied = _fake_window("system", THEME_LIGHT)
    hub_window.AimedgetHubWindow._on_system_color_scheme_changed(win)
    assert applied == [] and env.notified == []


# --- A dissolvência de modo ---

def test_mode_switch_animates_titlebar_with_the_fade(qapp, env):
    with mock.patch.object(tc, "animations_enabled", return_value=True):
        win, _applied = _fake_window("system", THEME_DARK)
        win.shell.show()
        QApplication.processEvents()
        hub_window.AimedgetHubWindow._on_system_color_scheme_changed(win)
        layer = win.shell._theme_crossfade
        assert layer is not None and layer.is_running()
        assert layer._duration == pytest.approx(tc.MODE_DURATION_MS / 1000.0)
        assert layer._shrink == 0.0
        _pump(tc.MODE_DURATION_MS / 1000.0 + 0.15)
    win.shell.hide()

    assert not layer.is_running()
    # Várias cores intermediárias (anima, não pula), indo só numa direção (claro aumenta), terminando na cor final
    assert len(env.bars) >= 4
    assert env.bars[-1] == THEME_LIGHT.bg
    lightness = [QColor(c).lightness() for c in env.bars]
    assert lightness == sorted(lightness)
    assert any(c not in (THEME_DARK.bg, THEME_LIGHT.bg) for c in env.bars)
    # Os botões do quadro trocam uma vez, no meio
    assert env.frames[-1] is False and env.frames.count(False) == 1


def test_in_out_curve_and_mix():
    assert tc.ease_in_out_cubic(0.0) == 0.0 and tc.ease_in_out_cubic(1.0) == 1.0
    assert tc.ease_in_out_cubic(0.5) == pytest.approx(0.5)
    assert tc.ease_in_out_cubic(0.15) < 0.05          # começa devagar (a saída rápida de antes parecia corte)
    assert tc.ease_out_cubic(0.15) > 0.35
    assert mix_hex("#000000", "#FFFFFF", 0.5) == "#808080"
    assert mix_hex("#191919", "#F7F6F3", 1.0) == "#F7F6F3"


def test_floating_card_mode_crossfade(qapp):
    from app.widgets.storage.storage_card import StorageCard
    card = StorageCard()
    try:
        card.show()
        QApplication.processEvents()
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=True):
            card.begin_skin_crossfade(tc.MODE_DURATION_MS, mode_switch=True)
        assert card._skin_swap_mode and card._skin_swap_prev is not None
        assert card._skin_swap_dur == pytest.approx(0.300)
        card.repaint()   # pinta o quadro de transição sem erro
        _pump(0.45)
        card.repaint()
        assert card._skin_swap_progress(card.now()) is None   # termina limpo
    finally:
        card.close()


def test_floating_card_without_animations_skips(qapp):
    from app.widgets.storage.storage_card import StorageCard
    card = StorageCard()
    try:
        card.show()
        with mock.patch("app.ui_components.floating_card.animations_enabled", return_value=False):
            card.begin_skin_crossfade(tc.MODE_DURATION_MS, mode_switch=True)
        assert card._skin_swap_prev is None
    finally:
        card.close()
