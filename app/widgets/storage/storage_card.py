"""
StorageCard - Janela flutuante do Storage Widget baseada em `FloatingCard`.

- Tamanho ancorado exato do Weather/Performance (300x262, raio 27); expande para baixo com mola.
- Relógio amarrado à taxa do monitor com teto em 240 Hz (`refresh_interval_ms`, sem piso de 16 ms).
- Por padrão, clicar fora do widget recolhe para 300x262; com "Sempre expandido" ligado, permanece aberto.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from app.core.anchor_manager import anchor_bar_items, anchor_manager
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.refresh_rate import refresh_interval_ms
from app.core.widget_animator import animations_enabled
from app.hub.theme import resolve_theme
from app.ui_components.floating_card import AMBIENT_FRAME_MS, CARD_H, CARD_W, SCALES, FloatingCard
from app.ui_components.fluent_menu import FluentMusicMenu
from app.ui_components.menu_action_bar import ActionBarItem
from app.widgets.storage.card_painter import (
    EXPAND_BTN_RECT,
    THEME_DARK,
    hit_test_drive,
    hit_test_row,
    open_btn_rect,
    paint_storage_card,
)
from app.widgets.storage.card_state import COMPACT_H, StorageState


_theme_cache = [0.0, THEME_DARK]


def card_theme() -> str:
    """Resolve o modo atual do Hub ('light', 'dark' ou 'true_dark') com cache curto de 0,5 s."""
    now = time.monotonic()
    if now - _theme_cache[0] < 0.5:
        return _theme_cache[1]
    pref = config_manager.get_hub_theme("system")
    mode = resolve_theme(pref).mode
    _theme_cache[0], _theme_cache[1] = now, mode
    return mode


def invalidate_card_theme():
    _theme_cache[0] = 0.0


class StorageCard(FloatingCard):
    ANCHOR_KEY = "storage"

    refresh_requested = Signal()
    always_expanded_changed = Signal(bool)

    def __init__(
        self,
        scale: float = 1.0,
        desktop_mode: bool = False,
        always_expanded: bool = False,
    ):
        self.state = StorageState(animated=animations_enabled(), always_expanded=always_expanded)
        self._last_tick: float = 0.0
        self._outside_filter_installed: bool = False
        super().__init__(scale=scale, desktop_mode=desktop_mode, card_w=CARD_W, card_h=CARD_H)
        app = QApplication.instance()
        if app is not None and hasattr(app, "styleHints") and hasattr(app.styleHints(), "colorSchemeChanged"):
            app.styleHints().colorSchemeChanged.connect(self._on_system_color_scheme_changed)

    def _on_system_color_scheme_changed(self, *_args):
        invalidate_card_theme()
        self.update()

    # --- Relógio: taxa do monitor até 240 Hz ---

    def _set_frame_interval(self):
        busy = self._busy(self.now())
        interval = refresh_interval_ms(self) if busy else AMBIENT_FRAME_MS
        if not self._clock.isActive():
            self._clock.start(interval)
        elif self._clock.interval() != interval:
            self._clock.setInterval(interval)

    def _on_before_show(self):
        self.state.animated = animations_enabled()
        self._last_tick = self.now()
        self._sync_outside_filter()

    def _card_is_busy(self, now: float) -> bool:
        dt = max(0.0, min(0.05, now - self._last_tick)) if self._last_tick > 0 else 0.016
        self._last_tick = now
        self.state.step(dt)
        self._sync_card_height()
        return self.state.busy()

    def _sync_card_height(self):
        h = max(COMPACT_H, float(self.state.card_h.x))
        target = self.state.target_card_height()
        if not self.state.busy() and abs(h - target) < 1.0:
            h = target
            self.state.card_h.snap(target)
        if abs(h - self._card_h) < 0.2:
            return
        self._card_h = h
        m = 2.0 * self.margin()
        new_w = int(round(self._card_w * self._scale + m))
        new_h = int(round(self._card_h * self._scale + m))
        if self.width() != new_w or self.height() != new_h:
            self.setFixedSize(new_w, new_h)
            self._shadows = {}
            if self.isVisible():
                anchor_manager().member_resized(self)

    def _card_theme(self) -> str:
        return card_theme()

    def _is_light_theme(self) -> bool:
        return self._card_theme() == "light"

    def paint_card_content(self, p: QPainter, rect: QRectF, now: float):
        mode = self._card_theme()
        paint_storage_card(p, rect, self.state, light=(mode == "light"), theme=mode)

    # --- Expansão e clique fora ---

    def set_expanded(self, expanded: bool):
        self.state.animated = animations_enabled()
        if self.state.set_expanded(expanded, animate=self.state.animated):
            self._last_tick = self.now()
            if not self.state.animated:
                self._sync_card_height()
            self._sync_outside_filter()
            self.kick()
            self.update()

    def set_always_expanded(self, enabled: bool):
        self.state.animated = animations_enabled()
        self.state.set_always_expanded(enabled, animate=self.state.animated)
        self._last_tick = self.now()
        if not self.state.animated:
            self._sync_card_height()
        self._sync_outside_filter()
        self.kick()
        self.update()

    def _sync_outside_filter(self):
        want = self.isVisible() and self.state.expanded and not self.state.always_expanded
        app = QApplication.instance()
        if app is None:
            return
        if want and not self._outside_filter_installed:
            app.installEventFilter(self)
            self._outside_filter_installed = True
        elif not want and self._outside_filter_installed:
            app.removeEventFilter(self)
            self._outside_filter_installed = False

    def eventFilter(self, obj, event) -> bool:
        if self.state.expanded and not self.state.always_expanded and self.isVisible():
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress:
                if isinstance(obj, QWidget) and obj.window() is not self:
                    self.set_expanded(False)
            elif etype == QEvent.Type.ApplicationDeactivate:
                self.set_expanded(False)
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        if self.state.expanded and not self.state.always_expanded:
            self.state.set_expanded(False, animate=False)
            self._sync_card_height()
        self._sync_outside_filter()
        super().hideEvent(event)

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None and self._outside_filter_installed:
            app.removeEventFilter(self)
            self._outside_filter_installed = False
        super().closeEvent(event)

    # --- Interação com o cartão ---

    def _on_card_hover(self, card_pos: QPointF, grip: bool) -> bool:
        if grip:
            self._clear_hover()
            return False
        prev = (self.state.hovered_expand, self.state.hovered_drive, self.state.hovered_row, self.state.hovered_open)
        self.state.hovered_expand = EXPAND_BTN_RECT.contains(card_pos)
        self.state.hovered_drive = hit_test_drive(self.state, card_pos)
        ob = open_btn_rect(self.state, self.state.selected_row)
        self.state.hovered_open = ob is not None and ob.contains(card_pos)
        self.state.hovered_row = -1 if (self.state.hovered_expand or self.state.hovered_drive >= 0 or self.state.hovered_open) else hit_test_row(self.state, card_pos)
        cur = (self.state.hovered_expand, self.state.hovered_drive, self.state.hovered_row, self.state.hovered_open)
        if cur != prev:
            self.update()
        return any((self.state.hovered_expand, self.state.hovered_drive >= 0, self.state.hovered_row >= 0, self.state.hovered_open))

    def _on_card_leave(self):
        self._clear_hover()

    def _clear_hover(self):
        if any((self.state.hovered_expand, self.state.hovered_drive >= 0, self.state.hovered_row >= 0, self.state.hovered_open)):
            self.state.hovered_expand = False
            self.state.hovered_drive = -1
            self.state.hovered_row = -1
            self.state.hovered_open = False
            self.update()

    def _is_interactive_hit(self, card_pos: QPointF) -> bool:
        if EXPAND_BTN_RECT.contains(card_pos):
            return True
        if hit_test_drive(self.state, card_pos) >= 0:
            return True
        ob = open_btn_rect(self.state, self.state.selected_row)
        if ob is not None and ob.contains(card_pos):
            return True
        return hit_test_row(self.state, card_pos) >= 0

    def _on_card_press(self, card_pos: QPointF) -> bool:
        if self._is_interactive_hit(card_pos):
            self._drag_offset = None
            self._dragged = False
            return True
        return False

    def _on_card_release(self, card_pos: QPointF) -> bool:
        if self._drag_offset is not None and self._dragged:
            return False
        if EXPAND_BTN_RECT.contains(card_pos):
            self.set_expanded(not self.state.expanded)
            return True

        drv_idx = hit_test_drive(self.state, card_pos)
        if drv_idx >= 0:
            self.state.animated = animations_enabled()
            if self.state.select_drive(drv_idx, animate=self.state.animated):
                self._last_tick = self.now()
                if not self.state.animated:
                    self._sync_card_height()
                self.kick()
                self.update()
            return True

        ob = open_btn_rect(self.state, self.state.selected_row)
        if ob is not None and ob.contains(card_pos):
            folder = self.state.rows[self.state.selected_row].folder
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder.path))
            return True

        row_idx = hit_test_row(self.state, card_pos)
        if row_idx >= 0:
            self.state.animated = animations_enabled()
            if self.state.select_row(row_idx, animate=self.state.animated):
                self._last_tick = self.now()
                if not self.state.animated:
                    self._sync_card_height()
                self._sync_outside_filter()
                self.kick()
                self.update()
            return True

        return False

    def _on_drag_finished(self, origin):
        if config_manager.get_storage("remember_position", False):
            config_manager.set_storage("position", [origin.x(), origin.y()])

    # --- Menu de contexto ---

    def contextMenuEvent(self, event):
        theme = resolve_theme(config_manager.get_hub_theme("system"))
        menu = FluentMusicMenu(parent=self, theme=theme)

        remember = bool(config_manager.get_storage("remember_position", False))
        bar = [
            ActionBarItem(
                key="refresh",
                icon="refresh",
                tooltip=t("storage_refresh_now"),
                close_menu=True,
                on_trigger=self.refresh_requested.emit,
            ),
            ActionBarItem(
                key="pin",
                icon="pin",
                tooltip=t("timer_menu_remember"),
                toggle=True,
                checked=remember,
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
            *anchor_bar_items(self),
        ]
        menu.add_action_bar(bar)

        act_always = QAction(t("storage_always_expanded_title"), self)
        menu.set_trailing_check(act_always, self.state.always_expanded)
        act_always.triggered.connect(lambda _c=False: self.always_expanded_changed.emit(not self.state.always_expanded))
        menu.addAction(act_always)

        size_menu = FluentMusicMenu(t("weather_menu_size"), menu, theme=theme)
        act_auto = QAction(t("music_scale_auto"), self)
        size_menu.set_trailing_check(act_auto, self.scale_auto)
        act_auto.triggered.connect(lambda _c=False: self.scale_changed.emit(None))
        size_menu.addAction(act_auto)
        size_menu.addSeparator()
        for sc in SCALES:
            act = QAction(f"{int(round(sc * 100))}%", self)
            size_menu.set_trailing_check(act, not self.scale_auto and abs(self._scale - sc) < 0.03)
            act.triggered.connect(lambda _c=False, v=sc: self.scale_changed.emit(v))
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
