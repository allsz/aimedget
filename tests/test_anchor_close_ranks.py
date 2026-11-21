"""
Esconder um membro de um grupo de ancoragem: ele fica AUSENTE (no grupo, sem ocupar espaço) e os outros fecham as
fileiras; ao voltar, o lugar reabre igual. Protótipo e valores: mockups/anchor-close-ranks.html.
"""
import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core import anchor_geometry as geo
from app.core import anchor_manager as am
from app.core import widget_animator as wa
from test_anchor import env, qapp  # noqa: F401  (fixtures)

GAP = 10.0


def _rect(c):
    return am.card_rect(c)


def _area():
    a = QGuiApplication.primaryScreen().availableGeometry()
    return geo.Rect.of(a.x(), a.y(), a.width(), a.height())


def _group(env, tree):
    g = am.Group(tree)
    for k in g.keys():
        env.mgr._groups[k] = g
    root = g.keys()[0]
    env.mgr._reflow(g, root)
    QApplication.processEvents()
    return g


def _row(*keys):
    t = keys[0]
    for k in keys[1:]:
        t = geo.Join(t, k, "x", 0, 0.0, GAP)
    return t


def _hide(c):
    c.animator.hide(160)
    QApplication.processEvents()


def _show(c):
    c.animator.show(200)
    QApplication.processEvents()


@pytest.fixture
def no_anim(env, monkeypatch):
    env.state["anim"] = False
    monkeypatch.setattr(wa, "animations_enabled", lambda: False)
    return env


# --- Uma fileira --------------------------------------------------------------------------------------------------


def test_hiding_the_middle_closes_the_row_and_showing_reopens_it_exactly(no_anim):
    env = no_anim
    area = _area()
    x0, y0 = area.l + 60, area.t + 120            # perto da borda ESQUERDA: a esquerda fica parada
    cs = [env.make(k, x0 + i * 400, y0) for i, k in enumerate(("weather", "performance", "storage", "battery"))]
    _group(env, _row("weather", "performance", "storage", "battery"))
    before = {c.ANCHOR_KEY: _rect(c) for c in cs}
    w, p, s, b = cs

    _hide(s)
    assert not s.isVisible()
    assert _rect(w) == before["weather"] and _rect(p) == before["performance"]           # o lado da borda não mexe
    assert _rect(b).l == pytest.approx(_rect(p).r + GAP, abs=1)                         # sem buraco
    assert env.mgr.group_of("storage") is env.mgr.group_of("battery")                   # continua no grupo

    _show(s)
    for c in cs:
        assert _rect(c) == pytest.approx(before[c.ANCHOR_KEY], abs=1)                    # tudo volta ao mesmo pixel


def test_a_group_docked_at_the_right_edge_keeps_that_edge_still(no_anim):
    env = no_anim
    area = _area()
    w = env.make("weather", 0, 0)
    width = _rect(w).w
    total = 4 * width + 3 * GAP
    x0, y0 = area.r - 30 - total, area.t + 120
    cs = [w] + [env.make(k, 0, 0) for k in ("performance", "storage", "battery")]
    w.move_card_to(int(x0), int(y0))
    QApplication.processEvents()
    _group(env, _row("weather", "performance", "storage", "battery"))
    right = _rect(cs[-1])
    left_before = _rect(cs[0]).l

    _hide(cs[2])                                                                        # Armazenamento
    assert _rect(cs[-1]) == pytest.approx(right, abs=1)                                 # Baterias (na borda) parada
    assert _rect(cs[0]).l == pytest.approx(left_before + width + GAP, abs=1)            # os de dentro andaram


def test_the_dragged_widget_can_take_the_space_because_there_is_no_hole(no_anim):
    """O bug do vídeo: com o buraco reservado, soltar outro widget ali o fazia voltar. Agora não há buraco."""
    env = no_anim
    area = _area()
    cs = [env.make(k, area.l + 60 + i * 400, area.t + 120) for i, k in enumerate(("weather", "performance", "storage"))]
    _group(env, _row("weather", "performance", "storage"))
    _hide(cs[1])
    visible = [_rect(c) for c in cs if c.isVisible()]
    assert visible[1].l - visible[0].r == pytest.approx(GAP, abs=1)


# --- Grade (2 fileiras de 3) --------------------------------------------------------------------------------------


def _grid(env, align: int):
    area = _area()
    keys_top, keys_bottom = ("weather", "performance", "storage"), ("battery", "music", "timer")
    cs = {}
    for i, k in enumerate(keys_top + keys_bottom):
        cs[k] = env.make(k, area.l + 60 + (i % 3) * 400, area.t + 80 + (i // 3) * 400)
    tree = geo.Join(_row(*keys_top), _row(*keys_bottom), "y", align, 0.0, GAP)
    _group(env, tree)
    return cs


def test_grid_centered_rows_meet_in_the_middle(no_anim):
    cs = _grid(no_anim, align=2)                      # fileiras centralizadas uma na outra
    before = {k: _rect(c) for k, c in cs.items()}
    _hide(cs["performance"])                          # o do meio da fileira de cima
    shift = (before["performance"].w + GAP) / 2
    assert _rect(cs["weather"]).l == pytest.approx(before["weather"].l + shift, abs=1)    # da esquerda para o meio
    assert _rect(cs["storage"]).l == pytest.approx(before["storage"].l - shift, abs=1)    # da direita para o meio
    for k in ("battery", "music", "timer"):           # a fileira de baixo não se mexe
        assert _rect(cs[k]) == pytest.approx(before[k], abs=1)
    _show(cs["performance"])
    for k, c in cs.items():
        assert _rect(c) == pytest.approx(before[k], abs=1)


def test_grid_left_aligned_rows_keep_the_left_column_lined_up(no_anim):
    cs = _grid(no_anim, align=0)                      # fileiras alinhadas à esquerda
    before = {k: _rect(c) for k, c in cs.items()}
    _hide(cs["performance"])
    assert _rect(cs["weather"]) == pytest.approx(before["weather"], abs=1)               # coluna da esquerda alinhada
    assert _rect(cs["storage"]).l == pytest.approx(_rect(cs["weather"]).r + GAP, abs=1)


# --- O que NÃO fecha as fileiras ----------------------------------------------------------------------------------


def test_show_desktop_hiding_the_whole_group_does_not_close_ranks(no_anim):
    env = no_anim
    area = _area()
    cs = [env.make(k, area.l + 60 + i * 400, area.t + 120) for i, k in enumerate(("weather", "performance", "storage"))]
    _group(env, _row("weather", "performance", "storage"))
    before = [_rect(c) for c in cs]
    for c in cs:                                      # o Win+D suspende todos (não fixados) de uma vez
        c._on_show_desktop(True)
    QApplication.processEvents()
    assert not env.mgr._absent
    for c in cs:
        c._on_show_desktop(False)
    QApplication.processEvents()
    assert [_rect(c) for c in cs] == pytest.approx(before, abs=1)


def test_closing_the_app_does_not_close_ranks(no_anim, monkeypatch):
    from PySide6.QtCore import QCoreApplication
    env = no_anim
    area = _area()
    cs = [env.make(k, area.l + 60 + i * 400, area.t + 120) for i, k in enumerate(("weather", "performance"))]
    _group(env, _row("weather", "performance"))
    monkeypatch.setattr(QCoreApplication, "closingDown", staticmethod(lambda: True))
    _hide(cs[0])
    assert not env.mgr._absent


# --- Abertura do app, borda da tela, desancorar com alguém escondido --------------------------------------------


def test_a_member_that_never_appeared_takes_no_space_and_opens_its_slot_later(no_anim):
    env = no_anim
    area = _area()
    w = env.make("weather", area.l + 60, area.t + 120)
    b = env.make("battery", area.l + 60 + 900, area.t + 120)
    g = am.Group(_row("weather", "timer", "battery"))          # o timer não abre junto com o app
    for k in g.keys():
        env.mgr._groups[k] = g
    env.mgr._sizes["timer"] = (200.0, 200.0)
    env.mgr._reflow(g, "weather")
    QApplication.processEvents()
    assert _rect(b).l == pytest.approx(_rect(w).r + GAP, abs=1)   # já começa fechado (sem o espaço do timer)

    t = env.make("timer", 0, 0)                                  # aparece depois (atalho): o lugar dele reabre
    assert _rect(t).l == pytest.approx(_rect(w).r + GAP, abs=1)
    assert _rect(b).l == pytest.approx(_rect(t).r + GAP, abs=1)


def test_reopening_near_the_screen_edge_keeps_the_whole_group_on_screen(no_anim):
    env = no_anim
    area = _area()
    w = env.make("weather", 0, 0)
    width = _rect(w).w
    cs = [w, env.make("performance", 0, 0), env.make("storage", 0, 0)]
    _group(env, _row("weather", "performance", "storage"))
    _hide(cs[1])
    # o par visível é levado até encostar na borda direita da tela, com o espaço do escondido "lá fora"
    gx = area.r - (2 * width + GAP) - 2
    dx = gx - _rect(cs[0]).l
    for c in (cs[0], cs[2]):
        r = _rect(c)
        c.move_card_to(int(r.l + dx), int(r.t))
    QApplication.processEvents()
    env.mgr._absent.discard("performance")          # simula o anterior ao reaparecer (o show refaz isso)
    env.mgr._absent.add("performance")
    _show(cs[1])
    rs = [_rect(c) for c in cs]
    assert min(r.l for r in rs) >= area.l - 1 and max(r.r for r in rs) <= area.r + 1   # cabe inteiro na tela
    assert rs[1].l == pytest.approx(rs[0].r + GAP, abs=1) and rs[2].l == pytest.approx(rs[1].r + GAP, abs=1)


def test_detaching_while_a_member_is_hidden_keeps_its_slot(no_anim):
    env = no_anim
    area = _area()
    cs = [env.make(k, area.l + 60 + i * 400, area.t + 120) for i, k in enumerate(("weather", "performance", "storage"))]
    _group(env, _row("weather", "performance", "storage"))
    w, p, s = cs
    _hide(p)
    env.mgr.detach(s)                                 # tira o Armazenamento (visível) do grupo
    assert not env.mgr.is_grouped(s)
    assert env.mgr.group_of("weather") is env.mgr.group_of("performance")
    _show(p)                                          # o escondido volta ao lado do Clima, como antes
    assert _rect(p).l == pytest.approx(_rect(w).r + GAP, abs=1)
    assert _rect(p).t == pytest.approx(_rect(w).t, abs=1)


# --- Com animação --------------------------------------------------------------------------------------------------


def _width(cs):
    rs = [_rect(c) for c in cs if c.isVisible() and not c.animator.is_hiding()]
    return max(r.r for r in rs) - min(r.l for r in rs)


def test_closing_and_reopening_slide_without_a_dent_and_end_clean(env, monkeypatch):
    env.state["anim"] = True
    monkeypatch.setattr(wa, "animations_enabled", lambda: True)
    area = _area()
    cs = [env.make(k, area.l + 60 + i * 400, area.t + 120) for i, k in enumerate(("weather", "performance", "storage", "battery"))]
    QTest.qWait(260)                                  # surgir inicial termina (os vizinhos estão "calmos")
    _group(env, _row("weather", "performance", "storage", "battery"))
    before = {c.ANCHOR_KEY: _rect(c) for c in cs}
    s, b = cs[2], cs[3]

    _hide(s)
    assert env.mgr._slide is not None                 # anima (não pula)
    widths = []
    for _ in range(40):
        QTest.qWait(16)
        widths.append(_width(cs))
    assert env.mgr._slide is None                     # terminou limpo
    assert widths == sorted(widths, reverse=True)     # só diminui: sem dente
    assert _rect(b).l == pytest.approx(_rect(cs[1]).r + GAP, abs=1)

    _show(s)
    assert s.animator.is_animating()
    assert s.windowOpacity() == 0.0                   # espera o espaço abrir antes de surgir
    QTest.qWait(am.REOPEN_DELAY_MS // 2)
    assert s.windowOpacity() == 0.0
    widths = []
    for _ in range(50):
        QTest.qWait(16)
        widths.append(max(r.r for r in (_rect(c) for c in cs)) - min(r.l for r in (_rect(c) for c in cs)))
    assert widths == sorted(widths)                   # só aumenta
    assert s.windowOpacity() == pytest.approx(1.0)
    for c in cs:
        assert _rect(c) == pytest.approx(before[c.ANCHOR_KEY], abs=1)


def test_grabbing_a_member_mid_slide_settles_it_first(env, monkeypatch):
    env.state["anim"] = True
    monkeypatch.setattr(wa, "animations_enabled", lambda: True)
    area = _area()
    cs = [env.make(k, area.l + 60 + i * 400, area.t + 120) for i, k in enumerate(("weather", "performance", "storage"))]
    QTest.qWait(260)
    _group(env, _row("weather", "performance", "storage"))
    _hide(cs[1])
    QTest.qWait(30)
    assert env.mgr._slide is not None
    env.mgr.drag_to(cs[2], cs[2].pos())               # pegou o Armazenamento no meio do deslize
    assert env.mgr._slide is None
    env.mgr.drag_end(cs[2])
    assert _rect(cs[2]).l == pytest.approx(_rect(cs[0]).r + GAP, abs=1)
