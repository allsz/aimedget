import ctypes
from ctypes import c_int, c_short
from PySide6.QtCore import QObject, QTimer, Signal


class KeyLockService(QObject):
    """
    Serviço em background para monitoramento de Caps Lock e Num Lock via Win32 API.
    Segue a diretriz anti-monolito: zero código de UI, emitindo apenas sinais Qt.
    """

    # Emite (nome_da_tecla: str, ativo: bool) -> ex: ("Caps Lock", True)
    keylock_changed = Signal(str, bool)

    VK_CAPITAL = 0x14
    VK_NUMLOCK = 0x90

    def __init__(self, poll_interval_ms: int = 25, parent: QObject | None = None):
        super().__init__(parent)
        self._user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
        if self._user32:
            self._user32.GetKeyState.argtypes = [c_int]
            self._user32.GetKeyState.restype = c_short

        self._caps_on = self.is_caps_lock_on()
        self._num_on = self.is_num_lock_on()

        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._poll_keys)
        self._timer.start()

    def is_caps_lock_on(self) -> bool:
        if not self._user32:
            return False
        try:
            return bool(self._user32.GetKeyState(self.VK_CAPITAL) & 0x0001)
        except Exception:
            return False

    def is_num_lock_on(self) -> bool:
        if not self._user32:
            return False
        try:
            return bool(self._user32.GetKeyState(self.VK_NUMLOCK) & 0x0001)
        except Exception:
            return False

    def _poll_keys(self):
        try:
            caps_now = self.is_caps_lock_on()
            if caps_now != self._caps_on:
                self._caps_on = caps_now
                self.keylock_changed.emit("Caps Lock", caps_now)

            num_now = self.is_num_lock_on()
            if num_now != self._num_on:
                self._num_on = num_now
                self.keylock_changed.emit("Num Lock", num_now)
        except Exception:
            pass
