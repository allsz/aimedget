"""
Mouses com o protocolo de 17 bytes dos dongles 2.4G "1K" (VXE/ATK, AJAZZ e parentes): um só código para o pacote, a
leitura e a troca dongle/cabo; cada marca entra como uma linha em FAMILIES.

O pacote (igual em todas as famílias confirmadas):
- Pedido: `ID 04 00 ... CS` (comando 04 = bateria). O último byte fecha a soma dos 17 bytes em 0x55.
- Resposta: `ID 04 00 00 00 02 | nível (0-100) | carregando (1) | tensão (2 bytes, mV, big-endian) | ... | CS`.

O que muda entre famílias é o transporte: como o pedido sai (relatório de saída ou de recurso), em que coleção a
resposta chega e com que id. Isso fica na tabela, com os PIDs confirmados com aparelho real.

Só dispositivos da tabela recebem pedidos: o mesmo comando 04 pode fazer outra coisa num firmware desconhecido.
Dispositivos fora da tabela com o mesmo formato de coleções só vão para o log (`log_candidates`), como pista do
próximo mouse a sondar com o dono por perto.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.services.battery import hid_win
from app.services.battery.models import KIND_MOUSE, BatteryDevice

log = logging.getLogger(__name__)

CMD_BATTERY = 0x04
PACKET_LEN = 17
CHECKSUM_TOTAL = 0x55          # a soma dos 17 bytes (id incluído) dá 0x55 módulo 256
REQUEST_ID = 0x08

SEND_OUTPUT = "output"         # WriteFile na coleção do pedido
SEND_FEATURE = "feature"       # HidD_SetFeature na coleção do pedido

READ_WINDOW_MS = 500

Reading = tuple[float, bool, int]   # (porcentagem, carregando, tensão em mV)


@dataclass(frozen=True)
class Family:
    source: str                         # vai em BatteryDevice.source e no prefixo do id
    vid: int
    pids: dict = field(default_factory=dict)     # pid -> nome do modelo
    wired_pids: frozenset = frozenset()          # o próprio mouse no cabo (o dongle fica mudo enquanto isso)
    send: str = SEND_OUTPUT
    request_page: int = 0xFF02
    reply_page: int = 0xFF02
    reply_id: int = REQUEST_ID

    @property
    def same_collection(self) -> bool:
        return self.request_page == self.reply_page


VXE = Family(
    source="vxe", vid=0x3554,
    # F58A = dongle "Mouse 1K"; F58C = o mouse (R1 PRO MAX) no cabo. Confirmados com aparelho.
    pids={0xF58A: "VXE Mouse", 0xF58C: "VXE Mouse"}, wired_pids=frozenset({0xF58C}),
)

AJAZZ = Family(
    source="ajazz", vid=0x25A7,
    # FA7C = dongle "2.4G Wireless Receiver" do AJ139 PRO; FA7B = o próprio mouse no cabo ("2.4G Wireless
    # Mouse&KeyBoard"), mesmo transporte. Pedido por recurso na FF02, resposta id 9 na FF01.
    pids={0xFA7C: "AJAZZ Mouse", 0xFA7B: "AJAZZ Mouse"}, wired_pids=frozenset({0xFA7B}),
    send=SEND_FEATURE, reply_page=0xFF01, reply_id=0x09,
)

FAMILIES = (VXE, AJAZZ)


# ---------------------------------------------------------------------------------------------------------- pacote

def checksum(packet: bytes) -> int:
    return (CHECKSUM_TOTAL - sum(packet[: PACKET_LEN - 1])) & 0xFF


def build_request(command: int = CMD_BATTERY, report_id: int = REQUEST_ID) -> bytes:
    pkt = bytearray(PACKET_LEN)
    pkt[0], pkt[1] = report_id, command
    pkt[PACKET_LEN - 1] = checksum(bytes(pkt))
    return bytes(pkt)


def parse_reply(reply: Optional[bytes], reply_id: int = REQUEST_ID) -> Optional[Reading]:
    """(porcentagem, carregando, tensão em mV) da resposta ao pedido de bateria, ou None se não for essa resposta."""
    if reply is None or len(reply) < PACKET_LEN or reply[0] != reply_id or reply[1] != CMD_BATTERY:
        return None
    if reply[PACKET_LEN - 1] != checksum(reply):
        return None
    level = reply[6]
    if level > 100:
        return None
    return float(level), reply[7] == 1, (reply[8] << 8) | reply[9]


# ------------------------------------------------------------------------------------------------------ coleções

# "hid#vid_25a7&pid_fa7c&mi_01&col07#7&19ddc0ef&0&0006#{...}" -> "vid_25a7&pid_fa7c&mi_01#7&19ddc0ef&0"
_PATH_RE = re.compile(r"hid#([^#]*?)(?:&col[0-9a-f]+)?#(.*)&[0-9a-f]+#", re.I)


def device_key(path: str) -> str:
    """O mesmo valor para todas as coleções de um aparelho (só o número da coleção muda no caminho)."""
    m = _PATH_RE.search(path or "")
    return (f"{m.group(1)}#{m.group(2)}" if m else path or "").lower()


def _fits_request(fam: Family, info: hid_win.HidInfo) -> bool:
    if info.usage_page != fam.request_page:
        return False
    size = info.feature_len if fam.send == SEND_FEATURE else info.output_len
    return size >= PACKET_LEN and (not fam.same_collection or info.input_len >= PACKET_LEN)


def _fits_reply(fam: Family, info: hid_win.HidInfo) -> bool:
    return info.usage_page == fam.reply_page and info.input_len >= PACKET_LEN


def _endpoints(fam: Family, hids: list[hid_win.HidInfo]) -> list[tuple[hid_win.HidInfo, hid_win.HidInfo]]:
    """(coleção do pedido, coleção da resposta) de cada aparelho da família."""
    if fam.same_collection:
        return [(i, i) for i in hids if i.vid == fam.vid and i.pid in fam.pids and _fits_request(fam, i)]
    groups: dict[str, dict[str, hid_win.HidInfo]] = {}
    for info in hids:
        if info.vid != fam.vid or info.pid not in fam.pids:
            continue
        if _fits_request(fam, info):
            groups.setdefault(device_key(info.path), {})["req"] = info
        elif _fits_reply(fam, info):
            groups.setdefault(device_key(info.path), {})["rep"] = info
    return [(g["req"], g["rep"]) for _k, g in sorted(groups.items()) if "req" in g and "rep" in g]


def _card_key(fam: Family, request: hid_win.HidInfo) -> str:
    # Coleção única: o caminho inteiro (os ids dos cartões VXE já salvos continuam os mesmos)
    return (request.serial or (request.path if fam.same_collection else device_key(request.path))).lower()


# --------------------------------------------------------------------------------------------------------- leitura

def _await_reply(handle, reply_id: int) -> Optional[Reading]:
    remaining, step = READ_WINDOW_MS, 50
    while remaining > 0:
        data = handle.read(step)
        remaining -= step
        if data is None:
            continue
        parsed = parse_reply(data, reply_id)
        if parsed is not None:
            return parsed
    return None


def _drain(handle):
    while handle.read(1) is not None:     # esvazia relatórios antigos (e deixa uma leitura armada)
        pass


def _send(fam: Family, handle) -> bool:
    request = build_request()
    return handle.set_feature(request) if fam.send == SEND_FEATURE else handle.write(request)


def query(fam: Family, request: hid_win.HidInfo, reply: hid_win.HidInfo) -> Optional[Reading]:
    if fam.same_collection:
        with hid_win.HidHandle(request, write=True) as handle:
            _drain(handle)
            return _await_reply(handle, fam.reply_id) if _send(fam, handle) else None
    with hid_win.HidHandle(reply) as listener, hid_win.HidHandle(request, write=True) as sender:
        _drain(listener)
        return _await_reply(listener, fam.reply_id) if _send(fam, sender) else None


def read_family(fam: Family, hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    found: list[tuple[str, str, Optional[Reading]]] = []
    wired: list[tuple[str, str, Optional[Reading]]] = []
    for request, reply in _endpoints(fam, hids):
        try:
            result = query(fam, request, reply)
        except OSError:
            continue
        if result is not None and request.pid not in fam.wired_pids and result[0] == 0 and not result[1]:
            # Dongle sem mouse no ar (ex.: o AJAZZ com o mouse no cabo responde nível 0). Um mouse de verdade a 0%
            # já desligou e nem chegaria a responder pelo dongle: vale como dongle mudo.
            result = None
        entry = (fam.pids[request.pid], _card_key(fam, request), result)
        (wired if request.pid in fam.wired_pids else found).append(entry)

    # No cabo o dongle fica mudo e o mouse aparece sozinho: cada mouse no cabo com leitura assume o lugar de um
    # dongle sem resposta (mesmo id, o cartão não duplica nem pisca). O que sobrar entra como dispositivo próprio.
    silent = sorted((i for i, f in enumerate(found) if f[2] is None), key=lambda i: found[i][1])
    absorbed: set[str] = set()
    for entry in sorted(wired, key=lambda w: w[1]):
        if entry[2] is not None and silent:
            i = silent.pop(0)
            found[i] = (found[i][0], found[i][1], entry[2])
            absorbed.add(f"{fam.source}:{entry[1]}")
        else:
            found.append(entry)

    # O cartão próprio do mouse no cabo (de uma leitura em que o dongle estava fora) não está mais "espetado": a
    # leitura dele agora vive no cartão do dongle, então o antigo sai na hora em vez de esperar a carência.
    _absorbed[fam.source] = absorbed

    # Mouse dormindo não responde: some da lista (o DeviceTracker segura o último valor um tempo)
    found = [f for f in found if f[2] is not None]

    # Vários aparelhos do mesmo modelo ganham número, numa ordem estável
    found.sort(key=lambda f: (f[0], f[1]))
    counts: dict[str, int] = {}
    for model, _k, _r in found:
        counts[model] = counts.get(model, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for model, key, (pct, charging, _mv) in found:
        seen[model] = seen.get(model, 0) + 1
        name = f"{model} {seen[model]}" if counts[model] > 1 else model
        out.append(BatteryDevice(id=f"{fam.source}:{key}", name=name, kind=KIND_MOUSE, percent=pct,
                                 charging=charging, source=fam.source))
    return out


_absorbed: dict[str, set[str]] = {}   # fonte -> ids de mouses no cabo cuja leitura foi para o cartão do dongle


def present_ids(hids: list[hid_win.HidInfo]) -> set[str]:
    """Ids dos cartões cujo aparelho (dongle ou mouse no cabo) ainda está espetado, responda ou não. Chamar depois
    de `read_devices` com a mesma lista: um mouse no cabo cuja leitura foi para o cartão do dongle não conta."""
    ids = {f"{fam.source}:{_card_key(fam, req)}" for fam in FAMILIES for req, _rep in _endpoints(fam, hids)}
    return ids - set().union(*_absorbed.values())


def vendor_ids() -> set[int]:
    return {f.vid for f in FAMILIES}


def read_devices(hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    out: list[BatteryDevice] = []
    for fam in FAMILIES:
        out += read_family(fam, hids)
    return out


# ------------------------------------------------------------------------------------------------------ candidatos

def candidates(hids: list[hid_win.HidInfo]) -> list[tuple[int, int, str]]:
    """(vid, pid, produto) de aparelhos fora da tabela com coleções de fabricante de 17 bytes nas páginas que as
    famílias conhecidas usam. Nada é enviado a eles."""
    known = {(f.vid, p) for f in FAMILIES for p in f.pids}
    pages = {p for f in FAMILIES for p in (f.request_page, f.reply_page)}
    seen: dict[tuple[int, int], str] = {}
    for i in hids:
        if (i.vid, i.pid) in known or i.usage_page not in pages:
            continue
        if max(i.input_len, i.output_len, i.feature_len) == PACKET_LEN:
            seen.setdefault((i.vid, i.pid), i.product)
    return [(v, p, name) for (v, p), name in sorted(seen.items())]


_logged_candidates = False


def log_candidates(enumerate_all=None) -> None:
    """Uma vez por execução: varre todos os HID e registra os candidatos (enumerar tudo a cada leitura sairia caro)."""
    global _logged_candidates
    if _logged_candidates:
        return
    _logged_candidates = True
    try:
        hids = (enumerate_all or hid_win.enumerate_hid)()
    except Exception:  # noqa: BLE001 - é só uma pista no log
        return
    for vid, pid, name in candidates(hids):
        log.info("battery: possível mouse 1K fora da tabela: %04X:%04X %s", vid, pid, name)
