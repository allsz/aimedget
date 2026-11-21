"""
Controles no protocolo do Switch Pro Controller (VID da Nintendo 057E, PID 2009): inclui o 8BitDo Pro 3 em modo
Switch por Bluetooth, que aparece com este ID. A carga vem no byte 2 do relatório de entrada completo (layout
documentado pela comunidade que fez a engenharia reversa do controle):

- Nibble alto do byte 2: nível em 4 barras (8 cheia, 6 média, 4 baixa, 2 crítica, 0 vazia); o bit 0 do nibble
  indica carregando.
- Relatórios com bateria: 0x30 (padrão contínuo), 0x21 (resposta a subcomando) e 0x31 (NFC/IR). O modo simples
  (0x3F) não traz a carga. Não mandamos subcomando para trocar de modo: um jogo que lê o simples poderia quebrar.
  Nesse caso o controle aparece com a carga desconhecida.

Só são 4 níveis, então a porcentagem é o meio da faixa e vai marcada como aproximada (como no XInput).
"""

from __future__ import annotations

from typing import Optional

from app.services.battery import hid_win
from app.services.battery.models import KIND_CONTROLLER, BatteryDevice

NINTENDO_VID = 0x057E
PRO_PIDS = {0x2009: "Pro Controller"}

BATTERY_REPORTS = (0x30, 0x21, 0x31)
LEVEL_PERCENT = {0x0: 5.0, 0x2: 15.0, 0x4: 40.0, 0x6: 65.0, 0x8: 90.0}

READ_WINDOW_MS = 220   # o controle manda dezenas de relatórios por segundo; isto basta para pegar alguns


def parse_report(report: bytes) -> Optional[tuple[float, bool]]:
    """(porcentagem aproximada, carregando) de um relatório de entrada, ou None se ele não traz a bateria."""
    if not report or len(report) < 3 or report[0] not in BATTERY_REPORTS:
        return None
    nibble = report[2] >> 4
    percent = LEVEL_PERCENT.get(nibble & 0xE)
    if percent is None:                        # níveis fora da tabela (ex.: 0xA, 0xC, 0xE) não existem no protocolo
        return None
    return percent, bool(nibble & 0x1)


def _is_gamepad_collection(info: hid_win.HidInfo) -> bool:
    return info.usage_page == 0x01 and info.usage in (0x04, 0x05)


def read_devices(hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    found: list[tuple[str, str, Optional[tuple[float, bool]]]] = []
    for info in hids:
        if info.vid != NINTENDO_VID or info.pid not in PRO_PIDS or not _is_gamepad_collection(info):
            continue
        result = None
        try:
            with hid_win.HidHandle(info) as handle:
                remaining = READ_WINDOW_MS
                step = 40
                while remaining > 0 and result is None:
                    report = handle.read(step)
                    remaining -= step
                    if report is None:
                        continue
                    result = parse_report(report)
        except OSError:
            continue
        found.append((PRO_PIDS[info.pid], (info.serial or info.path).lower(), result))

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
        out.append(BatteryDevice(id=f"switch:{key}", name=name, kind=KIND_CONTROLLER, percent=pct, charging=charging,
                                 approximate=pct is not None, source="switch"))
    return out
