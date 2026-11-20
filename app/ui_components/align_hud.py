"""
Floating Aligner HUD + Jelly Slider para alinhamento preciso e igualação de tamanho entre widgets.

- Aberto pelo botão mínimo "Alinhar" na barra superior Fluent Rail do menu de contexto de qualquer widget.
- Cápsula superior com ícones simples e arredondados (Pilha Esquerda / Centro / Direita, Linha Topo / Meio,
  Igualar Tamanho com animação ponto -> barrinha, e Concluir ✓), com pílula de hover de duas molas (TabPill).
- Logo abaixo da cápsula: o Jelly Slider (0..32 px) controlando a folga entre os widgets em tempo real.
"""

from __future__ import annotations

import time
import weakref
from typing import Optional

import shiboken6
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

from app.core import anchor_geometry as geo
from app.core import widget_animator
from app.core.anchor_manager import anchor_manager, card_rect
from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.osd_anchor import compute_osd_placement
from app.core.refresh_rate import refresh_interval_ms
from app.core.screen_metrics import get_screen_for_widget
from app.hub.theme import HubTheme, resolve_theme
from app.ui_components.jelly_slider import JellySlider
from app.ui_components.menu_action_bar import ActionBarItem, FluentActionBar
from app.core.frame_clock import FrameTimer

APPEAR_DUR_S = 0.145   # entrada rápida e sutil (~145 ms)
DISMISS_DUR_S = 0.110  # saída rápida (~110 ms)
SLIDE_PX = 8.0         # deslocamento sutil ao aparecer/sumir


class _HudCapsule(QWidget):
    """Cápsula arredondada com fundo e borda do tema do Hub."""

    def __init__(self, theme: HubTheme, radius: float = 12.0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = theme
        self._radius = radius

    def set_theme(self, theme: HubTheme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        bg = QColor(self._theme.menu_bg)
        bg.setAlpha(242)
        p.setBrush(bg)
        p.setPen(QPen(QColor(self._theme.line), 1.0))
        p.drawRoundedRect(r, self._radius, self._radius)
        p.end()


class AlignHudWindow(QWidget):
    """HUD flutuante de alinhamento + Jelly Slider logo abaixo."""

    def __init__(self, ref_widget: QWidget, theme: Optional[HubTheme] = None):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)

        self._ref_widget = weakref.ref(ref_widget)
        self._theme = theme or resolve_theme(config_manager.get_hub_theme("system"))
        self._axis, self._align, self._match_size, self._gap = self._load_initial_state(ref_widget)
        self._drag_offset: Optional[QPoint] = None
        self._placement_side: str = "right"
        self._rest_pos: QPoint = QPoint(0, 0)
        self._closing: bool = False
        self._app_filter_installed: bool = False

        # Animação sutil e rápida de entrada/saída na taxa do monitor (até 240 Hz)
        self._anim_dir: int = 0   # +1 aparecendo, -1 sumindo, 0 parado
        self._anim_t0: float = 0.0
        self._anim_timer = FrameTimer(self)
        self._anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._anim_timer.timeout.connect(self._tick_anim)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # 1. Cápsula superior: barra Fluent Rail com ações de alinhamento + Igualar Tamanho + Concluir
        self._toolbar_capsule = _HudCapsule(self._theme, radius=12.0, parent=self)
        tb_layout = QHBoxLayout(self._toolbar_capsule)
        tb_layout.setContentsMargins(6, 4, 6, 4)
        tb_layout.setSpacing(0)

        items = [
            ActionBarItem("stack_left", "align_left", t("align_stack_left"), toggle=True,
                          checked=(self._axis == "y" and self._align == 0),
                          on_trigger=lambda _c: self._apply_layout("y", 0)),
            ActionBarItem("stack_center", "align_center", t("align_stack_center"), toggle=True,
                          checked=(self._axis == "y" and self._align == 2),
                          on_trigger=lambda _c: self._apply_layout("y", 2)),
            ActionBarItem("stack_right", "align_right", t("align_stack_right"), toggle=True,
                          checked=(self._axis == "y" and self._align == 1),
                          on_trigger=lambda _c: self._apply_layout("y", 1)),
            ActionBarItem("row_top", "row_top", t("align_row_top"), toggle=True,
                          checked=(self._axis == "x" and self._align == 0),
                          on_trigger=lambda _c: self._apply_layout("x", 0)),
            ActionBarItem("row_mid", "row_mid", t("align_row_mid"), toggle=True,
                          checked=(self._axis == "x" and self._align == 2),
                          on_trigger=lambda _c: self._apply_layout("x", 2)),
            ActionBarItem("match_size", "match_size", t("align_match_size"), toggle=True,
                          checked=self._match_size,
                          on_trigger=self._on_match_size_toggled),
            ActionBarItem("done", "check", t("align_done"), toggle=False,
                          on_trigger=self.dismiss),
        ]
        self._bar = FluentActionBar(items, theme=self._theme, parent=self._toolbar_capsule)
        tb_layout.addWidget(self._bar)
        root.addWidget(self._toolbar_capsule)

        # 2. Jelly Slider logo abaixo da barra flutuante (controla o espaçamento 0..32 px em tempo real)
        self._slider_capsule = _HudCapsule(self._theme, radius=12.0, parent=self)
        sl_layout = QVBoxLayout(self._slider_capsule)
        sl_layout.setContentsMargins(8, 0, 8, 6)
        sl_layout.setSpacing(0)
        self._slider = JellySlider(
            minimum=0,
            maximum=32,
            value=self._gap,
            step_minor=4,
            step_major=8,
            theme=self._theme,
            parent=self._slider_capsule,
        )
        self._slider.live_value_changed.connect(self._on_live_gap_changed)
        self._slider.value_changed.connect(self._on_gap_changed)
        self._slider.interaction_finished.connect(self._on_gap_committed)
        sl_layout.addWidget(self._slider)
        root.addWidget(self._slider_capsule)

        self.setFixedWidth(316)
        self.adjustSize()
        self._position_near_ref()

    @staticmethod
    def _load_initial_state(ref_widget: QWidget) -> tuple[Optional[str], Optional[int], bool, int]:
        """
        Estado inicial dos botões. Um layout só aparece marcado se o grupo do widget está MESMO assim (lido da árvore);
        sem grupo nada vem marcado, para o HUD não sugerir um alinhamento que ainda não existe. "Igualar tamanho" e a
        folga vêm da última escolha.
        """
        prefs = config_manager.get_anchor("align_prefs", {})
        if not isinstance(prefs, dict):
            prefs = {}
        mgr = anchor_manager()
        axis = align = None
        match_size = bool(prefs.get("match_size", False))
        gap = int(round(mgr.current_gap_of(ref_widget)))
        if isinstance(prefs.get("gap"), (int, float)) and not mgr.is_grouped(ref_widget):
            gap = max(0, min(32, int(round(prefs["gap"]))))
        key = mgr._key(ref_widget)
        if key is not None and mgr.is_grouped(ref_widget):
            tree = mgr.group_of(key).tree
            if isinstance(tree, geo.Join) and tree.ax in ("x", "y") and tree.ai in (0, 1, 2):
                axis, align = tree.ax, tree.ai
                gap = max(0, min(32, int(round(tree.gap))))
        return axis, align, match_size, gap

    def _save_prefs(self) -> None:
        config_manager.set_anchor(
            "align_prefs",
            {
                "axis": self._axis,
                "align": self._align,
                "match_size": self._match_size,
                "gap": int(self._gap),
            },
        )

    @property
    def action_bar(self) -> FluentActionBar:
        return self._bar

    @property
    def slider(self) -> JellySlider:
        return self._slider

    def _ref(self) -> Optional[QWidget]:
        w = self._ref_widget()
        return w if (w is not None and shiboken6.isValid(w)) else None

    def _sync_layout_buttons(self) -> None:
        mapping = {
            "stack_left": ("y", 0),
            "stack_center": ("y", 2),
            "stack_right": ("y", 1),
            "row_top": ("x", 0),
            "row_mid": ("x", 2),
        }
        cur = (self._axis, self._align)
        for key, pair in mapping.items():
            btn = self._bar.button(key)
            if btn is not None:
                btn.set_active(pair == cur, animated=True)

    def _apply_layout(self, axis: str, align: int) -> None:
        self._axis = axis
        self._align = align
        self._sync_layout_buttons()
        self._save_prefs()
        w = self._ref()
        if w is not None:
            anchor_manager().align_widgets(
                w,
                axis=axis,
                align=align,
                gap=float(self._gap),
                match_size=self._match_size,
            )

    def _on_match_size_toggled(self, checked: bool) -> None:
        self._match_size = bool(checked)
        w = self._ref()
        if w is None or not checked:
            self._save_prefs()      # desligar só vale para os próximos alinhamentos: não move nem junta nada
            return
        # Se o usuário ainda não escolheu um eixo, assume empilhamento alinhado à esquerda (Clima + Perf)
        if self._axis is None or self._align is None:
            self._axis, self._align = "y", 0
            self._sync_layout_buttons()
        self._save_prefs()
        anchor_manager().align_widgets(
            w,
            axis=self._axis,
            align=self._align,
            gap=float(self._gap),
            match_size=self._match_size,
        )

    def _on_live_gap_changed(self, gap: float) -> None:
        """Atualiza a folga quadro a quadro na taxa do monitor (até 240 Hz), sem gravar em disco durante o arraste."""
        self._gap = int(round(gap))
        w = self._ref()
        if w is None:
            return
        mgr = anchor_manager()
        if mgr.is_grouped(w):
            mgr.set_group_gap(w, float(gap), save=False)
        # Sem grupo, a folga só fica guardada para o próximo alinhamento: mexer no slider nunca junta widgets.

    def _on_gap_changed(self, gap: int) -> None:
        """Garante compatibilidade para teclado e emissões diretas de `value_changed(int)`."""
        self._on_live_gap_changed(float(gap))

    def _on_gap_committed(self) -> None:
        """Ao soltar o slider, grava a folga final, as preferências e as posições lembradas uma única vez."""
        self._save_prefs()
        w = self._ref()
        if w is not None:
            anchor_manager().commit_group_layout(w)

    def _related_stack_windows(self) -> set[QWidget]:
        """Janelas pertencentes à pilha/grupo relacionado (clicar nelas mantém o HUD aberto)."""
        allowed: set[QWidget] = {self}
        w = self._ref()
        if w is None:
            return allowed
        allowed.add(w)
        mgr = anchor_manager()
        key = mgr._key(w)
        if key is not None:
            for k in mgr.group_of(key).keys():
                mw = mgr.window(k)
                if mw is not None:
                    allowed.add(mw)
        return allowed

    def _is_in_related_stack(self, target: Optional[QWidget]) -> bool:
        if target is None:
            return False
        top = target.window() if hasattr(target, "window") else target
        return top in self._related_stack_windows()

    def _anchor_bounds_qrect(self, w: QWidget) -> QRect:
        """Retângulo envolvente do widget (ou de todo o grupo ancorado) para o HUD abrir sempre fora dele."""
        mgr = anchor_manager()
        rects = [card_rect(w)]
        key = mgr._key(w)
        if key is not None:
            g = mgr.group_of(key)
            for k in g.keys():
                mw = mgr.window(k)
                if mw is not None and mw is not w and mw.isVisible():
                    rects.append(card_rect(mw))
        left = int(round(min(r.l for r in rects)))
        top = int(round(min(r.t for r in rects)))
        right = int(round(max(r.r for r in rects)))
        bottom = int(round(max(r.b for r in rects)))
        return QRect(left, top, max(1, right - left), max(1, bottom - top))

    def _position_near_ref(self) -> None:
        w = self._ref()
        if w is None:
            return
        anchor = self._anchor_bounds_qrect(w)
        screen = get_screen_for_widget(w)
        avail = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        pos, side = compute_osd_placement(anchor, self.size(), avail, gap=12, margin=8)
        self._placement_side = side
        self._rest_pos = pos
        self.move(pos)

    def _slide_vector(self) -> tuple[float, float]:
        """Vetor de origem sutil: nasce um pouco mais perto do widget e desliza para o lugar."""
        return {
            "right": (-SLIDE_PX, 0.0),
            "left": (SLIDE_PX, 0.0),
            "below": (0.0, -SLIDE_PX),
            "above": (0.0, SLIDE_PX),
        }.get(self._placement_side, (0.0, SLIDE_PX * 0.75))

    def present(self) -> None:
        """Exibe o HUD com fade + deslize sutil e rápido (ou instantâneo sem animações do Windows)."""
        self._closing = False
        self._install_outside_filter()
        if not widget_animator.animations_enabled():
            self.setWindowOpacity(1.0)
            self.move(self._rest_pos)
            self.show()
            self.raise_()
            self.activateWindow()
            return
        dx, dy = self._slide_vector()
        self.setWindowOpacity(0.0)
        self.move(int(round(self._rest_pos.x() + dx)), int(round(self._rest_pos.y() + dy)))
        self.show()
        self.raise_()
        self.activateWindow()
        self._anim_dir = 1
        self._anim_t0 = time.perf_counter()
        self._anim_timer.setInterval(refresh_interval_ms(self))
        self._anim_timer.start()

    def dismiss(self) -> None:
        """Fecha o HUD com fade + recuo sutil e rápido."""
        if self._closing:
            return
        self._closing = True
        self._remove_outside_filter()
        if not widget_animator.animations_enabled() or not self.isVisible():
            self._anim_timer.stop()
            super().close()
            return
        self._rest_pos = self.pos()
        self._anim_dir = -1
        self._anim_t0 = time.perf_counter()
        self._anim_timer.setInterval(refresh_interval_ms(self))
        self._anim_timer.start()

    def _tick_anim(self) -> None:
        dur = APPEAR_DUR_S if self._anim_dir > 0 else DISMISS_DUR_S
        p = min(1.0, (time.perf_counter() - self._anim_t0) / max(dur, 1e-4))
        dx, dy = self._slide_vector()

        if self._anim_dir > 0:
            eased = 1.0 - (1.0 - p) ** 3   # ease-out cúbico
            self.setWindowOpacity(eased)
            rem = 1.0 - eased
            self.move(
                int(round(self._rest_pos.x() + dx * rem)),
                int(round(self._rest_pos.y() + dy * rem)),
            )
            if p >= 1.0:
                self._anim_timer.stop()
                self._anim_dir = 0
                self.setWindowOpacity(1.0)
                self.move(self._rest_pos)
        else:
            eased = p * p * p              # ease-in cúbico
            self.setWindowOpacity(1.0 - eased)
            self.move(
                int(round(self._rest_pos.x() + dx * eased)),
                int(round(self._rest_pos.y() + dy * eased)),
            )
            if p >= 1.0:
                self._anim_timer.stop()
                self._anim_dir = 0
                super().close()

    def _install_outside_filter(self) -> None:
        app = QApplication.instance()
        if app is not None and not self._app_filter_installed:
            app.installEventFilter(self)
            self._app_filter_installed = True

    def _remove_outside_filter(self) -> None:
        app = QApplication.instance()
        if app is not None and self._app_filter_installed:
            app.removeEventFilter(self)
            self._app_filter_installed = False

    def _check_active_window(self) -> None:
        if self._closing or not self.isVisible():
            return
        active = QApplication.activeWindow()
        if not self._is_in_related_stack(active):
            self.dismiss()

    def eventFilter(self, obj, event) -> bool:
        if not self._closing and self.isVisible():
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress:
                if isinstance(obj, QWidget) and not self._is_in_related_stack(obj):
                    self.dismiss()
            elif etype == QEvent.Type.ApplicationDeactivate:
                self.dismiss()
            elif etype == QEvent.Type.WindowDeactivate:
                if isinstance(obj, QWidget) and obj in self._related_stack_windows():
                    QTimer.singleShot(0, self._check_active_window)
        return False

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if not self._closing and self.isVisible() and event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow():
                self._check_active_window()

    def closeEvent(self, event) -> None:
        self._anim_timer.stop()
        self._remove_outside_filter()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self._rest_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(self._rest_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


_active_hud: Optional[AlignHudWindow] = None


def open_align_hud(ref_widget: QWidget) -> AlignHudWindow:
    """Abre (ou reposiciona) o HUD flutuante de alinhamento para `ref_widget`."""
    global _active_hud
    if _active_hud is not None and shiboken6.isValid(_active_hud):
        _active_hud._remove_outside_filter()
        _active_hud.close()
        _active_hud.deleteLater()
    hud = AlignHudWindow(ref_widget)
    _active_hud = hud
    hud.present()
    return hud
