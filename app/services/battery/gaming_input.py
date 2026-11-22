"""
Controles de jogo pela API do próprio Windows (Windows.Gaming.Input): é de onde vem a bateria que o Windows mostra
na bandeja ("HID-compliant game controller: 10%"). Cobre o que XInput e os leitores por HID não alcançam, como um
controle que imita o Xbox por Bluetooth (GuliKit): para o XInput ele fica "sem bateria", mas o Windows sabe a carga.

- Cada controle traz `remaining / full_charge` em mWh (a carga é a razão) e o estado (descarregando, parado,
  carregando). Muitos controles só informam alguns níveis, então a porcentagem sai marcada como aproximada.
- Quem já tem leitor próprio (Sony, Switch Pro, XInput) é pulado: `claimed` diz quantos controles de cada fabricante
  os outros leitores já entregaram, e esses não aparecem duas vezes.
- O nome vem do Bluetooth (Configurações: "GuliKit Controller XW"); o nome genérico do Windows só serve de último
  recurso.
- Precisa dos pacotes winrt (Gaming.Input, Devices.Power, System, System.Power). Sem eles, ou fora do Windows,
  devolve lista vazia.
- A lista de controles do Windows se preenche em segundo plano: na primeira leitura do processo esperamos até 1 s.
- Controle com fio não aparece: o Windows devolve um relatório fixo (1000/1000 mWh, "descarregando") que não é a
  carga real, e não dá para saber se ele está carregando. Visto num GuliKit ligado por cabo.
- Importar o winrt ANTES do PySide6 num mesmo processo derruba o Python (violação de acesso). No app o PySide6 já
  está carregado; em scripts avulsos, importe o PySide6 primeiro.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional

from app.services.battery import hid_win
from app.services.battery.models import KIND_CONTROLLER, BatteryDevice

log = logging.getLogger(__name__)

# BatteryStatus (Windows.System.Power)
STATUS_NOT_PRESENT = 0
STATUS_DISCHARGING = 1
STATUS_IDLE = 2
STATUS_CHARGING = 3

WARMUP_S = 1.0

_api = None          # classe RawGameController, ou False se indisponível
_warm = False


def _load():
    global _api
    if _api is not None:
        return _api
    _api = False
    if sys.platform != "win32":
        return _api
    try:
        from winrt.windows.gaming.input import RawGameController
        import winrt.windows.devices.power      # noqa: F401 - o relatório de bateria usa estes tipos
        import winrt.windows.system.power       # noqa: F401
        _api = RawGameController
    except ImportError:
        log.info("battery: pacotes winrt de Gaming.Input ausentes; leitura do Windows desativada")
    return _api


def charge_from_report(remaining, full, status) -> Optional[tuple[Optional[float], bool]]:
    """(porcentagem ou None, carregando) de um relatório de bateria, ou None se não há bateria a mostrar."""
    try:
        status = int(status)
    except (TypeError, ValueError):
        return None
    if status == STATUS_NOT_PRESENT:
        return None
    charging = status == STATUS_CHARGING
    if remaining is None or not full:
        return None, charging
    return float(max(0.0, min(100.0, remaining * 100.0 / full))), charging


def choose_name(display_name: str, bluetooth_name: Optional[str], hid_product: Optional[str]) -> str:
    """Nome do cartão: Bluetooth > nome do Windows (se não for o genérico "...HID...") > string do HID > genérico."""
    if bluetooth_name:
        return bluetooth_name
    display = (display_name or "").strip()
    if display and "hid" not in display.lower():
        return display
    if hid_product:
        return hid_product
    return "Controller"


def _bluetooth_name(vid: int, pid: int, hids: list, names: dict) -> tuple[Optional[str], Optional[str]]:
    """(nome Bluetooth, string do HID) do controle com este VID/PID; só quando ele é único (senão não dá para saber
    qual é qual)."""
    matches = [h for h in hids if h.vid == vid and h.pid == pid]
    serials = {h.serial.lower() for h in matches if h.serial}
    product = next((h.product for h in matches if h.product), None)
    if len(serials) == 1:
        return names.get(next(iter(serials))), product
    return None, product


def read_devices(hids: list, claimed: Optional[dict] = None) -> list[BatteryDevice]:
    """`hids`: interfaces HID já listadas (para o nome). `claimed`: {VID: quantos já lidos por outros leitores}."""
    global _api, _warm
    api = _load()
    if not api:
        return []
    claimed = dict(claimed or {})
    controllers = list(api.raw_game_controllers)
    if not controllers and not _warm:
        deadline = time.monotonic() + WARMUP_S
        while not controllers and time.monotonic() < deadline:
            time.sleep(0.1)
            controllers = list(api.raw_game_controllers)
    _warm = True

    rows = []
    for ctrl in sorted(controllers, key=lambda c: (c.hardware_vendor_id, c.hardware_product_id, c.non_roamable_id)):
        vid, pid = int(ctrl.hardware_vendor_id), int(ctrl.hardware_product_id)
        if claimed.get(vid, 0) > 0:                     # já tem leitor próprio: não duplica
            claimed[vid] -= 1
            continue
        if not ctrl.is_wireless:
            continue                                    # no cabo o Windows devolve um relatório de mentira
                                                        # (1000/1000 mWh, "descarregando"): nada a mostrar
        try:
            report = ctrl.try_get_battery_report()
        except ImportError:                             # faltam pacotes winrt: desliga em vez de falhar a cada leitura
            _api = False
            log.warning("battery: faltam pacotes winrt para o relatório de bateria")
            return []
        except Exception:  # noqa: BLE001 - um controle com problema não derruba os outros
            log.exception("battery: gaming_input %04X:%04X", vid, pid)
            continue
        if report is None:
            continue
        result = charge_from_report(report.remaining_capacity_in_milliwatt_hours,
                                    report.full_charge_capacity_in_milliwatt_hours, report.status)
        if result is None:
            continue
        pct, charging = result
        rows.append((vid, pid, str(ctrl.non_roamable_id), ctrl.display_name, pct, charging))

    names = hid_win.bluetooth_names() if rows else {}
    named = []
    for vid, pid, ident, display, pct, charging in rows:
        bt, product = _bluetooth_name(vid, pid, hids, names)
        named.append((choose_name(display, bt, product), ident, pct, charging))

    # Nomes repetidos ganham número, numa ordem estável
    named.sort(key=lambda r: (r[0], r[1]))
    counts: dict[str, int] = {}
    for name, *_ in named:
        counts[name] = counts.get(name, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for name, ident, pct, charging in named:
        seen[name] = seen.get(name, 0) + 1
        label = f"{name} {seen[name]}" if counts[name] > 1 else name
        out.append(BatteryDevice(id=f"gaming:{ident}", name=label, kind=KIND_CONTROLLER, percent=pct,
                                 charging=charging, approximate=pct is not None, source="gaming"))
    return out
