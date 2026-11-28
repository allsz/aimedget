"""
Troca de skin dos widgets com o efeito escolhido no Hub (app/core/skin_switch.py).
Protótipo: mockups/widget-skin-switch.html.
"""
import sys
import time
from unittest import mock

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from app.core import skin_switch as ss
from app.core import widget_animator
from app.core.config_manager import config_manager


@pytest.fixture(autouse=True)
def _app_and_config(monkeypatch):
    QApplication.instance() or QApplication(sys.argv)
    store = {}
    monkeypatch.setattr(config_manager, "get_skin_switch_effect", lambda default: store.get("e", default))
    monkeypatch.setattr(config_manager, "set_skin_switch_effect", lambda e: store.__setitem__("e", e))
    yield store


def _layer(color: str, w: float, h: float) -> ss.Layer:
    pm = QPixmap(int(w), int(h))
    pm.fill(QColor(color))
    return ss.Layer(lambda p: p.drawPixmap(QPointF(0, 0), pm), (w, h), QRectF(0, 0, w, h), 12.0)


def _frame(effect: str, t: float, old: ss.Layer, new: ss.Layer) -> QImage:
    img = QImage(400, 300, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.translate(40, 40)
    ss.paint_switch(p, effect, t, old, new, QPointF(50, 30))
    p.end()
    return img


def test_default_is_spring_morph():
    assert ss.current_effect() == "morph"


def test_unknown_saved_effect_falls_back_to_default(_app_and_config):
    _app_and_config["e"] = "nope"
    assert ss.current_effect() == "morph"


@pytest.mark.parametrize("effect", ss.EFFECTS)
def test_every_effect_moves_from_old_to_new(effect):
    old, new = _layer("#ff0000", 200, 120), _layer("#0000ff", 240, 140)
    first, last = _frame(effect, 0.0, old, new), _frame(effect, 1.0, old, new)
    start, end = first.pixelColor(140, 100), last.pixelColor(140, 100)
    assert start.red() > 200 and start.blue() < 40           # começa no antigo
    assert end.blue() > 200 and end.red() < 40               # termina no novo, inteiro
    mids = [_frame(effect, t / 10, old, new) for t in range(1, 10)]
    assert sum(1 for m in mids if m != first and m != last) >= 3   # passa por quadros intermediários (não pula)


def test_morph_grows_the_card_from_its_top_left_corner():
    old, new = _layer("#ff0000", 200, 120), _layer("#0000ff", 240, 140)
    widths = []
    for i in range(0, 11):
        img = _frame("morph", i / 10, old, new)
        row = [img.pixelColor(x, 60).alpha() for x in range(40, 400)]
        widths.append(sum(1 for a in row if a > 128))
    assert widths[0] == pytest.approx(200, abs=2) and widths[-1] == pytest.approx(240, abs=2)
    assert img.pixelColor(41, 41).alpha() > 200               # o canto superior esquerdo ficou no lugar


class _Card(QWidget):
    """Janela mínima no papel de uma skin de Music/Timer."""

    def __init__(self, color: str, w: int, h: int):
        super().__init__()
        self.resize(w + 20, h + 20)
        self.art_margin = 10
        self._color, self._w, self._h = QColor(color), w, h

    def card_rect(self):
        return QRectF(10, 10, self._w, self._h)

    def anchor_card_radius(self):
        return 12.0

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.card_rect(), self._color)


def test_window_swap_uses_an_overlay_and_ends_with_the_new_window_shown(_app_and_config):
    _app_and_config["e"] = "press"
    old, new = _Card("#ff0000", 200, 120), _Card("#0000ff", 240, 140)
    old.move(100, 100)
    new.move(100, 100)
    old.show()
    QApplication.processEvents()
    with mock.patch.object(widget_animator, "animations_enabled", lambda: True):
        widget_animator.swap_skin_windows(old, new, True)
    overlay = new._skin_switch_overlay
    assert overlay is not None and overlay.isVisible()
    assert new.isVisible() and new.windowOpacity() == 0.0     # a nova espera invisível sob a animação
    assert not old.isVisible()
    assert not overlay.grab().isNull()                         # pinta
    overlay._t0 = time.perf_counter() - 10.0
    overlay._tick()                                            # tempo esgotado: termina limpo
    assert new.windowOpacity() == 1.0 and new._skin_switch_overlay is None
    new.close()


def test_window_swap_without_animations_is_instant(_app_and_config):
    old, new = _Card("#ff0000", 200, 120), _Card("#0000ff", 240, 140)
    old.show()
    with mock.patch.object(widget_animator, "animations_enabled", lambda: False):
        widget_animator.swap_skin_windows(old, new, True)
    assert new.isVisible() and new.windowOpacity() == 1.0 and not old.isVisible()
    assert getattr(new, "_skin_switch_overlay", None) is None
    new.close()


def test_pinned_widget_keeps_the_plain_fade(_app_and_config):
    """Fixado na área de trabalho, uma janela por cima ficaria acima dos apps: usa o dissolver de sempre."""
    _app_and_config["e"] = "flip"
    old, new = _Card("#ff0000", 200, 120), _Card("#0000ff", 240, 140)
    old.desktop_mode_target = lambda: True
    old.show()
    with mock.patch.object(widget_animator, "animations_enabled", lambda: True):
        widget_animator.swap_skin_windows(old, new, True)
    assert getattr(new, "_skin_switch_overlay", None) is None
    new.close()


def test_floating_card_skin_switch_paints_every_effect(_app_and_config):
    from app.widgets.performance.performance_controller import PerformanceWidgetController as PerformanceController
    from app.widgets.performance.card_state import SKIN_FLUENT, SKIN_NOTHING_DOT
    ctrl = PerformanceController()
    card = ctrl.skin
    with mock.patch.object(type(card), "isVisible", lambda self: True):
        for effect in ss.EFFECTS:
            _app_and_config["e"] = effect
            ctrl.set_skin(SKIN_NOTHING_DOT if ctrl.active_skin_name == SKIN_FLUENT else SKIN_FLUENT, save=False)
            assert card._skin_swap_effect == effect and card._skin_swap_prev is not None
            for frac in (0.25, 0.5, 0.75):
                card._skin_swap_t0 = card.now() - card._skin_swap_dur * frac
                assert not card.grab().isNull()
            card._skin_swap_t0 = card.now() - 10.0
            assert card._skin_swap_progress(card.now()) is None    # terminou e soltou a foto
    card.close()


def test_theme_changes_keep_the_plain_crossfade():
    """Trocar de TEMA (não de skin) continua no dissolver rápido de sempre."""
    from app.widgets.performance.performance_controller import PerformanceWidgetController as PerformanceController
    card = PerformanceController().skin
    with mock.patch.object(type(card), "isVisible", lambda self: True):
        card.begin_skin_crossfade()
    assert card._skin_swap_prev is not None and card._skin_swap_effect is None
    card.close()


def test_hub_card_saves_the_choice(_app_and_config):
    from app.hub.overview_page import OverviewPage
    page = OverviewPage()
    group = page._skin_switch_group
    assert group.selected() == "morph"
    group.button("flip").click()
    assert _app_and_config["e"] == "flip"
    page.deleteLater()
