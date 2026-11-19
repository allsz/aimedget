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
    QTest.qWait(int(am.INTRO_DUR * 1000) + 120)                      # a ondinha de "Ancorar" termina
    ra, rb = _rect(a), _rect(b)
    _drag(env.mgr, b, int(ra.r + GAP + 6 - rb.l), int(ra.t + 6 - rb.t))
    g = env.mgr.group_of("weather")
    first_gain = g.gain
    first_l = _rect(b).l
    assert first_l == pytest.approx(ra.r + GAP + 6, abs=1.5)        # o ímã ainda não puxou: não pula
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
