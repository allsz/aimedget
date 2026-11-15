"""
Intervalo de um timer de animação na taxa de atualização do monitor.

Um só lugar para a regra, usado por tudo que anima quadro a quadro (mixer, Caps/Num Lock, seletor de cor, deslize de
posição): 144 Hz -> 7 ms, 60 Hz -> 17 ms. O movimento deve usar o TEMPO REAL entre quadros (não contar quadros), então
a duração é a mesma em qualquer monitor; isto só decide com que frequência redesenhar.
"""

from PySide6.QtWidgets import QApplication, QWidget

DEFAULT_HZ = 60.0   # quando o Qt não informa a taxa (ou informa algo implausível)
MAX_HZ = 240.0      # acima disso o ganho é imperceptível e o timer só gasta CPU
MIN_MS = 4


def refresh_interval_ms(widget: QWidget | None = None) -> int:
    """Intervalo (ms) na taxa do monitor onde `widget` está; sem widget, o do monitor primário."""
    screen = widget.screen() if widget is not None else None
    if screen is None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app else None
    hz = float(screen.refreshRate()) if screen is not None and screen.refreshRate() > 10.0 else DEFAULT_HZ
    return max(MIN_MS, int(round(1000.0 / min(hz, MAX_HZ))))
