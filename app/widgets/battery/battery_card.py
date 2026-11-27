"""
BatteryCard - Janela flutuante do Battery Widget, sobre `FloatingCard`.

Diferente dos outros cartões, o tamanho é LIVRE: arrastar o canto muda largura e altura separadamente (não a
escala), e o layout se refaz na hora (anéis deslizam). O cartão nunca fica menor do que os dispositivos pedem: se
não couberem com anel de 52 px, ele cresce (com mola). Num grupo ancorado, os vizinhos acompanham a cada quadro.
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QPainter

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
    CHARGE_SPRING,
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
    Spring,
)


_theme_cache = [0.0, THEME_DARK, None]   # (quando, modo do cartão, cor de destaque do app)


def card_theme() -> str:
    """O cartão segue o tema do Hub: Claro, Escuro ou True Dark (preto). Cache de 0,5 s: a pintura roda por quadro e
    o modo "sistema" consulta o registro do Windows."""
    now = time.monotonic()
    if now - _theme_cache[0] < 0.5:
        return _theme_cache[1]
    pref = config_manager.get_hub_theme("system")
    hub = resolve_theme(pref)
    if pref == "true_dark":
        theme = THEME_BLACK
    else:
        theme = THEME_DARK if hub.is_dark else THEME_LIGHT
    _theme_cache[0], _theme_cache[1], _theme_cache[2] = now, theme, hub.accent
    return theme


def card_accent() -> QColor | None:
    """Cor do anel: a de destaque do app com "Seguir cor de destaque" ligado; senão None (o verde da paleta)."""
    if not config_manager.get_battery("follow_accent", False):
        return None
    card_theme()   # atualiza o cache, se vencido
    return QColor(_theme_cache[2]) if _theme_cache[2] else None


def invalidate_card_theme():
    _theme_cache[0] = 0.0


class BatteryCard(FloatingCard):
    ANCHOR_KEY = "battery"

    option_requested = Signal(str, str)        # (chave, valor) vindo do menu
    size_committed = Signal(float, float)      # tamanho escolhido no canto (soltou) ou por "redefinir"
    refresh_requested = Signal()

    def __init__(self, desktop_mode: bool = False, size=lay.DEFAULT_SIZE, options: Optional[Options] = None,
                 scale: float = 1.0):
        w, h = (float(size[0]), float(size[1])) if size else lay.DEFAULT_SIZE
        self.state = BatteryState(base_w=w, base_h=h, options=options or Options(), animated=animations_enabled())
        self._last_tick = 0.0
        self._free_resize: Optional[tuple] = None
        self._rest_origin: Optional[tuple[float, float]] = None   # canto do cartão sem overflow (px de tela)
        self._glide_x: Optional[Spring] = None
        self._glide_y: Optional[Spring] = None
        cw, ch = self.state.card_size()
        super().__init__(scale=scale, desktop_mode=desktop_mode, card_w=cw, card_h=ch)

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
        gliding = False
        if self._glide_x is not None and self._glide_y is not None:
            self._glide_x.step(dt)
            self._glide_y.step(dt)
            if self._glide_x.settled() and self._glide_y.settled():
                self._glide_x.snap()
                self._glide_y.snap()
                self._apply_window_size(self.width(), self.height(), card_l=self._glide_x.x, card_t=self._glide_y.x)
                self._glide_x = self._glide_y = None
            else:
                self._apply_window_size(self.width(), self.height(), card_l=self._glide_x.x, card_t=self._glide_y.x)
                gliding = True
        return busy or gliding

    def _card_needs_frames(self, now: float) -> bool:
        # A bolinha de carregando pulsa: só enquanto algum carrega e com animações ligadas (quadros de 33 ms)
        return self.state.animated and self.state.any_charging()

    def _apply_window_size(self, new_w: int, new_h: int, card_l: Optional[float] = None, card_t: Optional[float] = None):
        """Aplica tamanho (e posição, se dada) de uma vez só para evitar tremulação de 1 quadro ao crescer p/ esquerda/cima."""
        if card_l is not None and card_t is not None:
            r = self.card_rect()
            wx = int(round(card_l - r.x()))
            wy = int(round(card_t - r.y()))
            self.setMinimumSize(new_w, new_h)
            self.setMaximumSize(new_w, new_h)
            self.setGeometry(wx, wy, new_w, new_h)
            animator = getattr(self, "animator", None)
            if animator is not None:
                animator.move_rest(QPoint(wx, wy))
        else:
            self.setFixedSize(new_w, new_h)
        self._shadows = {}

    @staticmethod
    def _reachable_bounds(box: tuple[float, float, float, float], allow_overflow: bool) -> Optional[tuple[float, float, float, float]]:
        cx, cy = int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2)
        screen = QGuiApplication.screenAt(QPoint(cx, cy)) or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        a = screen.availableGeometry()
        cur = (float(a.x()), float(a.y()), float(a.x() + a.width()), float(a.y() + a.height()))
        screens = []
        for s in QGuiApplication.screens():
            g = s.availableGeometry()
            screens.append((float(g.x()), float(g.y()), float(g.x() + g.width()), float(g.y() + g.height())))
        return lay.reachable_bounds(box, cur, screens, allow_overflow=allow_overflow)

    def _sync_size(self, force_reposition: bool = False):
        w, h = self.state.card_size()
        size_changed = not (abs(w - self._card_w) < 0.35 and abs(h - self._card_h) < 0.35)
        if not size_changed and not force_reposition:
            return
        self._card_w, self._card_h = w, h
        m = 2.0 * self.margin()
        new_w = int(round(w * self._scale + m))
        new_h = int(round(h * self._scale + m))
        win_size_changed = (self.width() != new_w or self.height() != new_h)

        # Arraste manual do canto: mantém canto superior esquerdo fixo (sem empurrão de borda)
        if self._free_resize is not None or not self.isVisible():
            if win_size_changed:
                self._apply_window_size(new_w, new_h)
                if self.isVisible():
                    anchor_manager().member_resized(self)
            return

        s = self._scale or 1.0
        base_w_px = self.state.base_w * s
        base_h_px = self.state.base_h * s
        cur_w_px = w * s
        cur_h_px = h * s
        dw = max(0.0, cur_w_px - base_w_px)
        dh = max(0.0, cur_h_px - base_h_px)
        pivot = lay.expand_pivot(self.state.options.expand)
        allow_overflow = bool(self.state.options.overflow)

        mgr = anchor_manager()
        if mgr.is_grouped(self):
            self._rest_origin = None
            self._glide_x = self._glide_y = None
            if win_size_changed:
                self._apply_window_size(new_w, new_h)
            mgr.member_auto_resized(self, base_w_px, base_h_px, pivot, allow_overflow=allow_overflow)
            return

        # Cartão solto (sem grupo): pivô do D-pad + limite de borda/vazio + deslize suave (mola crítica)
        if self._rest_origin is None and (dw > 0.5 or dh > 0.5):
            r = self.card_rect()
            p = self.rest_pos()
            self._rest_origin = (float(p.x() + r.x()), float(p.y() + r.y()))

        if self._rest_origin is not None:
            rest_l, rest_t = self._rest_origin
            tl = rest_l + dw * pivot[0]
            tt = rest_t + dh * pivot[1]
            cand = (tl, tt, tl + cur_w_px, tt + cur_h_px)
            bounds = self._reachable_bounds(cand, allow_overflow=allow_overflow)
            if bounds is not None:
                al, at, ar_b, ab = bounds
                pad_l = min(12.0, max(0.0, rest_l - al))
                pad_t = min(12.0, max(0.0, rest_t - at))
                pad_r = min(12.0, max(0.0, ar_b - (rest_l + base_w_px)))
                pad_b = min(12.0, max(0.0, ab - (rest_t + base_h_px)))
                padded = (al + pad_l, at + pad_t, ar_b - pad_r, ab - pad_b)
                cdx, cdy = lay.clamp_shift(cand, padded)
                tl += cdx
                tt += cdy
            r = self.card_rect()
            p = self.rest_pos()
            cur_l, cur_t = float(p.x() + r.x()), float(p.y() + r.y())
            if self._live() and (abs(cur_l - tl) > 0.5 or abs(cur_t - tt) > 0.5):
                if self._glide_x is None or self._glide_y is None:
                    self._glide_x = Spring(cur_l, CHARGE_SPRING, tol=0.35)
                    self._glide_y = Spring(cur_t, CHARGE_SPRING, tol=0.35)
                self._glide_x.t, self._glide_y.t = tl, tt
                if win_size_changed:
                    self._apply_window_size(new_w, new_h, card_l=self._glide_x.x, card_t=self._glide_y.x)
                self.kick()
            else:
                self._glide_x = self._glide_y = None
                self._apply_window_size(new_w, new_h, card_l=tl, card_t=tt)
            if dw <= 0.5 and dh <= 0.5 and self.state.W.settled() and self.state.H.settled() and self._glide_x is None:
                self._rest_origin = None
        elif win_size_changed:
            self._apply_window_size(new_w, new_h)

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
            self._last_tick = self.now()
            if not self.state.animated:
                self.state.step(0.0)
            self._sync_size(force_reposition=True)
            self.kick()
            self.update()

    def set_base_size(self, w: float, h: float):
        self.state.animated = self._live()
        self.state.set_base_size(w, h)
        self._refresh()

    def base_size(self) -> tuple[float, float]:
        return self.state.base_w, self.state.base_h

    def is_scale_animating(self) -> bool:
        """Para o alinhador do anchor: o TAMANHO do cartão ainda está assentando. Só as molas de largura/altura contam;
        o arco enchendo, a face do hover ou a bolinha de carregando não seguram o alinhamento. A escala (controle de
        Tamanho do Hub) também conta enquanto a mola dela anda."""
        return self._scale_animator.is_active() or not (self.state.W.settled() and self.state.H.settled())

    def match_card_size(self, target_w: Optional[float] = None, target_h: Optional[float] = None,
                        animate: bool = False):
        """Alinhar tamanho com um vizinho (anchor): muda a largura OU a altura escolhida, nunca a escala. O alvo vem em
        px de tela (o cartão do vizinho); o formato é guardado sem a escala, então divide por ela."""
        s = self._scale or 1.0
        w = float(target_w) / s if target_w is not None else self.state.base_w
        h = float(target_h) / s if target_h is not None else self.state.base_h
        self.state.animated = animate and self._live()
        self.state.set_base_size(w, h)
        self._refresh()
        self.size_committed.emit(self.state.base_w, self.state.base_h)

    # --- Pintura ---

    def paint_card_content(self, p: QPainter, rect: QRectF, now: float):
        paint_battery_card(p, rect, self.state, theme=card_theme(), now=now, accent=card_accent())

    # --- Canto: tamanho livre ---

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_grip(self._to_card(event.position())):
            self._rest_origin = None
            self._glide_x = self._glide_y = None
            self._free_resize = (event.globalPosition(), self.state.base_w, self.state.base_h)
            self._resize_start = ("free",)      # a alça fica acesa enquanto arrasta
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._rest_origin = None
            self._glide_x = self._glide_y = None
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
        follow = bool(config_manager.get_battery("follow_accent", False))
        act_accent = QAction(t("battery_follow_accent_title"), self)
        menu.set_trailing_check(act_accent, follow)
        act_accent.triggered.connect(
            lambda _c=False: self.option_requested.emit("follow_accent", "off" if follow else "on")
        )
        menu.addAction(act_accent)
        menu.addSeparator()
        act_configure = QAction(t("menu_configure_widget"), self)
        act_configure.triggered.connect(self.configure_requested.emit)
        menu.addAction(act_configure)
        act_close = QAction(t("menu_close_widget"), self)
        act_close.triggered.connect(self.close_requested.emit)
        menu.addAction(act_close)
        menu.exec(event.globalPos())
