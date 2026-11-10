"""
SlideFadeAnimator - surgimento/desaparecimento de janelas flutuantes (fade + deslize curto).

Um único progresso `t` (0 = oculto, 1 = visível) alimenta opacidade e deslocamento vertical,
então inverter no meio da animação (ex.: apertar o atalho duas vezes) continua de onde está,
sem salto. A janela só se move durante a animação; a posição "de repouso" é guardada à parte
e exposta por `rest_pos()`, para que nada (arraste, "Lembrar posição", troca de skin) grave um
ponto deslocado.

Respeita a configuração "Efeitos de animação" do Windows: desligada = troca instantânea.
"""

import ctypes
import sys

from PySide6.QtCore import QEasingCurve, QObject, QPoint, Qt, QVariantAnimation
from PySide6.QtWidgets import QWidget

SLIDE_PX = 8

_SPI_GETCLIENTAREAANIMATION = 0x1042


def animations_enabled() -> bool:
    """False se o usuário desativou os efeitos de animação do Windows."""
    if sys.platform != "win32":
        return True
    try:
        flag = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0
        )
        return bool(flag.value) if ok else True
    except Exception:
        return True


class SlideFadeAnimator(QObject):
    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self._widget = widget
        self._t = 1.0                 # progresso atual
        self._target = 1.0
        self._rest: QPoint | None = None  # posição de repouso enquanto a animação estiver ativa

        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._on_finished)

    # --- Estado ---

    def is_animating(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def is_hiding(self) -> bool:
        return self.is_animating() and self._target == 0.0

    def rest_pos(self) -> QPoint:
        """Posição real do widget, sem o deslocamento da animação."""
        if self._rest is not None:
            return QPoint(self._rest)
        return self._widget.pos()

    # --- API ---

    def show(self, duration_ms: int):
        w = self._widget
        if not w.isVisible():
            self._rest = w.pos()
            self._t = 0.0
            self._apply(0.0)
            w.show()
        elif not self.is_animating():
            return  # já visível e parado
        self._run(1.0, duration_ms)

    def hide(self, duration_ms: int):
        w = self._widget
        if not w.isVisible():
            return
        if self._rest is None:
            self._rest = w.pos()
        self._run(0.0, duration_ms)

    def settle(self):
        """Conclui a animação em curso no estado final, imediatamente."""
        if not self.is_animating():
            return
        self._anim.stop()
        self._finalize()

    # --- Internos ---

    def _run(self, target: float, base_ms: int):
        self._target = target
        distance = abs(target - self._t)
        if not animations_enabled() or base_ms <= 0 or distance == 0.0:
            self._anim.stop()
            self._finalize()
            return
        self._widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._anim.stop()
        self._anim.setDuration(max(1, int(base_ms * distance)))
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(target)
        self._anim.start()

    def _apply(self, t: float):
        w = self._widget
        rest = self._rest if self._rest is not None else w.pos()
        w.setWindowOpacity(max(0.0, min(1.0, t)))
        w.move(rest.x(), rest.y() + round((1.0 - t) * SLIDE_PX))

    def _on_value(self, value):
        self._t = float(value)
        self._apply(self._t)

    def _on_finished(self):
        self._finalize()

    def _finalize(self):
        w = self._widget
        rest = self._rest if self._rest is not None else w.pos()
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        if self._target == 0.0:
            w.move(rest)
            w.hide()
            w.setWindowOpacity(1.0)
            self._t = 0.0
        else:
            w.move(rest)
            w.setWindowOpacity(1.0)
            self._t = 1.0
        self._rest = None
