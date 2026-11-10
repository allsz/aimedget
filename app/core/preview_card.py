"""
PreviewCard - Componente de cartão visual para exibição de widgets e skins no Hub.
- Renderiza a pintura vetorial real do widget/skin em escala calculada automaticamente.
- Cache de QPixmap em alta resolução (DPI-aware) renderizado sob demanda.
- Suporta estados de seleção, hover e rótulos tipográficos refinados.
"""

from typing import Any
from PySide6.QtCore import Qt, Signal, QRectF, QSize, QPointF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPixmap,
    QFont,
    QPainterPath,
    QMouseEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget, QSizePolicy

from app.core.preview_registry import WidgetSpec, SkinSpec
from app.core.typography import get_ui_font
from app.hub.theme import HubTheme, THEME_DARK


class PreviewCard(QWidget):
    """
    Cartão interativo contendo a pré-visualização vetorial escalada de um Widget ou Skin.
    """

    BADGE_H = 16.0
    BADGE_INSET_Y = 6.0
    BADGE_BAND = 28.0  # = inset + altura do selo + respiro até a prévia

    clicked = Signal(str)  # Emite o id da skin ou widget ao ser clicado
    active_toggled = Signal(str, bool)  # Emite (skin_id, is_active) ao alternar o controle de seleção

    def __init__(
        self,
        spec: WidgetSpec | SkinSpec,
        state: Any = None,
        theme: HubTheme = THEME_DARK,
        is_selected: bool = False,
        show_active_toggle: bool = False,
        is_active_in_menu: bool = True,
        before_toggle_callback=None,
        show_badge: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._show_badge = show_badge   # selo "EM USO" mesmo sem o toggle de menu (ex.: galeria de temas)
        self._spec = spec
        self._state = state if state is not None else spec.mock_state()
        self._theme = theme
        self._is_selected = is_selected
        self._is_hovered = False
        self._show_active_toggle = show_active_toggle
        self._is_active_in_menu = is_active_in_menu
        self._before_toggle_callback = before_toggle_callback

        self._cached_pixmap: QPixmap | None = None
        self._cache_key: tuple | None = None

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(130, 155)

        self.toggle_switch = None
        if self._show_active_toggle:
            from app.core.i18n import t
            from app.hub.components.pill_switch import PillSwitch

            self.toggle_switch = PillSwitch(
                checked=self._is_active_in_menu,
                theme=self._theme,
                compact=True,
                before_toggle=self._handle_before_toggle,
                parent=self,
            )
            self.toggle_switch.setToolTip(t("music_skin_toggle_tooltip"))
            self.toggle_switch.toggled_value.connect(self._on_switch_toggled)

    def sizeHint(self) -> QSize:
        return QSize(185, 170)

    def _handle_before_toggle(self, target_state: bool) -> bool:
        if self._before_toggle_callback is not None:
            can_toggle = self._before_toggle_callback(self._spec.id, target_state)
            if not can_toggle:
                from PySide6.QtGui import QCursor
                from PySide6.QtWidgets import QToolTip
                from app.core.i18n import t

                QToolTip.showText(QCursor.pos(), t("music_skin_min_one"))
                return False
        return True

    def _on_switch_toggled(self, checked: bool):
        self._is_active_in_menu = checked
        self.update()
        self.active_toggled.emit(self._spec.id, checked)

    def set_active_in_menu(self, active: bool):
        self._is_active_in_menu = active
        if self.toggle_switch:
            self.toggle_switch.blockSignals(True)
            self.toggle_switch.set_checked(active, animated=True)
            self.toggle_switch.blockSignals(False)
        self.update()

    def is_active_in_menu(self) -> bool:
        return self._is_active_in_menu

    def set_active(self, active: bool):
        self.set_active_in_menu(active)

    def is_active(self) -> bool:
        return self.is_active_in_menu()

    def set_toggleable(self, toggleable: bool, tooltip: str = ""):
        self._show_active_toggle = toggleable
        self._invalidate_cache()
        if toggleable and self.toggle_switch is None:
            from app.core.i18n import t
            from app.hub.components.pill_switch import PillSwitch

            self.toggle_switch = PillSwitch(
                checked=self._is_active_in_menu,
                theme=self._theme,
                compact=True,
                before_toggle=self._handle_before_toggle,
                parent=self,
            )
            self.toggle_switch.setToolTip(tooltip or t("music_skin_toggle_tooltip"))
            self.toggle_switch.toggled_value.connect(self._on_switch_toggled)
            self.toggle_switch.show()

            w = float(self.width())
            h = float(self.height())
            label_area_h = 38.0
            foot_y = h - label_area_h
            sw_w = float(self.toggle_switch.width())
            sw_h = float(self.toggle_switch.height())
            sw_x = int(w - 12.0 - sw_w)
            sw_y = int(foot_y + (label_area_h - sw_h) / 2.0)
            self.toggle_switch.move(sw_x, sw_y)
        elif not toggleable and self.toggle_switch is not None:
            self.toggle_switch.hide()
        self.update()

    def set_selected(self, selected: bool):
        if self._is_selected != selected:
            self._is_selected = selected
            self.update()

    def is_selected(self) -> bool:
        return self._is_selected

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        if self.toggle_switch:
            self.toggle_switch.set_theme(theme)
        self._invalidate_cache()
        self.update()

    def set_state(self, state: Any):
        self._state = state
        self._invalidate_cache()
        self.update()

    def _invalidate_cache(self):
        self._cached_pixmap = None
        self._cache_key = None

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._spec.id)
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._invalidate_cache()
        if self.toggle_switch:
            w = float(self.width())
            h = float(self.height())
            label_area_h = 38.0
            foot_y = h - label_area_h
            sw_w = float(self.toggle_switch.width())
            sw_h = float(self.toggle_switch.height())
            sw_x = int(w - 12.0 - sw_w)
            sw_y = int(foot_y + (label_area_h - sw_h) / 2.0)
            self.toggle_switch.move(sw_x, sw_y)

    def _render_preview_pixmap(self, stage_w: float, stage_h: float, dpr: float) -> QPixmap:
        """Gera o Pixmap da pré-visualização com anti-aliasing e escala perfeita."""
        px_w = max(1, int(round(stage_w * dpr)))
        px_h = max(1, int(round(stage_h * dpr)))

        pixmap = QPixmap(px_w, px_h)
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        p = QPainter(pixmap)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        # Determina o tamanho natural do widget
        natural = (
            self._spec.natural_size(self._state)
            if callable(self._spec.natural_size)
            else self._spec.natural_size
        )
        nat_w = max(1.0, float(natural.width()))
        nat_h = max(1.0, float(natural.height()))

        # Margens internas do palco para a miniatura respirar. Em cards com seletor de
        # ativação, o topo reserva uma faixa para o selo "EM USO" (sem sobrepor a prévia).
        padding = 12.0
        top_reserve = self.BADGE_BAND if (self._show_active_toggle or self._show_badge) else 0.0
        top_pad = top_reserve if top_reserve else padding
        avail_w = max(10.0, stage_w - padding * 2.0)
        avail_h = max(10.0, stage_h - top_pad - padding)

        # Auto-fit dinâmico: escala proporcional matemática sem números mágicos
        scale = min(avail_w / nat_w, avail_h / nat_h, 1.0)

        draw_w = nat_w * scale
        draw_h = nat_h * scale
        draw_x = (stage_w - draw_w) * 0.5
        draw_y = top_pad + (avail_h - draw_h) * 0.5

        # Renderiza a função pura de pintura da skin / widget
        p.save()
        p.translate(draw_x, draw_y)
        p.scale(scale, scale)
        self._spec.paint(p, QRectF(0.0, 0.0, nat_w, nat_h), self._state, self._theme)
        p.restore()
        p.end()

        return pixmap

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        card_radius = 10.0

        # Cores de container e borda baseadas no estado
        bg_color = QColor(self._theme.panel2)
        if self._is_selected:
            border_color = QColor(self._theme.accent)
            border_width = 1.6
        elif self._is_hovered:
            border_color = QColor(self._theme.mute)
            border_width = 1.0
        else:
            border_color = QColor(self._theme.line)
            border_width = 1.0

        # Fundo do cartão
        path = QPainterPath()
        path.addRoundedRect(rect, card_radius, card_radius)
        p.fillPath(path, bg_color)
        p.setPen(QPen(border_color, border_width))
        p.drawPath(path)

        # Região do Palco / Estágio visual (área onde o widget aparece)
        label_area_h = 38.0
        stage_margin = 6.0
        stage_rect = QRectF(
            stage_margin,
            stage_margin,
            w - stage_margin * 2.0,
            h - label_area_h - stage_margin,
        )

        # Fundo sutil do palco para destacar o widget
        stage_path = QPainterPath()
        stage_path.addRoundedRect(stage_rect, card_radius - 2.0, card_radius - 2.0)
        p.fillPath(stage_path, QColor(self._theme.panel))

        # Obtenção / Atualização do Pixmap em Cache
        dpr = self.devicePixelRatioF()
        cache_key = (
            int(round(stage_rect.width())),
            int(round(stage_rect.height())),
            dpr,
            self._theme.mode,
            id(self._state),
        )

        if self._cached_pixmap is None or self._cache_key != cache_key:
            self._cached_pixmap = self._render_preview_pixmap(
                stage_rect.width(), stage_rect.height(), dpr
            )
            self._cache_key = cache_key

        if self._cached_pixmap:
            if self._show_active_toggle and not self._is_active_in_menu:
                p.save()
                p.setOpacity(0.38)
                p.drawPixmap(QPointF(stage_rect.x(), stage_rect.y()), self._cached_pixmap)
                p.restore()
            else:
                p.drawPixmap(QPointF(stage_rect.x(), stage_rect.y()), self._cached_pixmap)

        # Rodapé: Título e Indicador de Seleção
        foot_y = h - label_area_h
        text_x = 12.0
        right_reserved = 48.0 if self._show_active_toggle else 24.0
        text_rect = QRectF(text_x, foot_y, w - text_x - right_reserved, label_area_h)

        is_disabled = self._show_active_toggle and not self._is_active_in_menu
        text_color = (
            self._theme.mute
            if is_disabled
            else (self._theme.accent if self._is_selected else self._theme.text)
        )
        p.setFont(get_ui_font(12, QFont.Weight.DemiBold if self._is_selected else QFont.Weight.Medium))
        p.setPen(QColor(text_color))
        p.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._spec.title,
        )

        # Badge elegante "EM USO" no palco se for a skin selecionada
        if (self._show_active_toggle or self._show_badge) and self._is_selected:
            from app.core.i18n import t

            badge_w = 52.0
            badge_h = self.BADGE_H
            badge_x = stage_rect.x() + 8.0
            badge_y = stage_rect.y() + self.BADGE_INSET_Y
            b_rect = QRectF(badge_x, badge_y, badge_w, badge_h)
            b_path = QPainterPath()
            b_path.addRoundedRect(b_rect, 4.0, 4.0)
            p.fillPath(b_path, QColor(self._theme.accent))
            p.setFont(get_ui_font(9.0, QFont.Weight.Bold))
            p.setPen(QColor(self._theme.ink))
            p.drawText(b_rect, Qt.AlignmentFlag.AlignCenter, t("music_skin_active_badge"))

        # Ponto indicador tradicional quando selecionado (somente para escolha única sem toggle)
        if not self._show_active_toggle and not self._show_badge and self._is_selected:
            dot_r = 3.5
            dot_cx = w - 16.0
            dot_cy = foot_y + label_area_h * 0.5
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._theme.accent))
            p.drawEllipse(QPointF(dot_cx, dot_cy), dot_r, dot_r)
