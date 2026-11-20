"""
Pílula deslizante ("Tab pill" de https://designbookmark.com/motion#db-tab-pill), nos dois eixos.

Duas molas por pílula, uma para cada ponta. A ponta que vai na frente (a de baixo ao descer, a da direita ao ir para
a direita) é dura (LEAD 620/40) e a de trás é mole (TRAIL 170/19): a pílula se estica até o novo item e depois puxa
a cauda. No design original o eixo é X; aqui o mesmo código serve ao eixo Y (barra lateral) trocando só quais
coordenadas do retângulo são "início" e "fim".

- `TabPill`: a camada. Fica atrás dos botões do pai, desenha a pílula (e, se pedido, o contorno de cada botão) e segue
  os botões quando eles mudam de lugar ou de tamanho (janela redimensionada, texto traduzido).
- `PillButton`: botão de texto transparente; a cor do texto segue o quanto a pílula já cobre o botão, então o texto
  vira (claro -> escuro) junto com a pílula, não antes dela.
- `ChipGroup`: uma fileira de PillButton + TabPill (os chips de tamanho 85/100/120% e °C/°F).

Sem seleção a pílula some (fade). Com os efeitos de animação do Windows desligados, tudo acontece na hora.
"""

import time

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QPushButton, QWidget
from app.core.refresh_rate import FRAME_MS, refresh_interval_ms

from app.core import widget_animator
from app.hub.components.city_list import Spring
from app.hub.theme import HubTheme, THEME_LIGHT
from app.core.frame_clock import FrameTimer

# Mais duras que as do exemplo original (620/40 e 170/19) para o app ficar ágil: ~180 ms para assentar num salto
# de 200 px (e ~130 ms num salto curto), ainda com o esticar visível.
LEAD = (3200.0, 98.0)    # ponta que vai na frente
TRAIL = (1500.0, 62.0)   # ponta que fica para trás (é ela que dá o esticar)
FADE = (900.0, 48.0)     # a pílula aparece/some quando não há seleção

SUBSTEPS = 4


def animations_enabled() -> bool:
    return widget_animator.animations_enabled()


def _mix(a: QColor, b: QColor, f: float) -> QColor:
    f = max(0.0, min(1.0, f))
    return QColor(round(a.red() + (b.red() - a.red()) * f), round(a.green() + (b.green() - a.green()) * f),
                  round(a.blue() + (b.blue() - a.blue()) * f), round(a.alpha() + (b.alpha() - a.alpha()) * f))


BLEND = (1100.0, 54.0)   # liga/desliga de um estado (cartão selecionado): ~150 ms


class Blend(QObject):
    """Valor 0..1 que persegue um alvo com mola (um pouco de quique); `on_change` é chamado a cada quadro."""

    def __init__(self, value: float, on_change, parent: QObject | None = None, spring=BLEND):
        super().__init__(parent)
        self._spring = Spring(value, spring)
        self._on_change = on_change
        self._last = 0.0
        self._timer = FrameTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def value(self) -> float:
        return self._spring.x

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def set(self, target: float, animated: bool = True):
        self._spring.t = float(target)
        if not animated or not animations_enabled():
            self._timer.stop()
            self._spring.x, self._spring.v = self._spring.t, 0.0
            self._on_change()
            return
        self._last = time.monotonic()
        self._timer.setInterval(refresh_interval_ms())
        self._timer.start()

    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last, 1 / 30) / SUBSTEPS
        self._last = now
        for _ in range(SUBSTEPS):
            self._spring.step(dt)
        if self._spring.settled():
            self._spring.x, self._spring.v = self._spring.t, 0.0
            self._timer.stop()
        self._on_change()


class TabPill(QWidget):
    """Camada com a pílula, atrás dos botões do `parent`. `vertical=True` faz o movimento no eixo Y."""

    def __init__(self, parent: QWidget, vertical: bool = False, color: str = "#FFFFFF", radius: float = 6.0,
                 outline: str | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._vertical = vertical
        self._color = QColor(color)
        self._outline = QColor(outline) if outline else None
        self._radius = radius
        self._buttons: dict = {}
        self._key = None
        self._a = Spring(0.0, TRAIL)     # início da pílula no eixo (esquerda / topo)
        self._b = Spring(0.0, TRAIL)     # fim da pílula no eixo (direita / base)
        self._alpha = Spring(0.0, FADE)
        self._cross = (0.0, 0.0)         # posição e tamanho no eixo que não anima
        self._last = 0.0
        self._timer = FrameTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.lower()

    # --- Configuração ---

    def track(self, key, button: QAbstractButton):
        self._buttons[key] = button
        button.installEventFilter(self)
        self.lower()

    def set_colors(self, color: str, outline: str | None = None):
        self._color = QColor(color)
        self._outline = QColor(outline) if outline else None
        self.update()

    def current_key(self):
        return self._key

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def rect_now(self) -> QRectF:
        a, b = self._a.x, max(self._a.x, self._b.x)
        c0, c1 = self._cross
        return QRectF(c0, a, c1, b - a) if self._vertical else QRectF(a, c0, b - a, c1)

    def coverage(self, button: QAbstractButton) -> float:
        """Fração (0..1) do botão, no eixo do movimento, que a pílula cobre agora; já vezes a opacidade."""
        g = button.geometry()
        start, length = (g.y(), g.height()) if self._vertical else (g.x(), g.width())
        if length <= 0:
            return 0.0
        a, b = self._a.x, max(self._a.x, self._b.x)
        overlap = max(0.0, min(b, start + length) - max(a, start))
        return min(1.0, overlap / length) * max(0.0, min(1.0, self._alpha.x))

    # --- Seleção ---

    def select(self, key, animated: bool = True):
        if key == self._key:
            return
        previous = self._key
        self._key = key
        button = self._buttons.get(key)
        if button is None:                       # nada marcado: a pílula some onde está
            self._alpha.t = 0.0
            if animated and animations_enabled() and self.isVisible():
                self._start()
            else:
                self._snap_alpha()
            return
        instant = not animated or not animations_enabled() or not self.isVisible()
        reappearing = previous is None
        self._alpha.t = 1.0
        if instant or reappearing:               # primeira vez ou voltando do nada: aparece no lugar, sem viajar
            self._place(button, snap=True)
            if instant:
                self._snap_alpha()
            else:
                self._start()
            return
        self._place(button, snap=False, retune=True)
        self._start()

    def _bounds(self, button: QAbstractButton):
        g = button.geometry()
        if self._vertical:
            return float(g.y()), float(g.y() + g.height()), (float(g.x()), float(g.width()))
        return float(g.x()), float(g.x() + g.width()), (float(g.y()), float(g.height()))

    def _place(self, button: QAbstractButton, snap: bool, retune: bool = False):
        a, b, self._cross = self._bounds(button)
        if retune:
            forward = a >= self._a.t
            lead, trail = (self._b, self._a) if forward else (self._a, self._b)
            lead.k, lead.c = LEAD
            trail.k, trail.c = TRAIL
        self._a.t, self._b.t = a, b
        if snap:
            self._a.x, self._b.x = a, b
            self._a.v = self._b.v = 0.0
        self.update()

    def _snap_alpha(self):
        self._timer.stop()
        self._alpha.x = self._alpha.t
        self._alpha.v = 0.0
        self._a.x, self._b.x = self._a.t, self._b.t
        self._a.v = self._b.v = 0.0
        self._refresh()

    def _start(self):
        self._last = time.monotonic()
        self._timer.setInterval(refresh_interval_ms(self))
        self._timer.start()

    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last, 1 / 30) / SUBSTEPS
        self._last = now
        for _ in range(SUBSTEPS):
            self._a.step(dt)
            self._b.step(dt)
            self._alpha.step(dt)
        if self._a.settled() and self._b.settled() and self._alpha.settled():
            self._snap_alpha()
        else:
            self._refresh()

    def _refresh(self):
        self.update()
        for button in self._buttons.values():
            button.update()

    # --- Segue os botões e o pai ---

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        kind = event.type()
        if obj is self.parent():
            if kind == QEvent.Type.Resize:
                self.setGeometry(self.parent().rect())
                self.lower()
        elif kind in (QEvent.Type.Move, QEvent.Type.Resize) and self._key is not None \
                and obj is self._buttons.get(self._key):
            # o botão marcado mudou de lugar/tamanho: as molas passam a mirar o novo retângulo
            self._place(obj, snap=not self._timer.isActive() or not self.isVisible())
            self._refresh()
        return False

    def showEvent(self, event):
        super().showEvent(event)
        self.lower()
        button = self._buttons.get(self._key)
        if button is not None and not self._timer.isActive():
            self._place(button, snap=True)
            self._snap_alpha()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._outline is not None:
            painter.setPen(self._outline)
            for button in self._buttons.values():
                g = QRectF(button.geometry()).adjusted(0.5, 0.5, -0.5, -0.5)
                painter.drawRoundedRect(g, self._radius, self._radius)
        alpha = max(0.0, min(1.0, self._alpha.x))
        if alpha <= 0.0:
            return
        color = QColor(self._color)
        color.setAlphaF(color.alphaF() * alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(self.rect_now(), self._radius, self._radius)


class PillButton(QPushButton):
    """Chip transparente: o fundo vem da pílula atrás dele; o texto escurece/clareia conforme a pílula cobre."""

    def __init__(self, text: str, layer_getter, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(text, parent)
        self._layer_getter = layer_getter
        self._theme = theme
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: 1px solid transparent; padding: 5px 12px; }")
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        self.setFont(font)

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    def paintEvent(self, event):
        layer = self._layer_getter()
        cover = layer.coverage(self) if layer is not None else 0.0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.underMouse()
        if hovered and cover < 1.0:
            fill = QColor(self._theme.panel2)
            fill.setAlphaF(1.0 - cover)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        resting = QColor(self._theme.text if hovered else self._theme.body)
        painter.setPen(_mix(resting, QColor(self._theme.bg), cover))
        painter.setFont(self.font())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class ChipGroup(QWidget):
    """Fileira de chips com a pílula deslizando entre eles. `chips`: [(chave, texto)]; `on_click(chave)`."""

    def __init__(self, chips, on_click, theme: HubTheme = THEME_LIGHT, selected=None, parent=None,
                 segmented: bool = False):
        super().__init__(parent)
        self._theme = theme
        self._segmented = bool(segmented)
        layout = QHBoxLayout(self)
        if self._segmented:
            layout.setContentsMargins(3, 3, 3, 3)
            layout.setSpacing(2)
            self.setFixedHeight(36)
            self._pill = TabPill(self, vertical=False, color=theme.text, radius=7.0, outline=None)
        else:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            self._pill = TabPill(self, vertical=False, color=theme.text, radius=6.0, outline=theme.line)
        self._buttons: dict = {}
        for key, text in chips:
            btn = PillButton(text, lambda: self._pill, theme, self)
            if self._segmented:
                btn.setStyleSheet("QPushButton { background: transparent; border: 0; padding: 0px 8px; }")
                font = QFont(btn.font())
                font.setPixelSize(12)
                btn.setFont(font)
                btn.setFixedHeight(30)
            btn.clicked.connect(lambda checked=False, k=key: on_click(k))
            layout.addWidget(btn, stretch=1 if self._segmented else 0)
            self._buttons[key] = btn
            self._pill.track(key, btn)
        self._pill.select(selected, animated=False)
        self._mark(selected)

    def paintEvent(self, event):
        if self._segmented:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(self._theme.bg))
            painter.setPen(QColor(self._theme.line))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10.0, 10.0)
        super().paintEvent(event)

    @property
    def buttons(self) -> dict:
        return self._buttons

    def _mark(self, key):
        for k, btn in self._buttons.items():
            btn.setProperty("selected", "true" if k == key else "false")   # estado legivel (testes, acessibilidade)

    def set_selected(self, key, animated: bool = True):
        key = key if key in self._buttons else None
        self._mark(key)
        self._pill.select(key, animated=animated)

    def selected(self):
        return self._pill.current_key()

    def button(self, key) -> PillButton:
        return self._buttons[key]

    def pill(self) -> TabPill:
        return self._pill

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._pill.set_colors(theme.text, None if self._segmented else theme.line)
        for btn in self._buttons.values():
            btn.set_theme(theme)
        if self._segmented:
            self.update()
