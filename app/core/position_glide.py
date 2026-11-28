"""
PositionGlide - desliza uma janela (ou qualquer coisa com posição) de um ponto da tela até outro.

Núcleo reutilizável do movimento de "troca de posição": o mixer, o Caps/Num Lock e os widgets (música, timer) se
reposicionam, e todos podem usar este mesmo motor. Quem usa só diz DE ONDE e PARA ONDE e como aplicar uma posição;
a direção do movimento sai sozinha do vetor entre os dois pontos (do canto inferior direito para o topo do centro,
o card atravessa a tela nessa direção).

- O tempo cresce com a distância (saltos curtos são rápidos, travessias da tela inteira levam um pouco mais) e fica
  entre MIN_MS e MAX_MS: o movimento sempre parece ágil.
- A curva desacelera no fim (OutQuart): arranca rápido e assenta, sem balançar nem passar do alvo (um card encostado
  na borda não pode vazar para fora da tela).
- O progresso vem do relógio, não de contar quadros, então a duração é a mesma a 60, 120 ou 144 Hz; o timer segue a
  taxa do monitor. Só roda enquanto desliza.
- Pode ser interrompido a qualquer momento por outro `start()`: o novo movimento parte do ponto que o chamador
  informar (normalmente onde a coisa está agora), sem saltos.
- `animations_enabled()` falso (Efeitos de animação do Windows desligado): quem chama vai direto, sem deslizar
  (`start` já faz isso quando `respect_system_setting=True`).

`apply(x, y)` recebe a posição (px inteiros) a cada quadro; para uma janela, passe `window.move`.

Dois jeitos de ligar a uma janela:
- `glide_widget_to(window, x, y)`: janelas de posição livre, onde o desenho dentro da janela não depende de onde ela
  está (os widgets de música e timer). Desliza da posição atual até (x, y).
- `reposition_with_glide(window, glide, card_offset, relayout)`: janelas cujo card é desenhado DE UM JEITO POR
  ÂNCORA dentro da janela (mixer, Caps/Num Lock). A troca de desenho é feita com a janela invisível (sem o quadro do
  bitmap velho na posição nova) e dali só a posição da janela anima.
"""

import math
import time
from contextlib import contextmanager
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget

from app.core.refresh_rate import refresh_interval_ms
from app.core.widget_animator import animations_enabled
from app.core.frame_clock import FrameTimer

MIN_MS = 220
MAX_MS = 420
MS_PER_PX = 0.07        # acrescenta ~70 ms a cada 1000 px de distância


def glide_duration_ms(distance_px: float) -> int:
    """Duração do deslize para uma distância: 220 ms nos saltos curtos, até 420 ms na tela inteira."""
    return int(round(max(MIN_MS, min(MAX_MS, MIN_MS + max(0.0, distance_px) * MS_PER_PX))))


def ease_out_quart(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 4


class PositionGlide(QObject):
    finished = Signal()

    def __init__(self, apply: Callable[[int, int], None], parent: QObject | None = None,
                 clock: Callable[[], float] = time.perf_counter):
        super().__init__(parent)
        self._apply = apply
        self._clock = clock
        self._start = QPointF()
        self._end = QPointF()
        self._duration = 1.0
        self._t0 = 0.0
        self._running = False
        self._timer = FrameTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

    # --- API ---

    def is_running(self) -> bool:
        return self._running

    def target(self) -> QPointF:
        """Para onde o movimento em curso vai (ou onde terminou)."""
        return QPointF(self._end)

    def position(self) -> QPointF:
        """Onde o movimento está agora."""
        return self._at(self._progress()) if self._running else QPointF(self._end)

    def start(self, start, end, duration_ms: int | None = None, respect_system_setting: bool = True) -> bool:
        """
        Começa a deslizar de `start` até `end` (QPoint/QPointF/tupla). Devolve True se vai animar; False se foi
        direto ao destino (distância nula ou efeitos de animação do Windows desligados), aplicando-o na hora.
        """
        self._start = self._pt(start)
        self._end = self._pt(end)
        distance = math.hypot(self._end.x() - self._start.x(), self._end.y() - self._start.y())
        if distance < 1.0 or (respect_system_setting and not animations_enabled()):
            self._timer.stop()
            self._running = False
            self._apply_point(self._end)
            return False
        self._duration = max(1, duration_ms if duration_ms is not None else glide_duration_ms(distance)) / 1000.0
        self._t0 = self._clock()
        self._running = True
        self._apply_point(self._start)
        self._timer.setInterval(refresh_interval_ms(self.parent() if isinstance(self.parent(), QWidget) else None))
        self._timer.start()
        return True

    def stop(self, settle: bool = False):
        """Interrompe. `settle=True` põe a coisa no destino (ex.: a janela vai ser escondida no meio do movimento)."""
        was_running = self._running
        self._timer.stop()
        self._running = False
        if was_running and settle:
            self._apply_point(self._end)

    # --- Motor ---

    @staticmethod
    def _pt(p) -> QPointF:
        if isinstance(p, (tuple, list)):
            return QPointF(float(p[0]), float(p[1]))
        return QPointF(float(p.x()), float(p.y()))

    def _progress(self) -> float:
        return min(1.0, max(0.0, (self._clock() - self._t0) / self._duration))

    def _at(self, raw: float) -> QPointF:
        k = ease_out_quart(raw)
        return QPointF(self._start.x() + (self._end.x() - self._start.x()) * k,
                       self._start.y() + (self._end.y() - self._start.y()) * k)

    def _apply_point(self, p: QPointF):
        self._apply(int(round(p.x())), int(round(p.y())))

    def _on_tick(self):
        if not self._running:
            return   # um timeout já enfileirado quando o movimento terminou/foi interrompido
        raw = self._progress()
        self._apply_point(self._at(raw))
        if raw >= 1.0:
            self._timer.stop()
            self._running = False
            self._apply_point(self._end)   # termina exatamente no destino
            self.finished.emit()


# --- Ligações prontas para janelas ---

@contextmanager
def unseen_while_relayout(widget: QWidget):
    """
    Move/redesenha a janela SEM mostrar o quadro intermediário. O desenho do card dentro da janela pode depender da
    âncora (embaixo, no meio ou em cima), e mover uma janela translúcida mostra, por um quadro, o bitmap antigo na
    posição nova (o card "teleportado") antes de o novo chegar. Aqui a janela fica com opacidade 0 durante a troca e só
    reaparece depois de redesenhada, com o desenho novo já no lugar novo. Escondida, não faz nada.
    """
    if not widget.isVisible():
        yield
        return
    widget.setWindowOpacity(0.0)
    widget.repaint()   # entrega a opacidade 0 ao Windows antes de mover
    try:
        yield
    finally:
        widget.repaint()   # desenho novo, já na posição nova (ainda invisível)
        widget.setWindowOpacity(1.0)
        widget.repaint()   # revela: bitmap novo e posição nova no mesmo quadro


def reposition_with_glide(widget: QWidget, glide: PositionGlide, card_offset: Callable[[], QPointF],
                          relayout: Callable[[], None], duration_ms: int | None = None) -> bool:
    """
    Troca a posição/âncora de uma janela cujo card muda de lugar DENTRO dela. `relayout()` muda o estado e leva a
    janela ao lugar FINAL; `card_offset()` devolve onde o card fica dentro da janela (é chamado antes e depois, então
    cada vez vê o desenho daquele momento). Com a janela na tela, o card parte de onde estava e desliza até o lugar
    novo; escondida, ou sem efeitos de animação, vai direto. Devolve True se está deslizando.
    """
    animate = widget.isVisible() and animations_enabled()
    start = final = QPointF()
    if animate:
        # Onde o card está na TELA agora (também no meio de outro deslize): dali ele parte para o lugar novo
        glide.stop()
        old_card_tl = QPointF(widget.pos()) + card_offset()
    with unseen_while_relayout(widget):
        relayout()   # a janela vai ao lugar FINAL
        if animate:
            # O desenho do card dentro da janela mudou: põe a janela de modo que o card apareça exatamente onde
            # estava, ainda invisível. Daqui só a posição da janela muda (o bitmap não).
            final = widget.pos()
            start = (old_card_tl - card_offset()).toPoint()
            widget.move(start)
    if animate and start != final:
        glide.start(start, final, duration_ms)   # None: a duração pela distância
    return glide.is_running()


class _StopGlideOnPress(QObject):
    """Quem pega o widget com o mouse (arrastar) assume o controle: o deslize em curso é interrompido."""

    def __init__(self, glide: PositionGlide, parent: QObject):
        super().__init__(parent)
        self._glide = glide

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and self._glide.is_running():
            self._glide.stop()
        return False


def glide_of(widget: QWidget) -> PositionGlide:
    """O PositionGlide da janela (criado na primeira vez). O animador de surgir/sumir o consulta para não esconder
    a janela no meio do deslize (ver SlideFadeAnimator.hide)."""
    glide = getattr(widget, "_position_glide", None)
    if glide is None:
        glide = PositionGlide(widget.move, parent=widget)
        widget._position_glide = glide
        widget.installEventFilter(_StopGlideOnPress(glide, widget))
    return glide


def glide_widget_to(widget: QWidget, x: int, y: int) -> bool:
    """
    Desliza uma janela de posição livre (onde o desenho dentro dela não depende do lugar) da posição atual até
    (x, y) da janela. Escondida ou sem efeitos de animação, vai direto. Devolve True se está deslizando.
    """
    glide = glide_of(widget)
    glide.stop()
    animator = getattr(widget, "animator", None)
    if animator is not None:
        animator.settle()   # termina a animação de surgir/sumir em curso: a posição de repouso passa a ser a real
    if not widget.isVisible():
        widget.move(x, y)
        return False
    return glide.start(widget.pos(), (x, y))
