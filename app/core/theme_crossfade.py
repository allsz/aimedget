"""
Troca de tema com transição curta e discreta, a mesma em todo o app.

Antes só os cartões do Clima e do Desempenho suavizavam a troca de tema (FloatingCard.begin_skin_crossfade); música,
timer, o mixer e o próprio Hub (claro/escuro) mudavam "no corte". Aqui está o movimento do Clima como peça comum:
160 ms, saída em curva cúbica, a aparência antiga se dissolve com um leve encolher (2,5%) por cima da nova.

Uso (ao redor de QUALQUER mudança de aparência que o usuário pediu e que o widget aplica na hora):

    with theme_crossfade(skin):
        skin.reload_skin_theme()

1. tira uma FOTO do widget como está; 2. o bloco aplica o tema novo (o custo some atrás da foto); 3. uma camada
transparente para o mouse mostra a foto por cima, sumindo em DURATION_MS. O primeiro quadro é idêntico à foto, então
não há salto. Se a janela mudar de tamanho/posição por causa do tema (margem da arte, inclinação), a foto continua no
mesmo ponto da tela. Sem "Efeitos de animação" do Windows, ou com o widget oculto, o bloco só aplica.

Troca de MODO (claro/escuro/true dark, manual ou seguindo o Windows): `mode_crossfade(...)`, mais longa e suave
(MODE_DURATION_MS, curva in-out, sem encolher), escolhida no protótipo mockups/theme-mode-transition.html (variante C).
Na troca de modo a janela inteira muda; uma dissolvência curta de saída rápida parecia corte. `on_progress(e)` recebe a
mesma curva a cada quadro (o Hub pinta a barra de título nativa junto com a dissolvência).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from app.core.frame_clock import FrameTimer
from app.core.refresh_rate import refresh_interval_ms
from app.core.widget_animator import animations_enabled

DURATION_MS = 160
SHRINK = 0.025   # quanto a aparência antiga encolhe ao sair (fração)
MODE_DURATION_MS = 300   # troca claro/escuro: protótipo mockups/theme-mode-transition.html, variante C


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    """Começa e termina devagar: a curva da troca de modo (claro/escuro)."""
    t = max(0.0, min(1.0, t))
    return 4.0 * t * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


class ThemeCrossfade(QWidget):
    """Camada filha, transparente para o mouse, que dissolve a foto antiga por cima do widget já com o tema novo."""

    def __init__(self, host: QWidget, snapshot: QPixmap, origin: QPoint, duration_ms: int, shrink: float,
                 ease: Callable[[float], float] = ease_out_cubic,
                 on_progress: Optional[Callable[[float], None]] = None):
        """`origin`: onde a área útil do widget estava NA TELA quando a foto foi tirada."""
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._snapshot = snapshot
        self._origin = QPoint(origin)
        self._shift = QPoint(0, 0)              # quanto a foto fica deslocada no widget (fixado em run())
        self._duration = max(0.04, duration_ms / 1000.0)
        self._shrink = float(shrink)
        self._ease = ease
        self._on_progress = on_progress   # recebe a curva (0..1) a cada quadro e 1.0 ao terminar
        self._t0 = 0.0
        self._timer = FrameTimer(self)
        self._timer.timeout.connect(self._tick)
        host.installEventFilter(self)
        self.hide()

    # --- Ciclo de vida ---

    def _host(self) -> Optional[QWidget]:
        """O widget dono (o pai Qt). Sem referência própria: se a janela morrer no meio da dissolvência (ex.: a skin
        é trocada e apagada 100 ms depois do tema), a camada morre junto, sem deixar ponteiro para trás."""
        try:
            return self.parentWidget()
        except RuntimeError:
            return None

    def run(self):
        host = self._host()
        if host is None:
            return
        self.setGeometry(host.rect())
        # Se aplicar o tema mexeu na janela (margem da arte, inclinação), a foto fica no mesmo ponto da TELA. Calculado
        # uma vez: arrastar o widget durante os 160 ms leva a foto junto, em vez de deixá-la para trás.
        self._shift = self._origin - host.mapToGlobal(QPoint(0, 0))
        self._t0 = time.perf_counter()
        self.raise_()
        self.show()
        self._timer.start(refresh_interval_ms(host))

    def stop(self):
        """Termina na hora e libera a camada (nunca setParent(None): oculta e apaga)."""
        self._timer.stop()
        self._notify(1.0)   # quem acompanha (barra de título) termina no estado final, mesmo se interrompido
        host = self._host()
        if host is not None:
            host.removeEventFilter(self)
            if getattr(host, "_theme_crossfade", None) is self:
                host._theme_crossfade = None
        self.hide()
        self.deleteLater()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def progress(self) -> float:
        return min(1.0, (time.perf_counter() - self._t0) / self._duration)

    def eventFilter(self, obj, event):
        try:   # durante a destruição da janela este filtro ainda pode ser chamado: nunca deixa a exceção subir
            host = self._host()
            if host is not None and obj is host and event.type() == QEvent.Type.Resize:
                self.setGeometry(host.rect())   # a camada acompanha; a foto é reposicionada no desenho
        except (RuntimeError, AttributeError):
            pass
        return False

    def _notify(self, e: float):
        cb, self._on_progress = self._on_progress, (self._on_progress if e < 1.0 else None)
        if cb is not None:
            try:
                cb(e)
            except RuntimeError:   # janela destruída no meio
                pass

    def _tick(self):
        if self.progress() >= 1.0:
            self.stop()
        else:
            self._notify(self._ease(self.progress()))
            self.update()

    # --- Desenho ---

    def paintEvent(self, _event):
        p = QPainter(self)
        e = self._ease(self.progress())
        shift = self._shift
        w = self._snapshot.width() / max(1.0, self._snapshot.devicePixelRatio())
        h = self._snapshot.height() / max(1.0, self._snapshot.devicePixelRatio())
        rect = QRectF(float(shift.x()), float(shift.y()), w, h)
        s = 1.0 - self._shrink * e
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(1.0 - e)
        c = rect.center()
        p.translate(c)
        p.scale(s, s)
        p.translate(-c)
        p.drawPixmap(QPointF(rect.topLeft()), self._snapshot)
        p.end()


def begin_theme_crossfade(widget: QWidget, duration_ms: int = DURATION_MS, shrink: float = SHRINK,
                          ease: Callable[[float], float] = ease_out_cubic,
                          on_progress: Optional[Callable[[float], None]] = None) -> Optional[ThemeCrossfade]:
    """Tira a foto do widget (se vale a pena animar) e devolve a camada; `run()` dela começa a dissolver."""
    if not isinstance(widget, QWidget) or not animations_enabled():
        return None
    if not widget.isVisible() or widget.width() < 2 or widget.height() < 2:
        return None
    previous = getattr(widget, "_theme_crossfade", None)
    if previous is not None:
        previous.hide()          # a foto nova não pode incluir a camada anterior
        previous._on_progress = None   # a nova transição continua a barra de título de onde ela está, sem salto
        previous.stop()
    snapshot = widget.grab()
    layer = ThemeCrossfade(widget, snapshot, widget.mapToGlobal(QPoint(0, 0)), duration_ms, shrink, ease, on_progress)
    widget._theme_crossfade = layer
    return layer


@contextmanager
def theme_crossfade(widget: QWidget, duration_ms: int = DURATION_MS, shrink: float = SHRINK) -> Iterator[None]:
    """Foto antes, aplica dentro do bloco, dissolve depois. Se o bloco falhar, a camada é descartada."""
    layer = begin_theme_crossfade(widget, duration_ms, shrink)
    try:
        yield
    except BaseException:
        if layer is not None:
            layer.stop()
        raise
    if layer is not None:
        layer.run()


@contextmanager
def mode_crossfade(widget: QWidget, on_progress: Optional[Callable[[float], None]] = None) -> Iterator[None]:
    """Troca de modo claro/escuro: 300 ms, curva in-out, sem encolher. Sem animação, `on_progress(1.0)` na hora."""
    layer = begin_theme_crossfade(widget, MODE_DURATION_MS, 0.0, ease_in_out_cubic, on_progress)
    try:
        yield
    except BaseException:
        if layer is not None:
            layer.stop()
        raise
    if layer is not None:
        layer.run()
    elif on_progress is not None:
        on_progress(1.0)
