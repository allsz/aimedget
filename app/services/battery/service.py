"""
BatteryService - lê as fontes numa thread de fundo e entrega a lista ao widget.

- Só roda com o widget na tela (start/stop); a primeira leitura é imediata, depois a cada `INTERVAL_S`.
- Um dispositivo que some numa leitura fica por mais `GRACE_POLLS` leituras com o último valor: um mouse que dormiu
  não pisca para fora e para dentro do cartão. Depois disso ele sai (com animação, no cartão).
- Cada fonte é isolada: se uma falhar, as outras continuam.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from app.services.battery import gaming_input, hid_win, logitech, sony, switch_pro, vxe, xinput
from app.services.battery.models import BatteryDevice, sort_devices

log = logging.getLogger(__name__)

INTERVAL_S = 60.0
GRACE_POLLS = 2


MICROSOFT_VID = 0x045E

# Fonte -> fabricante dos controles que ela já entrega (a leitura do Windows pula esses, para não duplicar)
CLAIM_VENDOR = {"xinput": MICROSOFT_VID, "sony": sony.SONY_VID, "switch": switch_pro.NINTENDO_VID}


def claimed_by_vendor(devices: list[BatteryDevice]) -> dict[int, int]:
    claimed: dict[int, int] = {}
    for d in devices:
        vid = CLAIM_VENDOR.get(d.source)
        if vid is not None:
            claimed[vid] = claimed.get(vid, 0) + 1
    return claimed


def read_all_sources() -> list[BatteryDevice]:
    devices: list[BatteryDevice] = []
    try:
        devices += xinput.read_devices()
    except Exception:  # noqa: BLE001 - uma fonte quebrada não derruba as outras
        log.exception("battery: xinput")
    try:
        hids = hid_win.enumerate_hid({sony.SONY_VID, logitech.LOGI_VID, switch_pro.NINTENDO_VID, vxe.VXE_VID,
                                      MICROSOFT_VID})
    except Exception:  # noqa: BLE001
        log.exception("battery: enumerate")
        hids = []
    for name, fn in (("sony", sony.read_devices), ("switch", switch_pro.read_devices),
                     ("logitech", logitech.read_devices), ("vxe", vxe.read_devices)):
        try:
            devices += fn(hids)
        except Exception:  # noqa: BLE001
            log.exception("battery: %s", name)
    try:
        devices += gaming_input.read_devices(hids, claimed_by_vendor(devices))
    except Exception:  # noqa: BLE001
        log.exception("battery: gaming")
    return devices


class DeviceTracker:
    """Junta leituras sucessivas aplicando a carência para quem sumiu (sem Qt, testável)."""

    def __init__(self, grace: int = GRACE_POLLS):
        self.grace = grace
        self._last: dict[str, BatteryDevice] = {}
        self._missed: dict[str, int] = {}

    def update(self, reading: list[BatteryDevice]) -> list[BatteryDevice]:
        now = {d.id: d for d in reading}
        for dev_id in list(self._last):
            if dev_id in now:
                continue
            self._missed[dev_id] = self._missed.get(dev_id, 0) + 1
            if self._missed[dev_id] > self.grace:
                del self._last[dev_id]
                del self._missed[dev_id]
        for dev_id, dev in now.items():
            self._last[dev_id] = dev
            self._missed.pop(dev_id, None)
        return sort_devices(self._last.values())


class BatteryService(QObject):
    devices_updated = Signal(list)    # list[BatteryDevice], já ordenada

    def __init__(self, parent=None, reader: Optional[Callable[[], list]] = None, interval_s: float = INTERVAL_S):
        super().__init__(parent)
        self._reader = reader or read_all_sources
        self._interval = float(interval_s)
        self._tracker = DeviceTracker()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_devices: list[BatteryDevice] = []

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.is_running():
                self._wake.set()
                return
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(target=self._run, name="BatteryService", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def refresh(self):
        """Lê agora (sem esperar o intervalo)."""
        if self.is_running():
            self._wake.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                reading = self._reader()
            except Exception:  # noqa: BLE001
                log.exception("battery: read")
                reading = []
            if self._stop.is_set():
                break
            devices = self._tracker.update(reading)
            self.last_devices = devices
            self.devices_updated.emit(devices)
            self._wake.wait(self._interval)
            self._wake.clear()
