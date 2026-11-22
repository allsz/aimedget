"""
Janela do Weather Widget: cartão flutuante sem moldura baseado em `FloatingCard`.

- Desenho em `card_painter` (o mesmo da miniatura do Hub); aqui ficam o estado do clima, as abas dos dias e o menu
  de contexto.
- Toda a mecânica do container (escala, arraste, canto de redimensionamento, sombra, fixação no desktop com onda de
  pontos e Win+D) é herdada de `FloatingCard`.
"""

import os
import sys
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QPainter

from app.core.anchor_manager import anchor_bar_items
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.widget_animator import animations_enabled
from app.hub.theme import resolve_theme
from app.ui_components.floating_card import (
    APPEAR_MS,
    GRIP,
    HIDE_MS,
    MAX_SCALE,
    MIN_SCALE,
    SCALES,
    SHADOW,
    FloatingCard,
)
from app.ui_components.fluent_menu import FluentMusicMenu
from app.ui_components.menu_action_bar import ActionBarItem
from app.widgets.weather import conditions as cond
from app.widgets.weather.card_painter import paint_card, tab_at, tab_rect
from app.widgets.weather.card_state import CardState
from app.widgets.weather.sky_painter import CARD_H, CARD_W

__all__ = ["WeatherCard", "SCALES", "MIN_SCALE", "MAX_SCALE", "GRIP", "SHADOW", "APPEAR_MS", "HIDE_MS"]


SCALE_STEP = 0.05            # Ctrl+roda: 5% por entalhe
WHEEL_THRESHOLD = 0.75       # fração de entalhe que conta como um passo (touchpads de alta resolução)
CITY_STEP_COOLDOWN_S = 0.25  # pausa mínima entre duas trocas de cidade pela roda


def dev_tools_enabled() -> bool:
    """Menu de pré-visualização das condições: rodando do código-fonte ou com AIMEDGET_DEV=1."""
    return not getattr(sys, "frozen", False) or os.environ.get("AIMEDGET_DEV") == "1"


class WeatherCard(FloatingCard):
    ANCHOR_KEY = "weather"
    refresh_requested = Signal()
    units_changed = Signal(str)            # 'c' / 'f'
    day_selected = Signal(int)
    preview_condition_requested = Signal(str)
    city_step = Signal(int)                # +1 próxima cidade, -1 anterior (a lista dá a volta)
    city_selected = Signal(int)            # escolhida no menu "Cidade"
    manage_cities_requested = Signal()     # "Gerenciar cidades…": abre o Hub na página do Clima

    def __init__(self, scale: float = 1.0, desktop_mode: bool = False):
        self.state = CardState(animated=animations_enabled())
        self._paint_cache: dict = {}       # camadas reaproveitadas entre quadros (ver card_painter.paint_card)
        self.city_names: list = []         # nomes para o menu "Cidade" (o controller mantém atualizado)
        self._wheel_acc = 0.0              # roda acumulada (touchpads mandam frações de entalhe)
        self._last_city_step = 0.0
        super().__init__(scale=scale, desktop_mode=desktop_mode, card_w=CARD_W, card_h=CARD_H)

    # --- Relógio e ciclo de vida ---

    def _on_before_show(self):
        self.state.animated = animations_enabled()

    def _card_needs_frames(self, now: float) -> bool:
        return self.state.animated

    def _card_is_busy(self, now: float) -> bool:
        return self.state.transitions_busy(now)

    # --- Pintura ---

    def paint_card_content(self, p: QPainter, rect: QRectF, now: float):
        paint_card(p, rect, self.state, now, cache=self._paint_cache)

    # --- Mouse e teclado ---

    def _grip_blocked(self, card_pos: QPointF) -> bool:
        return tab_rect(4).contains(card_pos)

    def _on_card_press(self, card_pos: QPointF) -> bool:
        tab = tab_at(card_pos)
        if tab >= 0 and self.state.days and not self.state.message:
            self.state.pressed_tab = tab
            self.state.press_t0 = self.now()
            self.kick()
            return True
        return False

    def _on_card_hover(self, card_pos: QPointF, grip: bool) -> bool:
        tab = tab_at(card_pos) if not self.state.message and not grip else -1
        if tab != self.state.hovered_tab:
            self.state.hovered_tab = tab
            self.update()
        return tab >= 0

    def _on_card_release(self, card_pos: QPointF) -> bool:
        if self.state.pressed_tab >= 0:
            pressed = self.state.pressed_tab
            self.state.pressed_tab = -1
            if tab_at(card_pos) == pressed:
                self.day_selected.emit(pressed)
            self.kick()
            return True
        return False

    def _on_card_leave(self):
        self.state.hovered_tab = -1

    def _on_drag_finished(self, origin: QPoint):
        if config_manager.get_weather("remember_position", False):
            config_manager.set_weather("position", [origin.x(), origin.y()])

    def keyPressEvent(self, event):
        n = len(self.state.days)
        if n and event.key() == Qt.Key.Key_Right:
            self.day_selected.emit((self.state.selected + 1) % n)
        elif n and event.key() == Qt.Key.Key_Left:
            self.day_selected.emit((self.state.selected - 1 + n) % n)
        elif event.key() == Qt.Key.Key_Down and len(self.city_names) > 1:
            self.city_step.emit(1)
        elif event.key() == Qt.Key.Key_Up and len(self.city_names) > 1:
            self.city_step.emit(-1)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        """
        Roda: troca de cidade (para baixo = próxima), um passo por entalhe com uma pausa curta entre passos, para um
        gesto de touchpad não varrer a lista inteira. Ctrl+roda: tamanho do cartão, como o zoom em todo o Windows.
        """
        dy = event.angleDelta().y()
        if not dy:
            return super().wheelEvent(event)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._wheel_acc += dy / 120.0
            notches = int(self._wheel_acc)
            if notches:
                self._wheel_acc -= notches
                self.scale_changed.emit(max(MIN_SCALE, min(MAX_SCALE, round(self._scale + notches * SCALE_STEP, 3))))
            event.accept()
            return
        if len(self.city_names) < 2:
            event.ignore()
            return
        self._wheel_acc += dy / 120.0
        if abs(self._wheel_acc) < WHEEL_THRESHOLD:
            event.accept()
            return
        direction = 1 if self._wheel_acc < 0 else -1
        self._wheel_acc = 0.0
        now = time.monotonic()
        if now - self._last_city_step >= CITY_STEP_COOLDOWN_S:
            self._last_city_step = now
            self.city_step.emit(direction)
        event.accept()

    # --- Menu de contexto ---

    def contextMenuEvent(self, event):
        theme = resolve_theme(config_manager.get_hub_theme("system"))
        menu = FluentMusicMenu(parent=self, theme=theme)

        remembered = bool(config_manager.get_weather("remember_position", False))
        bar_items = [
            ActionBarItem(
                key="refresh",
                icon="refresh",
                tooltip=t("weather_menu_refresh"),
                spin_on_click=True,
                on_trigger=self.refresh_requested.emit,
            ),
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
            *anchor_bar_items(self),
        ]
        menu.add_action_bar(bar_items)

        city_menu = FluentMusicMenu(t("weather_menu_city"), menu, theme=theme)
        for i, name in enumerate(self.city_names):
            act = QAction(name, self)
            city_menu.set_trailing_check(act, i == self.state.city_index)
            act.triggered.connect(lambda checked=False, k=i: self.city_selected.emit(k))
            city_menu.addAction(act)
        if self.city_names:
            city_menu.addSeparator()
        act_manage = QAction(t("weather_menu_manage_cities"), self)
        act_manage.triggered.connect(self.manage_cities_requested.emit)
        city_menu.addAction(act_manage)
        menu.addMenu(city_menu)

        unit = config_manager.get_weather("units", "c")
        units_menu = FluentMusicMenu(t("weather_menu_units"), menu, theme=theme)
        for key, label in (("c", "°C"), ("f", "°F")):
            act = QAction(label, self)
            units_menu.set_trailing_check(act, unit == key)
            act.triggered.connect(lambda checked=False, k=key: self.units_changed.emit(k))
            units_menu.addAction(act)
        menu.addMenu(units_menu)

        if dev_tools_enabled() and self.state.days:
            menu.addSeparator()
            preview_menu = FluentMusicMenu(t("weather_menu_preview"), menu, theme=theme)
            current = self.state.days[self.state.selected].condition
            for key in cond.ALL_CONDITIONS:
                label = t(f"weather_cond_{cond.name_key(key)}")
                if key in cond.DAY_OF:
                    label += " " + t("weather_menu_night_suffix")
                act = QAction(label, self)
                preview_menu.set_trailing_check(act, key == current)
                act.triggered.connect(lambda checked=False, k=key: self.preview_condition_requested.emit(k))
                preview_menu.addAction(act)
            menu.addMenu(preview_menu)

        menu.addSeparator()
        act_configure = QAction(t("menu_configure_widget"), self)
        act_configure.triggered.connect(self.configure_requested.emit)
        menu.addAction(act_configure)
        act_close = QAction(t("menu_close_widget"), self)
        act_close.triggered.connect(self.close_requested.emit)
        menu.addAction(act_close)
        menu.exec(event.globalPos())
