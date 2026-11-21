"""
Avisos do Windows que valem uma leitura de bateria fora de hora: dispositivo entrou/saiu (WM_DEVICECHANGE) e PC voltou
do sono (WM_POWERBROADCAST). O Windows manda os dois para toda janela de nível superior, então um filtro de eventos
nativos do Qt os vê sem janela extra nem registro.

- `classify()` é puro (testável); o filtro só chama o callback, que deve ser barato (o serviço só marca a rajada).
- Fora do Windows o filtro existe mas nunca dispara.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable, Optional

from PySide6.QtCore import QAbstractNativeEventFilter

WM_DEVICECHANGE = 0x0219
WM_POWERBROADCAST = 0x0218

DBT_DEVNODES_CHANGED = 0x0007
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004

PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

_DEVICE_EVENTS = {DBT_DEVNODES_CHANGED, DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE}
_RESUME_EVENTS = {PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC}


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def last_input_tick() -> Optional[int]:
    """Instante (ms do sistema) da última entrada de mouse/teclado, ou None fora do Windows. Uma chamada barata:
    serve para saber "o usuário mexeu em algo" sem ver cada movimento."""
    if sys.platform != "win32":
        return None
    info = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return int(info.dwTime)


def classify(message: int, wparam: int) -> Optional[str]:
    """"device", "resume" ou None (mensagem que não interessa)."""
    if message == WM_DEVICECHANGE and wparam in _DEVICE_EVENTS:
        return "device"
    if message == WM_POWERBROADCAST and wparam in _RESUME_EVENTS:
        return "resume"
    return None


class SystemEventFilter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32" and bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                msg = wintypes.MSG.from_address(int(message))
                reason = classify(int(msg.message), int(msg.wParam or 0))
            except (ValueError, TypeError, OSError):
                reason = None
            if reason:
                self._callback(reason)
        return False, 0
