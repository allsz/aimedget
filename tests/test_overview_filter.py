"""Filtrar/buscar na Visão geral: os cartões saem do layout sem virar janela solta (nunca setParent(None))."""
import sys

from PySide6.QtWidgets import QApplication

from app.hub.pages import OverviewPage


def _app():
    return QApplication.instance() or QApplication(sys.argv)


def test_filtered_out_cards_stay_children_of_the_grid_and_come_back():
    _app()
    page = OverviewPage()
    page.resize(900, 700)
    page.show()
    QApplication.processEvents()
    grid = page.grid_container
    cards = list(page._cards)
    assert cards

    page._on_search_changed("zzz-nada-combina")
    QApplication.processEvents()
    for card in cards:
        assert card.parentWidget() is grid          # nada vira janela própria
        assert not card.isWindow()
        assert not card.isVisible()
    assert page.grid_layout.count() == 0

    page._on_search_changed("")
    QApplication.processEvents()
    assert page.grid_layout.count() == len(cards)
    for card in cards:
        assert card.parentWidget() is grid and card.isVisible()
    page.close()
    page.deleteLater()
