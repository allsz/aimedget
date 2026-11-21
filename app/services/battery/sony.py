"""
DualSense e DualShock 4: a carga vem no byte de status do relatório de entrada (layout do hid-playstation do Linux
e do SDL).

- USB: relatório 0x01 completo, sempre com a bateria.
- Bluetooth: só o relatório completo (0x31 no DualSense, 0x11 no DS4) traz a bateria. O controle começa no modo
  simples (0x01, sem bateria) e só passa ao completo quando um app pede (Steam, DS4Windows, um jogo). Não forçamos a
  troca: ela pode quebrar jogos que leem o modo simples. Nesse caso o controle aparece com a carga desconhecida.
"""

from __future__ import annotations

from typing import Optional

from app.services.battery import hid_win
from app.services.battery.models import KIND_CONTROLLER, BatteryDevice

SONY_VID = 0x054C
DUALSENSE_PIDS = {0x0CE6: "DualSense", 0x0DF2: "DualSense Edge"}
DS4_PIDS = {0x05C4: "DualShock 4", 0x09CC: "DualShock 4", 0x0BA0: "DualShock 4"}

READ_WINDOW_MS = 220   # o controle manda centenas de relatórios por segundo; isto basta para pegar alguns


def parse_dualsense(report: bytes) -> Optional[tuple[float, bool]]:
    """(porcentagem, carregando) de um relatório do DualSense, ou None se ele não traz a bateria."""
    if not report:
        return None
    rid = report[0]
    if rid == 0x01 and len(report) >= 54:      # USB
        status = report[53]
    elif rid == 0x31 and len(report) >= 55:    # Bluetooth, modo completo
        status = report[54]
    else:
        return None
    level = status & 0x0F
    charge = (status & 0xF0) >> 4
    if charge == 0x0:
        return float(min(level * 10 + 5, 100)), False
    if charge == 0x1:
        return float(min(level * 10 + 5, 100)), True
    if charge == 0x2:
        return 100.0, False
    return None                                # 0xA/0xB/0xF: erro de temperatura/tensão/carga


def parse_ds4(report: bytes, bluetooth: bool) -> Optional[tuple[float, bool]]:
    if not report:
        return None
    rid = report[0]
    if not bluetooth and rid == 0x01 and len(report) >= 31:
        status = report[30]
    elif bluetooth and rid == 0x11 and len(report) >= 33:
        status = report[32]
    else:
        return None
    level = status & 0x0F
    cable = bool(status & 0x10)
    if cable:
        if level < 10:
            return float(level * 10 + 5), True
        if level == 10:
            return 100.0, True
        if level == 11:
            return 100.0, False
        return None
    return float(min(level * 10 + 5, 100)), False


def _model(info: hid_win.HidInfo) -> Optional[str]:
    if info.vid != SONY_VID:
        return None
    return DUALSENSE_PIDS.get(info.pid) or DS4_PIDS.get(info.pid)


def _is_gamepad_collection(info: hid_win.HidInfo) -> bool:
    return info.usage_page == 0x01 and info.usage in (0x04, 0x05)


def read_devices(hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    found: list[tuple[str, str, Optional[tuple[float, bool]]]] = []
    for info in hids:
        model = _model(info)
        if model is None or not _is_gamepad_collection(info):
            continue
        result = None
        try:
            with hid_win.HidHandle(info) as handle:
                deadline = READ_WINDOW_MS
                step = 40
                while deadline > 0 and result is None:
                    report = handle.read(step)
                    deadline -= step
                    if report is None:
                        continue
                    if info.pid in DUALSENSE_PIDS:
                        result = parse_dualsense(report)
                    else:
                        result = parse_ds4(report, info.is_bluetooth)
        except OSError:
            continue
        key = (info.serial or info.path).lower()
        found.append((model, key, result))

    # Vários controles do mesmo modelo ganham número, numa ordem estável (serial/caminho)
    found.sort(key=lambda f: (f[0], f[1]))
    counts: dict[str, int] = {}
    for model, _k, _r in found:
        counts[model] = counts.get(model, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for model, key, result in found:
        seen[model] = seen.get(model, 0) + 1
        name = f"{model} {seen[model]}" if counts[model] > 1 else model
        pct, charging = result if result is not None else (None, False)
        out.append(BatteryDevice(id=f"sony:{key}", name=name, kind=KIND_CONTROLLER, percent=pct, charging=charging,
                                 source="sony"))
    return out
