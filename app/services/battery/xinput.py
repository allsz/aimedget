"""
XInput (API documentada da Microsoft): controles compatíveis com Xbox sem fio. A carga vem em 4 faixas
(vazia 0-10%, baixa 10-40%, média 40-70%, cheia 70-100%), então a porcentagem é o meio da faixa e marcada como
aproximada. Controle com fio informa "com fio" e não aparece (não tem bateria).
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from app.services.battery.models import KIND_CONTROLLER, BatteryDevice

BATTERY_DEVTYPE_GAMEPAD = 0
BATTERY_TYPE_ALKALINE = 0x02
BATTERY_TYPE_NIMH = 0x03
LEVEL_PERCENT = {0: 5.0, 1: 25.0, 2: 55.0, 3: 85.0}


class XINPUT_BATTERY_INFORMATION(ctypes.Structure):
    _fields_ = [("BatteryType", ctypes.c_ubyte), ("BatteryLevel", ctypes.c_ubyte)]


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


_dll = None


def _load():
    global _dll
    if _dll is not None:
        return _dll
    _dll = False
    if sys.platform != "win32":
        return _dll
    for name in ("xinput1_4", "xinput9_1_0"):
        try:
            dll = ctypes.WinDLL(name)
            dll.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
            dll.XInputGetState.restype = wintypes.DWORD
            dll.XInputGetBatteryInformation.argtypes = [wintypes.DWORD, ctypes.c_ubyte,
                                                        ctypes.POINTER(XINPUT_BATTERY_INFORMATION)]
            dll.XInputGetBatteryInformation.restype = wintypes.DWORD
            _dll = dll
            break
        except (OSError, AttributeError):
            continue
    return _dll


def battery_from_info(battery_type: int, level: int):
    """(porcentagem, aproximada) ou None quando não há bateria a mostrar (com fio, desconhecida, desligado)."""
    if battery_type not in (BATTERY_TYPE_ALKALINE, BATTERY_TYPE_NIMH):
        return None
    return LEVEL_PERCENT.get(level, None)


def read_devices() -> list[BatteryDevice]:
    dll = _load()
    if not dll:
        return []
    found = []
    for user in range(4):
        state = XINPUT_STATE()
        if dll.XInputGetState(user, ctypes.byref(state)) != 0:
            continue
        info = XINPUT_BATTERY_INFORMATION()
        if dll.XInputGetBatteryInformation(user, BATTERY_DEVTYPE_GAMEPAD, ctypes.byref(info)) != 0:
            continue
        pct = battery_from_info(info.BatteryType, info.BatteryLevel)
        if pct is None:
            continue
        found.append((user, pct))
    out = []
    for user, pct in found:
        name = f"Xbox Controller {user + 1}" if len(found) > 1 else "Xbox Controller"
        out.append(BatteryDevice(id=f"xinput:{user}", name=name, kind=KIND_CONTROLLER, percent=pct,
                                 approximate=True, source="xinput"))
    return out
