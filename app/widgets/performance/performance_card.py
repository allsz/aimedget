"""
PerformanceCard - Janela flutuante do widget de desempenho, reutilizando `FloatingCard`.

Herda tamanho (300x262, raio 27), sombra, redimensionamento pelo canto, arraste livre entre monitores,
fixação na área de trabalho com onda de pontos e suporte ao Win+D.
"""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QPainter

from app.core.anchor_manager import add_anchor_actions
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.widget_animator import animations_enabled
from app.hub.theme import resolve_theme
from app.ui_components.floating_card import CARD_H, CARD_W, SCALES, FloatingCard
from app.ui_components.fluent_menu import FluentMusicMenu
from app.widgets.performance.card_painter import paint_performance_card, pill_at
from app.widgets.performance.card_state import ALL_METRICS, PerformanceState


class PerformanceCard(FloatingCard):
    ANCHOR_KEY = "performance"
    metric_selected = Signal(str)

    def __init__(
        self,
        scale: float = 1.0,
        desktop_mode: bool = False,
        selected_metric: str = "cpu",
        fps_enabled: bool = False,
    ):
        self.state = PerformanceState(
            selected=selected_metric if selected_metric in ALL_METRICS else "cpu",
            prev_selected=selected_metric if selected_metric in ALL_METRICS else "cpu",
            animated=animations_enabled(),
            fps_enabled=bool(fps_enabled),
        )
        if not self.state.fps_enabled and self.state.selected == "fps":
            self.state.selected = "cpu"
            self.state.prev_selected = "cpu"
        super().__init__(scale=scale, desktop_mode=desktop_mode, card_w=CARD_W, card_h=CARD_H)

    # --- Ciclo de vida e relógio ---

    def _on_before_show(self):
        self.state.animated = animations_enabled()

    def _card_is_busy(self, now: float) -> bool:
        return self.state.transitions_busy(now)

    # --- Pintura ---

    def paint_card_content(self, p: QPainter, rect: QRectF, now: float):
        paint_performance_card(p, rect, self.state, pinned=self._desktop_mode, now=now)

    # --- Interação (pílulas de métrica, arraste, teclado) ---

    def _pill_count(self) -> int:
        return len(self.state.visible_metrics())

    def _on_card_press(self, card_pos: QPointF) -> bool:
        idx = pill_at(card_pos, self._pill_count())
        if idx >= 0:
            self.state.pressed_pill = idx
            self.update()
            return True
        return False

    def _on_card_hover(self, card_pos: QPointF, grip: bool) -> bool:
        idx = -1 if grip else pill_at(card_pos, self._pill_count())
        if idx != self.state.hovered_pill:
            self.state.hovered_pill = idx
            self.update()
        return idx >= 0

    def _on_card_release(self, card_pos: QPointF) -> bool:
        if self.state.pressed_pill >= 0:
            pressed = self.state.pressed_pill
            self.state.pressed_pill = -1
            visible = self.state.visible_metrics()
            if pill_at(card_pos, len(visible)) == pressed and 0 <= pressed < len(visible):
                self.metric_selected.emit(visible[pressed])
            self.update()
            return True
        return False

    def _on_card_leave(self):
        self.state.hovered_pill = -1

    def _on_drag_finished(self, origin: QPoint):
        if config_manager.get_performance("remember_position", False):
            config_manager.set_performance("position", [origin.x(), origin.y()])

    def keyPressEvent(self, event):
        visible = self.state.visible_metrics()
        if event.key() == Qt.Key.Key_Down:
            nxt = (self.state.selected_index() + 1) % len(visible)
            self.metric_selected.emit(visible[nxt])
        elif event.key() == Qt.Key.Key_Up:
            prv = (self.state.selected_index() - 1 + len(visible)) % len(visible)
            self.metric_selected.emit(visible[prv])
        else:
            super().keyPressEvent(event)

    # --- Menu de contexto ---

    def contextMenuEvent(self, event):
        theme = resolve_theme(config_manager.get_hub_theme("system"))
        menu = FluentMusicMenu(parent=self, theme=theme)

        size_menu = FluentMusicMenu(t("weather_menu_size"), menu, theme=theme)
        for value in SCALES:
            act = QAction(f"{int(round(value * 100))}%", self)
            size_menu.set_trailing_check(act, abs(self._scale - value) < 0.01)
            act.triggered.connect(lambda checked=False, v=value: self.scale_changed.emit(v))
            size_menu.addAction(act)
        menu.addMenu(size_menu)

        remembered = bool(config_manager.get_performance("remember_position", False))
        act_remember = QAction(t("timer_menu_remember"), self)
        menu.set_trailing_check(act_remember, remembered)
        act_remember.triggered.connect(lambda: self.remember_position_changed.emit(not remembered))
        menu.addAction(act_remember)

        act_desktop = QAction(t("weather_menu_desktop"), self)
        menu.set_trailing_check(act_desktop, self._desktop_mode)
        act_desktop.triggered.connect(lambda: self.desktop_mode_changed.emit(not self._desktop_mode))
        menu.addAction(act_desktop)
        add_anchor_actions(menu, self)

        menu.addSeparator()
        act_close = QAction(t("menu_close_widget"), self)
        act_close.triggered.connect(self.close_requested.emit)
        menu.addAction(act_close)
        menu.exec(event.globalPos())
