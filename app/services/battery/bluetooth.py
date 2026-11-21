"""
Bateria de qualquer dispositivo Bluetooth que o próprio Windows já conhece: é o número que aparece em Configurações >
Bluetooth ("QCY-T13 ANC 100%"). Fones informam pelo perfil mãos-livres (HFP) e dispositivos LE pelo serviço de bateria
do GATT; nos dois casos o Windows guarda a carga numa propriedade do nó do dispositivo. Ler essa propriedade não abre
nada nem acorda o dispositivo: é uma consulta ao gerenciador de dispositivos (cfgmgr32), em milissegundos.

- A carga fica no nó do serviço mãos-livres (BTHENUM\\{0000111E-...}) no Bluetooth clássico, ou no próprio nó do
  dispositivo (BTHLE\\DEV_...) no LE. Nome, tipo e "conectado" ficam no nó do dispositivo. O elo é o endereço
  Bluetooth, que está no ID de todos.
- O Windows mantém a última carga depois que o dispositivo desconecta (um fone na gaveta continua com 50%), então só
  entra quem está conectado agora.
- O tipo vem da categoria que o Windows dá ao dispositivo ("Communication.Headset.Bluetooth", "Input.Mouse"); sem ela,
  da classe Bluetooth do dispositivo; sem ela, do serviço mãos-livres.
- Pelo HFP a carga vem em degraus de 10%: sai marcada como aproximada.
- Quem já tem leitor próprio (Logitech, Sony, Switch, VXE, Xbox) é pulado pelo endereço (`skip`).
"""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable, Optional

from app.services.battery.models import (
    KIND_CONTROLLER,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_OTHER,
    KIND_PHONE,
    BatteryDevice,
)

SOURCE = "bluetooth"

# Serviços do perfil mãos-livres: AG = o PC é o "telefone" (o outro lado é um fone); HF = o PC é o fone (o outro lado
# é um celular)
HFP_AG = "0000111e"
HFP_HF = "0000111f"

_ADDRESS = re.compile(r"^[0-9a-f]{12}$")


@dataclass(frozen=True)
class Node:
    """Um nó do gerenciador de dispositivos, com as propriedades que interessam (None = ausente)."""
    instance_id: str
    battery: Optional[int] = None
    connected: Optional[bool] = None
    name: str = ""
    category: str = ""
    class_of_device: Optional[int] = None


def address_of(instance_id: str) -> Optional[str]:
    """Endereço Bluetooth (12 hex minúsculos) de um ID de instância, ou None.

    BTHENUM\\DEV_84AC609EBDE8\\...                         -> dispositivo clássico
    BTHENUM\\{0000111E-...}_VID&...\\7&2584258&0&84AC609EBDE8_C00000000  -> serviço do dispositivo
    BTHLE\\DEV_DBA3DD9CAFC0\\...                           -> dispositivo LE
    """
    parts = instance_id.split("\\")
    if len(parts) < 3:
        return None
    if parts[1].upper().startswith("DEV_"):
        addr = parts[1][4:].lower()
    else:
        addr = parts[2].split("&")[-1].split("_")[0].lower()
    return addr if _ADDRESS.match(addr) else None


def is_device_node(instance_id: str) -> bool:
    parts = instance_id.split("\\")
    return len(parts) >= 2 and parts[0].upper() in ("BTHENUM", "BTHLE") and parts[1].upper().startswith("DEV_")


def service_of(instance_id: str) -> str:
    """GUID curto (8 hex minúsculos) do serviço de um nó BTHENUM\\{...}, ou ""."""
    parts = instance_id.split("\\")
    if len(parts) >= 2 and parts[1].startswith("{"):
        return parts[1][1:9].lower()
    return ""


def kind_from(category: str, class_of_device: Optional[int], services: Iterable[str]) -> str:
    cat = (category or "").lower()
    if cat:
        if cat.startswith("input.mouse") or cat.startswith("input.touchpad"):
            return KIND_MOUSE
        if cat.startswith("input.keyboard"):
            return KIND_KEYBOARD
        if cat.startswith("input.gaming") or "gamepad" in cat or "joystick" in cat:
            return KIND_CONTROLLER
        if "headset" in cat or "headphone" in cat or "earbud" in cat:
            return KIND_HEADSET
        if cat.startswith("communication.phone"):
            return KIND_PHONE
    if class_of_device:
        major = (class_of_device >> 8) & 0x1F
        minor = (class_of_device >> 2) & 0x3F
        if major == 0x02:
            return KIND_PHONE
        if major == 0x04 and minor in (0x01, 0x02, 0x06):     # headset, mãos-livres, fone de ouvido
            return KIND_HEADSET
        if major == 0x05:
            sub = (minor >> 4) & 0x03
            if sub == 0x01:
                return KIND_KEYBOARD
            if sub == 0x02:
                return KIND_MOUSE
            if (minor & 0x0F) in (0x01, 0x02):                  # joystick, gamepad
                return KIND_CONTROLLER
    services = set(services)
    if HFP_AG in services:
        return KIND_HEADSET
    if HFP_HF in services:
        return KIND_PHONE
    return KIND_OTHER


def build_devices(nodes: Iterable[Node], skip: Optional[set] = None) -> list[BatteryDevice]:
    """Agrupa os nós por endereço e devolve um BatteryDevice por dispositivo conectado que tem carga."""
    skip = {s.lower() for s in (skip or ())}
    parents: dict[str, list[Node]] = {}     # um celular tem nó clássico E nó LE com o mesmo endereço
    battery: dict[str, tuple[int, bool]] = {}           # endereço -> (carga, veio do HFP)
    services: dict[str, set] = {}
    for node in nodes:
        addr = address_of(node.instance_id)
        if addr is None:
            continue
        if is_device_node(node.instance_id):
            parents.setdefault(addr, []).append(node)
        else:
            services.setdefault(addr, set()).add(service_of(node.instance_id))
        if node.battery is not None and 0 <= node.battery <= 100:
            from_hfp = not is_device_node(node.instance_id)
            # Com carga nos dois (raro), a do próprio dispositivo (LE, 1 em 1%) ganha da do HFP
            if addr not in battery or (battery[addr][1] and not from_hfp):
                battery[addr] = (int(node.battery), from_hfp)

    out = []
    for addr, (pct, from_hfp) in battery.items():
        group = parents.get(addr, [])
        if addr in skip or not any(p.connected is True for p in group):
            continue
        name = next((p.name.strip() for p in group if p.name.strip()), "Bluetooth")
        category = next((p.category for p in group if p.category and p.category.lower() != "unknown"), "")
        cod = next((p.class_of_device for p in group if p.class_of_device), None)
        kind = kind_from(category, cod, services.get(addr, ()))
        out.append(BatteryDevice(id=f"bt:{addr}", name=name, kind=kind, percent=float(pct),
                                 approximate=from_hfp, source=SOURCE))
    return out


def hid_addresses(hids: Iterable) -> dict[str, int]:
    """{endereço: VID} das interfaces HID por Bluetooth (clássico ou LE) já listadas pelos outros leitores."""
    out: dict[str, int] = {}
    for h in hids:
        path = h.path.lower()
        if "00001124-0000-1000-8000-00805f9b34fb" not in path and "00001812-0000-1000-8000-00805f9b34fb" not in path:
            continue
        serial = (h.serial or "").lower().replace(":", "")
        if _ADDRESS.match(serial):
            out[serial] = h.vid
            continue
        m = re.search(r"_([0-9a-f]{12})(?=[&#_\\]|$)", path)
        if m:
            out[m.group(1)] = h.vid
    return out


# --- Windows (cfgmgr32) ---

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.ULONG)]


def _key(guid: str, pid: int) -> _DEVPROPKEY:
    g = guid.strip("{}").split("-")
    tail = bytes.fromhex(g[3] + g[4])
    return _DEVPROPKEY(_GUID(int(g[0], 16), int(g[1], 16), int(g[2], 16), (ctypes.c_ubyte * 8)(*tail)), pid)


KEY_BATTERY = ("{104EA319-6EE2-4701-BD47-8DDBF425BBE5}", 2)
KEY_CONNECTED = ("{83DA6326-97A6-4088-9453-A1923F573B29}", 15)
KEY_FRIENDLY_NAME = ("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)
KEY_CATEGORY = ("{78C34FC8-104A-4ACA-9EA4-524D52996E57}", 90)
KEY_CLASS_OF_DEVICE = ("{2BD67D8B-8BEB-48D5-87E0-6CDA3428040A}", 10)

DEVPROP_TYPE_BYTE = 0x03
DEVPROP_TYPE_UINT32 = 0x07
DEVPROP_TYPE_BOOLEAN = 0x11
DEVPROP_TYPE_STRING = 0x12
DEVPROP_TYPE_STRING_LIST = 0x2012

CR_SUCCESS = 0
CR_BUFFER_SMALL = 0x1A
CM_GETIDLIST_FILTER_ENUMERATOR = 0x1
CM_GETIDLIST_FILTER_PRESENT = 0x100

_cfg = None


def _load():
    global _cfg
    if _cfg is not None:
        return _cfg
    _cfg = False
    if sys.platform != "win32":
        return _cfg
    try:
        cfg = ctypes.WinDLL("cfgmgr32")
        cfg.CM_Get_Device_ID_List_SizeW.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.LPCWSTR, wintypes.ULONG]
        cfg.CM_Get_Device_ID_List_SizeW.restype = wintypes.ULONG
        cfg.CM_Get_Device_ID_ListW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG]
        cfg.CM_Get_Device_ID_ListW.restype = wintypes.ULONG
        cfg.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR, wintypes.ULONG]
        cfg.CM_Locate_DevNodeW.restype = wintypes.ULONG
        cfg.CM_Get_DevNode_PropertyW.argtypes = [wintypes.DWORD, ctypes.POINTER(_DEVPROPKEY),
                                                 ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p,
                                                 ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
        cfg.CM_Get_DevNode_PropertyW.restype = wintypes.ULONG
        _cfg = cfg
    except (OSError, AttributeError):
        _cfg = False
    return _cfg


def _ids(cfg, enumerator: str) -> list[str]:
    flags = CM_GETIDLIST_FILTER_ENUMERATOR | CM_GETIDLIST_FILTER_PRESENT
    for _ in range(3):                                  # a lista pode crescer entre o tamanho e a leitura
        size = wintypes.ULONG(0)
        if cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), enumerator, flags) != CR_SUCCESS:
            return []
        buf = ctypes.create_unicode_buffer(size.value + 1)
        cr = cfg.CM_Get_Device_ID_ListW(enumerator, buf, size.value + 1, flags)
        if cr == CR_BUFFER_SMALL:
            continue
        if cr != CR_SUCCESS:
            return []
        raw = ctypes.wstring_at(ctypes.addressof(buf), size.value)
        return [s for s in raw.split("\0") if s]
    return []


def _prop(cfg, devinst: int, key: tuple):
    k = _key(*key)
    ptype = wintypes.ULONG(0)
    size = wintypes.ULONG(0)
    cr = cfg.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(k), ctypes.byref(ptype), None, ctypes.byref(size), 0)
    if cr != CR_BUFFER_SMALL or size.value == 0:
        return None
    buf = (ctypes.c_ubyte * size.value)()
    if cfg.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(k), ctypes.byref(ptype), buf, ctypes.byref(size),
                                    0) != CR_SUCCESS:
        return None
    t = ptype.value
    if t == DEVPROP_TYPE_BYTE:
        return buf[0]
    if t == DEVPROP_TYPE_BOOLEAN:
        return buf[0] != 0
    if t == DEVPROP_TYPE_UINT32 and size.value >= 4:
        return int.from_bytes(bytes(buf[:4]), "little")
    if t in (DEVPROP_TYPE_STRING, DEVPROP_TYPE_STRING_LIST):
        text = bytes(buf).decode("utf-16-le", errors="ignore")
        return [s for s in text.split("\0") if s] if t == DEVPROP_TYPE_STRING_LIST else text.rstrip("\0")
    return None


def _read_nodes() -> list[Node]:
    cfg = _load()
    if not cfg:
        return []
    nodes = []
    for enumerator in ("BTHENUM", "BTHLE"):
        for iid in _ids(cfg, enumerator):
            devinst = wintypes.DWORD(0)
            if cfg.CM_Locate_DevNodeW(ctypes.byref(devinst), iid, 0) != CR_SUCCESS:
                continue
            inst = devinst.value
            battery = _prop(cfg, inst, KEY_BATTERY)
            if is_device_node(iid):
                category = _prop(cfg, inst, KEY_CATEGORY)
                if isinstance(category, list):
                    category = category[0] if category else ""
                cod = _prop(cfg, inst, KEY_CLASS_OF_DEVICE)
                nodes.append(Node(iid, battery=battery if isinstance(battery, int) else None,
                                  connected=_prop(cfg, inst, KEY_CONNECTED),
                                  name=_prop(cfg, inst, KEY_FRIENDLY_NAME) or "",
                                  category=category if isinstance(category, str) else "",
                                  class_of_device=cod if isinstance(cod, int) else None))
            elif isinstance(battery, int):
                nodes.append(Node(iid, battery=battery))
            elif service_of(iid) in (HFP_AG, HFP_HF):
                nodes.append(Node(iid))                 # sem carga, mas diz o tipo
    return nodes


def read_devices(skip: Optional[set] = None) -> list[BatteryDevice]:
    """`skip`: endereços que outro leitor já entrega."""
    return build_devices(_read_nodes(), skip)
