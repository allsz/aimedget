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
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from app.services.battery import (
    bluetooth,
    gaming_input,
    hid_win,
    logitech,
    sony,
    switch_pro,
    system_events,
    vxe,
    xinput,
)
from app.services.battery.models import BatteryDevice, sort_devices

log = logging.getLogger(__name__)

INTERVAL_S = 60.0
GRACE_POLLS = 2
# Depois de um aviso do sistema (dispositivo entrou/saiu, PC acordou): leituras extras nestes instantes. O primeiro
# atraso junta a rajada de avisos; os outros pegam o receptor/Bluetooth que ainda está voltando do sono.
BURST_DELAYS_S = (0.3, 1.0, 3.0, 6.0)
# Dispositivo que já apareceu e sumiu (mouse desligado com o dongle no PC): o Windows não avisa quando ele volta, e
# ele só responde acordado. Então, enquanto faltar alguém, olhamos a última entrada do usuário a cada ACTIVITY_CHECK_S
# (uma chamada barata) e, se ele mexeu em algo, lemos na hora, no máximo a cada ACTIVITY_GAP_S. Quem sumiu há mais
# de MISSING_TTL_S deixa de ser procurado.
# Fontes que mandam dados sem parar (controles): sumir de uma leitura = desligado/desconectado, sem carência.
# O Bluetooth genérico entra aqui também: o "conectado" do Windows é confiável, então sumir é ter desconectado.
STREAMING_SOURCES = frozenset({"xinput", "sony", "switch", "gaming", bluetooth.SOURCE})
CONFIRM_DELAY_S = 0.5     # controle faltou uma vez: lê de novo em seguida para confirmar
ACTIVITY_CHECK_S = 1.0
ACTIVITY_GAP_S = 5.0
MISSING_TTL_S = 30 * 60.0


MICROSOFT_VID = 0x045E

# Fonte -> fabricante dos controles que ela já entrega (a leitura do Windows pula esses, para não duplicar)
CLAIM_VENDOR = {"xinput": MICROSOFT_VID, "sony": sony.SONY_VID, "switch": switch_pro.NINTENDO_VID}


# Fabricante -> fontes com leitor próprio para ele (o Bluetooth genérico pula esses dispositivos se a fonte entregou
# algo; se ela não entregou nada, o número do Windows serve de reserva)
DEDICATED_SOURCES = {
    sony.SONY_VID: {"sony"},
    switch_pro.NINTENDO_VID: {"switch"},
    logitech.LOGI_VID: {"logitech"},
    vxe.VXE_VID: {"vxe"},
    MICROSOFT_VID: {"xinput", "gaming"},
}


def bluetooth_skip(hids: list, devices: list[BatteryDevice]) -> set[str]:
    """Endereços Bluetooth que um leitor próprio já cobre: interface HID por Bluetooth de um fabricante cuja fonte
    entregou algum dispositivo nesta leitura."""
    sources = {d.source for d in devices}
    return {addr for addr, vid in bluetooth.hid_addresses(hids).items()
            if DEDICATED_SOURCES.get(vid, set()) & sources}


def claimed_by_vendor(devices: list[BatteryDevice]) -> dict[int, int]:
    claimed: dict[int, int] = {}
    for d in devices:
        vid = CLAIM_VENDOR.get(d.source)
        if vid is not None:
            claimed[vid] = claimed.get(vid, 0) + 1
    return claimed


_pool: Optional[ThreadPoolExecutor] = None


def _executor() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="BatteryRead")
    return _pool


def _timed(name: str, fn: Callable[[], list], times: dict) -> list:
    t0 = time.monotonic()
    try:
        return fn()
    except Exception:  # noqa: BLE001 - uma fonte quebrada não derruba as outras
        log.exception("battery: %s", name)
        return []
    finally:
        times[name] = time.monotonic() - t0


def read_all_sources() -> list[BatteryDevice]:
    """Fontes em paralelo (a leitura leva o tempo da mais lenta, não a soma). As leituras do Windows (controles e
    Bluetooth genérico) vêm depois, porque pulam o que as outras já entregaram."""
    t0 = time.monotonic()
    times: dict[str, float] = {}
    pool = _executor()
    xin = pool.submit(_timed, "xinput", xinput.read_devices, times)
    hids = _timed("enumerate", lambda: hid_win.enumerate_hid(
        {sony.SONY_VID, logitech.LOGI_VID, switch_pro.NINTENDO_VID, vxe.VXE_VID, MICROSOFT_VID}), times)
    hid_jobs = [pool.submit(_timed, name, (lambda fn=fn: fn(hids)), times)
                for name, fn in (("sony", sony.read_devices), ("switch", switch_pro.read_devices),
                                 ("logitech", logitech.read_devices), ("vxe", vxe.read_devices))]
    devices: list[BatteryDevice] = list(xin.result())
    for job in hid_jobs:                    # ordem fixa: a saída não depende de quem terminou antes
        devices += job.result()
    claimed = claimed_by_vendor(devices)
    devices += _timed("gaming", lambda: gaming_input.read_devices(hids, claimed), times)
    skip = bluetooth_skip(hids, devices)
    devices += _timed("bluetooth", lambda: bluetooth.read_devices(skip), times)
    log.debug("battery: read %.2fs (%s)", time.monotonic() - t0,
              ", ".join(f"{k} {v:.2f}" for k, v in sorted(times.items())))
    return devices


class DeviceTracker:
    """Junta leituras sucessivas aplicando a carência para quem sumiu (sem Qt, testável)."""

    def __init__(self, grace: int = GRACE_POLLS):
        self.grace = grace
        self._last: dict[str, BatteryDevice] = {}
        self._missed: dict[str, int] = {}

    def update(self, reading: list[BatteryDevice], count_misses: bool = True,
               drop_missing: bool = False) -> list[BatteryDevice]:
        """Quem some:
        - controle (fonte em STREAMING_SOURCES): sai na hora, em qualquer leitura; ele manda dados sem parar, então
          não responder é estar desligado ou fora de alcance;
        - pelo dongle (mouse/teclado): pode só estar dormindo. `count_misses=False` (leituras extras) não gasta a
          carência; senão um mouse dormindo sairia só porque outro dispositivo foi ligado;
        - `drop_missing=True` (atualizar à mão): todo mundo que não respondeu sai."""
        now = {d.id: d for d in reading}
        for dev_id in list(self._last):
            if dev_id in now:
                continue
            if drop_missing:
                del self._last[dev_id]
                self._missed.pop(dev_id, None)
                continue
            if self._last[dev_id].source in STREAMING_SOURCES:
                # Um soluço do Bluetooth não tira o controle: a primeira falta pede confirmação (leitura logo em
                # seguida, ver `unconfirmed`); a segunda seguida tira.
                self._missed[dev_id] = self._missed.get(dev_id, 0) + 1
                if self._missed[dev_id] >= 2:
                    del self._last[dev_id]
                    del self._missed[dev_id]
                continue
            if not count_misses:
                continue
            self._missed[dev_id] = self._missed.get(dev_id, 0) + 1
            if self._missed[dev_id] > self.grace:
                del self._last[dev_id]
                del self._missed[dev_id]
        for dev_id, dev in now.items():
            self._last[dev_id] = dev
            self._missed.pop(dev_id, None)
        return sort_devices(self._last.values())

    def unconfirmed(self) -> bool:
        """Algum controle faltou uma vez e espera a leitura de confirmação."""
        return any(self._last[i].source in STREAMING_SOURCES for i in self._missed if i in self._last)


class BatteryService(QObject):
    devices_updated = Signal(list)    # list[BatteryDevice], já ordenada

    def __init__(self, parent=None, reader: Optional[Callable[[], list]] = None, interval_s: float = INTERVAL_S,
                 burst_delays: tuple = BURST_DELAYS_S, activity: Optional[Callable[[], Optional[int]]] = None,
                 activity_check_s: float = ACTIVITY_CHECK_S, activity_gap_s: float = ACTIVITY_GAP_S,
                 missing_ttl_s: float = MISSING_TTL_S, confirm_delay_s: float = CONFIRM_DELAY_S):
        super().__init__(parent)
        self._confirm_delay = float(confirm_delay_s)
        self._activity = activity or system_events.last_input_tick
        self._activity_check = float(activity_check_s)
        self._activity_gap = float(activity_gap_s)
        self._missing_ttl = float(missing_ttl_s)
        self._missing: dict[str, float] = {}  # id -> quando sumiu (monotonic)
        self._seen: set[str] = set()
        self._next_check = 0.0
        self._last_tick: Optional[int] = None
        self._last_probe = 0.0
        self._reader = reader or read_all_sources
        self._interval = float(interval_s)
        self._burst_delays = tuple(float(d) for d in burst_delays)
        self._tracker = DeviceTracker()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_devices: list[BatteryDevice] = []
        # Estado da agenda (protegido por _lock)
        self._force = False
        self._next_poll = 0.0
        self._burst: list[float] = []         # instantes (monotonic) das leituras extras pendentes
        self._burst_changed = False
        self._event_at: Optional[float] = None
        self._event_reason = ""
        self.reads = 0                        # leituras feitas (para testes e diagnóstico)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.is_running():
                self._wake.set()
                return
            self._stop.clear()
            self._wake.clear()
            self._force = False
            self._next_poll = 0.0             # primeira leitura imediata
            self._burst = []
            self._event_at = None
            self._next_check = 0.0
            self._last_tick = None
            self._thread = threading.Thread(target=self._run, name="BatteryService", daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._burst = []
            self._event_at = None
        self._stop.set()
        self._wake.set()

    def refresh(self):
        """Lê agora (sem esperar o intervalo)."""
        if self.is_running():
            with self._lock:
                self._force = True
            self._wake.set()

    def notify_change(self, reason: str = "device"):
        """Aviso do sistema (dispositivo entrou/saiu, PC acordou): agenda a rajada de leituras. Avisos seguidos
        reiniciam a rajada, então uma enxurrada de avisos vira uma leitura só. Barato: pode ser chamado da thread de
        interface."""
        if not self.is_running() or self._stop.is_set():
            return
        now = time.monotonic()
        with self._lock:
            self._burst = [now + d for d in self._burst_delays]
            self._burst_changed = False
            if self._event_at is None:
                self._event_at = now
                self._event_reason = reason
        self._wake.set()

    def burst_pending(self) -> bool:
        with self._lock:
            return bool(self._burst)

    def missing_ids(self) -> set[str]:
        return set(self._missing)

    def _next_deadline(self) -> float:
        if self._force:
            return 0.0
        times = [self._next_poll] + self._burst[:1]
        if self._missing:
            times.append(self._next_check)
        return min(times)

    def _activity_says_read(self, now: float) -> bool:
        """Só com alguém faltando: o usuário mexeu em algo desde a última olhada, e já passou o intervalo mínimo."""
        self._next_check = now + self._activity_check
        try:
            tick = self._activity()
        except Exception:  # noqa: BLE001
            tick = None
        moved = tick is not None and self._last_tick is not None and tick != self._last_tick
        if tick is not None:
            self._last_tick = tick
        return moved and now - self._last_probe >= self._activity_gap

    def _track_missing(self, ids: frozenset, now: float):
        self._seen |= ids
        for dev_id in self._seen - ids:
            self._missing.setdefault(dev_id, now)
        for dev_id in list(self._missing):
            if dev_id in ids or now - self._missing[dev_id] > self._missing_ttl:
                del self._missing[dev_id]
                if dev_id not in ids:
                    self._seen.discard(dev_id)

    def _run(self):
        last_ids: Optional[frozenset] = None
        while not self._stop.is_set():
            with self._lock:
                remaining = self._next_deadline() - time.monotonic()
            if remaining > 0:
                self._wake.wait(remaining)
                self._wake.clear()
                continue

            with self._lock:
                now = time.monotonic()
                manual = self._force
                regular = self._force or now >= self._next_poll
                in_burst = bool(self._burst) and self._burst[0] <= now
                probe = False
                if not (regular or in_burst):
                    if not (self._missing and now >= self._next_check):
                        continue
                    probe = self._activity_says_read(now)
                    if not probe:
                        continue
                    if self._event_at is None:
                        self._event_at, self._event_reason = now, "activity"
                if probe or regular or in_burst:
                    self._last_probe = now
                self._force = False
                self._burst = [t for t in self._burst if t > now]
            t0 = time.monotonic()
            try:
                reading = self._reader()
            except Exception:  # noqa: BLE001
                log.exception("battery: read")
                reading = []
            self.reads += 1
            if self._stop.is_set():
                break
            devices = self._tracker.update(reading, count_misses=regular, drop_missing=manual)
            ids = frozenset(d.id for d in devices)
            read_ids = frozenset(d.id for d in reading)
            done = time.monotonic()
            with self._lock:
                returned = bool(self._missing.keys() & read_ids)
                self._track_missing(read_ids, done)   # pela leitura crua: quem está na carência também falta
            changed = (last_ids is not None and ids != last_ids) or returned
            last_ids = ids
            self.last_devices = devices
            self.devices_updated.emit(devices)

            with self._lock:
                if regular:
                    self._next_poll = done + self._interval
                if self._event_at is not None and changed:
                    log.info("battery: %s -> list changed %.2fs after the event (read %.2fs, %d device(s))",
                             self._event_reason, done - self._event_at, done - t0, len(devices))
                if in_burst or regular:
                    if changed:
                        self._burst_changed = True
                    elif self._burst_changed and self._burst:
                        self._burst = []      # mudou e depois ficou igual: assentou, encerra a rajada
                if self._tracker.unconfirmed():   # depois do "assentou", para não ser cancelada por ele
                    self._burst = sorted(self._burst + [done + self._confirm_delay])
                if not self._burst:
                    self._event_at = None
                    self._burst_changed = False
