"""
Troca de página do Hub: a foto da página antiga fica por cima, some (fade) e escorrega no eixo Y na direção em que a
barra lateral andou (descer na barra: a antiga sobe; subir: a antiga desce), revelando a nova por baixo.
180 ms no total, curva de saída rápida (cúbica) para a troca parecer imediata.
"""

import time

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

DURATION_MS = 180
SHIFT_PX = 12
FRAME_MS = 8


def ease_out(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


class PageTransition(QWidget):
    """Camada transparente ao mouse, filha do QStackedWidget. `start(foto, direção)`; some sozinha ao terminar."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pixmap: QPixmap | None = None
        self._dir = 1
        self._t0 = 0.0
        self._progress = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def progress(self) -> float:
        return self._progress

    def start(self, snapshot: QPixmap, direction: int):
        self._pixmap = snapshot
        self._dir = 1 if direction >= 0 else -1
        self._progress = 0.0
        self._t0 = time.monotonic()
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._pixmap = None
        self._progress = 1.0
        self.hide()

    def _tick(self):
        self._progress = (time.monotonic() - self._t0) * 1000.0 / DURATION_MS
        if self._progress >= 1.0:
            self.stop()
        else:
            self.update()

    def paintEvent(self, event):
        if self._pixmap is None:
            return
        e = ease_out(self._progress)
        painter = QPainter(self)
        painter.setOpacity(1.0 - e)
        painter.setClipRect(QRect(0, 0, self.width(), self.height()))
        painter.drawPixmap(0, int(round(-self._dir * SHIFT_PX * e)), self._pixmap)
