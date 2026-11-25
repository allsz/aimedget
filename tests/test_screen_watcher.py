"""
Troca de monitores: cada widget fica no monitor em que foi posto, como uma skin do Rainmeter (`310@1`).
Monitores do Windows falsos (injetados no ScreenWatcher, em px físicos), janelas de verdade. Os casos vêm do
diagnóstico (crash_reports/screen_debug.log): o Windows não move as janelas quando a principal muda, só os números
dos monitores mudam.
"""
import time

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core import anchor_geometry as geo
from app.core import anchor_manager as am
from app.core import screen_watcher as sw
from app.core import widget_animator as wa
from app.core.anchor_geometry import Rect
from app.core.config_manager import config_manager
from test_anchor import _drag, env, qapp  # noqa: F401  (fixtures)

GAP = 10.0


def _real() -> sw.Monitor:
    mons = sw.native_monitors()
    return next(m for m in mons if m.primary)


def _mon(device, rect, scale, primary=False):
    return sw.Monitor(device, rect, rect, scale, primary)


def _use(env, monitors):
    env.mgr._screens._monitors_fn = lambda: list(monitors)
    return env.mgr._screens


def _native(c) -> Rect:
    return sw.card_native(c, [_real()])


def _column(env, keys, x=80, y=80):
    area = _real().work
    s = _real().scale
    cs = [env.make(k, int(area.l / s + x), int(area.t / s + y + i * 260)) for i, k in enumerate(keys)]
    t = keys[0]
    for k in keys[1:]:
        t = geo.Join(t, k, "y", 0, 0.0, GAP)
    g = am.Group(t)
    for k in keys:
        env.mgr._groups[k] = g
    env.mgr._reflow(g, keys[0])
    QApplication.processEvents()
    return cs


def _change(watcher):
    """O Qt avisou da troca; o vigia devolve os widgets no próximo giro do laço de eventos."""
    watcher.screens_changed()
    QApplication.processEvents()


def _settle(watcher):
    watcher.settle()
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture
def no_anim(env, monkeypatch):
    env.state["anim"] = False
    monkeypatch.setattr(wa, "animations_enabled", lambda: False)
    return env


@pytest.fixture
def anim(env, monkeypatch):
    env.state["anim"] = True
    monkeypatch.setattr(wa, "animations_enabled", lambda: True)
    return env


# --- Parte pura ----------------------------------------------------------------------------------------------------


def test_placement_is_bound_to_its_monitor():
    odyssey = _mon(r"\\.\DISPLAY1", Rect.of(2560, -207, 1080, 1920), 1.0)
    sfp = _mon(r"\\.\DISPLAY2", Rect.of(0, 0, 2560, 1440), 1.0, primary=True)
    p = sw.placement_of(Rect.of(2573, 400, 241, 210), [odyssey, sfp])
    assert p == sw.Placement(r"\\.\DISPLAY1", 13, 607, 1.0)

    # a TV vira principal: os mesmos monitores com outros números (valores do log)
    tv = _mon(r"\\.\DISPLAY3", Rect.of(0, 0, 3840, 2160), 1.25, primary=True)
    odyssey2 = _mon(r"\\.\DISPLAY1", Rect.of(-1080, 0, 1080, 1920), 1.0)
    m, x, y = sw.resolve(p, [tv, odyssey2])
    assert (m.device, x, y) == (r"\\.\DISPLAY1", -1067, 607)
    assert sw.resolve(p, [tv]) is None                                     # monitor desligado


def test_batch_moves_only_when_every_window_shares_the_scale():
    class W:
        def __init__(self, dpr):
            self._dpr = dpr

        def windowHandle(self):
            return None

        def devicePixelRatioF(self):
            return self._dpr

    assert am._same_scale([W(1.0), W(1.0)])
    assert not am._same_scale([W(1.0), W(1.25)])


# --- Com janelas de verdade ---------------------------------------------------------------------------------------


def test_main_monitor_swap_keeps_every_widget_on_its_monitor_instantly(no_anim):
    """O pulo para a TV: o monitor dos widgets "andou" na área de trabalho; eles vão junto, na hora, sem mudar de
    tamanho, e o grupo continua em fileira."""
    env = no_anim
    real = _real()
    watcher = _use(env, [_mon("MON", real.rect, real.scale, primary=True)])
    cs = _column(env, ["weather", "performance", "battery"])
    for c in cs:
        watcher.remember(c)
    before = [_native(c) for c in cs]

    shift = (200, 30)
    _use(env, [_mon("TV", Rect.of(real.rect.l - 3840, real.rect.t, 3840, 2160), 1.25, primary=True),
               _mon("MON", real.rect.moved(*shift), real.scale)])
    _change(watcher)

    after = [_native(c) for c in cs]
    for a, b in zip(after, before):                                    # já no lugar, sem esperar o assentar
        assert (a.l, a.t) == pytest.approx((b.l + shift[0], b.t + shift[1]), abs=1)
        assert (a.w, a.h) == pytest.approx((b.w, b.h), abs=1)
    assert watcher.is_settling()

    _settle(watcher)
    assert [_native(c) for c in cs] == [pytest.approx(r, abs=1) for r in after]   # o resgate não mexe em nada
    assert watcher.placement("weather").screen == "MON"


def test_widgets_are_back_inside_the_switch_signal_and_on_wm_displaychange(no_anim):
    """Sem esperar o próximo giro do laço (que só chegava 460-720 ms depois): já de volta quando o sinal retorna."""
    import ctypes
    from ctypes import wintypes

    env = no_anim
    real = _real()
    watcher = _use(env, [_mon("MON", real.rect, real.scale, primary=True)])
    c = env.make("weather", int(real.work.l / real.scale + 120), int(real.work.t / real.scale + 140))
    watcher.remember(c)
    before = _native(c)

    _use(env, [_mon("MON", real.rect.moved(150, 0), real.scale, primary=True)])
    watcher.screens_changed()                                   # sem processEvents
    assert _native(c).l == pytest.approx(before.l + 150, abs=1)
    _settle(watcher)

    _use(env, [_mon("MON", real.rect.moved(60, 20), real.scale, primary=True)])
    msg = wintypes.MSG(int(c.winId()), sw.WM_DISPLAYCHANGE, 32, 0)
    sw.native_event(ctypes.addressof(msg))                      # o aviso do Windows também basta
    n = _native(c)
    assert (n.l, n.t) == pytest.approx((before.l + 60, before.t + 20), abs=1)
    assert watcher.is_settling()
    _settle(watcher)


def test_nothing_moves_or_reflows_while_the_monitors_are_switching(no_anim):
    env = no_anim
    real = _real()
    watcher = _use(env, [_mon("MON", real.rect, real.scale, primary=True)])
    cs = _column(env, ["weather", "performance"])
    for c in cs:
        watcher.remember(c)
    watcher.screens_changed()                      # começou a trocar (as mesmas telas: ninguém muda de lugar)
    before = [am.card_rect(c) for c in cs]

    _drag(env.mgr, cs[0], 300, 0)                  # o Qt está com as coordenadas velhas: o arraste espera
    env.mgr.member_resized(cs[0])
    assert [am.card_rect(c) for c in cs] == before
    _settle(watcher)
    assert not watcher.is_settling()


def test_missing_monitor_is_provisional_and_the_widget_returns_with_it(no_anim):
    """Big Picture desligando o monitor: o widget vai para a principal sem perder o lugar, e volta quando ele volta."""
    env = no_anim
    real = _real()
    half = real.rect.w / 2
    main = _mon("MAIN", Rect(real.rect.l, real.rect.t, real.rect.l + half, real.rect.b), real.scale, primary=True)
    ext = _mon("EXT", Rect(real.rect.l + half, real.rect.t, real.rect.r, real.rect.b), real.scale)
    watcher = _use(env, [main, ext])
    s = real.scale
    c = env.make("storage", int((ext.rect.l + 150) / s), int((ext.rect.t + 200) / s))
    watcher.remember(c)
    saved = watcher.placement("storage")
    assert saved.screen == "EXT"

    _use(env, [main])
    _change(watcher)
    _settle(watcher)
    assert watcher.placement("storage") == saved              # o lugar provisório não vira o lugar dele
    assert "storage" in watcher._provisional
    env.mgr._screens.remember(c)                              # gravações automáticas são ignoradas
    assert watcher.placement("storage") == saved

    _use(env, [main, ext])                                    # o monitor voltou
    _change(watcher)
    n = _native(c)
    assert (n.l, n.t) == pytest.approx((ext.rect.l + saved.dx, ext.rect.t + saved.dy), abs=1)


def test_dragging_while_the_monitor_is_missing_chooses_a_new_place(no_anim):
    env = no_anim
    real = _real()
    watcher = _use(env, [_mon("GONE", real.rect, real.scale, primary=True)])
    c = env.make("battery", int(real.work.l / real.scale + 200), int(real.work.t / real.scale + 200))
    watcher.remember(c)
    _use(env, [_mon("MON", real.rect, real.scale, primary=True)])
    _change(watcher)
    _settle(watcher)
    assert watcher.placement("battery").screen == "GONE"

    _drag(env.mgr, c, 40, 0)                                  # o usuário escolheu: vale o lugar novo
    env.mgr.drag_end(c)
    assert watcher.placement("battery").screen == "MON"
    assert "battery" not in watcher._provisional


def test_opening_puts_a_remembered_widget_on_its_monitor(no_anim, monkeypatch):
    """A principal mudou com o app fechado: a posição absoluta da configuração aponta para outro lugar."""
    env = no_anim
    real = _real()
    watcher = _use(env, [real])
    watcher._placements["weather"] = sw.Placement(real.device, 300, 260, real.scale)
    monkeypatch.setattr(config_manager, "get_weather",
                        lambda k, d=None: True if k == "remember_position" else d)
    c = env.make("weather", int(real.work.l / real.scale + 900), int(real.work.t / real.scale + 500))
    n = _native(c)
    assert (n.l, n.t) == pytest.approx((real.rect.l + 300, real.rect.t + 260), abs=2)


def test_rescue_of_a_group_from_a_missing_monitor_is_animated_and_ends_clean(anim):
    env = anim
    real = _real()
    watcher = _use(env, [_mon("GONE", real.rect, real.scale, primary=True)])
    cs = _column(env, ["weather", "performance"], x=900, y=500)
    for c in cs:
        watcher.remember(c)
    cs[0].move_card_to(cs[0].card_origin().x() + 600, cs[0].card_origin().y())   # a fileira desfeita pelo Windows
    QApplication.processEvents()
    start = am.card_rect(cs[0])

    _use(env, [_mon("MON", real.rect, real.scale, primary=True)])
    _change(watcher)
    _settle(watcher)
    QTest.qWait(40)
    mid = am.card_rect(cs[0])
    assert mid != pytest.approx(start, abs=1)                                     # andou...

    end = time.perf_counter() + 3.0
    while env.mgr._slide is not None and time.perf_counter() < end:
        QTest.qWait(16)
    assert env.mgr._slide is None                                                 # ...e terminou
    a, b = am.card_rect(cs[0]), am.card_rect(cs[1])
    assert b.t == pytest.approx(a.b + GAP, abs=1) and b.l == pytest.approx(a.l, abs=1)   # de volta à fileira
    assert watcher.placement("weather").screen == "GONE"                          # provisório: não grava
