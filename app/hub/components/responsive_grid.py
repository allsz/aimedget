"""
ResponsiveCardGrid - Grid dinâmico e auto-responsivo para miniaturas de skins e widgets.
Evita sobreposição e quebra horizontal indesejada:
- 4 colunas quando há espaço pleno na janela.
- 2 colunas (2x2) quando a janela é redimensionada para largura média/compacta.
- 1 coluna em larguras extremas.
"""

from typing import List
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget


class ResponsiveCardGrid(QWidget):
    """
    Container de grid adaptativo que calcula dinamicamente o número ideal de colunas
    baseado na largura disponível do container, sem sobreposição de cartões.
    """

    def __init__(self, min_card_width: int = 150, spacing: int = 16, parent: QWidget | None = None):
        super().__init__(parent)
        self._min_card_width = min_card_width
        self._spacing = spacing
        self._cards: List[QWidget] = []
        self._current_cols = -1

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)

    def add_card(self, card: QWidget):
        """Adiciona um card ao grid responsivo."""
        self._cards.append(card)
        self._relayout(force=True)

    def set_cards(self, cards: List[QWidget]):
        """Define a lista completa de cards."""
        self._cards = list(cards)
        self._relayout(force=True)

    def minimumSizeHint(self) -> QSize:
        """
        Retorna a largura mínima necessária para acomodar uma coluna,
        permitindo que a janela e o viewport encolham suavemente sem travar.
        """
        return QSize(self._min_card_width, 140)

    def _calc_cols(self, width: int) -> int:
        if not self._cards or width <= 0:
            return 1
        total = len(self._cards)
        gap = self._spacing
        min_w = self._min_card_width

        # Se couberem todos os cards em 1 linha
        if width >= total * min_w + (total - 1) * gap:
            return total

        # Se couberem pelo menos 2 colunas
        if width >= 2 * min_w + gap:
            return 2

        return 1

    def _relayout(self, force: bool = False):
        w = self.width()
        cols = self._calc_cols(w)
        if not force and cols == self._current_cols:
            return
        self._current_cols = cols

        for i in reversed(range(self._grid.count())):
            self._grid.takeAt(i)

        for idx, card in enumerate(self._cards):
            r = idx // cols
            c = idx % cols
            self._grid.addWidget(card, r, c)

        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()
