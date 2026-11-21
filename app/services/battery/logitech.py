"""
Logitech HID++ 2.0 (o caminho do Solaar): pergunta a cada dispositivo do receptor qual o índice da função de
bateria e lê a carga.

- Receptor (Bolt C548, Unifying C52B, Lightspeed...): coleção de fabricante página 0xFF00, uso 0x02 (relatório longo,
  20 bytes, id 0x11). Dispositivos nos índices 1..6.
- Bluetooth direto: página 0xFF43, índice 0xFF.

Funções usadas: Root (índice 0) getFeature; 0x0005 DEVICE_NAME (nome e tipo); 0x1004 UNIFIED_BATTERY getStatus ou,
nos mais antigos, 0x1000 BATTERY_STATUS. O Logi Options+ pode estar aberto: cada app usa o seu "software id", e as
respostas dos outros são ignoradas.
"""

from __future__ import annotations

import time
from typing import Optional

from app.services.battery import hid_win
from app.services.battery.models import (
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_OTHER,
    BatteryDevice,
)

LOGI_VID = 0x046D
SW_ID = 0x0B
LONG = 0x11
SHORT = 0x10
REPLY_MS = 900    # dispositivo do receptor em economia de energia pode demorar para responder
# Cada pergunta usa um software id diferente (gira entre estes): uma resposta atrasada de uma pergunta anterior nunca
# casa com a atual (as perguntas ao Root têm sempre o mesmo formato). Os ids baixos ficam para outros apps.
SW_IDS = tuple(range(0x08, 0x10))

FEAT_ROOT = 0x0000
FEAT_NAME = 0x0005
FEAT_BATTERY_STATUS = 0x1000
FEAT_UNIFIED_BATTERY = 0x1004

# Tipo do 0x0005 getDeviceType -> nosso tipo
_DEVICE_TYPES = {0: KIND_KEYBOARD, 2: KIND_KEYBOARD, 3: KIND_MOUSE, 4: KIND_MOUSE, 5: KIND_MOUSE, 8: KIND_HEADSET}


def build_request(index: int, feature_index: int, function: int, params: bytes = b"", sw: int = SW_ID) -> bytes:
    head = bytes([LONG, index & 0xFF, feature_index & 0xFF, ((function & 0x0F) << 4) | (sw & 0x0F)])
    return head + bytes(params).ljust(16, b"\x00")[:16]


def match_reply(reply: bytes, index: int, feature_index: int, function: int, sw: int = SW_ID):
    """True = resposta nossa; False = erro nosso; None = não é conosco (outro app, outra pergunta, notificação)."""
    if not reply or len(reply) < 5 or reply[0] not in (LONG, SHORT) or reply[1] != (index & 0xFF):
        return None
    fn_sw = ((function & 0x0F) << 4) | (sw & 0x0F)
    if reply[2] == 0xFF and len(reply) >= 5:                        # erro HID++ 2.0
        return False if (reply[3] == feature_index and reply[4] == fn_sw) else None
    if reply[0] == SHORT and reply[2] == 0x8F:                      # erro HID++ 1.0 (ex.: dispositivo dormindo)
        return False if (reply[3] == feature_index and reply[4] == fn_sw) else None
    if reply[2] == feature_index and reply[3] == fn_sw:
        return True
    return None


def parse_unified_battery(params: bytes) -> Optional[tuple[float, bool, bool]]:
    """0x1004 getStatus -> (porcentagem, carregando, aproximada)."""
    if len(params) < 3:
        return None
    soc, levels, charge = params[0], params[1], params[2]
    charging = charge in (1, 2)
    if charge == 3:
        return 100.0, False, False
    if soc > 0:
        return float(min(100, soc)), charging, False
    # Sem porcentagem: só faixas (bit 3 cheia, 2 boa, 1 baixa, 0 crítica)
    for bit, pct in ((8, 90.0), (4, 60.0), (2, 20.0), (1, 5.0)):
        if levels & bit:
            return pct, charging, True
    return None


def parse_battery_status(params: bytes) -> Optional[tuple[float, bool, bool]]:
    """0x1000 getBatteryLevelStatus -> (porcentagem, carregando, aproximada)."""
    if len(params) < 3:
        return None
    level, status = params[0], params[2]
    if status in (5, 6, 7):        # bateria inválida, erro térmico, outro erro
        return None
    if status == 3:
        return 100.0, False, False
    if level == 0:
        return None
    return float(min(100, level)), status in (1, 2, 4), False


class _Channel:
    """As coleções HID++ de um receptor (longa para escrever/ler; curta só para ler erros de 1.0)."""

    def __init__(self, long_info: hid_win.HidInfo, short_info: Optional[hid_win.HidInfo]):
        self.long = hid_win.HidHandle(long_info, write=True)
        self.short = None
        if short_info is not None:
            try:
                self.short = hid_win.HidHandle(short_info)
            except OSError:
                self.short = None
        self._sw_next = 0

    def close(self):
        self.long.close()
        if self.short is not None:
            self.short.close()

    def _drain(self):
        """Descarta o que ficou na fila (respostas atrasadas, notificações, conversa de outros apps)."""
        for handle in (self.long, self.short):
            if handle is None:
                continue
            for _ in range(64):
                if handle.read(0) is None:
                    break

    def ask(self, index: int, feature_index: int, function: int, params: bytes = b"") -> Optional[bytes]:
        """Parâmetros da resposta (16 bytes), ou None (erro, tempo esgotado)."""
        sw = SW_IDS[self._sw_next % len(SW_IDS)]
        self._sw_next += 1
        self._drain()
        if not self.long.write(build_request(index, feature_index, function, params, sw)):
            return None
        deadline = time.monotonic() + REPLY_MS / 1000.0
        while time.monotonic() < deadline:
            for handle in (self.long, self.short):
                if handle is None:
                    continue
                reply = handle.read(15)
                if reply is None:
                    continue
                verdict = match_reply(reply, index, feature_index, function, sw)
                if verdict is True:
                    return bytes(reply[4:20])
                if verdict is False:
                    return None
        return None

    def feature_index(self, index: int, feature: int) -> int:
        reply = self.ask(index, 0x00, 0, bytes([(feature >> 8) & 0xFF, feature & 0xFF]))
        return reply[0] if reply else 0


def _device_name(ch: _Channel, index: int, cache: dict) -> tuple[str, str]:
    if index in cache:
        return cache[index]
    name, kind = "", KIND_OTHER
    fi = ch.feature_index(index, FEAT_NAME)
    if fi:
        count = ch.ask(index, fi, 0)
        if count:
            total = count[0]
            chars = b""
            while len(chars) < total:
                part = ch.ask(index, fi, 1, bytes([len(chars)]))
                if not part:
                    break
                chars += part[: max(0, total - len(chars))]
            name = chars.decode("utf-8", "ignore").strip("\x00 ").strip()
        dtype = ch.ask(index, fi, 2)
        if dtype:
            kind = _DEVICE_TYPES.get(dtype[0], KIND_OTHER)
    result = (name or "Logitech", kind)
    if name:
        cache[index] = result
    return result


def _read_battery(ch: _Channel, index: int) -> Optional[tuple[float, bool, bool]]:
    fi = ch.feature_index(index, FEAT_UNIFIED_BATTERY)
    if fi:
        reply = ch.ask(index, fi, 1)
        return parse_unified_battery(reply) if reply else None
    fi = ch.feature_index(index, FEAT_BATTERY_STATUS)
    if fi:
        reply = ch.ask(index, fi, 0)
        return parse_battery_status(reply) if reply else None
    return None


# Nomes e tipos já lidos (por receptor + índice): o nome não muda, então não pergunta toda vez
_NAME_CACHE: dict[str, dict] = {}


def _receivers(hids: list[hid_win.HidInfo]):
    """(coleção longa, coleção curta ou None, índices) de cada receptor/dispositivo HID++ presente."""
    logi = [h for h in hids if h.vid == LOGI_VID]
    out = []
    for h in logi:
        if h.usage_page == 0xFF00 and h.usage == 0x02:
            base = h.path.lower().split("&col")[0]
            short = next((s for s in logi if s.usage_page == 0xFF00 and s.usage == 0x01
                          and s.path.lower().split("&col")[0] == base), None)
            out.append((h, short, range(1, 7)))
        elif h.usage_page == 0xFF43 and h.output_len >= 20:
            out.append((h, None, (0xFF,)))
    return out


def read_devices(hids: list[hid_win.HidInfo]) -> list[BatteryDevice]:
    out: list[BatteryDevice] = []
    for long_info, short_info, indices in _receivers(hids):
        try:
            ch = _Channel(long_info, short_info)
        except OSError:
            continue
        rkey = (long_info.serial or long_info.path.lower().split("&col")[0])
        cache = _NAME_CACHE.setdefault(rkey, {})
        try:
            for index in indices:
                battery = _read_battery(ch, index)
                if battery is None:
                    continue
                name, kind = _device_name(ch, index, cache)
                pct, charging, approx = battery
                out.append(BatteryDevice(id=f"logi:{rkey}:{index}", name=name, kind=kind, percent=pct,
                                         charging=charging, approximate=approx, source="logitech"))
        finally:
            ch.close()
    return out
