"""
Seletor circular de modo de aparência (Claro, Escuro, OLED e Sistema).

Cada opção é um círculo preenchido com a cor de fundo real do modo correspondente:
- Claro: THEME_LIGHT.bg
- Escuro: THEME_DARK.bg
- OLED: THEME_TRUE_DARK.bg
- Sistema: metade Claro (canto superior esquerdo) e metade Escuro (canto inferior direito) em diagonal 50/50.

O item selecionado recebe um anel externo na cor de destaque do Hub; hover e foco também têm feedback tátil.
"""

from typing import Callable, Iterable, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QWidget

from app.hub.components.tab_pill import Blend
from app.hub.theme import HubTheme, THEME_DARK, THEME_LIGHT, THEME_TRUE_DARK


class ThemeSwatchButton(QAbstractButton):
    """Botão circular que mostra a cor real do modo de aparência."""

    HIT_SIZE = 34
    SWATCH_DIAMETER = 22.0
    RING_WIDTH = 2.0
    RING_GAP = 2.5

    def __init__(self, mode: str, label: str, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._theme = theme
        self._selected = False
        self._sel_blend = Blend(0.0, self.update, self)
        self._hover_blend = Blend(0.0, self.update, self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedSize(self.HIT_SIZE, self.HIT_SIZE)
        self.setProperty("selected", "false")
        self.set_label(label)

    @property
    def mode(self) -> str:
        return self._mode

    def set_label(self, label: str):
        self.setToolTip(label)
        self.setAccessibleName(label)

    def set_selected(self, selected: bool, animated: bool = True):
        self._selected = bool(selected)
        self.setProperty("selected", "true" if self._selected else "false")
        self._sel_blend.set(1.0 if self._selected else 0.0, animated=animated)

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self.HIT_SIZE, self.HIT_SIZE)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._hover_blend.set(1.0)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover_blend.set(0.0)

    def _swatch_rect(self) -> QRectF:
        inset = (self.HIT_SIZE - self.SWATCH_DIAMETER) / 2.0
        return QRectF(inset, inset, self.SWATCH_DIAMETER, self.SWATCH_DIAMETER)

    def _ring_rect(self) -> QRectF:
        r = self._swatch_rect()
        expand = self.RING_GAP + self.RING_WIDTH / 2.0
        return r.adjusted(-expand, -expand, expand, expand)

    def _inner_border_color(self) -> QColor:
        if self._mode == "light":
            return QColor(0, 0, 0, 42)
        if self._mode in ("dark", "true_dark"):
            return QColor(255, 255, 255, 58) if self._theme.is_dark else QColor(0, 0, 0, 38)
        # system: contorno neutro legível tanto sobre claro quanto escuro
        return QColor(255, 255, 255, 52) if self._theme.is_dark else QColor(0, 0, 0, 46)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        swatch = self._swatch_rect()
        ring = self._ring_rect()

        # 1. Anel externo de hover / foco / seleção
        sel = max(0.0, min(1.0, self._sel_blend.value))
        hov = max(0.0, min(1.0, self._hover_blend.value))

        if sel > 0.01:
            ring_color = QColor(self._theme.accent)
            ring_color.setAlphaF(sel)
            p.setPen(QPen(ring_color, self.RING_WIDTH))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring)
        elif self.hasFocus():
            ring_color = QColor(self._theme.accent)
            ring_color.setAlphaF(0.75)
            p.setPen(QPen(ring_color, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring)
        elif hov > 0.01:
            hover_color = QColor(self._theme.mute)
            hover_color.setAlphaF(0.45 * hov)
            p.setPen(QPen(hover_color, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring)

        # 2. Preenchimento circular do modo
        clip = QPainterPath()
        clip.addEllipse(swatch)
        p.save()
        p.setClipPath(clip)
        p.setPen(Qt.PenStyle.NoPen)

        if self._mode == "light":
            p.setBrush(QColor(THEME_LIGHT.bg))
            p.drawRect(swatch)
        elif self._mode == "dark":
            p.setBrush(QColor(THEME_DARK.bg))
            p.drawRect(swatch)
        elif self._mode == "true_dark":
            p.setBrush(QColor(THEME_TRUE_DARK.bg))
            p.drawRect(swatch)
        else:
            # Sistema: 50% Claro (canto superior esquerdo) + 50% Escuro (canto inferior direito) em diagonal
            p.setBrush(QColor(THEME_LIGHT.bg))
            p.drawRect(swatch)
            dark_half = QPolygonF([
                QPointF(swatch.right(), swatch.top()),
                QPointF(swatch.right(), swatch.bottom()),
                QPointF(swatch.left(), swatch.bottom()),
            ])
            p.setBrush(QColor(THEME_DARK.bg))
            p.drawPolygon(dark_half)
        p.restore()

        # 3. Filete interno sutil para separar o círculo do fundo do card
        p.setPen(QPen(self._inner_border_color(), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(swatch.adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()


class ThemeSwatchGroup(QWidget):
    """Fileira de círculos de cor para alternar entre Claro, Escuro, OLED e Sistema."""

    def __init__(
        self,
        items: Iterable[Tuple[str, str]],
        on_pick: Callable[[str], None],
        theme: HubTheme = THEME_LIGHT,
        selected: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._theme = theme
        self._buttons: dict[str, ThemeSwatchButton] = {}
        self._selected: str | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        for key, label in items:
            btn = ThemeSwatchButton(key, label, theme=theme, parent=self)
            btn.clicked.connect(lambda _=False, k=key: on_pick(k))
            self._buttons[key] = btn
            row.addWidget(btn)

        if selected is not None:
            self.set_selected(selected, animated=False)

    @property
    def buttons(self) -> dict[str, ThemeSwatchButton]:
        return self._buttons

    def button(self, key: str) -> ThemeSwatchButton:
        return self._buttons[key]

    def set_label(self, key: str, label: str):
        if key in self._buttons:
            self._buttons[key].set_label(label)

    def set_selected(self, key: str | None, animated: bool = True):
        self._selected = key
        for k, btn in self._buttons.items():
            btn.set_selected(k == key, animated=animated)

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        for btn in self._buttons.values():
            btn.set_theme(theme)
