"""
AccentEntryRow - linha do campo de cor (hex) com o botão "Redefinir" que aparece só quando há cor personalizada.

Sem cor personalizada, o campo fica sozinho à direita (alinhado à ponta da trilha do seletor). Quando o usuário
muda a cor, ele desliza para a esquerda e o "Redefinir" sai de trás dele, formando um par colado (GAP_PX entre eles)
CENTRALIZADO sob a barra de cor:
- o campo desliza da direita até a posição do par, com um leve passo além do alvo (OutBack) que assenta;
- o "Redefinir" sai de trás do campo um instante depois (RESET_DELAY), com mais overshoot, surgindo em fade e descendo
  uns pixels ao lugar; ao sair, o mesmo caminho de volta (ele recua para trás do campo e o campo volta à direita).

Um progresso (0 -> 1) controla tudo, então a animação pode ser interrompida no meio sem saltos. Os filhos são
posicionados à mão (um layout não anima posição). `inset` alinha a ponta direita à da trilha do seletor.
"""

from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLineEdit, QPushButton, QSizePolicy, QWidget

from app.core.widget_animator import animations_enabled

DURATION_MS = 480          # entrada/saída completas; trechos parciais (interrupção) são proporcionais
MIN_MS = 140
GAP_PX = 8                 # espaço entre o campo e o botão quando juntos
RESET_DELAY = 0.14         # fração do progresso que o botão espera para começar a sair de trás do campo
FIELD_OVERSHOOT = 1.0      # passo além do alvo discreto: o par assenta em vez de quicar
RESET_OVERSHOOT = 1.1
FADE_SPAN = 0.7            # fração do trecho do botão em que ele passa de invisível a opaco
DROP_PX = 4                # o botão chega descendo esses pixels


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
        field.raise_()   # o botão sai de trás dele

        self._fade = QGraphicsOpacityEffect(reset)
        reset.setGraphicsEffect(self._fade)

        self._field_curve = QEasingCurve(QEasingCurve.Type.OutBack)
        self._field_curve.setOvershoot(FIELD_OVERSHOOT)
        self._reset_curve = QEasingCurve(QEasingCurve.Type.OutBack)
        self._reset_curve.setOvershoot(RESET_OVERSHOOT)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DURATION_MS)
        # O tempo é suavizado nas duas pontas (parte e chega sem tranco); as curvas de cada voz entram por cima em _apply.
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
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
        self._reset.setEnabled(shown)   # some: deixa de ser clicável na hora, mesmo durante o movimento
        if shown:
            self._reset.setVisible(True)
        target = 1.0 if shown else 0.0
        self._anim.stop()
        if not animated or not self.isVisible() or not animations_enabled():
            self._set_progress(target)
            self._on_finished()
            return
        start = self._progress   # parte de onde está: interromper não dá salto
        self._anim.setStartValue(start)
        self._anim.setEndValue(target)
        self._anim.setDuration(max(MIN_MS, int(DURATION_MS * abs(target - start))))
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
        fh = self._field.sizeHint().height()
        rw = self._reset.sizeHint().width()
        rh = self._reset.sizeHint().height()
        p = max(0.0, min(1.0, self._progress))

        # Voz 1: o campo vai da direita (alinhado à barra) à posição do par centralizado
        alone_x = w - self._inset - fw
        pair_x = (w - (fw + GAP_PX + rw)) / 2.0
        fx = alone_x + (pair_x - alone_x) * self._field_curve.valueForProgress(p)
        self._field.setGeometry(round(fx), (h - fh) // 2, fw, fh)

        # Voz 2: o botão espera um instante e sai de trás do campo até o lado dele, com overshoot e fade
        raw = max(0.0, min(1.0, (p - RESET_DELAY) / (1.0 - RESET_DELAY)))
        final_x = pair_x + fw + GAP_PX
        start_x = fx + fw - rw
        rx = start_x + (final_x - start_x) * self._reset_curve.valueForProgress(raw)
        drop = DROP_PX * (1.0 - min(1.0, raw))
        self._reset.setGeometry(round(rx), round((h - rh) / 2.0 + drop), rw, rh)
        f = max(0.0, min(1.0, raw / FADE_SPAN))
        self._fade.setOpacity(f * f * (3.0 - 2.0 * f))   # smoothstep: o fade nasce e termina suave, sem corte

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply()   # um resize feito com o widget oculto só chega aqui
