"""
AccentEntryRow - linha do campo de cor (hex) com o botão "Restaurar" que aparece só quando há cor personalizada.

Sem cor personalizada, o campo fica sozinho à direita (alinhado à ponta da trilha do seletor). Quando o usuário
muda a cor, o campo desliza para a esquerda e o "Restaurar" sai de trás dele, colado à sua borda (com fade).
Restaurar faz o caminho inverso. Uma única animação (0 -> 1) controla tudo, com desaceleração exponencial, e pode
ser interrompida no meio sem saltos.

Os filhos são posicionados à mão (um layout não anima posição). `inset` alinha as pontas às da trilha do seletor.
"""

from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLineEdit, QPushButton, QSizePolicy, QWidget

DURATION_MS = 260


class AccentEntryRow(QWidget):
    def __init__(self, field: QLineEdit, reset: QPushButton, inset: int = 0, shown: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._field = field
        self._reset = reset
        self._inset = inset
        self._shown = shown
        self._progress = 1.0 if shown else 0.0
        self._idle: list = []
        field.setParent(self)
        reset.setParent(self)

        self._fade = QGraphicsOpacityEffect(reset)
        reset.setGraphicsEffect(self._fade)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        self._anim.valueChanged.connect(self._set_progress)
        self._anim.finished.connect(self._on_finished)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(max(field.sizeHint().height(), reset.sizeHint().height()))
        reset.setVisible(shown)
        reset.setEnabled(shown)
        self._apply()

    # --- API ---

    def reset_shown(self) -> bool:
        """Estado pedido (o destino da animação), não o quadro atual."""
        return self._shown

    def is_animating(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def when_idle(self, fn):
        """Roda `fn` já, ou quando a animação em curso terminar. Serve para adiar trabalho pesado (reaplicar o
        estilo do Hub leva ~70 ms) que, no meio do movimento, congelaria alguns quadros."""
        if not self.is_animating():
            fn()
        elif fn not in self._idle:
            self._idle.append(fn)

    def set_reset_shown(self, shown: bool, animated: bool = True):
        if shown == self._shown:
            return
        self._shown = shown
        self._reset.setEnabled(shown)   # some: deixa de ser clicável na hora, mesmo durante o fade
        if shown:
            self._reset.setVisible(True)
        target = 1.0 if shown else 0.0
        self._anim.stop()
        if not animated or not self.isVisible():
            self._set_progress(target)
            self._on_finished()
            return
        self._anim.setStartValue(self._progress)   # parte de onde está: interromper não dá salto
        self._anim.setEndValue(target)
        self._anim.start()

    def relayout(self):
        """Recalcula as posições (ex.: o texto do botão mudou com o idioma)."""
        self.setFixedHeight(max(self._field.sizeHint().height(), self._reset.sizeHint().height()))
        self._apply()

    # --- Animação ---

    def _set_progress(self, value):
        self._progress = float(value)
        self._apply()

    def _on_finished(self):
        if not self._shown:
            self._reset.setVisible(False)
        callbacks, self._idle = self._idle, []
        for fn in callbacks:
            fn()

    def _apply(self):
        w = self.width()
        h = self.height()
        fw = self._field.width() or self._field.sizeHint().width()
        rw = self._reset.sizeHint().width()
        p = self._progress

        right_x = w - self._inset - fw
        left_x = self._inset
        fx = right_x + (left_x - right_x) * p
        self._field.setGeometry(round(fx), (h - self._field.sizeHint().height()) // 2, fw,
                                self._field.sizeHint().height())

        # O "Restaurar" vem colado à borda direita do campo (sai de trás dele, recortado pela linha) até a
        # posição final; assim os dois nunca se sobrepõem durante o deslize.
        final_rx = w - self._inset - rw
        gap = final_rx - (left_x + fw)
        rx = max(final_rx, fx + fw + gap)
        self._reset.setGeometry(round(rx), (h - self._reset.sizeHint().height()) // 2, rw,
                                self._reset.sizeHint().height())
        self._fade.setOpacity(p)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply()   # um resize feito com o widget oculto só chega aqui
