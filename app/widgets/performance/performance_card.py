"""
PerformanceCard - Janela flutuante do widget de desempenho, reutilizando `FloatingCard`.

Herda tamanho (300x262, raio 27), sombra, redimensionamento pelo canto, arraste livre entre monitores,
fixação na área de trabalho com onda de pontos e suporte ao Win+D.
"""

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from app.core.anchor_manager import anchor_bar_items
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.widget_animator import animations_enabled
from app.hub.theme import resolve_theme
from app.ui_components.floating_card import CARD_H, CARD_W, SCALES, FloatingCard
from app.ui_components.fluent_menu import FluentMusicMenu
from app.ui_components.menu_action_bar import ActionBarItem
from app.widgets.performance.card_painter import (
    ND_TRIGGER_RECT,
    done_hit,
    nd_dropdown_item_at,
    nd_dropdown_rect,
    nd_pager_dot_at,
    paint_performance_card,
    pill_at,
    pill_bounds,
    pill_rect,
)
from app.widgets.performance.card_state import (
    ALL_METRICS,
    PERFORMANCE_SKINS,
    SKIN_FLUENT,
    SKIN_NOTHING_DOT,
    PerformanceState,
    normalize_metric_order,
)


class PerformanceCard(FloatingCard):
    ANCHOR_KEY = "performance"
    metric_selected = Signal(str)
    metric_order_changed = Signal(list)
    skin_switch_requested = Signal(str)

    def __init__(
        self,
        scale: float = 1.0,
        desktop_mode: bool = False,
        selected_metric: str = "cpu",
        fps_enabled: bool = False,
        metric_order=None,
        skin_id: str = SKIN_FLUENT,
    ):
        self.state = PerformanceState(
            selected=selected_metric if selected_metric in ALL_METRICS else "cpu",
            prev_selected=selected_metric if selected_metric in ALL_METRICS else "cpu",
            animated=animations_enabled(),
            fps_enabled=bool(fps_enabled),
            skin_id=skin_id if skin_id in PERFORMANCE_SKINS else SKIN_FLUENT,
            metric_order=normalize_metric_order(metric_order),
        )
        if not self.state.fps_enabled and self.state.selected == "fps":
            self.state.selected = "cpu"
            self.state.prev_selected = "cpu"
        self._drag_grab_dy: float = 0.0
        self._last_reorder_tick: float = 0.0
        self._reorder_filter_installed: bool = False
        super().__init__(scale=scale, desktop_mode=desktop_mode, card_w=CARD_W, card_h=CARD_H)

    # --- Ciclo de vida e relógio ---

    def _on_before_show(self):
        self.state.animated = animations_enabled()

    def _decay_pill_offsets(self, now: float):
        if not self.state.pill_y_offsets:
            self._last_reorder_tick = now
            return
        if not self.state.animated:
            self.state.pill_y_offsets.clear()
            self._last_reorder_tick = now
            return
        dt = max(0.0, min(0.05, now - self._last_reorder_tick)) if self._last_reorder_tick > 0 else 0.016
        self._last_reorder_tick = now
        factor = math.exp(-18.0 * dt)
        done = []
        for k, v in self.state.pill_y_offsets.items():
            nv = v * factor
            if abs(nv) < 0.25:
                done.append(k)
            else:
                self.state.pill_y_offsets[k] = nv
        for k in done:
            del self.state.pill_y_offsets[k]

    def _step_dropdown(self, now: float):
        target = 1.0 if self.state.dropdown_open else 0.0
        if not self.state.animated:
            self.state.dropdown_progress = target
            return
        dt = max(0.0, min(0.05, now - self._last_reorder_tick)) if self._last_reorder_tick > 0 else 0.016
        step = 1.0 - math.exp(-22.0 * dt)
        self.state.dropdown_progress += (target - self.state.dropdown_progress) * step
        if abs(self.state.dropdown_progress - target) < 0.01:
            self.state.dropdown_progress = target

    def _card_is_busy(self, now: float) -> bool:
        self._step_dropdown(now)
        self._decay_pill_offsets(now)
        return self.state.transitions_busy(now)

    def set_skin(self, skin_id: str):
        sid = skin_id if skin_id in PERFORMANCE_SKINS else SKIN_FLUENT
        if sid == self.state.skin_id:
            return
        if self.state.reorder_mode:
            self.set_reorder_mode(False)
        self.state.dropdown_open = False
        self.state.dropdown_progress = 0.0
        self.state.dropdown_hovered = -1
        self.state.trigger_hovered = False
        self.state.skin_id = sid
        self.update()

    def set_dropdown_open(self, open_: bool):
        open_ = bool(open_)
        if open_ == self.state.dropdown_open:
            return
        self.state.dropdown_open = open_
        self.state.animated = animations_enabled()
        if not self.state.animated:
            self.state.dropdown_progress = 1.0 if open_ else 0.0
        if not open_:
            self.state.dropdown_hovered = -1
        self._last_reorder_tick = self.now()
        self.kick()
        self.update()

    # --- Modo de reordenação ---

    def is_reordering(self) -> bool:
        return bool(self.state.reorder_mode)

    def set_reorder_mode(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self.state.reorder_mode:
            return
        self.state.reorder_mode = enabled
        self.state.animated = animations_enabled()
        self.state.drag_metric = None
        self.state.pressed_pill = -1
        self.state.done_hovered = False
        self.state.done_pressed = False
        self.state.pill_y_offsets.clear()
        if enabled:
            self.state.reorder_t0 = self.now()
            self._last_reorder_tick = self.state.reorder_t0
            self._install_reorder_filter()
            self.activateWindow()
            self.setFocus()
            self.kick()
        else:
            self._remove_reorder_filter()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def _install_reorder_filter(self):
        app = QApplication.instance()
        if app is not None and not self._reorder_filter_installed:
            app.installEventFilter(self)
            self._reorder_filter_installed = True

    def _remove_reorder_filter(self):
        app = QApplication.instance()
        if app is not None and self._reorder_filter_installed:
            app.removeEventFilter(self)
            self._reorder_filter_installed = False

    def eventFilter(self, obj, event) -> bool:
        if self.state.reorder_mode and self.isVisible():
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress and self.state.drag_metric is None:
                if isinstance(obj, QWidget) and obj.window() is not self:
                    self.set_reorder_mode(False)
            elif etype == QEvent.Type.ApplicationDeactivate and self.state.drag_metric is None:
                self.set_reorder_mode(False)
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        if self.state.reorder_mode:
            self.set_reorder_mode(False)
        super().hideEvent(event)

    def closeEvent(self, event):
        self._remove_reorder_filter()
        super().closeEvent(event)

    # --- Pintura ---

    def paint_card_content(self, p: QPainter, rect: QRectF, now: float):
        paint_performance_card(p, rect, self.state, pinned=self._desktop_mode, now=now)

    # --- Interação (pílulas de métrica, reordenação, arraste, teclado) ---

    def _pill_count(self) -> int:
        return len(self.state.visible_metrics())

    def _on_card_press(self, card_pos: QPointF) -> bool:
        if self.state.skin_id == SKIN_NOTHING_DOT:
            visible = self.state.visible_metrics()
            count = len(visible)
            if self.state.dropdown_open:
                idx = nd_dropdown_item_at(card_pos, count)
                if 0 <= idx < count:
                    self.metric_selected.emit(visible[idx])
                    self.set_dropdown_open(False)
                    return True
                if ND_TRIGGER_RECT.contains(card_pos):
                    self.set_dropdown_open(False)
                    return True
                self.set_dropdown_open(False)
                return True
            if ND_TRIGGER_RECT.contains(card_pos):
                self.set_dropdown_open(True)
                return True
            dot_idx = nd_pager_dot_at(card_pos, count, self.state.selected_index())
            if 0 <= dot_idx < count:
                self.metric_selected.emit(visible[dot_idx])
                return True
            return False

        if self.state.reorder_mode:
            if done_hit(card_pos):
                self.state.done_pressed = True
                self.update()
                return True
            visible = self.state.visible_metrics()
            idx = pill_at(card_pos, len(visible))
            if 0 <= idx < len(visible):
                r = pill_rect(idx, len(visible))
                self.state.drag_metric = visible[idx]
                self._drag_grab_dy = card_pos.y() - r.y()
                self.state.drag_y = r.y()
                self._last_reorder_tick = self.now()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.kick()
                return True
            return False

        idx = pill_at(card_pos, self._pill_count())
        if idx >= 0:
            self.state.pressed_pill = idx
            self.update()
            return True
        return False

    def _on_card_move(self, card_pos: QPointF) -> bool:
        if not (self.state.reorder_mode and self.state.drag_metric is not None):
            return False
        visible = self.state.visible_metrics()
        count = len(visible)
        if self.state.drag_metric not in visible:
            return False
        y0, h, gap, y_max = pill_bounds(count)
        self.state.drag_y = max(y0, min(y_max, card_pos.y() - self._drag_grab_dy))
        step = h + gap
        target = max(0, min(count - 1, int(round((self.state.drag_y - y0) / step))))
        cur = visible.index(self.state.drag_metric)
        if target != cur:
            old_ys = {m: pill_rect(i, count).y() + self.state.pill_y_offsets.get(m, 0.0) for i, m in enumerate(visible)}
            if self.state.move_visible_metric(cur, target):
                new_visible = self.state.visible_metrics()
                for i, m in enumerate(new_visible):
                    if m != self.state.drag_metric:
                        self.state.pill_y_offsets[m] = old_ys[m] - pill_rect(i, count).y()
                self._last_reorder_tick = self.now()
                self.kick()
        self.update()
        return True

    def _on_card_hover(self, card_pos: QPointF, grip: bool) -> bool:
        if self.state.skin_id == SKIN_NOTHING_DOT:
            count = self._pill_count()
            if self.state.dropdown_open:
                dd_idx = -1 if grip else nd_dropdown_item_at(card_pos, count)
                trig = (not grip) and ND_TRIGGER_RECT.contains(card_pos)
                if dd_idx != self.state.dropdown_hovered or trig != self.state.trigger_hovered:
                    self.state.dropdown_hovered = dd_idx
                    self.state.trigger_hovered = trig
                    self.update()
                return dd_idx >= 0 or trig
            trig = (not grip) and ND_TRIGGER_RECT.contains(card_pos)
            dot = -1 if (grip or trig) else nd_pager_dot_at(card_pos, count, self.state.selected_index())
            if trig != self.state.trigger_hovered:
                self.state.trigger_hovered = trig
                self.update()
            return trig or dot >= 0

        if self.state.reorder_mode:
            done = (not grip) and done_hit(card_pos)
            idx = -1 if (grip or done) else pill_at(card_pos, self._pill_count())
            changed = (done != self.state.done_hovered) or (idx != self.state.hovered_pill)
            self.state.done_hovered = done
            self.state.hovered_pill = idx
            if changed:
                self.update()
            return done or idx >= 0
        idx = -1 if grip else pill_at(card_pos, self._pill_count())
        if idx != self.state.hovered_pill:
            self.state.hovered_pill = idx
            self.update()
        return idx >= 0

    def _on_card_release(self, card_pos: QPointF) -> bool:
        if self.state.reorder_mode:
            if self.state.done_pressed:
                self.state.done_pressed = False
                if done_hit(card_pos):
                    self.set_reorder_mode(False)
                else:
                    self.update()
                return True
            if self.state.drag_metric is not None:
                self.state.drag_metric = None
                self.metric_order_changed.emit(list(self.state.metric_order))
                over_pill = pill_at(card_pos, self._pill_count()) >= 0
                self.setCursor(Qt.CursorShape.PointingHandCursor if over_pill else Qt.CursorShape.ArrowCursor)
                self.update()
                return True
            return False

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
        self.state.done_hovered = False
        self.state.trigger_hovered = False
        self.state.dropdown_hovered = -1

    def wheelEvent(self, event):
        if self.state.skin_id == SKIN_NOTHING_DOT and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            delta = event.angleDelta().y()
            if delta != 0:
                visible = self.state.visible_metrics()
                if len(visible) > 1:
                    step = -1 if delta > 0 else 1
                    nxt = (self.state.selected_index() + step) % len(visible)
                    self.metric_selected.emit(visible[nxt])
                event.accept()
                return
        super().wheelEvent(event)

    def _on_drag_finished(self, origin: QPoint):
        if config_manager.get_performance("remember_position", False):
            config_manager.set_performance("position", [origin.x(), origin.y()])

    def keyPressEvent(self, event):
        if self.state.dropdown_open and event.key() == Qt.Key.Key_Escape:
            self.set_dropdown_open(False)
            event.accept()
            return
        if self.state.reorder_mode and event.key() == Qt.Key.Key_Escape:
            self.set_reorder_mode(False)
            event.accept()
            return
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

        remembered = bool(config_manager.get_performance("remember_position", False))
        bar_items = [
            ActionBarItem(
                key="pin",
                icon="pin",
                tooltip=t("timer_menu_remember"),
                toggle=True,
                checked=remembered,
                on_trigger=self.remember_position_changed.emit,
            ),
            ActionBarItem(
                key="desktop",
                icon="desktop",
                tooltip=t("weather_menu_desktop"),
                toggle=True,
                checked=self._desktop_mode,
                on_trigger=self.desktop_mode_changed.emit,
            ),
            ActionBarItem(
                key="reorder",
                icon="reorder",
                tooltip=t("perf_menu_reorder"),
                toggle=True,
                checked=self.is_reordering(),
                close_menu=True,
                on_trigger=self.set_reorder_mode,
            ),
            *anchor_bar_items(self),
        ]
        menu.add_action_bar(bar_items)

        skins_menu = FluentMusicMenu(t("menu_skins"), menu, theme=theme)
        for sid, label in ((SKIN_FLUENT, t("perf_skin_label")), (SKIN_NOTHING_DOT, "Nothing Dot")):
            act = QAction(label, self)
            skins_menu.set_trailing_check(act, self.state.skin_id == sid)
            act.triggered.connect(lambda checked=False, k=sid: self.skin_switch_requested.emit(k))
            skins_menu.addAction(act)
        menu.addMenu(skins_menu)

        size_menu = FluentMusicMenu(t("weather_menu_size"), menu, theme=theme)
        for value in SCALES:
            act = QAction(f"{int(round(value * 100))}%", self)
            size_menu.set_trailing_check(act, abs(self._scale - value) < 0.01)
            act.triggered.connect(lambda checked=False, v=value: self.scale_changed.emit(v))
            size_menu.addAction(act)
        menu.addMenu(size_menu)

        menu.addSeparator()
        act_configure = QAction(t("menu_configure_widget"), self)
        act_configure.triggered.connect(self.configure_requested.emit)
        menu.addAction(act_configure)
        act_close = QAction(t("menu_close_widget"), self)
        act_close.triggered.connect(self.close_requested.emit)
        menu.addAction(act_close)
        menu.exec(event.globalPos())
