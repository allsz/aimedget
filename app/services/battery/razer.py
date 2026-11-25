"""
Mouses Razer pelo protocolo documentado no OpenRazer (driver Linux, GPL-2.0; aqui só os fatos do protocolo, sem
código copiado): https://github.com/openrazer/openrazer, arquivos driver/razercommon.{c,h},
driver/razerchromacommon.c, driver/razermouse_driver.{c,h}.

NÃO CONFIRMADO COM APARELHO: ninguém do projeto tem um Razer ainda. Só pedidos de LEITURA (bateria e carga) vão para
os modelos da tabela, com os valores que o OpenRazer usa para cada PID; resposta fora do esperado = sem leitura.
A primeira leitura de cada modelo vai para o log, para quem tiver um Razer confirmar.

O pacote (relatório de recurso 0, 90 bytes; no Windows o buffer leva o id 0 na frente = 91):
  status | transaction_id | remaining_packets (2) | protocol_type | data_size | command_class | command_id |
  arguments[80] | crc | reserved
  - crc = XOR dos bytes 2..87.
  - status da resposta: 0x02 = ok, 0x01 = ocupado, 0x03 falha, 0x04 tempo esgotado, 0x05 sem suporte.
  - Bateria: classe 0x07, comando 0x80, data_size 0x02; nível 0-255 em arguments[1].
  - Carregando: classe 0x07, comando 0x84, data_size 0x02; 0/1 em arguments[1].
  - Entre o pedido e a leitura da resposta o driver espera um tempo que depende do modelo (600 us a 400 ms).
  - O pedido vai para a interface USB 0, ou 3 em alguns modelos (`index` na tabela).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from app.services.battery import hid_win
from app.services.battery.models import KIND_MOUSE, BatteryDevice

log = logging.getLogger(__name__)

RAZER_VID = 0x1532
SOURCE = "razer"

REPORT_LEN = 90
STATUS_BUSY = 0x01
STATUS_OK = 0x02
CLASS_MISC = 0x07
CMD_BATTERY = 0x80
CMD_CHARGING = 0x84

RETRIES = 3
BUSY_WAIT_S = 0.01

WAIT_DEFAULT = 600e-6      # RAZER_MOUSE_WAIT_US
WAIT_NEW = 31000e-6        # RAZER_NEW_MOUSE_RECEIVER_WAIT_US
WAIT_VIPER = 59900e-6      # RAZER_VIPER_MOUSE_RECEIVER_WAIT_US
WAIT_ATHERIS = 400000e-6   # RAZER_ATHERIS_RECEIVER_WAIT_US


@dataclass(frozen=True)
class Model:
    name: str
    tx: int                 # transaction_id que o OpenRazer usa no charge_level desse PID
    wait: float = WAIT_DEFAULT
    index: int = 0          # interface USB que recebe o pedido
    charging: bool = True   # False: o OpenRazer não pergunta (pilhas AA ou sem suporte)


def _m(name, tx, wait=WAIT_DEFAULT, index=0, charging=True):
    return Model(name, tx, wait, index, charging)


# PID -> modelo, do switch do charge_level (transaction_id) e do razer_get_report (espera e interface).
MODELS: dict[int, Model] = {
    # transaction_id 0x3F
    0x0059: _m("Razer Lancehead", 0x3F),
    0x005A: _m("Razer Lancehead", 0x3F),
    0x0072: _m("Razer Mamba Wireless", 0x3F, WAIT_NEW),
    0x0073: _m("Razer Mamba Wireless", 0x3F, WAIT_NEW),
    0x007C: _m("Razer DeathAdder V2 Pro", 0x3F, WAIT_VIPER),
    0x007D: _m("Razer DeathAdder V2 Pro", 0x3F, WAIT_VIPER),
    # transaction_id 0x1F
    0x008F: _m("Razer Naga Pro", 0x1F),
    0x0090: _m("Razer Naga Pro", 0x1F, WAIT_NEW),
    0x0088: _m("Razer Basilisk Ultimate", 0x1F, WAIT_NEW),
    0x0086: _m("Razer Basilisk Ultimate", 0x1F, WAIT_NEW),
    0x006F: _m("Razer Lancehead Wireless", 0x1F, WAIT_NEW),
    0x0070: _m("Razer Lancehead Wireless", 0x1F, WAIT_NEW),
    0x0062: _m("Razer Atheris", 0x1F, WAIT_ATHERIS, charging=False),
    0x0094: _m("Razer Orochi V2", 0x1F, WAIT_ATHERIS, charging=False),
    0x0095: _m("Razer Orochi V2", 0x1F, WAIT_ATHERIS, charging=False),
    0x00E0: _m("Razer Orochi V2", 0x1F, WAIT_ATHERIS, charging=False),
    0x0077: _m("Razer Pro Click", 0x1F, WAIT_NEW),
    0x0080: _m("Razer Pro Click", 0x1F, WAIT_NEW),
    0x009C: _m("Razer DeathAdder V2 X HyperSpeed", 0x1F, WAIT_NEW, charging=False),
    0x00A6: _m("Razer Viper V2 Pro", 0x1F, WAIT_NEW),
    0x00A5: _m("Razer Viper V2 Pro", 0x1F, WAIT_NEW),
    0x009E: _m("Razer Viper Mini SE", 0x1F, WAIT_VIPER),
    0x009F: _m("Razer Viper Mini SE", 0x1F, WAIT_VIPER),
    0x00DB: _m("Razer Cobra HyperSpeed", 0x1F, WAIT_NEW),
    0x00DA: _m("Razer Cobra HyperSpeed", 0x1F, WAIT_NEW),
    0x00B0: _m("Razer Cobra Pro", 0x1F, WAIT_NEW),
    0x00AF: _m("Razer Cobra Pro", 0x1F, WAIT_NEW),
    0x00B7: _m("Razer DeathAdder V3 Pro", 0x1F, WAIT_NEW),
    0x00B6: _m("Razer DeathAdder V3 Pro", 0x1F, WAIT_NEW),
    0x00C3: _m("Razer DeathAdder V3 Pro", 0x1F, WAIT_NEW),
    0x00C2: _m("Razer DeathAdder V3 Pro", 0x1F, WAIT_NEW),
    0x00C4: _m("Razer DeathAdder V3 HyperSpeed", 0x1F, WAIT_NEW),
    0x00C5: _m("Razer DeathAdder V3 HyperSpeed", 0x1F, WAIT_NEW),
    0x00B3: _m("Razer HyperPolling Dongle", 0x1F, WAIT_VIPER),
    0x00AA: _m("Razer Basilisk V3 Pro", 0x1F, WAIT_NEW),
    0x00AB: _m("Razer Basilisk V3 Pro", 0x1F, WAIT_NEW),
    0x00CB: _m("Razer Basilisk V3 35K", 0x1F, index=3, charging=False),
    0x00CC: _m("Razer Basilisk V3 Pro 35K", 0x1F, WAIT_NEW),
    0x00CD: _m("Razer Basilisk V3 Pro 35K", 0x1F, WAIT_NEW),
    0x00D6: _m("Razer Basilisk V3 Pro 35K", 0x1F, WAIT_NEW),
    0x00D7: _m("Razer Basilisk V3 Pro 35K", 0x1F, WAIT_NEW),
    0x009A: _m("Razer Pro Click Mini", 0x1F, WAIT_NEW),
    0x00A7: _m("Razer Naga V2 Pro", 0x1F, WAIT_NEW),
    0x00A8: _m("Razer Naga V2 Pro", 0x1F, WAIT_NEW),
    0x00B4: _m("Razer Naga V2 HyperSpeed", 0x1F, WAIT_NEW, charging=False),
    0x00B8: _m("Razer Viper V3 HyperSpeed", 0x1F, WAIT_VIPER, charging=False),
    0x00B9: _m("Razer Basilisk V3 X HyperSpeed", 0x1F, WAIT_NEW, charging=False),
    0x00D4: _m("Razer Basilisk Mobile", 0x1F, WAIT_NEW, charging=False),
    0x00D3: _m("Razer Basilisk Mobile", 0x1F, WAIT_NEW, charging=False),
    0x00BE: _m("Razer DeathAdder V4 Pro", 0x1F, WAIT_NEW),
    0x00BF: _m("Razer DeathAdder V4 Pro", 0x1F, WAIT_NEW),
    0x00E5: _m("Razer Viper V4 Pro", 0x1F, WAIT_VIPER, index=3),
    0x00E6: _m("Razer Viper V4 Pro", 0x1F, WAIT_VIPER, index=3),
    0x00C0: _m("Razer Viper V3 Pro", 0x1F, WAIT_NEW),
    0x00C1: _m("Razer Viper V3 Pro", 0x1F, WAIT_VIPER),
    0x00DE: _m("Razer Viper V3 Pro SE", 0x1F, WAIT_NEW),
    0x00DF: _m("Razer Viper V3 Pro SE", 0x1F, WAIT_VIPER),
    0x00C8: _m("Razer Pro Click V2 Vertical", 0x1F, WAIT_NEW),
    0x00C7: _m("Razer Pro Click V2 Vertical", 0x1F, WAIT_NEW),
    0x00D0: _m("Razer Pro Click V2", 0x1F, WAIT_NEW),
    0x00D1: _m("Razer Pro Click V2", 0x1F, WAIT_NEW),
    # transaction_id 0xFF
    0x001F: _m("Razer Naga Epic", 0xFF),
    0x0024: _m("Razer Mamba 2012", 0xFF),
    0x0025: _m("Razer Mamba 2012", 0xFF),
    0x0032: _m("Razer Ouroboros", 0xFF),
    0x003E: _m("Razer Naga Epic Chroma", 0xFF),
    0x003F: _m("Razer Naga Epic Chroma", 0xFF),
    0x0044: _m("Razer Mamba", 0xFF),
    0x0045: _m("Razer Mamba", 0xFF),
    0x007A: _m("Razer Viper Ultimate", 0xFF, WAIT_VIPER),
    0x007B: _m("Razer Viper Ultimate", 0xFF, WAIT_VIPER),
    0x0083: _m("Razer Basilisk X HyperSpeed", 0xFF, WAIT_NEW, charging=False),
}


# --------------------------------------------------------------------------------------------------------- pacote

def crc(report: bytes) -> int:
    value = 0
    for b in report[2:88]:
        value ^= b
    return value


def build_request(tx: int, command_id: int, command_class: int = CLASS_MISC, data_size: int = 0x02) -> bytes:
    """90 bytes do pedido (sem o id do relatório)."""
    pkt = bytearray(REPORT_LEN)
    pkt[1] = tx
    pkt[5], pkt[6], pkt[7] = data_size, command_class, command_id
    pkt[88] = crc(pkt)
    return bytes(pkt)


def parse_reply(reply: Optional[bytes], command_id: int, command_class: int = CLASS_MISC) -> Optional[int]:
    """arguments[1] de uma resposta OK ao comando pedido; None se ocupado, falhou ou é resposta de outra coisa."""
    if reply is None or len(reply) < REPORT_LEN:
        return None
    if reply[0] != STATUS_OK or reply[6] != command_class or (reply[7] & 0x7F) != (command_id & 0x7F):
        return None
    return reply[9]


def percent_from_level(level: int) -> float:
    return round(level * 100 / 255)


# ------------------------------------------------------------------------------------------------------ coleções

_MI_RE = re.compile(r"&mi_([0-9a-f]{2})", re.I)
_COL_RE = re.compile(r"&col[0-9a-f]+", re.I)


def interface_number(path: str) -> int:
    m = _MI_RE.search(path or "")
    return int(m.group(1), 16) if m else 0


def _card_key(info: hid_win.HidInfo) -> str:
    return (info.serial or _COL_RE.sub("", info.path)).lower()


def _endpoints(hids: list[hid_win.HidInfo]) -> list[hid_win.HidInfo]:
    """Uma coleção por aparelho: a da interface certa com relatório de recurso de 90 bytes (+1 do id = 91)."""
    chosen: dict[str, hid_win.HidInfo] = {}
    for info in hids:
        model = MODELS.get(info.pid) if info.vid == RAZER_VID else None
        if model is None or interface_number(info.path) != model.index:
            continue
        if info.feature_len != REPORT_LEN + 1:
            continue
        chosen.setdefault(_card_key(info), info)
    return [chosen[k] for k in sorted(chosen)]


def present_ids(hids: list[hid_win.HidInfo]) -> set[str]:
    return {f"{SOURCE}:{_card_key(i)}" for i in _endpoints(hids)}


# --------------------------------------------------------------------------------------------------------- leitura

def _ask(handle, model: Model, command_id: int, sleep=time.sleep) -> Optional[int]:
    request = b"\x00" + build_request(model.tx, command_id)
    for _ in range(RETRIES):
        if not handle.set_feature(request):
            return None
        sleep(model.wait)
        raw = handle.get_feature(0)
        if raw is None:
            return None
        reply = raw[1:]                    # tira o id 0 do relatório
        value = parse_reply(reply, command_id)
        if value is not None:
            return value
        if len(reply) < REPORT_LEN or reply[0] != STATUS_BUSY:
            return None
        sleep(BUSY_WAIT_S)
    return None


def query(info: hid_win.HidInfo, sleep=time.sleep) -> Optional[tuple[float, bool]]:
    model = MODELS[info.pid]
    with hid_win.FeatureHandle(info) as handle:
        level = _ask(handle, model, CMD_BATTERY, sleep)
        if level is None:
            return None
        charging = model.charging and _ask(handle, model, CMD_CHARGING, sleep) == 1
    return float(percent_from_level(level)), charging


_confirmed: set[int] = set()


def read_devices(hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    found = []
    for info in _endpoints(hids):
        try:
            result = query(info)
        except OSError:
            continue
        if result is None or result[0] == 0 and not result[1]:
            continue                       # sem resposta, ou receptor sem mouse no ar
        if info.pid not in _confirmed:
            _confirmed.add(info.pid)
            log.info("battery: Razer %04X (%s) respondeu: %.0f%%%s", info.pid, MODELS[info.pid].name, result[0],
                     ", carregando" if result[1] else "")
        found.append((MODELS[info.pid].name, _card_key(info), result))

    found.sort(key=lambda f: (f[0], f[1]))
    counts: dict[str, int] = {}
    for name, _k, _r in found:
        counts[name] = counts.get(name, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for name, key, (pct, charging) in found:
        seen[name] = seen.get(name, 0) + 1
        label = f"{name} {seen[name]}" if counts[name] > 1 else name
        out.append(BatteryDevice(id=f"{SOURCE}:{key}", name=label, kind=KIND_MOUSE, percent=pct, charging=charging,
                                 source=SOURCE))
    return out
