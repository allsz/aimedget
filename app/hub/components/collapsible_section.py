"""
CollapsibleSection - recolhe/expande um bloco da página do Hub com animação (altura + fade).

Serve para esconder o que não vale para a opção escolhida (ex.: a galeria de temas quando a skin do Timer não aceita
temas), em vez de deixar um controle que não faz nada.

Como funciona (e por que assim): o conteúdo NÃO fica num layout da seção. Ele é posicionado à mão, sempre com a sua
altura natural, no topo da seção; a seção só muda a própria altura (altura natural x progresso) e o que passa dela é
cortado. Assim o conteúdo nunca é espremido nem re-quebrado durante a animação, e a seção não tem "altura mínima" que
brigue com a altura animada (era isso que fazia a página tremer). O espaço entre o bloco e o de cima (`gap`) fica DENTRO
da seção, então ao recolher nada abaixo dá o salto de um espaçamento que some de uma vez.

Durante a animação a seção pinta uma FOTO do conteúdo (tirada no início) em vez dos widgets vivos: os cards da galeria
não são repintados a cada quadro nem passam por um efeito de opacidade, que era o que rasgava a imagem (tearing).

Respeita "Efeitos de animação" do Windows (desligado = troca instantânea). Fechada, a seção fica oculta de verdade:
nada nela recebe foco nem clique.
"""

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QSize, QVariantAnimation
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.core.widget_animator import animations_enabled

DURATION_MS = 280
QWIDGETSIZE_MAX = 16777215


class CollapsibleSection(QWidget):
    def __init__(self, content: QWidget, gap: int = 0, opened: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._content = content
        self._gap = gap
        self._open = opened
        self._progress = 1.0 if opened else 0.0   # 0 = recolhida, 1 = aberta
        self._snapshot: QPixmap | None = None
        self._steady: list[QWidget] = []   # vizinhos que NÃO podem mudar de tamanho enquanto a seção anima
        content.setParent(self)
        content.show()
        content.installEventFilter(self)   # o conteúdo cresceu/encolheu (ex.: temas importados): a seção acompanha
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.valueChanged.connect(self._on_progress)
        self._anim.finished.connect(self._on_finished)
        self._apply_height()
        self.setVisible(opened)

    # --- Estado ---

    def keep_steady(self, *widgets: QWidget):
        """Widgets vizinhos (ex.: o card de skins) que ficam com a altura travada durante a animação. Sem isso, quando
        a página não cabe na janela, o layout espreme o card de skins a cada quadro e ele "pulsa"."""
        self._steady = list(widgets)

    def is_open(self) -> bool:
        return self._open

    def is_animating(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    # --- Controle ---

    def set_open(self, opened: bool, animate: bool = True):
        if opened == self._open and not self.is_animating():
            return
        self._open = opened
        parent = self.parentWidget()
        can_animate = animate and animations_enabled() and parent is not None and parent.isVisible()
        if not can_animate:
            self._anim.stop()
            self._progress = 1.0 if opened else 0.0
            self._settle()
            return

        for w in self._steady:
            w.setMinimumHeight(w.height())   # só a galeria anima; o card de cima mantém o tamanho
        self.setVisible(True)
        self._take_snapshot()
        # Guarda o ponto de partida ANTES de mexer na animação: setStartValue/setEndValue emitem valueChanged, que
        # atualizava _progress para o valor final e deixava a abertura com 1 ms (a galeria "aparecia" sem animar).
        start = self._progress
        end = 1.0 if opened else 0.0
        self._anim.stop()
        self._anim.blockSignals(True)
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.blockSignals(False)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic if opened else QEasingCurve.Type.InOutCubic)
        self._anim.setDuration(max(1, int(DURATION_MS * abs(end - start))))
        self._anim.start()

    # --- Medidas: a altura da seção é (altura natural do bloco + gap) x progresso ---

    def _natural_height(self, width: int) -> int:
        inner = max(1, width)
        if self._content.hasHeightForWidth():
            h = self._content.heightForWidth(inner)
        else:
            h = self._content.sizeHint().height()
        return max(h, self._content.minimumSizeHint().height()) + self._gap

    def _current_height(self, width: int) -> int:
        return int(round(self._natural_height(width) * self._progress))

    def sizeHint(self) -> QSize:
        return QSize(max(self._content.sizeHint().width(), 1), self._current_height(self._width_for_measure()))

    def _width_for_measure(self) -> int:
        return self.width() if self.width() > 1 else max(self._content.sizeHint().width(), 1)

    def _apply_height(self):
        """Altura FIXA a cada passo (mínima = máxima): o layout da página recebe um valor exato e não redistribui
        sobra de espaço de um jeito diferente a cada quadro."""
        h = self._current_height(self._width_for_measure())
        if h != self.height() or self.minimumHeight() != h:
            self.setFixedHeight(h)

    def eventFilter(self, obj, event):
        if obj is self._content and event.type() == QEvent.Type.LayoutRequest:
            self._apply_height()
            self._place_content()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_height()   # a largura mudou: a galeria quebra em outro número de linhas
        self._place_content()

    def _place_content(self):
        """O conteúdo fica no topo (abaixo do gap) com a altura natural; o que passa da seção é cortado."""
        width = self.width()
        self._content.setGeometry(0, self._gap, width, max(0, self._natural_height(width) - self._gap))

    # --- Animação ---

    def _take_snapshot(self):
        """Foto do conteúdo na altura natural; os widgets reais ficam ocultos até a animação acabar."""
        if self._snapshot is None:
            self._place_content()
            if self._content.layout() is not None:
                self._content.layout().activate()
            self._content.show()
            self._snapshot = self._content.grab()
        self._content.hide()

    def _on_progress(self, value):
        self._progress = float(value)
        self._apply_height()
        self.update()

    def paintEvent(self, event):
        if self._snapshot is None:
            return
        p = QPainter(self)
        p.setOpacity(max(0.0, min(1.0, self._progress)))
        p.drawPixmap(QPoint(0, self._gap), self._snapshot)   # o que passa da altura da seção é cortado
        p.end()

    def _on_finished(self):
        self._settle()

    def _settle(self):
        """Estado final: aberta = altura natural cheia (acompanha o conteúdo se ele crescer); fechada = oculta."""
        self._snapshot = None
        for w in self._steady:
            w.setMinimumHeight(0)
        self._apply_height()
        self.setVisible(self._open)
        if self._open:
            self._place_content()
            self._content.show()
        self.update()


def skin_supports_themes(specs, skin_key: str | None) -> bool:
    """A skin aceita temas visuais? Skins com arte própria declaram `supports_themes=False`."""
    spec = next((s for s in specs if s.id == skin_key), None)
    return True if spec is None else spec.supports_themes


def skin_and_theme_block(skin_card: QWidget, theme_card: QWidget, gap: int, opened: bool):
    """
    Bloco "skins + galeria de temas" das páginas de widgets (Timer, Música): a galeria fica numa seção que recolhe
    quando a skin escolhida não aceita temas. O espaço entre os dois cards fica dentro da seção, e a sobra de altura
    vai para um elástico no fim (sem ele o layout a reparte em vãos entre os cards e eles dão trancos).
    Devolve (bloco, seção).
    """
    block = QWidget()
    lay = QVBoxLayout(block)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(skin_card)
    section = CollapsibleSection(theme_card, gap=gap, opened=opened)
    section.keep_steady(skin_card)
    lay.addWidget(section)
    lay.addStretch(1)
    return block, section
