"""Modelo de um dispositivo com bateria, comum a todas as fontes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

KIND_MOUSE = "mouse"
KIND_KEYBOARD = "keyboard"
KIND_CONTROLLER = "controller"
KIND_HEADSET = "headset"
KIND_PHONE = "phone"
KIND_OTHER = "other"

# Ordem em que os tipos aparecem no cartão (depois, pelo nome)
KIND_ORDER = (KIND_MOUSE, KIND_KEYBOARD, KIND_CONTROLLER, KIND_HEADSET, KIND_PHONE, KIND_OTHER)


@dataclass(frozen=True)
class BatteryDevice:
    id: str                         # estável entre leituras (fonte + serial/índice)
    name: str                       # "MX Master 3S", "DualSense 2"
    kind: str                       # KIND_*
    percent: Optional[float]        # 0..100; None = o dispositivo está ligado mas não informou a carga
    charging: bool = False
    approximate: bool = False       # a fonte só dá faixas (XInput, níveis da Logitech)
    source: str = ""                # "xinput", "sony", "switch", "logitech", "vxe", "ajazz"

    def sort_key(self) -> tuple:
        kind = KIND_ORDER.index(self.kind) if self.kind in KIND_ORDER else len(KIND_ORDER)
        return (kind, self.name.casefold(), self.id)


def sort_devices(devices) -> list[BatteryDevice]:
    return sorted(devices, key=lambda d: d.sort_key())
