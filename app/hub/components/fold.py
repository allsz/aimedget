"""
Fold - embrulha um widget para ele abrir/fechar a altura em vez de aparecer/sumir "no corte".

Não tem relógio próprio: segue o progresso (0..1) de outra animação, a cada quadro dela. Assim um vizinho (ex.: o
botão "Adicionar minha localização") fecha exatamente enquanto a linha nova da lista abre, e a altura do cartão
varia sem dente. O espaço acima do conteúdo (`gap`) fica DENTRO do Fold, para fechar junto com ele.

    fold.set_open(False)                                    # na hora
    fold.set_open(False, (lista.frame, anim.progress))      # acompanhando a animação da lista
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QVBoxLayout, QWidget

QWIDGETSIZE_MAX = (1 << 24) - 1


class Fold(QWidget):
    def __init__(self, child: QWidget, gap: int = 0, align=None, parent=None):
        super().__init__(parent)
        self.child = child
        self._gap = gap
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, gap, 0, 0)
        layout.setSpacing(0)
        if align is None:
            layout.addWidget(child)
        else:
            layout.addWidget(child, alignment=align)
        self._open = True
        self._anim = None   # (sinal, progresso, altura inicial, altura final, ao_terminar)
        self._effect: QGraphicsOpacityEffect | None = None

    def is_open(self) -> bool:
        return self._open

    def is_animating(self) -> bool:
        return self._anim is not None

    def natural_height(self) -> int:
        return self._gap + max(0, self.child.sizeHint().height())

    def set_open(self, open_: bool, follow=None, on_done=None):
        """follow = (sinal emitido a cada quadro, função que devolve o progresso 0..1); None = na hora."""
        open_ = bool(open_)
        if follow is not None and open_ == self._open and (self._anim is not None or self.isHidden() != open_):
            if self._anim is None and on_done is not None:
                on_done()
            return   # já está lá, ou já está indo para lá
        self._stop()
        self._open = open_
        if follow is None:
            self.setVisible(open_)
            if on_done is not None:
                on_done()
            return
        signal, progress = follow
        start = 0 if self.isHidden() else self.height()
        target = self.natural_height() if open_ else 0
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = (signal, progress, start, target, on_done)
        self.setFixedHeight(start)
        self.setVisible(True)
        signal.connect(self._on_frame)
        self._on_frame()

    def _on_frame(self):
        if self._anim is None:
            return
        _signal, progress, start, target, on_done = self._anim
        f = max(0.0, min(1.0, float(progress())))
        h = start + (target - start) * f
        self.setFixedHeight(int(round(h)))
        if self._effect is not None:
            nat = max(1, self.natural_height())
            self._effect.setOpacity(max(0.0, min(1.0, h / nat)))
        if f >= 1.0:
            self._stop()
            self.setVisible(self._open)
            if on_done is not None:
                on_done()

    def _stop(self):
        if self._anim is not None:
            try:
                self._anim[0].disconnect(self._on_frame)
            except (RuntimeError, TypeError):
                pass
            self._anim = None
        if self._effect is not None:
            self.setGraphicsEffect(None)
            self._effect = None
        self.setMinimumHeight(0)
        self.setMaximumHeight(QWIDGETSIZE_MAX)
