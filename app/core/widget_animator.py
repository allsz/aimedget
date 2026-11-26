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
import time

from PySide6.QtCore import QEasingCurve, QObject, QPoint, Qt, QTimer, QVariantAnimation
from PySide6.QtWidgets import QWidget

from app.core.frame_clock import FrameTimer
from app.core.refresh_rate import refresh_interval_ms

SLIDE_PX = 8

# Troca de área de trabalho virtual (variação B do protótipo mockups/virtual-desktop-switch.html, escolhida pelo
# usuário): o widget sai junto com os apps e volta do lado oposto, como se viesse com a área nova.
SWEEP_PX = 24
SWEEP_OUT_MS = 144          # 45% do deslize do Windows (~320 ms): sai junto com os apps
SWEEP_FADE_IN_MS = 160
SWEEP_SPRING = (420.0, 34.0)  # mola SLIDE (CLAUDE.md)
SWEEP_SETTLE_PX = 0.5

_SPI_GETCLIENTAREAANIMATION = 0x1042


def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


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
        # Surgir adiado: num grupo de ancoragem, quem volta espera os vizinhos abrirem o espaço (ver anchor_manager)
        self._delay_ms = 0
        self._delay_timer = QTimer(self)
        self._delay_timer.setSingleShot(True)
        self._delay_timer.timeout.connect(self._start_delayed)
        self._delayed_duration = 0
        # Troca de área de trabalho virtual: sai/volta na horizontal (ver sweep)
        self._sweep: dict | None = None
        self._sweep_clock = FrameTimer(self)
        self._sweep_clock.setTimerType(Qt.TimerType.PreciseTimer)
        self._sweep_clock.timeout.connect(self._step_sweep)

    # --- Estado ---

    def is_animating(self) -> bool:
        return (self._anim.state() == QVariantAnimation.State.Running or self._delay_timer.isActive()
                or self._sweep is not None)

    def is_sweeping(self) -> bool:
        return self._sweep is not None

    def is_hiding(self) -> bool:
        return self.is_animating() and self._target == 0.0

    def rest_pos(self) -> QPoint:
        """Posição real do widget, sem o deslocamento da animação."""
        if self._rest is not None:
            return QPoint(self._rest)
        return self._widget.pos()

    # --- API ---

    def show(self, duration_ms: int):
        self._end_sweep()
        w = self._widget
        if not w.isVisible():
            self._rest = w.pos()
            self._t = 0.0
            self._apply(0.0)
            w.show()        # o showEvent pode pedir um surgir adiado (delay_appear)
        elif not self.is_animating():
            return  # já visível e parado
        delay, self._delay_ms = self._delay_ms, 0
        if delay > 0 and self._t == 0.0 and animations_enabled() and duration_ms > 0:
            self._target = 1.0
            self._widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._delayed_duration = duration_ms
            self._delay_timer.start(delay)
            return
        self._run(1.0, duration_ms)

    def delay_appear(self, ms: int):
        """Chamado durante o show() (no showEvent): o fade de entrada só começa daqui a `ms`."""
        self._delay_ms = max(0, int(ms))

    def _start_delayed(self):
        if self._target == 1.0 and self._widget.isVisible():
            self._run(1.0, self._delayed_duration)

    def hide(self, duration_ms: int):
        self._end_sweep()
        w = self._widget
        if not w.isVisible():
            return
        self._delay_timer.stop()
        if not self.is_hiding():
            from app.core.anchor_manager import anchor_manager   # aqui: evita import circular
            anchor_manager().member_leaving(w)   # num grupo, os outros fecham as fileiras enquanto ele some
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

    def sweep(self, direction: int):
        """
        Troca de área de trabalho virtual: sai para o lado dos apps (-direction) enquanto eles deslizam e volta do
        lado oposto com a mola SLIDE. Só com o widget parado na tela e com as animações do Windows ligadas (sem elas,
        o widget fica onde está, como hoje). Outra troca no meio recomeça a partir de onde o widget está.
        """
        w = self._widget
        if not direction or not w.isVisible() or not animations_enabled():
            return
        if self._anim.state() == QVariantAnimation.State.Running or self._delay_timer.isActive():
            return   # surgindo/sumindo: essa animação manda
        glide = getattr(w, "_position_glide", None)
        if glide is not None and glide.is_running():
            return   # deslizando para outro lugar: a posição de repouso ainda não é a final
        if self._rest is None:
            self._rest = w.pos()
        prev = self._sweep
        offset = (w.pos() - self._rest).x() if prev else 0.0
        opacity = w.windowOpacity() if prev else 1.0
        self._sweep = {"dir": 1 if direction > 0 else -1, "t0": time.perf_counter(), "last": time.perf_counter(),
                       "from_x": float(offset), "from_opacity": float(opacity), "spring": None, "in_t0": 0.0}
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if not self._sweep_clock.isActive():
            self._sweep_clock.start(refresh_interval_ms(w))
        self._step_sweep()

    def _step_sweep(self):
        s = self._sweep
        w = self._widget
        if s is None or self._rest is None or not w.isVisible():
            self._end_sweep()
            return
        now = time.perf_counter()
        elapsed_ms = (now - s["t0"]) * 1000.0
        dt = min(0.064, now - s["last"])
        s["last"] = now
        if elapsed_ms < SWEEP_OUT_MS:
            q = _ease_out_cubic(elapsed_ms / SWEEP_OUT_MS)
            x = s["from_x"] + (-s["dir"] * SWEEP_PX - s["from_x"]) * q
            opacity = s["from_opacity"] * (1.0 - q)
        else:
            spring = s["spring"]
            if spring is None:
                spring = s["spring"] = [s["dir"] * SWEEP_PX, 0.0]   # posição, velocidade (alvo 0)
                s["in_t0"] = elapsed_ms
            k, c = SWEEP_SPRING
            sub = dt / 4.0
            for _ in range(4):   # massa 1, Euler semi-implícito, 4 subpassos (como city_list.Spring)
                spring[1] += (-k * spring[0] - c * spring[1]) * sub
                spring[0] += spring[1] * sub
            x = spring[0]
            fade = min(1.0, (elapsed_ms - s["in_t0"]) / SWEEP_FADE_IN_MS)
            opacity = _ease_out_cubic(fade)
            if fade >= 1.0 and abs(spring[0]) < SWEEP_SETTLE_PX and abs(spring[1]) < SWEEP_SETTLE_PX * 20:
                self._end_sweep()
                return
        w.setWindowOpacity(max(0.0, min(1.0, opacity)))
        w.move(self._rest.x() + round(x), self._rest.y())

    def _end_sweep(self):
        """Termina a troca no lugar de repouso, totalmente visível."""
        if self._sweep is None:
            return
        self._sweep = None
        self._sweep_clock.stop()
        w = self._widget
        if self._rest is not None:
            w.move(self._rest)
        w.setWindowOpacity(1.0)
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._rest = None

    def settle(self):
        """Conclui a animação em curso no estado final, imediatamente."""
        if not self.is_animating():
            return
        if self._sweep is not None:
            self._end_sweep()
            return
        self._delay_timer.stop()
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


SKIN_SWAP_MS = 150


def swap_skin_windows(old_skin: QWidget | None, new_skin: QWidget, was_visible: bool, duration_ms: int = SKIN_SWAP_MS):
    """
    Troca uma janela de skin antiga por uma nova sem piscar e sem ativar o Hub no fundo.

    Mostrar `new_skin` ANTES de fechar `old_skin` impede o Windows de pular o foco para a
    próxima janela do processo (o Hub) quando a skin antiga fecha. Com animações ligadas,
    faz um crossfade rápido (~150 ms) entre a antiga e a nova.
    """
    if not was_visible:
        if old_skin is not None:
            old_skin.close()
            old_skin.deleteLater()
        return

    # Evita roubar foco / mexer na pilha Z de outras janelas (como o Hub atrás de outro app)
    new_skin.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    if old_skin is None or not animations_enabled():
        new_skin.setWindowOpacity(1.0)
        new_skin.show()
        new_skin.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        if old_skin is not None:
            old_skin.close()
            old_skin.deleteLater()
        return

    old_skin.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    new_skin.setWindowOpacity(0.0)
    new_skin.show()
    new_skin.raise_()
    new_skin.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)

    anim = QVariantAnimation(new_skin)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(max(1, int(duration_ms)))
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _on_step(val):
        f = max(0.0, min(1.0, float(val)))
        new_skin.setWindowOpacity(f)
        try:
            old_skin.setWindowOpacity(1.0 - f)
        except RuntimeError:
            pass

    def _on_done():
        new_skin.setWindowOpacity(1.0)
        try:
            old_skin.close()
            old_skin.deleteLater()
        except RuntimeError:
            pass

    anim.valueChanged.connect(_on_step)
    anim.finished.connect(_on_done)
    prev_anim = getattr(new_skin, "_skin_swap_anim", None)
    if prev_anim is not None:
        prev_anim.stop()
    new_skin._skin_swap_anim = anim
    anim.start()
