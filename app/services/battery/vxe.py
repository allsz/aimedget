"""
Mouses VXE / ATK pelo dongle "Mouse 1K" (VID 3554): relatório de saída 8 de 17 bytes na coleção de fabricante
(FF02/0002), a mesma conversa que o app web hub.atk.pro tem com o dongle.

- Pedido: `08 04 00 ... CS` (id 8, comando 04 = bateria). O último byte fecha a soma de todos os 17 bytes em 0x55,
  nos pedidos e nas respostas.
- Resposta: `08 04 00 00 00 02 | nível | carga | tensão (2 bytes, mV, big-endian) | ... | CS`. O nível já vem em 0-100.
- Confirmados com um VXE R1 PRO MAX: o dongle F58A (sem fio) e o próprio mouse F58C (no cabo), com o mesmo
  protocolo. A configuração do app da ATK lista irmãos da mesma família (F503, F505, F50B, F58D) que
  provavelmente usam o mesmo protocolo; entram em PIDS quando alguém confirmar.
- Carregando: byte 7 igual a 1 (visto no cabo, com a tensão mais alta). Com o cabo o percentual vem inflado pela
  carga e cai ao desligar o cabo.

No cabo o mouse vira um dispositivo próprio (F58C) e o dongle para de responder. Um dongle sem resposta e um
mouse no cabo com leitura são tratados como o mesmo mouse: o cartão fica com o id do dongle, sem duplicar.
Mouse dormindo: sem resposta, o mouse aparece com carga desconhecida, como os outros dispositivos sem leitura.
"""

from __future__ import annotations

from typing import Optional

from app.services.battery import hid_win
from app.services.battery.models import KIND_MOUSE, BatteryDevice

VXE_VID = 0x3554
PIDS = {0xF58A: "VXE Mouse", 0xF58C: "VXE Mouse"}   # F58A = dongle; F58C = o mouse (R1 PRO MAX) no cabo
WIRED_PIDS = {0xF58C}

REPORT_ID = 0x08
CMD_BATTERY = 0x04
PACKET_LEN = 17
CHECKSUM_TOTAL = 0x55          # a soma dos 17 bytes (id incluído) dá 0x55 módulo 256

READ_WINDOW_MS = 500


def _checksum(packet: bytes) -> int:
    return (CHECKSUM_TOTAL - sum(packet[: PACKET_LEN - 1])) & 0xFF


def build_request(command: int = CMD_BATTERY) -> bytes:
    pkt = bytearray(PACKET_LEN)
    pkt[0], pkt[1] = REPORT_ID, command
    pkt[PACKET_LEN - 1] = _checksum(bytes(pkt))
    return bytes(pkt)


def parse_reply(reply: bytes) -> Optional[tuple[float, bool, int]]:
    """(porcentagem, carregando, tensão em mV) da resposta ao pedido de bateria, ou None se não for essa resposta."""
    if reply is None or len(reply) < PACKET_LEN or reply[0] != REPORT_ID or reply[1] != CMD_BATTERY:
        return None
    if reply[PACKET_LEN - 1] != _checksum(reply):
        return None
    level = reply[6]
    if level > 100:
        return None
    return float(level), reply[7] == 1, (reply[8] << 8) | reply[9]


def _is_vendor_collection(info: hid_win.HidInfo) -> bool:
    return info.usage_page == 0xFF02 and info.output_len >= PACKET_LEN and info.input_len >= PACKET_LEN


def _query(info: hid_win.HidInfo) -> Optional[tuple[float, bool, int]]:
    with hid_win.HidHandle(info, write=True) as handle:
        while handle.read(1) is not None:          # esvazia relatórios antigos para não confundir com a resposta
            pass
        if not handle.write(build_request()):
            return None
        remaining = READ_WINDOW_MS
        step = 50
        while remaining > 0:
            reply = handle.read(step)
            remaining -= step
            if reply is None:
                continue
            parsed = parse_reply(reply)
            if parsed is not None:
                return parsed
    return None


def read_devices(hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    found: list[tuple[str, str, Optional[tuple[float, bool, int]]]] = []
    wired: list[tuple[str, str, Optional[tuple[float, bool, int]]]] = []
    for info in hids:
        if info.vid != VXE_VID or info.pid not in PIDS or not _is_vendor_collection(info):
            continue
        try:
            result = _query(info)
        except OSError:
            continue
        entry = (PIDS[info.pid], (info.serial or info.path).lower(), result)
        (wired if info.pid in WIRED_PIDS else found).append(entry)

    # No cabo o dongle fica mudo e o mouse aparece sozinho: cada mouse no cabo com leitura assume o lugar de um
    # dongle sem resposta (mesmo id, o cartão não duplica nem pisca). O que sobrar entra como dispositivo próprio.
    silent = sorted((i for i, f in enumerate(found) if f[2] is None), key=lambda i: found[i][1])
    for entry in sorted(wired, key=lambda w: w[1]):
        if entry[2] is not None and silent:
            i = silent.pop(0)
            found[i] = (found[i][0], found[i][1], entry[2])
        else:
            found.append(entry)

    # Mouse dormindo não responde: some da lista, como os da Logitech (o DeviceTracker segura o último valor um tempo)
    found = [f for f in found if f[2] is not None]

    # Vários dongles do mesmo modelo ganham número, numa ordem estável (serial/caminho)
    found.sort(key=lambda f: (f[0], f[1]))
    counts: dict[str, int] = {}
    for model, _k, _r in found:
        counts[model] = counts.get(model, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for model, key, result in found:
        seen[model] = seen.get(model, 0) + 1
        name = f"{model} {seen[model]}" if counts[model] > 1 else model
        pct, charging = (result[0], result[1]) if result is not None else (None, False)
        out.append(BatteryDevice(id=f"vxe:{key}", name=name, kind=KIND_MOUSE, percent=pct, charging=charging,
                                 source="vxe"))
    return out
