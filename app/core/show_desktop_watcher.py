"""
ShowDesktopWatcher - sabe quando o Windows está em "Mostrar área de trabalho" (Win+D).

O Windows não avisa isso diretamente. A detecção é a do Rainmeter (System::CheckDesktopState): uma janela-marcador
invisível fica logo acima do desktop; o Win+D traz o desktop para a frente de tudo, e o marcador passa a ficar
ABAIXO dele. A volta é reconhecida quando o marcador fica acima do desktop de novo, ou quando um app de verdade vira
o primeiro plano por cima do desktop (Win+D de novo, ou um app aberto pela barra de tarefas).

Gatilhos: aviso de troca de primeiro plano (com rechecagens logo depois) e uma checagem a cada 250 ms. Só roda
enquanto algum widget pediu (`acquire`/`release`): sem ninguém, nada fica ligado.
"""

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget

from app.core import desktop_layer

POLL_MS = 250
RECHECK_MS = (0, 40, 120, 300)


class ShowDesktopWatcher(QObject):
    active_changed = Signal(bool)   # True = "Mostrar área de trabalho" ligado

    def __init__(self, parent=None):
        super().__init__(parent)
        self._users = 0
        self._active = False
        self._marker: QWidget | None = None
        self._hook: desktop_layer.ForegroundHook | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self.check)

    def is_active(self) -> bool:
        return self._active

    def is_running(self) -> bool:
        return self._timer.isActive()

    def acquire(self):
        self._users += 1
        if self._users == 1:
            self._start()

    def release(self):
        if self._users == 0:
            return
        self._users -= 1
        if self._users == 0:
            self._stop()

    # --- Internos ---

    def _marker_hwnd(self) -> int:
        if self._marker is None:
            # Janela nativa que nunca é mostrada: só ocupa um lugar na pilha (invisível, sem barra de tarefas)
            self._marker = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
            self._marker.setGeometry(-32000, -32000, 1, 1)
        return int(self._marker.winId())

    def _place_marker(self):
        desktop_layer.send_to_desktop_layer(self._marker_hwnd())

    def _start(self):
        if not desktop_layer.IS_WINDOWS:
            return
        self._active = False
        self._place_marker()
        self._hook = desktop_layer.ForegroundHook(self._on_foreground_changed)
        self._timer.start()

    def _stop(self):
        self._timer.stop()
        if self._hook is not None:
            self._hook.close()
            self._hook = None
        if self._active:
            self._active = False
            self.active_changed.emit(False)

    def _on_foreground_changed(self):
        for ms in RECHECK_MS:
            QTimer.singleShot(ms, self, self.check)

    def check(self):
        if not self._timer.isActive():
            return
        marker_below = desktop_layer.is_below_desktop(self._marker_hwnd())
        if not self._active and marker_below:
            self._active = True
            self.active_changed.emit(True)
        elif self._active and (not marker_below or desktop_layer.foreground_is_app_above_desktop()):
            self._active = False
            self._place_marker()   # de volta logo acima do desktop, pronto para o próximo Win+D
            self.active_changed.emit(False)


_watcher: ShowDesktopWatcher | None = None


def show_desktop_watcher() -> ShowDesktopWatcher:
    """Um só vigia para o app inteiro (qualquer widget pode pedir)."""
    global _watcher
    if _watcher is None:
        _watcher = ShowDesktopWatcher()
    return _watcher
