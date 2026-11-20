"""
SlideFadeAnimator - surgimento/desaparecimento de janelas flutuantes (fade + deslize curto).

Um único progresso `t` (0 = oculto, 1 = visível) alimenta opacidade e deslocamento vertical,
então inverter no meio da animação (ex.: apertar o atalho duas vezes) continua de onde está,
sem salto. A janela só se move durante a animação; a posição "de repouso" é guardada à parte
e exposta por `rest_pos()`, para que nada (arraste, "Lembrar posição", troca de skin) grave um
ponto deslocado.

Respeita a configuração "Efeitos de animação" do Windows: desligada = troca instantânea.

Para ligar um widget a isto sem repetir código há dois mixins:
- `AnimatedSkinMixin` na JANELA (skin): cria o animador e expõe `rest_pos()`.
- `AnimatedVisibilityMixin` no CONTROLLER: `show`/`hide` animados, `is_shown`, `is_hiding` e `settle`, com os tempos
  padrão. O widget de música e o timer usam os mesmos; um widget novo só os herda.
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


class AnimatedSkinMixin:
    """Para a janela (skin) de um widget que surge/some com SlideFadeAnimator: dono do animador e da posição de repouso."""

    def _init_animator(self) -> "SlideFadeAnimator":
        self.animator = SlideFadeAnimator(self)
        return self.animator

    def rest_pos(self) -> QPoint:
        """Posição real da janela, sem o deslocamento da animação de surgir/sumir."""
        return self.animator.rest_pos()


class AnimatedVisibilityMixin:
    """
    Para o controller de um widget cujo `self.skin` usa AnimatedSkinMixin: mostrar/esconder animados e as consultas
    de estado. Durante o fade-out a janela ainda está na tela, então "visível" não é o mesmo que `is_shown()`.
    """

    # Tempos da animação de surgir/sumir (ms). O timeout é mais lento: ninguém pediu, então o widget se retira sem
    # chamar atenção. Pelo atalho/Hub a resposta é seca.
    APPEAR_MS = 200
    HIDE_MS = 160
    SOFT_HIDE_MS = 320

    def _is_shown(self) -> bool:
        """Visível e não em retirada (durante o fade-out o widget ainda está na tela)."""
        return bool(self.skin and self.skin.isVisible() and not self.skin.animator.is_hiding())

    def is_shown(self) -> bool:
        return self._is_shown()

    def is_hiding(self) -> bool:
        return bool(self.skin and self.skin.animator.is_hiding())

    def settle(self):
        """Conclui qualquer animação em curso antes de mover/trocar o widget."""
        if self.skin:
            self.skin.animator.settle()

    def _animate_show(self):
        if self.skin:
            self.skin.animator.show(self.APPEAR_MS)

    def _animate_hide(self, soft: bool = False):
        if self.skin:
            self.skin.animator.hide(self.SOFT_HIDE_MS if soft else self.HIDE_MS)


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
        glide = getattr(w, "_position_glide", None)   # deslize de troca de posição em curso (ver position_glide.py)
        if glide is not None:
            glide.stop(settle=True)   # a posição de repouso tem de ser o destino, não um ponto do caminho
        if self._rest is None:
            self._rest = w.pos()
        self._run(0.0, duration_ms)

    def move_rest(self, pos: QPoint):
        """
        Muda a posição de repouso. Com a janela surgindo/sumindo, o deslocamento da animação continua por cima do
        lugar novo (sem salto e sem a animação devolver a janela ao lugar antigo); parada, a janela só vai para lá.
        """
        if self._rest is None:
            self._widget.move(pos)
            return
        offset = self._widget.pos() - self._rest
        self._rest = QPoint(pos)
        self._widget.move(self._rest + offset)

    def set_rest_geometry(self, x: int, y: int, w: int, h: int):
        """
        Tamanho e posição de repouso numa operação só (setGeometry é um SetWindowPos no Windows): ao mudar a margem
        transparente em volta do cartão, a janela nunca aparece um quadro com o tamanho novo no lugar antigo. Com a
        janela surgindo/sumindo, o deslocamento da animação continua por cima do lugar novo.
        """
        widget = self._widget
        offset = QPoint(0, 0) if self._rest is None else widget.pos() - self._rest
        if self._rest is not None:
            self._rest = QPoint(x, y)
        widget.setMinimumSize(0, 0)                 # sem isso o setFixedSize abaixo redimensionaria em outro passo
        widget.setMaximumSize(16777215, 16777215)
        widget.setGeometry(x + offset.x(), y + offset.y(), w, h)
        widget.setFixedSize(w, h)

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
