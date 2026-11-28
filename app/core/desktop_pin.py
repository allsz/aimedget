"""
DesktopPinMixin - "Fixar na área de trabalho" para widgets que não são FloatingCard (Música e Timer).

Clima e Desempenho já tinham a opção (em `FloatingCard`). Sem ela, um grupo ancorado com a Música ou o Timer ficava
com camadas misturadas: um membro por cima de tudo e o resto atrás das janelas. Com a opção em todos os widgets, o
grupo sempre tem uma camada só, e o anchor leva todos juntos (ver `AnchorManager._adopt_layer`).

Mesmas peças do FloatingCard:
- `desktop_layer.apply_layer` ao mostrar e ao trocar (logo acima do desktop, ou sempre no topo);
- `DesktopPinGuard` mantém o widget fixado no lugar depois do Win+D;
- o gancho de WM_WINDOWPOSCHANGING (`nativeEvent`) impede que um `raise_()` o tire do nível do desktop;
- a troca acontece no meio da onda de pontos que atravessa o cartão (mesmo desenho e tempos do FloatingCard),
  desenhada por uma camada filha por cima do cartão, então nenhuma skin precisa mudar o próprio paintEvent.
  Sem animações do Windows (ou oculto), troca na hora.

Quem usa: chama `_init_desktop_pin(enabled)` no __init__ (depois de setWindowFlags), `_desktop_pin_shown()` no
showEvent, `_desktop_pin_hidden()` no hideEvent, devolve `desktop_pin_native_event(...)` no nativeEvent e declara o
sinal `desktop_mode_changed = Signal(bool)` (pedido do menu; o controller aplica, grava e avisa o Hub).
"""

from __future__ import annotations

import time
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from app.core import desktop_layer, screen_watcher
from app.core.desktop_pin_guard import DesktopPinGuard
from app.core.refresh_rate import refresh_interval_ms
from app.core.widget_animator import animations_enabled
from app.core.frame_clock import FrameTimer

WAVE_DUR = 0.750          # os mesmos do FloatingCard (floating_card.py)
WAVE_SWITCH_AT = 0.5


class _PinWaveLayer(QWidget):
    """Filho transparente que desenha a onda de pontos por cima do cartão do widget."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host
        self.progress: Optional[float] = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setGeometry(0, 0, host.width(), host.height())
        host.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(0, 0, self._host.width(), self._host.height())
        return False

    def paintEvent(self, event):
        if self.progress is None:
            return
        from app.core.anchor_manager import _local_card, card_radius
        from app.ui_components.floating_card import paint_dot_wave

        rect = QRectF(_local_card(self._host))
        if rect.width() <= 0 or rect.height() <= 0:
            return
        p = QPainter(self)
        paint_dot_wave(p, rect, self.progress, card_w=rect.width(), card_h=rect.height(),
                       radius=card_radius(self._host))
        p.end()


class DesktopPinMixin:
    _desktop_mode = False
    _wave_t0: Optional[float] = None
    _wave_target: Optional[bool] = None

    def _init_desktop_pin(self, enabled: bool):
        self._desktop_mode = bool(enabled)
        self._wave_t0 = None
        self._wave_target = None
        if desktop_layer.IS_WINDOWS:
            # No Windows a camada é aplicada por desktop_layer (topmost ou logo acima do desktop). A dica do Qt
            # reaplicaria "sempre no topo" a cada show e brigaria com o modo fixado.
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        elif self._desktop_mode:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self._pin_guard = DesktopPinGuard(self)
        self._pin_wave = _PinWaveLayer(self)
        self._pin_clock = FrameTimer(self)
        self._pin_clock.setTimerType(Qt.TimerType.PreciseTimer)
        self._pin_clock.timeout.connect(self._step_pin_wave)

    # --- Estado ---

    def is_desktop_mode(self) -> bool:
        return self._desktop_mode

    def desktop_mode_target(self) -> bool:
        """A camada para onde o widget vai (durante a onda de pontos a troca ainda não aconteceu)."""
        return self._wave_target if self._wave_target is not None else self._desktop_mode

    def pin_guard(self) -> DesktopPinGuard:
        return self._pin_guard

    def wave_progress(self, now: Optional[float] = None) -> Optional[float]:
        if self._wave_t0 is None:
            return None
        return ((time.perf_counter() if now is None else now) - self._wave_t0) / WAVE_DUR

    # --- Troca ---

    def set_desktop_mode(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self.desktop_mode_target():
            return
        from app.core.anchor_manager import anchor_manager
        anchor_manager().member_layer_changed(self, enabled)   # num grupo, todos mudam de camada juntos
        if self.isVisible() and animations_enabled():
            if self._wave_t0 is None:
                self._wave_t0 = time.perf_counter()
            self._wave_target = enabled
            self._pin_wave.raise_()
            self._pin_wave.show()
            if not self._pin_clock.isActive():
                self._pin_clock.start(refresh_interval_ms(self))
            self._step_pin_wave()
            return
        self._wave_t0 = self._wave_target = None
        self._apply_desktop_mode(enabled)

    def _step_pin_wave(self):
        progress = self.wave_progress()
        if progress is None:
            self._pin_clock.stop()
            return
        if progress >= WAVE_SWITCH_AT and self._wave_target is not None:
            target, self._wave_target = self._wave_target, None
            self._apply_desktop_mode(target)
        if progress >= 1.0:
            self._end_pin_wave()
            return
        self._pin_wave.progress = progress
        self._pin_wave.update()

    def _end_pin_wave(self):
        self._wave_t0 = None
        self._pin_clock.stop()
        self._pin_wave.progress = None
        self._pin_wave.hide()

    def _apply_desktop_mode(self, enabled: bool):
        if enabled == self._desktop_mode:
            return
        self._desktop_mode = enabled
        if not desktop_layer.IS_WINDOWS:
            was_visible = self.isVisible()
            flags = self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags if enabled else flags | Qt.WindowType.WindowStaysOnTopHint)
            if was_visible:
                self.show()
            return
        if self.isVisible():
            desktop_layer.apply_layer(int(self.winId()), enabled)
        self._sync_desktop_pin_guard()

    def _sync_desktop_pin_guard(self):
        if self._desktop_mode and self.isVisible():
            self._pin_guard.start()
        else:
            self._pin_guard.stop()

    # --- Ganchos da janela ---

    def _desktop_pin_shown(self):
        if desktop_layer.IS_WINDOWS:
            desktop_layer.apply_layer(int(self.winId()), self._desktop_mode)
        self._sync_desktop_pin_guard()

    def _desktop_pin_hidden(self):
        if self._wave_target is not None:          # oculto no meio da onda: a troca vale na hora
            target, self._wave_target = self._wave_target, None
            self._apply_desktop_mode(target)
        self._end_pin_wave()
        self._pin_guard.stop()

    def desktop_pin_native_event(self, event_type, message):
        screen_watcher.native_event(self, message)   # troca de monitor (e o diagnóstico, se ligado)
        if self._desktop_mode and desktop_layer.IS_WINDOWS:
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == desktop_layer.WM_WINDOWPOSCHANGING:
                    desktop_layer.on_window_pos_changing(msg.lParam, int(msg.hWnd or 0))
                elif msg.message == desktop_layer.WM_WINDOWPOSCHANGED:
                    desktop_layer.on_window_pos_changed(msg.lParam, int(msg.hWnd or 0))
            except (TypeError, ValueError, OSError):
                pass
        return False, 0
