"""Baterias: "Seguir cor de destaque" pinta o anel na cor do app; desligado (padrão), o anel continua verde."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.widgets.battery import battery_card, battery_controller
from app.widgets.battery.card_painter import LOW_RED, PALETTES, THEME_DARK, THEME_LIGHT, paint_battery_card
from app.widgets.battery.specs import mock_state


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _colors(theme: str, accent=None) -> set[str]:
    state = mock_state()
    w, h = state.card_size()
    img = QImage(int(w), int(h), QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    paint_battery_card(p, QRectF(0, 0, w, h), state, theme=theme, accent=accent)
    p.end()
    return {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())
            if img.pixelColor(x, y).alpha() == 255}


@pytest.mark.parametrize("theme", [THEME_DARK, THEME_LIGHT])
def test_ring_is_green_by_default_and_accent_when_following(qapp, theme):
    green = PALETTES[theme].ok.name()
    assert green in _colors(theme)
    amber = PALETTES[theme].low.name()
    assert amber in _colors(theme)          # padrão: bateria fraca em âmbar
    with_accent = _colors(theme, QColor("#3366FF"))
    assert "#3366ff" in with_accent
    assert green not in with_accent
    assert LOW_RED[theme] in with_accent    # seguindo o destaque: bateria fraca em vermelho
    assert amber not in with_accent


def test_card_accent_reads_option(qapp, monkeypatch):
    opts = {"follow_accent": False}
    monkeypatch.setattr(battery_card.config_manager, "get_battery", lambda k, d=None: opts.get(k, d))
    assert battery_card.card_accent() is None   # padrão: verde
    opts["follow_accent"] = True
    battery_card.invalidate_card_theme()
    accent = battery_card.card_accent()
    assert accent is not None and accent.isValid()


def _fake_controller(saved: dict):
    calls = []
    skin = SimpleNamespace(begin_skin_crossfade=lambda *a, **k: calls.append("fade"),
                           update=lambda: calls.append("update"))
    emitted = []
    ctrl = SimpleNamespace(skin=skin, ring_color_changed=SimpleNamespace(emit=lambda: emitted.append(True)))
    return ctrl, calls, emitted


def test_toggle_fades_saves_and_notifies(qapp, monkeypatch):
    saved = {"follow_accent": False}
    monkeypatch.setattr(battery_controller.config_manager, "get_battery", lambda k, d=None: saved.get(k, d))
    monkeypatch.setattr(battery_controller.config_manager, "set_battery", lambda k, v: saved.__setitem__(k, v))
    ctrl, calls, emitted = _fake_controller(saved)

    battery_controller.BatteryWidgetController.set_follow_accent(ctrl, True)
    assert saved["follow_accent"] is True
    assert calls[0] == "fade"   # foto da cor antiga antes de trocar (dissolve, sem corte)
    assert emitted == [True]    # a miniatura do Hub repinta

    calls.clear()
    battery_controller.BatteryWidgetController.set_follow_accent(ctrl, True)   # repetido: nada a fazer
    assert calls == []
