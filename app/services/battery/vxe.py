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

from app.services.battery import hid_win, mouse_1k
from app.services.battery.models import BatteryDevice

FAMILY = mouse_1k.VXE
VXE_VID = FAMILY.vid
PIDS = FAMILY.pids
WIRED_PIDS = FAMILY.wired_pids

REPORT_ID = mouse_1k.REQUEST_ID
CMD_BATTERY = mouse_1k.CMD_BATTERY
PACKET_LEN = mouse_1k.PACKET_LEN
_checksum = mouse_1k.checksum


def build_request(command: int = CMD_BATTERY) -> bytes:
    return mouse_1k.build_request(command)


def parse_reply(reply: bytes) -> Optional[tuple[float, bool, int]]:
    return mouse_1k.parse_reply(reply, FAMILY.reply_id)


def read_devices(hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    return mouse_1k.read_family(FAMILY, hids)
