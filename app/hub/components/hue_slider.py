"""
HueSlider - seletor de matiz para a cor de destaque do app.

A trilha mostra as cores que o tema realmente vai usar (derivadas por `derive_accent` para o modo claro/escuro
atual), então o que o usuário vê na trilha é o que ele recebe. O botão deslizante leva a cor escolhida.

- `hueChanged(int)`: a cada movimento (aplicar ao vivo)
- `hueCommitted(int)`: ao soltar o botão do mouse ou ao terminar um ajuste pelo teclado
- Teclado: setas ±1°, Shift+setas ±10°, Home/End; foco visível por anel.

Onda: ao ARRASTAR (mover além de DRAG_THRESHOLD px com o botão apertado) a paleta vira uma COLINA preenchida: a base
continua reta e a paleta cresce por baixo de uma curva suave, com o botão SEMPRE no ponto mais alto dela (o pico fica
exatamente sob o botão, sem atraso), deixando as cores bem visíveis. Perto de uma ponta o lado da colina virado para
ela encolhe para caber (a queda fica mais íngreme, mas segue uma curva em S inteira que pousa na barra). Só nos
últimos px sobra uma parede, que sobe do FIM da barra e arredonda para dentro da onda, até o botão chegar à ponta
com a crista cheia. Tudo sem salto. Ao soltar, a colina volta ao tamanho normal de forma suave. Um clique simples (sem arrastar) e o
teclado não ligam a onda. Sem "Efeitos de animação" do Windows, não há onda. A faixa de altura da colina e do botão
fica reservada acima da trilha (HEADROOM).

A colina tem "água": a subida e a retração são uma mola criticamente amortecida (começa devagar, acelera e assenta sem
quina de velocidade nem repique), e com o botão em movimento o lado de trás da colina alarga (cauda arrastada) enquanto
o da frente estreita, voltando à forma simétrica quando o botão para. O pico continua exatamente sob o botão.

O movimento usa o tempo real entre quadros e o timer segue a taxa de atualização do monitor (60, 120, 144 Hz...).
Só roda durante o arrasto e a retração; um quadro custa ~1 ms.
"""

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.core.refresh_rate import refresh_interval_ms
from app.core.widget_animator import animations_enabled
from app.hub.theme import HubTheme, THEME_DARK, derive_accent
from app.core.frame_clock import FrameTimer

TRACK_H = 10.0
KNOB_R = 10.0
KNOB_GROW = 0.12         # o botão cresce esta fração quando a colina está inteira
# Folga lateral: o anel de foco do botão (com ele crescido) e a sombra cabem inteiros, mesmo na extremidade da barra.
# (KNOB_R + 1,5 do anel) x (1 + KNOB_GROW) + meia espessura do traço + 1 px de ar, arredondado para cima.
MARGIN = float(math.ceil((KNOB_R + 1.5) * (1.0 + KNOB_GROW) + 0.75 + 1.0))
STEPS = 36   # paradas do gradiente (a cada 10°)

LIFT_PX = 18             # quanto a paleta cresce para cima no pico da colina
HEADROOM = 26            # faixa reservada acima da trilha: cabe a colina e o botão sobre o pico
KNOB_RISE = 8.0          # quanto o botão sobe em relação à trilha quando a colina está inteira (fica sobre o pico)
WAVE_HALF_W = 85.0       # meia-largura da colina, em px: larga e suave, quase a trilha toda
WAVE_MIN_W = 34.0        # o quanto a queda pode encolher perto de uma ponta (inclinação máxima ~45°)
DRAG_THRESHOLD = 4.0    # quanto o mouse precisa andar apertado para ser "arrastar" e não um clique
RISE_RATE = 24.0         # frequência da mola de subida (rad/s): a colina nasce devagar, acelera e assenta sem salto
FALL_RATE = 13.0         # frequência da mola de retração (rad/s): mais lenta, ~0,4 s para voltar ao normal
SKEW_SPEED = 650.0       # velocidade do botão (px/s) em que a inclinação da colina chega ao máximo
SKEW_SMOOTH = 0.07       # constante de tempo (s) do filtro da velocidade: tira o ruído dos passos de 1 grau
TRAIL_GAIN = 0.55        # quanto o lado de TRÁS da colina alarga na velocidade máxima (a cauda arrasta)
LEAD_LOSS = 0.30         # quanto o lado da FRENTE estreita (a colina empina na direção do movimento)
END_ROUND_GAIN = 0.15    # quanto o canto da ponta alarga por px de onda ali (a parede sobe -> canto mais suave)
END_ROUND_MAX = 3.0      # limite desse alargamento, em px (pequeno: a crista tem de ficar sob o botão, que cobre ~10 px da ponta)

class HueSlider(QWidget):
    hueChanged = Signal(int)
    hueCommitted = Signal(int)

    def __init__(self, hue: int = 33, theme: HubTheme = THEME_DARK, parent: QWidget | None = None):
        super().__init__(parent)
        self._hue = int(hue) % 360
        self._theme = theme
        self._dragging = False
        self._press_x = 0.0
        self._wave_drag = False      # o mouse já andou além do limite: é um arrasto de verdade, não um clique
        self._lift = 0.0             # 0 = trilha reta, 1 = crista inteira
        self._lift_v = 0.0           # velocidade da mola da altura (1/s)
        self._skew = 0.0             # -1..1: sentido e intensidade do arrasto da cauda (suavizado)
        self._prev_kx: float | None = None
        self._last_tick = 0.0
        self._grad_cache: tuple[bool, list[QColor]] | None = None   # cores da trilha para o modo atual
        self._timer = FrameTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)
        self.setFixedHeight(int(KNOB_R * 2 + 8) + HEADROOM)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- API ---

    def hue(self) -> int:
        return self._hue

    def set_hue(self, hue: int):
        """Move o botão sem emitir sinais (uso programático, ex.: restaurar o padrão)."""
        hue = max(0, min(359, int(hue)))
        if hue != self._hue:
            self._hue = hue
            self.update()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._grad_cache = None
        self.update()

    def is_wave_dragging(self) -> bool:
        """O usuário está ARRASTANDO (não só clicando)? Quem aplica a cor usa isso para não animar durante o arrasto."""
        return self._dragging and self._wave_drag

    def lift(self) -> float:
        """Altura atual da onda (0 a 1)."""
        return self._lift

    # --- Geometria ---

    def _center_y(self) -> float:
        """Altura do centro da trilha em repouso: a faixa da crista fica acima dela."""
        return HEADROOM + (self.height() - HEADROOM) / 2.0

    def _track_rect(self) -> QRectF:
        return QRectF(MARGIN, self._center_y() - TRACK_H / 2.0, self.width() - 2 * MARGIN, TRACK_H)

    def _hue_at(self, x: float) -> int:
        track = self._track_rect()
        ratio = (x - track.left()) / max(1.0, track.width())
        return max(0, min(359, int(round(ratio * 359))))

    def _knob_x(self) -> float:
        track = self._track_rect()
        return track.left() + track.width() * (self._hue / 359.0)

    # --- Entrada ---

    def _move_to(self, x: float):
        hue = self._hue_at(x)
        if hue != self._hue:
            self._hue = hue
            self.update()
            self.hueChanged.emit(hue)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._wave_drag = False
            self._press_x = event.position().x()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._move_to(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            if not self._wave_drag and abs(event.position().x() - self._press_x) >= DRAG_THRESHOLD:
                self._wave_drag = True
            if self._wave_drag:
                self._start_timer()   # religa se o timer parou numa pausa do mouse (no-op com ele ativo)
            self._move_to(event.position().x())   # o pico é sempre o botão: andar com ele já leva a colina junto

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._wave_drag = False
            self._start_timer()   # a onda se retrai
            self.hueCommitted.emit(self._hue)

    def keyPressEvent(self, event):
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            new = self._hue - step
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            new = self._hue + step
        elif key == Qt.Key.Key_Home:
            new = 0
        elif key == Qt.Key.Key_End:
            new = 359
        else:
            super().keyPressEvent(event)
            return
        new = max(0, min(359, new))
        if new != self._hue:
            self._hue = new
            self.update()
            self.hueChanged.emit(new)
            self.hueCommitted.emit(new)

    # --- Onda ---

    def _wave_target(self) -> float:
        return 1.0 if (self._wave_drag and animations_enabled()) else 0.0

    def _start_timer(self):
        if not self._timer.isActive():
            self._last_tick = time.perf_counter()
            self._timer.setInterval(refresh_interval_ms(self))   # relê: a janela pode ter trocado de monitor
            self._timer.start()

    def _on_tick(self):
        now = time.perf_counter()
        self._step(max(0.001, min(0.05, now - self._last_tick)))
        self._last_tick = now

    def _step(self, dt: float):
        """Avança a onda `dt` segundos (separado do timer para poder ser testado sem esperar)."""
        target = self._wave_target()
        omega = RISE_RATE if target > self._lift else FALL_RATE
        # Mola criticamente amortecida, solução exata por passo (estável com qualquer dt): sem repique e sem o "tranco"
        # inicial de uma aproximação exponencial, que já nasce na velocidade máxima.
        e = self._lift - target
        k = self._lift_v + omega * e
        decay = math.exp(-omega * dt)
        self._lift = target + (e + k * dt) * decay
        self._lift_v = (self._lift_v - k * omega * dt) * decay
        if target == 0.0:
            self._lift = max(0.0, self._lift)   # a retração nunca passa do zero, mesmo vindo com velocidade para cima

        kx = self._knob_x()
        if self._prev_kx is None:
            self._prev_kx = kx
        speed = (kx - self._prev_kx) / dt
        self._prev_kx = kx
        goal = max(-1.0, min(1.0, speed / SKEW_SPEED)) if self._wave_drag else 0.0
        self._skew += (goal - self._skew) * (1.0 - math.exp(-dt / SKEW_SMOOTH))

        settled = abs(self._lift - target) < 0.002 and abs(self._lift_v) < 0.02
        if settled and abs(self._skew) < 0.01:
            self._lift, self._lift_v, self._skew = target, 0.0, 0.0
            self._prev_kx = None
            self._timer.stop()
        self.update()

    def _flat_ends(self) -> tuple[float, float]:
        """x onde a barra deixa de ser reta, nas duas pontas (dali até o fim da barra fica o canto redondo; a altura
        da onda nesses pontos é a referência da "parede" de cada ponta)."""
        flat = TRACK_H / 2.0
        return MARGIN + flat, self.width() - MARGIN - flat

    def _crest_x(self) -> float:
        """Onde fica o pico da colina: sempre exatamente sob o botão."""
        return self._knob_x()

    def _bell(self, x: float) -> float:
        """Perfil da colina (0 a 1): sino com o pico sob o botão, simétrico longe das pontas. Perto de uma ponta o lado
        de lá encolhe para caber, e só bem no fim sobra parede; tudo muda de forma contínua com a posição do botão."""
        crest = self._crest_x()
        # Cada lado da colina cabe no espaço que tem até a ponta da barra: longe das pontas a queda tem a largura
        # cheia; chegando perto, ela ENCOLHE (fica mais íngreme, mas continua uma curva em S inteira que pousa na
        # barra), em vez de ser cortada no meio por uma parede. Só nos últimos WAVE_MIN_W px, quando a queda já está
        # no máximo de inclinação, é que ela passa da ponta e sobra parede (arredondada em `_top_y`).
        # A queda pousa onde a barra ainda é reta: o canto redondo da ponta fica intacto, sem ressalto.
        flat_left, flat_right = self._flat_ends()
        room = (crest - flat_left) if x < crest else (flat_right - crest)
        # A cauda arrasta: com o botão indo para a direita (skew > 0) o lado esquerdo (atrás) alarga e o direito estreita.
        behind = (x < crest) == (self._skew > 0.0)
        shape = 1.0 + (TRAIL_GAIN if behind else -LEAD_LOSS) * abs(self._skew)
        half_w = max(WAVE_MIN_W, min(WAVE_HALF_W * shape, room))
        d = abs(x - crest)
        if d >= half_w:
            return 0.0
        return 0.5 * (1.0 + math.cos(math.pi * d / half_w))

    def _crest_height(self) -> float:
        """Altura do pico (px acima da barra)."""
        return LIFT_PX * self._lift

    def _wave_offset(self, x: float) -> float:
        """Quanto a paleta cresce para cima (negativo = para cima) em `x`."""
        if self._lift <= 0.0:
            return 0.0
        return -self._crest_height() * self._bell(x)

    def _end_radius(self, end_x: float) -> float:
        """Raio (horizontal) do canto arredondado da ponta em `end_x`: o da barra em repouso, e mais largo conforme a
        colina sobe ali, para a curva do canto se misturar com a onda que chega."""
        return TRACK_H / 2.0 + min(END_ROUND_MAX, END_ROUND_GAIN * -self._wave_offset(end_x))

    def _top_y(self, x: float) -> float:
        """Borda de cima da paleta em `x` (a silhueta desenhada). No meio é a trilha mais a onda. Em cada ponta a
        borda desce num quarto de elipse até o FIM da barra (tangente vertical ali, sem quina nem degrau, e sem
        mudança de inclinação onde encontra a onda). Sem onda na ponta, é exatamente o canto redondo da barra."""
        track = self._track_rect()
        half = TRACK_H / 2.0
        height = half - self._wave_offset(x)          # acima do centro da trilha
        left_d, right_d = x - track.left(), track.right() - x
        d, end_x = (left_d, track.left()) if left_d <= right_d else (right_d, track.right())
        r = self._end_radius(end_x)
        if d < r:
            u = (r - max(0.0, d)) / r
            height *= math.sqrt(max(0.0, 1.0 - u * u))
        return self._center_y() - height

    def _knob_y(self) -> float:
        """Altura do centro do botão: sempre no topo da crista."""
        return self._center_y() - self._crest_height() * self._bell(self._knob_x()) - KNOB_RISE * self._lift

    # --- Desenho ---

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing)
        track = self._track_rect()
        is_dark = self._theme.is_dark

        if self._grad_cache is None or self._grad_cache[0] != is_dark:
            self._grad_cache = (is_dark, [QColor(derive_accent(min(359, round(i * 359 / STEPS)), is_dark)[0])
                                          for i in range(STEPS + 1)])
        grad = QLinearGradient(track.left(), 0, track.right(), 0)
        for i, color in enumerate(self._grad_cache[1]):
            grad.setColorAt(i / STEPS, color)
        lifted = self._lift > 0.001
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(track, TRACK_H / 2, TRACK_H / 2)   # a trilha de sempre: a base fica reta e no lugar
        if lifted:
            # Colina: a mesma paleta (o gradiente só depende de x) crescendo por cima da trilha, de ponta a ponta. A
            # base é a linha do centro da trilha (não deixa fresta). Nas pontas a borda segue `_top_y`: sem onda ali é
            # o próprio canto redondo da barra; com onda, a parede sobe do fim da barra e arredonda para dentro dela.
            # Perto das pontas o passo é mais fino, porque ali a borda é quase vertical.
            x0, x1 = track.left(), track.right()
            cy = self._center_y()
            fine0 = x0 + self._end_radius(x0)
            fine1 = x1 - self._end_radius(x1)
            hill = QPainterPath()
            hill.moveTo(x0, cy)
            x = x0
            while x < x1:
                hill.lineTo(x, self._top_y(x))
                x = min(x1, x + (0.25 if (x < fine0 or x >= fine1) else 1.0))
            hill.lineTo(x1, cy)
            hill.closeSubpath()
            p.drawPath(hill)

        # Botão: anel na cor do painel (separa da paleta) + miolo na cor escolhida. Na colina ele fica SEMPRE no ponto
        # mais alto (a altura do pico, também nas pontas) e cresce um pouco, com uma sombra suave embaixo.
        kx = self._knob_x()
        center = QPointF(kx, self._knob_y())
        scale = 1.0 + KNOB_GROW * self._lift
        picked = QColor(derive_accent(self._hue, is_dark)[0])
        if lifted:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(55 * self._lift)))
            r_shadow = (KNOB_R + 1.0) * scale
            p.drawEllipse(QPointF(center.x(), center.y() + 3.0 * self._lift), r_shadow, r_shadow)
        p.setBrush(QColor(self._theme.panel))
        p.setPen(QPen(QColor(self._theme.line), 1.0))
        p.drawEllipse(center, (KNOB_R - 0.5) * scale, (KNOB_R - 0.5) * scale)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(picked)
        p.drawEllipse(center, (KNOB_R - 4.0) * scale, (KNOB_R - 4.0) * scale)

        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(self._theme.text), 1.5))
            p.drawEllipse(center, (KNOB_R + 1.5) * scale, (KNOB_R + 1.5) * scale)
        p.end()
