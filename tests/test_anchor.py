"""Ancoragem de widgets: geometria do ímã, árvore de junção, gerenciador (arraste, grupo, onda) e desenho da rede."""

import time

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core import anchor_geometry as geo
from app.core import anchor_manager as am
from app.core.anchor_geometry import GAP, Rect
from app.core.config_manager import config_manager
from app.ui_components.anchor_net import paint_lattice
from app.ui_components.floating_card import FloatingCard


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# --- Geometria -----------------------------------------------------------------------------------------------------


def test_candidate_locks_only_when_touching_and_aligned():
    t = Rect.of(100, 100, 200, 120)
    d = Rect.of(t.r + GAP + 4, 103, 150, 120)          # à direita, 4 px longe e 3 px abaixo
    c = geo.candidate(d, t)
    assert c.lock and c.b == 1.0
    assert (c.sx, c.sy) == (-4, -3)
    assert c.ax == "x" and not c.d_first and c.ai == 0
    assert c.origin[0] == pytest.approx(t.r + GAP / 2)

    off = geo.candidate(Rect.of(t.r + GAP + 4, 140, 150, 120), t)   # encostado mas desalinhado
    assert not off.lock and off.sx == -4 and off.sy == 0
    assert 0.0 < off.b < 1.0

    far = geo.candidate(Rect.of(t.r + 600, 100, 150, 120), t)
    assert far.b == 0.0 and not far.lock and (far.sx, far.sy) == (0, 0)


def test_proximity_brightens_as_widgets_approach():
    t = Rect.of(0, 0, 100, 100)
    values = [geo.candidate(Rect.of(100 + gap, 0, 100, 100), t).b for gap in (250, 150, 80, 30)]
    assert values == sorted(values) and values[0] < values[-1] <= geo.PROXIMITY_MAX


def test_focus_seg_is_the_facing_edge():
    a = Rect.of(0, 0, 100, 100)
    assert geo.focus_seg(a, Rect.of(150, 20, 50, 50)) == (100, 20, 100, 70)    # à direita: borda direita
    assert geo.focus_seg(a, Rect.of(10, 130, 50, 50)) == (10, 100, 60, 100)    # embaixo: borda de baixo
    assert geo.focus_seg(a, Rect.of(150, 150, 20, 20)) == (100, 100, 100, 100)  # na diagonal: o canto


def test_layout_keeps_gap_and_alignment_when_a_member_grows():
    rects = {"music": Rect.of(0, 0, 260, 96), "weather": Rect.of(0, 106, 220, 130)}
    stack = geo.join_from_rects("music", "weather", "y", rects)          # weather embaixo, à esquerda
    assert (stack.ai, stack.gap) == (0, 10)
    rects["perf"] = Rect.of(270, (0 + 236) / 2 - 85, 170, 170)         # centrado no lado da pilha
    tree = geo.join_from_rects(stack, "perf", "x", rects)
    assert tree.ai == 2

    sizes = {"music": (260, 96), "weather": (300, 160), "perf": (170, 170)}   # weather cresceu
    pos = geo.layout(tree, sizes, "music", (0, 0))
    assert pos["weather"] == (0, 106)
    stack_r = 300                                                        # o contorno da pilha agora é o weather
    assert pos["perf"][0] == stack_r + 10
    stack_mid = (0 + 106 + 160) / 2
    assert pos["perf"][1] + 85 == pytest.approx(stack_mid)


def test_prune_and_json_round_trip():
    rects = {"a": Rect.of(0, 0, 100, 50), "b": Rect.of(110, 0, 80, 50), "c": Rect.of(0, 60, 100, 40)}
    tree = geo.join_from_rects(geo.join_from_rects("a", "b", "x", rects), "c", "y", rects)
    assert sorted(geo.members(tree)) == ["a", "b", "c"]
    back = geo.from_json(geo.to_json(tree))
    assert geo.to_json(back) == geo.to_json(tree)

    rest = geo.prune(tree, "b", rects)
    assert sorted(geo.members(rest)) == ["a", "c"]
    assert geo.layout(rest, {"a": (100, 50), "c": (100, 40)}, "a", (0, 0))["c"] == (0, 60)   # nada se mexe
    assert geo.prune("a", "a", rects) is None

    assert geo.from_json({"A": "a", "B": "a", "ax": "x", "ai": 0, "off": 0, "gap": 10}) is None   # repetido
    assert geo.from_json({"A": "a", "ax": "x"}) is None
    assert geo.from_json({"A": "a", "B": "b", "ax": "z", "ai": 0, "off": 0, "gap": 10}) is None


# --- Desenho -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("style", ["dots", "lines", "both"])
def test_paint_lattice_draws_only_where_visible(qapp, style):
    img = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    U = Rect.of(150, 150, 100, 100)
    lit = paint_lattice(p, U, U.grown(120), 18, style, lambda x, y: (1.0 if x > 250 else 0.0, 0.0, 0.0))
    none = paint_lattice(p, U, U.grown(120), 18, style, lambda x, y: (0.0, 0.0, 0.0))
    p.end()
    assert lit > 0 and none == 0
    assert img.pixelColor(380, 200).alpha() == 0 or style == "lines"   # longe da grade (entre linhas) nada


def test_lattice_cells_are_square_and_phase_locked():
    from app.ui_components.anchor_net import lattice
    xs = lattice(100.0, 0.0, 400.0, 18.0)
    assert 100.0 in xs
    assert {round(b - a, 6) for a, b in zip(xs, xs[1:])} == {18.0}


# --- Gerenciador com janelas de verdade --------------------------------------------------------------------------


class _Card(FloatingCard):
    def __init__(self, key: str):
        self.ANCHOR_KEY = key
        super().__init__(scale=1.0)

    def paint_card_content(self, p, rect, now):
        pass


@pytest.fixture
def env(qapp, monkeypatch):
    store = {}
    monkeypatch.setattr(config_manager, "get_anchor", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(config_manager, "set_anchor", lambda k, v: store.__setitem__(k, v))
    state = {"anim": False}
    monkeypatch.setattr(am, "animations_enabled", lambda: state["anim"])
    monkeypatch.setattr(am, "_manager", None)
    cards = []

    def make(key, x, y):
        c = _Card(key)
        c.move_card_to(x, y)
        c.show()
        QApplication.processEvents()
        cards.append(c)
        return c

    class Env:
        pass

    e = Env()
    e.store, e.state, e.make = store, state, make
    e.mgr = am.anchor_manager()
    yield e
    for c in cards:
        c.hide()
        c.deleteLater()
    if am._manager is not None and am._manager._overlay is not None:
        am._manager._overlay.hide()
        am._manager._overlay.deleteLater()
    QApplication.processEvents()


def _drag(mgr, card, dx, dy):
    """Arrasta o cartão em (dx, dy) como o mouseMoveEvent faria (janela = posição atual + delta)."""
    start = card.pos()
    mgr.drag_to(card, QPoint(start.x() + dx, start.y() + dy))


def _rect(card):
    return am.card_rect(card)


def test_join_without_animations_is_instant_and_saved(env):
    a = env.make("weather", 200, 200)
    b = env.make("performance", 700, 260)
    env.mgr.set_anchored(a, True)
    ra, rb = _rect(a), _rect(b)
    # leva b para 4 px à direita do encaixe e 5 px abaixo do topo de a
    _drag(env.mgr, b, int(ra.r + GAP + 4 - rb.l), int(ra.t + 5 - rb.t))
    assert env.mgr._drag.best.lock
    rb = _rect(b)
    assert rb.l == pytest.approx(ra.r + GAP, abs=1) and rb.t == pytest.approx(ra.t, abs=1)   # ímã na hora
    env.mgr.drag_end(b)
    assert env.mgr.is_grouped(a) and env.mgr.is_grouped(b)
    assert not env.mgr.is_anchored(a)                     # o grupo novo nasce sem âncora
    assert env.mgr._boom is None                          # sem animações: sem onda
    assert len(env.store["groups"]) == 1
    QTest.qWait(30)
    assert env.mgr._overlay is None or not env.mgr._overlay.isVisible()


def test_group_moves_together_and_detach_keeps_positions(env):
    a = env.make("weather", 200, 200)
    b = env.make("performance", 700, 260)
    env.mgr.set_anchored(a, True)
    ra, rb = _rect(a), _rect(b)
    _drag(env.mgr, b, int(ra.r + GAP - rb.l), int(ra.t - rb.t))
    env.mgr.drag_end(b)
    before_a, before_b = _rect(a), _rect(b)

    _drag(env.mgr, a, 37, -21)                            # arrastar qualquer membro leva o grupo
    env.mgr.drag_end(a)
    assert _rect(a).l - before_a.l == pytest.approx(37, abs=1)
    assert _rect(b).l - before_b.l == pytest.approx(37, abs=1)
    assert _rect(b).t - before_b.t == pytest.approx(-21, abs=1)

    keep_a, keep_b = _rect(a), _rect(b)
    env.mgr.detach(b)
    assert not env.mgr.is_grouped(a) and not env.mgr.is_grouped(b)
    assert _rect(a) == keep_a and _rect(b) == keep_b
    assert env.store["groups"] == []


def test_resizing_a_member_keeps_the_stack_seamless(env):
    a = env.make("weather", 200, 200)
    b = env.make("performance", 200, 600)
    env.mgr.set_anchored(a, True)
    ra, rb = _rect(a), _rect(b)
    _drag(env.mgr, b, int(ra.l - rb.l), int(ra.b + GAP - rb.t))      # embaixo de a, alinhado à esquerda
    env.mgr.drag_end(b)
    assert env.mgr.is_grouped(b)
    a.set_scale(1.3)                                                  # a cresce: b desce junto, sem encostar
    ra, rb = _rect(a), _rect(b)
    assert rb.t - ra.b == pytest.approx(GAP, abs=1)
    assert rb.l == pytest.approx(ra.l, abs=1)


def test_member_returns_to_its_place_when_shown_again(env):
    a = env.make("weather", 200, 200)
    b = env.make("performance", 700, 260)
    env.mgr.set_anchored(a, True)
    ra, rb = _rect(a), _rect(b)
    _drag(env.mgr, b, int(ra.r + GAP - rb.l), int(ra.t - rb.t))
    env.mgr.drag_end(b)
    b.hide()
    b.move_card_to(50, 50)                                            # o controller pôs em outro lugar
    b.show()
    QApplication.processEvents()
    assert _rect(b).l == pytest.approx(_rect(a).r + GAP, abs=1)
    assert _rect(b).t == pytest.approx(_rect(a).t, abs=1)


def test_magnet_and_net_animate_then_end_clean(env):
    env.state["anim"] = True
    a = env.make("weather", 200, 200)
    b = env.make("performance", 700, 260)
    env.mgr.set_anchored(a, True)
    QTest.qWait(600)                                                  # o brilho de "Ancorar" assenta
    ra, rb = _rect(a), _rect(b)
    _drag(env.mgr, b, int(ra.r + GAP + 6 - rb.l), int(ra.t + 6 - rb.t))
    g = env.mgr.group_of("weather")
    first_gain = g.gain
    first_l = _rect(b).l
    assert ra.r + GAP + 1 < first_l <= ra.r + GAP + 6.5               # o ímã puxa aos poucos: não pula
    assert first_gain < 0.9                                           # a rede acende aos poucos
    QTest.qWait(400)
    assert _rect(b).l == pytest.approx(ra.r + GAP, abs=1)             # o ímã assentou
    assert g.gain == pytest.approx(1.0, abs=0.02)                     # travado: brilho (quase) cheio
    assert env.mgr._overlay is not None and env.mgr._overlay.isVisible()

    env.mgr.drag_end(b)
    assert env.mgr._boom is not None                                  # junção com onda
    origin = env.mgr._boom.origin
    assert origin[0] == pytest.approx(ra.r + GAP / 2, abs=1)          # sai do meio do encaixe
    env.mgr._boom.t0 -= am.BOOM_DUR * 0.6                             # adianta a onda
    QTest.qWait(int(am.BOOM_DUR * 0.4 * 1000) + 300)
    assert env.mgr._boom is None
    assert all(gr.gain == 0.0 for gr in env.mgr.groups())
    assert not env.mgr.is_busy()                                      # relógio parado: custo zero
    assert not env.mgr._overlay.isVisible()                           # a janela da rede some


def _layer(card):
    layer = getattr(card, "_anchor_glow_layer", None)
    return layer if layer is not None and am._alive(layer) else None


def test_anchor_mode_is_a_pulsing_glow_not_a_grid_flash(env, monkeypatch):
    from app.ui_components import anchor_net
    drawn = []
    real = anchor_net.paint_lattice
    monkeypatch.setattr(anchor_net, "paint_lattice", lambda *a, **k: drawn.append(1) or real(*a, **k))
    env.state["anim"] = True
    a = env.make("weather", 200, 200)
    g = env.mgr.group_of("weather")

    env.mgr.set_anchored(a, True)
    seen = [g.glow]
    for _ in range(12):
        QTest.qWait(40)
        seen.append(g.glow)
    assert seen == sorted(seen) and seen[0] < 0.2 and seen[-1] > 0.6           # acende aos poucos, sem salto
    QTest.qWait(500)
    layer = _layer(a)
    assert layer is not None and layer.level() > 0.3 and env.mgr.is_busy()     # o pulso mantém o relógio
    assert env.mgr._clock.interval() == am.PULSE_FRAME_MS                        # só o pulso: 30 fps
    levels = set()
    for _ in range(25):                                                          # pulsa (varia), não fica parado
        QTest.qWait(60)
        levels.add(round(layer.level(), 2))
    assert len(levels) > 5
    assert g.gain == 0.0 and not drawn                                           # nenhuma grade, nenhum círculo
    assert env.mgr._overlay is None or not env.mgr._overlay.isVisible()          # nada na janela de cima

    env.mgr.set_anchored(a, False)
    seen = [g.glow]
    for _ in range(30):
        QTest.qWait(40)
        seen.append(g.glow)
    assert seen == sorted(seen, reverse=True) and seen[-1] == 0.0               # apaga aos poucos
    assert not drawn and layer.level() == 0.0 and not layer.has_room
    assert not env.mgr.is_busy()                                                 # custo zero de novo


def test_glow_lives_in_the_widget_window_and_follows_it(env):
    """Na janela do próprio widget: mesma camada (área de trabalho ou por cima) e mesmo quadro no arraste."""
    env.state["anim"] = True
    a = env.make("weather", 200, 200)
    env.mgr.set_anchored(a, True)
    QTest.qWait(600)
    layer = _layer(a)
    assert layer.window() is a and layer.geometry() == a.rect()
    for _ in range(6):
        QTest.qWait(30)
        _drag(env.mgr, a, 25, 10)
        assert layer.window() is a
    assert env.mgr.group_of("weather").glow > 0.95                               # continua aceso no arraste
    env.mgr.drag_end(a)


def test_glow_uses_the_app_accent_color(env, monkeypatch):
    from app.hub import theme as hub_theme
    monkeypatch.setattr(hub_theme, "resolve_theme", lambda *a, **k: type("T", (), {"accent": "#12ab34"})())
    a = env.make("weather", 200, 200)
    env.mgr._accent_cache = None
    env.mgr.set_anchored(a, True)
    assert _layer(a)._color.name() == "#12ab34"


def _join_right(env, a, b):
    ra, rb = _rect(a), _rect(b)
    _drag(env.mgr, b, int(ra.r + GAP + 3 - rb.l), int(ra.t + 2 - rb.t))
    env.mgr.drag_end(b)


def test_glow_fades_away_after_a_successful_join(env):
    env.state["anim"] = True
    a = env.make("weather", 200, 200)
    b = env.make("performance", 800, 260)
    env.mgr.set_anchored(b, True)                     # X (b) ancorado, arrastado até Y (a)
    QTest.qWait(1000)
    assert _layer(b).level() > 0.3
    _join_right(env, a, b)
    assert env.mgr.is_grouped(b) and not env.mgr.is_anchored(b)
    seen = []
    for _ in range(30):
        QTest.qWait(40)
        seen.append(env.mgr.group_of("performance").glow)
    assert seen == sorted(seen, reverse=True) and seen[0] > 0.0      # apaga aos poucos, não corta
    assert seen[-1] == 0.0 and _layer(b).level() == 0.0              # e não fica aceso depois da junção


def test_glow_is_gone_after_join_without_animations(env):
    a = env.make("weather", 200, 200)
    b = env.make("performance", 800, 260)
    env.mgr.set_anchored(b, True)
    _join_right(env, a, b)
    assert _layer(b).level() == 0.0


@pytest.mark.parametrize("target_pinned", [True, False])
def test_dragged_widget_adopts_the_target_layer(env, target_pinned):
    a = env.make("weather", 200, 200)                  # Y: o alvo
    b = env.make("performance", 800, 260)              # X: ancorado e arrastado
    for card in (a, b):                                # o controller aplica o pedido (como no app)
        card.desktop_mode_changed.connect(card.set_desktop_mode)
    a.set_desktop_mode(target_pinned)
    b.set_desktop_mode(not target_pinned)
    QTest.qWait(900)                                   # trocar de camada passa pela onda de pontos do cartão
    assert a.is_desktop_mode() is target_pinned and b.is_desktop_mode() is not target_pinned
    env.mgr.set_anchored(b, True)
    _join_right(env, a, b)
    QTest.qWait(900)
    assert b.is_desktop_mode() is target_pinned and a.is_desktop_mode() is target_pinned


def test_anchor_glow_without_animations_is_steady_and_instant(env):
    a = env.make("weather", 200, 200)
    g = env.mgr.group_of("weather")
    env.mgr.set_anchored(a, True)
    assert g.glow == 1.0 and _layer(a).level() > 0
    assert not env.mgr.is_busy()                                                 # sem pulso, sem relógio
    env.mgr.set_anchored(a, False)
    assert g.glow == 0.0 and _layer(a).level() == 0.0


def test_timer_window_makes_room_for_the_glow_without_moving_the_card(qapp):
    from app.widgets.timer.skins.windows_skin import WindowsTimerSkin
    t = WindowsTimerSkin()
    t.move_square_to(300, 300)
    before_origin, before_side, before_w = t.square_origin(), t.square_side(), t.width()
    t.anchor_glow_room(True)
    assert t.square_origin() == before_origin and t.square_side() == before_side
    assert t.width() >= before_side + 2 * (t.ANCHOR_GLOW_ROOM - t.ART_FREE_PAD)
    t.anchor_glow_room(False)
    assert t.width() == before_w and t.square_origin() == before_origin
    t.deleteLater()


def test_no_net_without_anchor(env):
    a = env.make("weather", 200, 200)
    b = env.make("performance", 700, 260)
    ra, rb = _rect(a), _rect(b)
    _drag(env.mgr, b, int(ra.r + GAP + 4 - rb.l), int(ra.t + 3 - rb.t))
    assert env.mgr._drag.best is None                                 # ninguém ancorado: arraste livre
    assert _rect(b).l == pytest.approx(ra.r + GAP + 4, abs=1)
    env.mgr.drag_end(b)
    assert not env.mgr.is_grouped(b)


def test_floating_card_drag_goes_through_the_manager(env):
    a = env.make("weather", 200, 200)
    b = env.make("performance", 700, 260)
    env.mgr.set_anchored(a, True)
    b._drag_offset = QPoint(40, 40)
    ra = _rect(a)
    local = am._local_card(b)
    target = QPoint(int(ra.r + GAP + 3 - local.x()) + 40, int(ra.t + 2 - local.y()) + 40)
    ev = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(10, 10), QPointF(target), Qt.MouseButton.NoButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    b.mouseMoveEvent(ev)
    assert _rect(b).l == pytest.approx(ra.r + GAP, abs=1)             # o ímã agiu no arraste real
    rel = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(10, 10), QPointF(target),
                      Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    b.mouseReleaseEvent(rel)
    assert env.mgr.is_grouped(b)


def test_saved_groups_are_loaded_and_bad_entries_ignored(qapp, monkeypatch):
    tree = geo.join_from_rects("music", "weather", "y",
                               {"music": Rect.of(0, 0, 260, 96), "weather": Rect.of(0, 106, 220, 130)})
    store = {"groups": [geo.to_json(tree), {"A": "x"}, geo.to_json(geo.Join("timer", "nope", "x", 0, 0, 10))],
             "sizes": {"music": [260, 96]}}
    monkeypatch.setattr(config_manager, "get_anchor", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(config_manager, "set_anchor", lambda k, v: store.__setitem__(k, v))
    mgr = am.AnchorManager()
    assert sorted(mgr.group_of("music").keys()) == ["music", "weather"]
    assert mgr.group_of("timer").keys() == ["timer"]
    assert mgr._sizes["music"] == (260.0, 96.0)


def test_style_settings_fall_back_to_defaults(monkeypatch):
    store = {"net_style": "squiggles", "boom": "ring"}
    monkeypatch.setattr(config_manager, "get_anchor", lambda k, d=None: store.get(k, d))
    assert am.net_style() == am.DEFAULT_NET_STYLE
    assert am.boom_style() == "ring"


# --- Camada do grupo e movimento em lote -------------------------------------------------------------------------


def _pinnable(env, key, x, y, pinned=False):
    card = env.make(key, x, y)
    card.desktop_mode_changed.connect(card.set_desktop_mode)     # o controller aplica o pedido (como no app)
    card.set_desktop_mode(pinned)
    return card


def test_pinning_one_member_pins_the_whole_group(env):
    a = _pinnable(env, "weather", 200, 200)
    b = _pinnable(env, "performance", 800, 260)
    env.mgr.set_anchored(b, True)
    _join_right(env, a, b)
    a.set_desktop_mode(True)                                     # "Fixar na área de trabalho" num membro
    QTest.qWait(900)
    assert a.is_desktop_mode() and b.is_desktop_mode()
    b.set_desktop_mode(False)                                    # e soltar pelo outro membro solta os dois
    QTest.qWait(900)
    assert not a.is_desktop_mode() and not b.is_desktop_mode()


def test_net_window_lives_in_the_group_layer(env):
    from app.core import desktop_layer
    a = _pinnable(env, "weather", 200, 200, pinned=True)
    b = _pinnable(env, "performance", 800, 260, pinned=True)
    QTest.qWait(900)
    env.mgr.set_anchored(a, True)
    ra, rb = _rect(a), _rect(b)
    _drag(env.mgr, b, int(ra.r + 60 - rb.l), int(ra.t - rb.t))   # perto: a rede aparece
    ov = env.mgr._overlay
    assert ov.isVisible() and ov.is_desktop()                    # grupo na área de trabalho: rede também
    if desktop_layer.IS_WINDOWS:
        ex = desktop_layer._user32.GetWindowLongW(int(ov.winId()), desktop_layer.GWL_EXSTYLE)
        assert not ex & desktop_layer.WS_EX_TOPMOST              # não fica por cima dos apps
    env.mgr.drag_end(b)

    a.set_desktop_mode(False)                                    # o alvo (e o grupo dele) vai para cima
    QTest.qWait(900)
    _drag(env.mgr, b, int(ra.r + 60 - _rect(b).l), 0)
    assert not env.mgr._overlay.is_desktop()
    env.mgr.drag_end(b)


def test_group_windows_move_in_one_batch(env, monkeypatch):
    from app.core import desktop_layer
    if not desktop_layer.IS_WINDOWS:
        pytest.skip("lote de janelas só no Windows")
    calls = []
    real = desktop_layer.defer_move
    monkeypatch.setattr(desktop_layer, "defer_move", lambda moves: calls.append(len(moves)) or real(moves))
    a = env.make("weather", 200, 200)
    b = env.make("performance", 800, 260)
    env.mgr.set_anchored(a, True)
    _join_right(env, b, a)
    before_a, before_b = _rect(a), _rect(b)
    calls.clear()
    _drag(env.mgr, a, 40, 25)
    assert calls and calls[-1] == 2                              # os dois na mesma chamada
    assert _rect(a).l - before_a.l == pytest.approx(40, abs=1)
    assert _rect(b).l - before_b.l == pytest.approx(40, abs=1)
    assert _rect(b).t - before_b.t == pytest.approx(25, abs=1)
    env.mgr.drag_end(a)


def test_batch_failure_falls_back_to_moving_one_by_one(env, monkeypatch):
    from app.core import desktop_layer
    monkeypatch.setattr(desktop_layer, "defer_move", lambda moves: False)
    a = env.make("weather", 200, 200)
    b = env.make("performance", 800, 260)
    env.mgr.set_anchored(a, True)
    _join_right(env, b, a)
    before_b = _rect(b)
    _drag(env.mgr, a, -30, 15)
    assert _rect(b).l - before_b.l == pytest.approx(-30, abs=1)
    assert _rect(b).t - before_b.t == pytest.approx(15, abs=1)
    env.mgr.drag_end(a)


# --- Alinhador (HUD): só o mais próximo, desliza, uma camada só ----------------------------------------------------


def test_align_without_group_takes_only_the_nearest_widget(env):
    a = env.make("weather", 200, 200)
    near = env.make("performance", 620, 240)
    far = env.make("music", 1400, 700)
    far_before = _rect(far)
    env.mgr.align_widgets(a, axis="y", align=0, gap=10.0)
    assert sorted(env.mgr.group_of("weather").keys()) == ["performance", "weather"]
    assert len(env.mgr.group_of("music").keys()) == 1                  # o de longe não foi puxado
    assert (_rect(far).l, _rect(far).t) == (far_before.l, far_before.t)
    ra, rn = _rect(a), _rect(near)
    assert abs(rn.l - ra.l) < 1.0 and abs(rn.t - ra.b - 10.0) < 1.0


def test_align_slides_into_place_then_ends_clean(env):
    env.state["anim"] = True
    a = env.make("weather", 200, 200)
    b = env.make("performance", 700, 260)
    start = _rect(b)
    env.mgr.align_widgets(a, axis="y", align=0, gap=10.0)
    goal = (_rect(a).l, _rect(a).b + 10.0)
    assert env.mgr._arranging()                                          # não pulou para o lugar
    xs = []
    for _ in range(80):
        QTest.qWait(16)
        xs.append(_rect(b).l)
        if not env.mgr._arranging():
            break
    assert len(set(round(x) for x in xs)) > 4                           # passou por várias posições
    # vai na direção do alvo; a mola SLIDE (420/34) passa no máximo uns 2 px e volta, sem ir e vir
    assert all(x2 <= x1 + 3.0 for x1, x2 in zip([start.l] + xs, xs))
    assert min(xs) >= goal[0] - 4.0
    assert not env.mgr._arranging()
    assert abs(_rect(b).l - goal[0]) < 1.0 and abs(_rect(b).t - goal[1]) < 1.0
    assert env.store.get("groups")                                      # salvo ao terminar


def test_align_without_animations_is_instant(env):
    a = env.make("weather", 200, 200)
    b = env.make("performance", 700, 260)
    env.mgr.align_widgets(a, axis="x", align=0, gap=10.0)
    assert not env.mgr._arranging()
    assert abs(_rect(b).l - _rect(a).r - 10.0) < 1.0 and abs(_rect(b).t - _rect(a).t) < 1.0


def test_aligned_group_shares_the_reference_layer(env):
    a = _pinnable(env, "weather", 200, 200, pinned=True)
    b = _pinnable(env, "performance", 700, 260, pinned=False)
    QTest.qWait(900)
    env.mgr.align_widgets(a, axis="y", align=0)
    QTest.qWait(900)
    assert a.is_desktop_mode() and b.is_desktop_mode()


def test_group_with_a_member_that_cannot_pin_stays_on_top(env):
    a = _pinnable(env, "weather", 200, 200, pinned=True)
    music = env.make("music", 700, 260)
    music.desktop_mode_target = None          # um widget sem "Fixar na área de trabalho" (salvaguarda do anchor)
    QTest.qWait(900)
    env.mgr.align_widgets(a, axis="y", align=0)
    QTest.qWait(900)
    assert not a.is_desktop_mode()            # uma camada só: o grupo inteiro fica por cima
