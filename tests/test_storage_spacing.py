"""Espaçamento padrão do Hub: tokens e chip_row (veja app/hub/ui_tokens.py e CLAUDE.md)."""

import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QPushButton

from app.hub.components.chips import chip, chip_row
from app.hub.ui_tokens import CARD_MARGINS, CHIP_GAP


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def test_chip_row_puts_the_standard_gap_between_buttons(qapp):
    from PySide6.QtWidgets import QWidget
    host = QWidget()
    a, b = chip("Um"), chip("Dois")
    host.setLayout(chip_row(a, b))
    host.show()
    _pump(0.1)
    assert b.x() - (a.x() + a.width()) == CHIP_GAP
    host.close()


def test_storage_folder_buttons_have_gap_and_card_bottom_matches_top(qapp, monkeypatch):
    from app.core.config_manager import config_manager
    monkeypatch.setattr(config_manager, "_save", lambda *a, **k: None)
    from app.hub.storage_page import StoragePage
    page = StoragePage()
    page.resize(760, 1300)
    page.show()
    _pump()
    a, b = page.btn_add_folder, page.btn_restore_folders
    assert b.x() - (a.x() + a.width()) == CHIP_GAP
    card = page.folders_card
    if page.folder_list.height() > 0:
        last_bottom = page.folder_list.mapTo(card, page.folder_list.rect().bottomLeft()).y() + 1
        from app.hub.ui_tokens import LIST_ROW_GAP
        content_bottom = last_bottom - LIST_ROW_GAP
        assert card.height() - content_bottom == CARD_MARGINS[3]
    page.close()
