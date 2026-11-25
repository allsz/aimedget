"""
Mouses AJAZZ pelo dongle "2.4G Wireless Receiver" (VID 25A7): o pacote de 17 bytes dos VXE (`mouse_1k.py`), com o
transporte diferente.

- Pedido: relatório de RECURSO 8 (`08 04 00 ... CS`) na coleção de fabricante FF02/0002.
- Resposta: relatório de ENTRADA 9 na coleção FF01 do mesmo dongle: `09 04 00 00 00 02 | nível | ... | CS`.
- Confirmado com um AJAZZ AJ139 PRO: pelo dongle FA7C `09 04 00 00 00 02 2d 00 ...` = 45%; no cabo o mouse vira
  FA7B, com o mesmo transporte, e responde `09 04 00 00 00 02 5f 01 ...` = 95%, carregando (byte 7 = 1). Os bytes
  da tensão vêm zerados nos dois casos.
"""

from __future__ import annotations

from typing import Optional

from app.services.battery import hid_win, mouse_1k
from app.services.battery.models import BatteryDevice

FAMILY = mouse_1k.AJAZZ
AJAZZ_VID = FAMILY.vid
PIDS = FAMILY.pids
device_key = mouse_1k.device_key


def build_request() -> bytes:
    return mouse_1k.build_request()


def parse_reply(reply: bytes) -> Optional[tuple[float, bool]]:
    parsed = mouse_1k.parse_reply(reply, FAMILY.reply_id)
    return None if parsed is None else parsed[:2]


def read_devices(hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    return mouse_1k.read_family(FAMILY, hids)
