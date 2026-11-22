"""
BatteryCard - Janela flutuante do Battery Widget, sobre `FloatingCard`.

Diferente dos outros cartões, o tamanho é LIVRE: arrastar o canto muda largura e altura separadamente (não a
escala), e o layout se refaz na hora (anéis deslizam). O cartão nunca fica menor do que os dispositivos pedem: se
não couberem com anel de 52 px, ele cresce (com mola). Num grupo ancorado, os vizinhos acompanham a cada quadro.
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QPainter

from app.core.anchor_manager import anchor_bar_items, anchor_manager
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.refresh_rate import refresh_interval_ms
from app.core.widget_animator import animations_enabled
from app.hub.theme import resolve_theme
from app.ui_components.floating_card import AMBIENT_FRAME_MS, FloatingCard
from app.ui_components.fluent_menu import FluentMusicMenu
from app.ui_components.menu_action_bar import ActionBarItem
from app.widgets.battery import layout as lay
from app.widgets.battery.card_painter import THEME_BLACK, THEME_DARK, THEME_LIGHT, paint_battery_card
from app.widgets.battery.card_state import (
    FACE_BOTH,
    FACE_HOVER,
    FACE_ICON,
    FACE_PERCENT,
    LABEL_NAME,
    LABEL_TYPE,
    SHOW_ALL,
    SHOW_HEADER,
    SHOW_NAMES,
    SHOW_NONE,
    BatteryState,
    Options,
)


_theme_cache = [0.0, THEME_DARK]


def card_theme() -> str:
    """O cartão segue o tema do Hub: Claro, Escuro ou True Dark (preto). Cache de 0,5 s: a pintura roda por quadro e
    o modo "sistema" consulta o registro do Windows."""
    now = time.monotonic()
    if now - _theme_cache[0] < 0.5:
        return _theme_cache[1]
    pref = config_manager.get_hub_theme("system")
    if pref == "true_dark":
        theme = THEME_BLACK
    else:
        theme = THEME_DARK if resolve_theme(pref).is_dark else THEME_LIGHT
    _theme_cache[0], _theme_cache[1] = now, theme
    return theme


def invalidate_card_theme():
    _theme_cache[0] = 0.0


class BatteryCard(FloatingCard):
    ANCHOR_KEY = "battery"

    option_requested = Signal(str, str)        # (chave, valor) vindo do menu
    size_committed = Signal(float, float)      # tamanho escolhido no canto (soltou) ou por "redefinir"
    refresh_requested = Signal()

    def __init__(self, desktop_mode: bool = False, size=lay.DEFAULT_SIZE, options: Optional[Options] = None):
        w, h = (float(size[0]), float(size[1])) if size else lay.DEFAULT_SIZE
        self.state = BatteryState(base_w=w, base_h=h, options=options or Options(), animated=animations_enabled())
        self._last_tick = 0.0
        self._free_resize: Optional[tuple] = None
        cw, ch = self.state.card_size()
        super().__init__(scale=1.0, desktop_mode=desktop_mode, card_w=cw, card_h=ch)

    # --- Relógio ---

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

    def _card_is_busy(self, now: float) -> bool:
        dt = max(0.0, min(0.05, now - self._last_tick)) if self._last_tick > 0 else 0.016
        self._last_tick = now
        busy = self.state.step(dt)
        self._sync_size()
        return busy

    def _card_needs_frames(self, now: float) -> bool:
        # A bolinha de carregando pulsa: só enquanto algum carrega e com animações ligadas (quadros de 33 ms)
        return self.state.animated and self.state.any_charging()

    def _sync_size(self):
        w, h = self.state.card_size()
        if abs(w - self._card_w) < 0.35 and abs(h - self._card_h) < 0.35:
            return
        self._card_w, self._card_h = w, h
        m = 2.0 * self.margin()
        new_w = int(round(w * self._scale + m))
        new_h = int(round(h * self._scale + m))
        if self.width() != new_w or self.height() != new_h:
            self.setFixedSize(new_w, new_h)
            self._shadows = {}
            if self.isVisible():
                anchor_manager().member_resized(self)   # num grupo, os vizinhos acompanham o tamanho novo

    def _live(self) -> bool:
        """Anima só com o cartão na tela e as animações do Windows ligadas; oculto, vai direto ao alvo."""
        return animations_enabled() and self.isVisible()

    def _refresh(self):
        self._last_tick = self.now()
        if not self.state.animated:
            self.state.step(0.0)
        self._sync_size()
        self.kick()
        self.update()

    # --- Dados e opções (chamados pelo controller) ---

    def set_devices(self, devices: list):
        self.state.animated = self._live()
        self.state.set_devices(devices)
        self._refresh()

    def set_options(self, options: Options):
        if options.face != self.state.options.face or options != self.state.options:
            self.state.animated = self._live()
            self.state.set_options(options)
            self._refresh()

    def set_base_size(self, w: float, h: float):
        self.state.animated = self._live()
        self.state.set_base_size(w, h)
        self._refresh()

    def base_size(self) -> tuple[float, float]:
        return self.state.base_w, self.state.base_h

    def is_scale_animating(self) -> bool:
        """Para o alinhador do anchor: o TAMANHO do cartão ainda está assentando. Só as molas de largura/altura contam;
        o arco enchendo, a face do hover ou a bolinha de carregando não seguram o alinhamento."""
        return not (self.state.W.settled() and self.state.H.settled())

    def match_card_size(self, target_w: Optional[float] = None, target_h: Optional[float] = None,
                        animate: bool = False):
        """Alinhar tamanho com um vizinho (anchor): muda a largura OU a altura escolhida, nunca a escala."""
        w = float(target_w) if target_w is not None else self.state.base_w
        h = float(target_h) if target_h is not None else self.state.base_h
        self.state.animated = animate and self._live()
        self.state.set_base_size(w, h)
        self._refresh()
        self.size_committed.emit(self.state.base_w, self.state.base_h)

    # --- Pintura ---

    def paint_card_content(self, p: QPainter, rect: QRectF, now: float):
        paint_battery_card(p, rect, self.state, theme=card_theme(), now=now)

    # --- Canto: tamanho livre ---

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_grip(self._to_card(event.position())):
            self._free_resize = (event.globalPosition(), self.state.base_w, self.state.base_h)
            self._resize_start = ("free",)      # a alça fica acesa enquanto arrasta
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._free_resize is not None and event.buttons() & Qt.MouseButton.LeftButton:
            start, w0, h0 = self._free_resize
            delta = event.globalPosition() - start
            self.state.animated = self._live()
            self.state.set_base_size(w0 + delta.x() / self._scale, h0 + delta.y() / self._scale, direct=True)
            self._sync_size()
            self.kick()
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._free_resize is not None:
            self._free_resize = None
            self._resize_start = None
            self.size_committed.emit(self.state.base_w, self.state.base_h)
            self.update()
            return
        super().mouseReleaseEvent(event)

    # --- Passar o mouse: porcentagem ---

    def enterEvent(self, event):
        self.state.set_hovered(True)
        self._refresh()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.state.set_hovered(False)
        self._refresh()
        super().leaveEvent(event)

    def _on_drag_finished(self, origin):
        if config_manager.get_battery("remember_position", False):
            config_manager.set_battery("position", [origin.x(), origin.y()])

    # --- Menu de contexto ---

    def _choice_menu(self, menu, theme, title_key: str, key: str, current: str, choices):
        sub = FluentMusicMenu(t(title_key), menu, theme=theme)
        for value, label_key in choices:
            act = QAction(t(label_key), self)
            sub.set_trailing_check(act, current == value)
            act.triggered.connect(lambda _c=False, k=key, v=value: self.option_requested.emit(k, v))
            sub.addAction(act)
        menu.addMenu(sub)

    def contextMenuEvent(self, event):
        theme = resolve_theme(config_manager.get_hub_theme("system"))
        menu = FluentMusicMenu(parent=self, theme=theme)
        o = self.state.options
        menu.add_action_bar([
            ActionBarItem(key="refresh", icon="refresh", tooltip=t("battery_refresh_now"), close_menu=True,
                          on_trigger=self.refresh_requested.emit),
            ActionBarItem(key="pin", icon="pin", tooltip=t("timer_menu_remember"), toggle=True,
                          checked=bool(config_manager.get_battery("remember_position", False)),
                          on_trigger=self.remember_position_changed.emit),
            ActionBarItem(key="desktop", icon="desktop", tooltip=t("weather_menu_desktop"), toggle=True,
                          checked=self._desktop_mode, on_trigger=self.desktop_mode_changed.emit),
            *anchor_bar_items(self),
        ])
        self._choice_menu(menu, theme, "battery_opt_face_title", "face", o.face, (
            (FACE_HOVER, "battery_face_hover"), (FACE_ICON, "battery_face_icon"),
            (FACE_PERCENT, "battery_face_percent"), (FACE_BOTH, "battery_face_both")))
        self._choice_menu(menu, theme, "battery_opt_label_title", "label", o.label, (
            (LABEL_NAME, "battery_label_name"), (LABEL_TYPE, "battery_label_type")))
        self._choice_menu(menu, theme, "battery_opt_show_title", "show", o.show, (
            (SHOW_ALL, "battery_show_all"), (SHOW_NAMES, "battery_show_names"),
            (SHOW_HEADER, "battery_show_header"), (SHOW_NONE, "battery_show_none")))
        self._choice_menu(menu, theme, "battery_opt_odd_title", "odd", o.odd, (
            (lay.ODD_CENTER, "battery_odd_center"), (lay.ODD_LEFT, "battery_odd_left")))
        act_count = QAction(t("battery_menu_show_count"), self)
        menu.set_trailing_check(act_count, o.count)
        act_count.triggered.connect(lambda _c=False: self.option_requested.emit("count", "off" if o.count else "on"))
        menu.addAction(act_count)
        act_reset = QAction(t("battery_reset_size"), self)
        act_reset.triggered.connect(lambda _c=False: self.option_requested.emit("size", "reset"))
        menu.addAction(act_reset)
        menu.addSeparator()
        act_configure = QAction(t("menu_configure_widget"), self)
        act_configure.triggered.connect(self.configure_requested.emit)
        menu.addAction(act_configure)
        act_close = QAction(t("menu_close_widget"), self)
        act_close.triggered.connect(self.close_requested.emit)
        menu.addAction(act_close)
        menu.exec(event.globalPos())
