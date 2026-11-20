"""
Barra de ações minimalista no topo dos menus de contexto (estilo Windows 11 Fluent Rail).

- Botões auto-espaçados (somente ícones vetoriais simples e arredondados, sem rótulo de texto;
  dica completa no tooltip ao pairar).
- Pílula de hover com física de duas molas idêntica ao `TabPill` do Hub (`°C` / `°F`), esticando
  e deslizando suavemente de um ícone para o outro.
- Indicador de estado ativo (toggles) em animação ponto -> barrinha: desmarcado não mostra nada;
  ao marcar surge um ponto mínimo que cresce com mola até virar uma barrinha arredondada na cor
  de destaque; ao desmarcar encolhe de volta ao ponto e some.
- Respeita `widget_animator.animations_enabled()`: com animações do Windows desligadas, tudo
  acontece instantaneamente.
"""

from __future__ import annotations

import math
import time
import weakref
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QWidget,
    QWidgetAction,
)

from app.core import widget_animator
from app.core.refresh_rate import refresh_interval_ms
from app.hub.theme import HubTheme, THEME_DARK


class _Spring:
    """Mola amortecida 1D (mesma física do TabPill do Hub, sem dependência circular)."""

    __slots__ = ("x", "t", "v", "k", "c")

    def __init__(self, x: float = 0.0, params: tuple[float, float] = (1500.0, 62.0)):
        self.x = float(x)
        self.t = float(x)
        self.v = 0.0
        self.k, self.c = params

    def step(self, dt: float) -> None:
        a = -self.k * (self.x - self.t) - self.c * self.v
        self.v += a * dt
        self.x += self.v * dt

    def settled(self, eps: float = 1e-3) -> bool:
        return abs(self.x - self.t) < eps and abs(self.v) < eps * 10.0

# Mesma física de duas molas do TabPill do Hub (app/hub/components/tab_pill.py)
LEAD = (3200.0, 98.0)     # ponta que vai na frente
TRAIL = (1500.0, 62.0)    # ponta que fica atrás (dá o esticar suave)
FADE = (900.0, 48.0)      # aparecer/sumir da pílula ao entrar/sair da barra

# Física do indicador ponto -> barrinha
BAR_GROW = (520.0, 27.0)  # cresce com leve quique elástico ao marcar
BAR_SHRINK = (900.0, 52.0)
DOT_FADE = (1600.0, 72.0)
COLOR_BLEND = (1100.0, 54.0)

FRAME_MS = 16
SUBSTEPS = 4
SPIN_DURATION_S = 0.44


def _animations_enabled() -> bool:
    return widget_animator.animations_enabled()


def _mix(a: QColor, b: QColor, f: float) -> QColor:
    f = max(0.0, min(1.0, f))
    return QColor(
        round(a.red() + (b.red() - a.red()) * f),
        round(a.green() + (b.green() - a.green()) * f),
        round(a.blue() + (b.blue() - a.blue()) * f),
        round(a.alpha() + (b.alpha() - a.alpha()) * f),
    )


@dataclass
class ActionBarItem:
    """Descreve um botão mínimo da barra superior de um menu de contexto."""

    key: str
    icon: str
    tooltip: str
    on_trigger: Callable
    toggle: bool = False
    checked: bool = False
    spin_on_click: bool = False
    close_menu: bool = False


def draw_menu_icon(painter: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Desenha ícones vetoriais simples e arredondados em grade 24x24, nítidos em qualquer DPI."""
    size = min(rect.width(), rect.height())
    scale = size / 24.0
    ox = rect.center().x() - 12.0 * scale
    oy = rect.center().y() - 12.0 * scale

    painter.save()
    painter.translate(ox, oy)
    painter.scale(scale, scale)

    pen = QPen(
        color,
        1.85,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "refresh":
        # Arco circular suave + ponta de seta arredondada no topo direito
        arc = QPainterPath()
        arc.arcMoveTo(QRectF(4.2, 4.2, 15.6, 15.6), 42)
        arc.arcTo(QRectF(4.2, 4.2, 15.6, 15.6), 42, -295)
        painter.drawPath(arc)
        head = QPainterPath()
        head.moveTo(19.6, 4.4)
        head.lineTo(19.6, 9.2)
        head.lineTo(14.8, 9.2)
        painter.drawPath(head)

    elif name == "pin":
        # Alfinete simples e arredondado (Lembrar posição)
        body = QPainterPath()
        body.moveTo(8.5, 4.5)
        body.lineTo(15.5, 4.5)
        body.moveTo(9.8, 4.5)
        body.lineTo(9.2, 10.2)
        body.cubicTo(7.4, 11.1, 6.5, 12.4, 6.5, 14.0)
        body.lineTo(17.5, 14.0)
        body.cubicTo(17.5, 12.4, 16.6, 11.1, 14.8, 10.2)
        body.lineTo(14.2, 4.5)
        painter.drawPath(body)
        painter.drawLine(QPointF(12.0, 14.0), QPointF(12.0, 20.2))

    elif name == "desktop":
        # Monitor minimalista com cantos arredondados e base curta (Fixar na área de trabalho)
        painter.drawRoundedRect(QRectF(3.5, 4.5, 17.0, 11.5), 2.8, 2.8)
        painter.drawLine(QPointF(12.0, 16.0), QPointF(12.0, 19.6))
        painter.drawLine(QPointF(8.4, 19.6), QPointF(15.6, 19.6))

    elif name == "anchor":
        # Âncora arredondada (argola, haste, travessa e arco suave embaixo)
        painter.drawEllipse(QPointF(12.0, 5.6), 2.2, 2.2)
        painter.drawLine(QPointF(12.0, 7.8), QPointF(12.0, 19.8))
        painter.drawLine(QPointF(8.6, 10.8), QPointF(15.4, 10.8))
        arc = QPainterPath()
        arc.arcMoveTo(QRectF(4.6, 8.2, 14.8, 11.6), 192)
        arc.arcTo(QRectF(4.6, 8.2, 14.8, 11.6), 192, 156)
        painter.drawPath(arc)

    elif name == "detach":
        # Elo separado e arredondado (Soltar do grupo)
        left = QPainterPath()
        left.moveTo(10.0, 14.0)
        left.lineTo(8.3, 15.7)
        left.cubicTo(6.9, 17.1, 4.7, 17.1, 3.3, 15.7)
        left.cubicTo(1.9, 14.3, 1.9, 12.1, 3.3, 10.7)
        left.lineTo(6.0, 8.0)
        painter.drawPath(left)
        right = QPainterPath()
        right.moveTo(14.0, 10.0)
        right.lineTo(15.7, 8.3)
        right.cubicTo(17.1, 6.9, 19.3, 6.9, 20.7, 8.3)
        right.cubicTo(22.1, 9.7, 22.1, 11.9, 20.7, 13.3)
        right.lineTo(18.0, 16.0)
        painter.drawPath(right)
        painter.drawLine(QPointF(8.2, 4.5), QPointF(9.6, 6.5))
        painter.drawLine(QPointF(14.4, 17.5), QPointF(15.8, 19.5))

    elif name == "smart_hover":
        # Dial/controle de ajuste fino por scroll (Timer)
        painter.drawEllipse(QPointF(12.0, 12.0), 3.6, 3.6)
        painter.drawLine(QPointF(12.0, 3.8), QPointF(12.0, 6.2))
        painter.drawLine(QPointF(12.0, 17.8), QPointF(12.0, 20.2))
        painter.drawLine(QPointF(3.8, 12.0), QPointF(6.2, 12.0))
        painter.drawLine(QPointF(17.8, 12.0), QPointF(20.2, 12.0))

    elif name == "reset_size":
        # Seta circular anti-horária suave (Redefinir tamanho)
        arc = QPainterPath()
        arc.arcMoveTo(QRectF(4.4, 4.4, 15.2, 15.2), 138)
        arc.arcTo(QRectF(4.4, 4.4, 15.2, 15.2), 138, 290)
        painter.drawPath(arc)
        head = QPainterPath()
        head.moveTo(4.6, 4.6)
        head.lineTo(4.6, 9.3)
        head.lineTo(9.3, 9.3)
        painter.drawPath(head)

    elif name in ("align", "align_left"):
        # Duas barras arredondadas alinhadas à esquerda
        painter.drawLine(QPointF(4.5, 4.2), QPointF(4.5, 19.8))
        painter.drawRoundedRect(QRectF(8.0, 6.2, 11.5, 4.2), 1.8, 1.8)
        painter.drawRoundedRect(QRectF(8.0, 13.6, 7.8, 4.2), 1.8, 1.8)

    elif name == "align_center":
        # Duas barras arredondadas centralizadas
        painter.drawLine(QPointF(12.0, 3.6), QPointF(12.0, 20.4))
        painter.drawRoundedRect(QRectF(5.2, 6.2, 13.6, 4.2), 1.8, 1.8)
        painter.drawRoundedRect(QRectF(7.6, 13.6, 8.8, 4.2), 1.8, 1.8)

    elif name == "align_right":
        # Duas barras arredondadas alinhadas à direita
        painter.drawLine(QPointF(19.5, 4.2), QPointF(19.5, 19.8))
        painter.drawRoundedRect(QRectF(4.5, 6.2, 11.5, 4.2), 1.8, 1.8)
        painter.drawRoundedRect(QRectF(8.2, 13.6, 7.8, 4.2), 1.8, 1.8)

    elif name == "row_top":
        # Duas colunas arredondadas alinhadas pelo topo
        painter.drawLine(QPointF(4.2, 4.5), QPointF(19.8, 4.5))
        painter.drawRoundedRect(QRectF(6.0, 8.0, 4.5, 11.2), 1.8, 1.8)
        painter.drawRoundedRect(QRectF(13.5, 8.0, 4.5, 7.6), 1.8, 1.8)

    elif name == "row_mid":
        # Duas colunas arredondadas centralizadas horizontalmente
        painter.drawLine(QPointF(3.6, 12.0), QPointF(20.4, 12.0))
        painter.drawRoundedRect(QRectF(6.0, 5.4, 4.5, 13.2), 1.8, 1.8)
        painter.drawRoundedRect(QRectF(13.5, 7.6, 4.5, 8.8), 1.8, 1.8)

    elif name == "match_size":
        # Duas barras de mesmo comprimento (igualar tamanho / bordas alinhadas)
        painter.drawRoundedRect(QRectF(4.5, 5.4, 15.0, 4.8), 2.0, 2.0)
        painter.drawRoundedRect(QRectF(4.5, 13.8, 15.0, 4.8), 2.0, 2.0)

    elif name == "check":
        # Checkmark simples e arredondado (Concluir)
        chk = QPainterPath()
        chk.moveTo(5.2, 12.5)
        chk.lineTo(10.0, 17.3)
        chk.lineTo(18.8, 7.2)
        painter.drawPath(chk)

    painter.restore()


class FluentRailButton(QAbstractButton):
    """Botão de ícone mínimo com indicador animado ponto -> barrinha e rotação opcional."""

    def __init__(
        self,
        item: ActionBarItem,
        theme: HubTheme,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.item = item
        self._theme = theme
        self._hovered = False

        self.setCheckable(item.toggle)
        if item.toggle:
            self.setChecked(item.checked)
        self.setToolTip(item.tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(36)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        init_on = 1.0 if (item.toggle and item.checked) else 0.0
        self._bar = _Spring(init_on, BAR_GROW)
        self._dot_alpha = _Spring(init_on, DOT_FADE)
        self._accent_blend = _Spring(init_on, COLOR_BLEND)

        self._spin_t0: Optional[float] = None
        self._spin_angle: float = 0.0
        self._last = 0.0

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(refresh_interval_ms(self))
        self._timer.timeout.connect(self._tick)

    def sizeHint(self) -> QSize:
        return QSize(44, 36)

    def set_theme(self, theme: HubTheme) -> None:
        self._theme = theme
        self.update()

    def set_active(self, active: bool, animated: bool = True) -> None:
        if not self.item.toggle:
            return
        self.setChecked(active)
        target = 1.0 if active else 0.0
        if not animated or not _animations_enabled():
            self._bar.x = self._bar.t = target
            self._bar.v = 0.0
            self._dot_alpha.x = self._dot_alpha.t = target
            self._dot_alpha.v = 0.0
            self._accent_blend.x = self._accent_blend.t = target
            self._accent_blend.v = 0.0
            self.update()
            return

        if active:
            self._bar.k, self._bar.c = BAR_GROW
            self._dot_alpha.t = 1.0
            self._bar.t = 1.0
        else:
            self._bar.k, self._bar.c = BAR_SHRINK
            self._bar.t = 0.0
            # dot_alpha só desliga quando a barra encolher perto do ponto
        self._accent_blend.t = target
        self._start_anim()

    def trigger_spin(self) -> None:
        if not _animations_enabled():
            return
        self._spin_t0 = time.perf_counter()
        self._spin_angle = 0.0
        self._start_anim()

    def _start_anim(self) -> None:
        self._timer.setInterval(refresh_interval_ms(self))
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._last, 1.0 / 30.0) / SUBSTEPS
        self._last = now

        for _ in range(SUBSTEPS):
            self._bar.step(dt)
            if not self.isChecked() and self._bar.x < 0.16:
                self._dot_alpha.t = 0.0
            self._dot_alpha.step(dt)
            self._accent_blend.step(dt)

        spinning = False
        if self._spin_t0 is not None:
            elapsed = now - self._spin_t0
            if elapsed >= SPIN_DURATION_S:
                self._spin_t0 = None
                self._spin_angle = 0.0
            else:
                p = elapsed / SPIN_DURATION_S
                eased = 1.0 - (1.0 - p) ** 3
                self._spin_angle = 360.0 * eased
                spinning = True

        done = (
            not spinning
            and self._bar.settled()
            and self._dot_alpha.settled()
            and self._accent_blend.settled()
        )
        if done:
            self._bar.x, self._bar.v = self._bar.t, 0.0
            self._dot_alpha.x, self._dot_alpha.v = self._dot_alpha.t, 0.0
            self._accent_blend.x, self._accent_blend.v = self._accent_blend.t, 0.0
            self._timer.stop()
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        parent = self.parent()
        if isinstance(parent, FluentActionBar):
            parent._on_button_enter(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        parent = self.parent()
        if isinstance(parent, FluentActionBar):
            parent._on_button_leave()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        t = self._theme
        base = QColor(t.text if self._hovered else t.body)
        accent = QColor(t.accent)
        icon_color = _mix(base, accent, self._accent_blend.x)

        # Ícone centralizado (levemente elevado 1px para acomodar a barrinha embaixo com equilíbrio)
        cx = self.width() / 2.0
        cy = self.height() / 2.0 - 0.5
        icon_size = 16.0
        icon_rect = QRectF(cx - icon_size / 2.0, cy - icon_size / 2.0, icon_size, icon_size)

        p.save()
        if self._spin_angle != 0.0:
            p.translate(cx, cy)
            p.rotate(self._spin_angle)
            p.translate(-cx, -cy)
        elif self.isDown():
            p.translate(cx, cy)
            p.scale(0.92, 0.92)
            p.translate(-cx, -cy)
        draw_menu_icon(p, self.item.icon, icon_rect, icon_color)
        p.restore()

        # Indicador ponto -> barrinha (completamente invisível quando desmarcado)
        if self.item.toggle:
            alpha = max(0.0, min(1.0, self._dot_alpha.x))
            if alpha > 0.01:
                grow = max(0.0, self._bar.x)  # pode passar levemente de 1.0 no overshoot elástico
                bar_h = 2.5
                dot_w = bar_h
                target_w = 14.0
                bar_w = max(dot_w, dot_w + (target_w - dot_w) * grow)
                bar_y = self.height() - 4.8
                bar_rect = QRectF(cx - bar_w / 2.0, bar_y, bar_w, bar_h)

                ind_color = QColor(t.accent)
                ind_color.setAlphaF(ind_color.alphaF() * alpha)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ind_color)
                p.drawRoundedRect(bar_rect, bar_h / 2.0, bar_h / 2.0)

        p.end()


class _RailHoverPill(QWidget):
    """Pílula de hover de duas molas (TabPill) atrás dos botões do FluentActionBar."""

    def __init__(self, parent: QWidget, theme: HubTheme):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._theme = theme
        self._hovered_btn: Optional[QAbstractButton] = None
        self._a = _Spring(0.0, TRAIL)
        self._b = _Spring(0.0, TRAIL)
        self._alpha = _Spring(0.0, FADE)
        self._y = (2.0, 32.0)
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(refresh_interval_ms(self))
        self._timer.timeout.connect(self._tick)
        self.setGeometry(parent.rect())
        self.lower()

    def set_theme(self, theme: HubTheme) -> None:
        self._theme = theme
        self.update()

    def hover(self, button: Optional[QAbstractButton]) -> None:
        if button is self._hovered_btn:
            return
        previous = self._hovered_btn
        self._hovered_btn = button

        if button is None:
            self._alpha.t = 0.0
            if _animations_enabled() and self.isVisible():
                self._start()
            else:
                self._snap()
            return

        g = button.geometry()
        inset_x, inset_y = 3.0, 2.0
        target_a = float(g.left()) + inset_x
        target_b = float(g.right() + 1) - inset_x
        self._y = (float(g.top()) + inset_y, max(4.0, float(g.height()) - 2.0 * inset_y))

        instant = not _animations_enabled() or not self.isVisible()
        reappearing = previous is None
        self._alpha.t = 1.0

        if instant or reappearing:
            self._a.x = self._a.t = target_a
            self._b.x = self._b.t = target_b
            self._a.v = self._b.v = 0.0
            if instant:
                self._snap()
            else:
                self._start()
            return

        forward = target_a >= self._a.t
        lead, trail = (self._b, self._a) if forward else (self._a, self._b)
        lead.k, lead.c = LEAD
        trail.k, trail.c = TRAIL
        self._a.t, self._b.t = target_a, target_b
        self._start()

    def _start(self) -> None:
        self._timer.setInterval(refresh_interval_ms(self))
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def _snap(self) -> None:
        self._timer.stop()
        self._alpha.x, self._alpha.v = self._alpha.t, 0.0
        self._a.x, self._a.v = self._a.t, 0.0
        self._b.x, self._b.v = self._b.t, 0.0
        self.update()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._last, 1.0 / 30.0) / SUBSTEPS
        self._last = now
        for _ in range(SUBSTEPS):
            self._a.step(dt)
            self._b.step(dt)
            self._alpha.step(dt)
        if self._a.settled() and self._b.settled() and self._alpha.settled():
            self._snap()
        else:
            self.update()

    def paintEvent(self, event) -> None:
        alpha = max(0.0, min(1.0, self._alpha.x))
        if alpha <= 0.005:
            return
        w = max(0.0, self._b.x - self._a.x)
        if w <= 1.0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill = QColor(255, 255, 255, 28) if self._theme.is_dark else QColor(31, 30, 29, 20)
        fill.setAlphaF(fill.alphaF() * alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(self._a.x, self._y[0], w, self._y[1]), 7.0, 7.0)
        p.end()


class FluentActionBar(QWidget):
    """
    Barra superior estilo Windows 11 Fluent Rail para menus de contexto.
    Botões de ícone auto-espaçados, divisórias verticais sutis, pílula de hover de duas molas
    e indicador ponto -> barrinha nos toggles ativos.
    """

    def __init__(
        self,
        items: Sequence[ActionBarItem],
        theme: HubTheme = THEME_DARK,
        menu: Optional[QMenu] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._theme = theme
        self._menu_ref = weakref.ref(menu) if menu is not None else None
        self._buttons: dict[str, FluentRailButton] = {}
        self._ordered_buttons: list[FluentRailButton] = []

        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._pill = _RailHoverPill(self, theme)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(0)

        for item in items:
            btn = FluentRailButton(item, theme, self)
            btn.clicked.connect(self._on_sender_clicked)
            layout.addWidget(btn, 1)
            self._buttons[item.key] = btn
            self._ordered_buttons.append(btn)

        self._pill.lower()

    @property
    def buttons(self) -> dict[str, FluentRailButton]:
        return self._buttons

    def button(self, key: str) -> Optional[FluentRailButton]:
        return self._buttons.get(key)

    def set_theme(self, theme: HubTheme) -> None:
        self._theme = theme
        self._pill.set_theme(theme)
        for btn in self._ordered_buttons:
            btn.set_theme(theme)
        self.update()

    def _on_sender_clicked(self) -> None:
        btn = self.sender()
        if isinstance(btn, FluentRailButton):
            self._on_button_clicked(btn)

    def _on_button_clicked(self, btn: FluentRailButton) -> None:
        item = btn.item
        if item.toggle:
            new_state = btn.isChecked()
            btn.set_active(new_state, animated=True)
            item.on_trigger(new_state)
        else:
            if item.spin_on_click:
                btn.trigger_spin()
            item.on_trigger()
        menu = self._menu_ref() if self._menu_ref is not None else None
        if item.close_menu and menu is not None:
            menu.close()

    def _on_button_enter(self, btn: FluentRailButton) -> None:
        self._pill.hover(btn)

    def _on_button_leave(self) -> None:
        if not any(b.underMouse() for b in self._ordered_buttons):
            self._pill.hover(None)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._pill.setGeometry(self.rect())
        self._pill.lower()

    def leaveEvent(self, event) -> None:
        self._pill.hover(None)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        if len(self._ordered_buttons) < 2:
            return
        p = QPainter(self)
        div_color = QColor(255, 255, 255, 20) if self._theme.is_dark else QColor(0, 0, 0, 20)
        p.setPen(QPen(div_color, 1.0))
        div_h = 18.0
        for i in range(len(self._ordered_buttons) - 1):
            left_btn = self._ordered_buttons[i]
            right_btn = self._ordered_buttons[i + 1]
            x = (left_btn.geometry().right() + 1 + right_btn.geometry().left()) / 2.0
            y0 = (left_btn.geometry().height() - div_h) / 2.0
            p.drawLine(QPointF(x, y0), QPointF(x, y0 + div_h))
        p.end()


def attach_action_bar(menu: QMenu, items: Sequence[ActionBarItem], theme: HubTheme) -> Optional[FluentActionBar]:
    """Insere uma `FluentActionBar` no topo do `menu` seguida de separador."""
    if not items:
        return None
    # QWidgetAction.setDefaultWidget() assume a posse do widget; não passar parent=menu evita double-free no GC.
    bar = FluentActionBar(items, theme=theme, menu=menu, parent=None)
    wa = QWidgetAction(menu)
    wa.setDefaultWidget(bar)
    menu.addAction(wa)
    menu.addSeparator()
    return bar
