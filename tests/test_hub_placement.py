"""Hotfix 1.1.3: o Hub abria fora de todas as telas quando a posição salva era de um monitor que não existe mais
(ícone na barra de tarefas, nenhuma janela à vista)."""
import sys

from PySide6.QtWidgets import QApplication

from app.hub import hub_placement as hp

# Arranjo real do relatório: três monitores, nenhum à esquerda do x = 0
SCREENS = [(0, 0, 2560, 1392), (2560, -207, 1080, 1872), (3640, -207, 3072, 1680)]
PRIMARY = SCREENS[0]


def test_position_left_of_every_screen_is_pulled_back_to_primary():
    fitted = hp.fit_to_screens((-3025, 482, 1243, 1013), SCREENS, PRIMARY)
    assert fitted == ((2560 - 1243) // 2, (1392 - 1013) // 2, 1243, 1013)
    assert hp.is_reachable(fitted, SCREENS)


def test_visible_position_is_kept_on_any_monitor():
    for rect in [(100, 100, 1020, 680), (2600, 0, 1000, 700), (4000, -100, 1200, 800)]:
        assert hp.fit_to_screens(rect, SCREENS, PRIMARY) == rect


def test_partly_off_screen_but_grabbable_is_kept():
    # Metade para fora pela esquerda: a barra de título continua pegável
    rect = (-500, 200, 1020, 680)
    assert hp.fit_to_screens(rect, SCREENS, PRIMARY) == rect


def test_title_bar_above_the_screens_is_not_reachable():
    # Corpo visível, mas a barra de título ficou acima do topo: não dá para arrastar
    assert not hp.is_reachable((300, -400, 1020, 680), [PRIMARY])
    fitted = hp.fit_to_screens((300, -400, 1020, 680), [PRIMARY], PRIMARY)
    assert hp.is_reachable(fitted, [PRIMARY])


def test_only_a_sliver_on_screen_is_pulled_back():
    rect = (2560 - 40, 300, 1020, 680)   # só 40 px dentro da tela principal, nada nas outras
    assert hp.fit_to_screens(rect, [PRIMARY], PRIMARY) != rect


def test_window_bigger_than_the_screen_shrinks_to_fit():
    small = (0, 0, 800, 500)
    assert hp.fit_to_screens((-5000, 0, 1243, 1013), [small], small) == (0, 0, 800, 500)


def test_no_screens_leaves_geometry_alone():
    rect = (-3025, 482, 1243, 1013)
    assert hp.fit_to_screens(rect, [], None) == rect


def test_hub_window_opens_on_a_real_screen(monkeypatch):
    """O Hub de verdade, com a posição salva do relatório: tem que ficar numa tela conectada agora."""
    app = QApplication.instance() or QApplication(sys.argv)
    from app.hub import hub_window

    monkeypatch.setattr(hub_window.config_manager, "get_hub_geometry", lambda: (-30000, 482, 1243, 1013))
    monkeypatch.setattr(hub_window.config_manager, "save_hub_geometry", lambda *a: None)
    hub = hub_window.AimedgetHubWindow(defer_ui=True)
    try:
        g = hub.geometry()
        screens, _primary = hp.current_screens()
        assert hp.is_reachable((g.x(), g.y(), g.width(), g.height()), screens)
    finally:
        hub.tray_icon.hide()
        hub.deleteLater()
        app.processEvents()
