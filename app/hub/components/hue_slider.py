"""
HueSlider - seletor de matiz para a cor de destaque do app.

A trilha mostra as cores que o tema realmente vai usar (derivadas por `derive_accent` para o modo claro/escuro
atual), então o que o usuário vê na trilha é o que ele recebe. O botão deslizante leva a cor escolhida.

- `hueChanged(int)`: a cada movimento (aplicar ao vivo)
- `hueCommitted(int)`: ao soltar o botão do mouse ou ao terminar um ajuste pelo teclado
- Teclado: setas ±1°, Shift+setas ±10°, Home/End; foco visível por anel.

Onda: ao ARRASTAR (mover além de DRAG_THRESHOLD px com o botão apertado) a paleta vira uma COLINA preenchida: a base
continua reta e a paleta cresce por baixo de uma curva suave, com o botão SEMPRE no ponto mais alto dela (o pico fica
exatamente sob o botão, sem atraso), deixando as cores bem visíveis. Nas pontas da barra a colina não achata: ela
termina num ombro arredondado e numa parede reta rente ao fim da barra. Ao soltar, a colina volta ao tamanho normal de
forma suave. Um clique simples (sem arrastar) e o
teclado não ligam a onda. Sem "Efeitos de animação" do Windows, não há onda. A faixa de altura da colina e do botão
fica reservada acima da trilha (HEADROOM).

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

TRACK_H = 10.0
KNOB_R = 10.0
MARGIN = KNOB_R + 2.0   # folga lateral para o anel de foco não ser cortado
STEPS = 36   # paradas do gradiente (a cada 10°)

LIFT_PX = 14             # quanto a paleta cresce para cima no pico da colina
HEADROOM = 22            # faixa reservada acima da trilha: cabe a colina e o botão sobre o pico
KNOB_RISE = 8.0          # quanto o botão sobe em relação à trilha quando a colina está inteira (fica sobre o pico)
WAVE_HALF_W = 110.0      # meia-largura da colina, em px: larga e suave, quase a trilha toda
SHOULDER_W = 16.0        # largura do ombro arredondado onde a colina encontra a ponta da barra, em px
SHOULDER_DROP = 6.0      # quanto o ombro desce até a parede reta do fim da barra, em px (com a colina inteira)
DRAG_THRESHOLD = 4.0     # quanto o mouse precisa andar apertado para ser "arrastar" e não um clique
RISE_RATE = 16.0         # velocidade de subida da colina (1/s): rápida, acompanha o dedo
FALL_RATE = 7.0          # velocidade de retração (1/s): mais lenta, ~0,4 s para voltar ao normal


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
        self._last_tick = 0.0
        self._grad_cache: tuple[bool, list[QColor]] | None = None   # cores da trilha para o modo atual
        self._timer = QTimer(self)
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
                self._start_timer()
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
        rate = RISE_RATE if target > self._lift else FALL_RATE
        self._lift += (target - self._lift) * (1.0 - math.exp(-rate * dt))
        if abs(self._lift - target) < 0.002:
            self._lift = target
            self._timer.stop()
        self.update()

    def _bell(self, x: float) -> float:
        """Perfil da colina (0 a 1): um sino suave com o pico exatamente sob o botão."""
        d = abs(x - self._knob_x())
        return 0.0 if d >= WAVE_HALF_W else 0.5 * (1.0 + math.cos(math.pi * d / WAVE_HALF_W))

    def _crest_height(self) -> float:
        """Altura do pico (px acima da barra): onde o botão repousa."""
        return LIFT_PX * self._lift

    def _wave_offset(self, x: float) -> float:
        """Quanto a paleta cresce para cima (negativo = para cima) em `x`.

        O pico é sempre o botão. Nas pontas da barra a colina não achata: a borda vira um ombro arredondado (um arco de
        SHOULDER_W px que desce até SHOULDER_DROP px) e termina numa parede reta, rente ao fim da barra, como no esboço.
        A descida do ombro encolhe junto com a altura da colina naquele ponto, então não há degrau quando o pico se
        afasta da ponta.
        """
        if self._lift <= 0.0:
            return 0.0
        height = self._crest_height() * self._bell(x)
        left, right = MARGIN, self.width() - MARGIN
        for edge_x, dx in ((left, x - left), (right, right - x)):
            if dx < SHOULDER_W:
                wall = min(SHOULDER_DROP * self._lift, 0.45 * self._crest_height() * self._bell(edge_x))
                t = 1.0 - max(0.0, dx) / SHOULDER_W
                height -= wall * (1.0 - math.sqrt(max(0.0, 1.0 - t * t)))
        return -max(0.0, height)

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
            # Colina: a mesma paleta (o gradiente só depende de x) crescendo por cima da trilha, até a curva. A base
            # entra 3 px na trilha para não deixar fresta entre as duas formas.
            top, x0, x1 = track.top(), track.left(), track.right()
            hill = QPainterPath()
            hill.moveTo(x0, top + 3.0)
            x = x0
            while x < x1:
                hill.lineTo(x, top + self._wave_offset(x))
                x = min(x1, x + 1.0)
            hill.lineTo(x1, top + self._wave_offset(x1))
            hill.lineTo(x1, top + 3.0)
            hill.closeSubpath()
            p.drawPath(hill)

        # Botão: anel na cor do painel (separa da paleta) + miolo na cor escolhida. Na colina ele fica SEMPRE no ponto
        # mais alto (a altura do pico, também nas pontas) e cresce um pouco, com uma sombra suave embaixo.
        kx = self._knob_x()
        center = QPointF(kx, self._center_y() - self._crest_height() - KNOB_RISE * self._lift)
        scale = 1.0 + 0.12 * self._lift
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
