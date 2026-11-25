"""
Chips: o botão padrão do Hub e a fileira que os agrupa. Toda fileira de botões lado a lado sai de `chip_row`, que já
traz o vão `CHIP_GAP`; assim nenhuma tela esquece o espaço entre eles.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton

from app.hub.ui_tokens import CHIP_GAP


def chip(text: str = "", on_click=None, *, primary: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("class", "Chip")
    if primary:
        btn.setProperty("selected", "true")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def chip_row(*buttons: QPushButton) -> QHBoxLayout:
    """Fileira de chips com o vão padrão e sem margens (quem posiciona a fileira é o layout pai)."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(CHIP_GAP)
    for btn in buttons:
        row.addWidget(btn)
    return row
