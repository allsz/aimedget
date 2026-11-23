"""
Acesso HID mínimo no Windows por ctypes (setupapi + hid.dll + kernel32), sem dependências.

- `enumerate_hid()`: lista as interfaces HID presentes com VID/PID, página/uso da coleção e tamanhos de relatório.
  Abre cada uma SEM acesso (0), o que funciona até para teclado e mouse que o sistema mantém abertos.
- `HidHandle`: abre uma interface para ler/escrever com I/O sobreposto e tempo limite (nunca bloqueia para sempre).

Ler um relatório de entrada não atrapalha ninguém: cada handle tem a própria fila no Windows.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
DIGCF_PRESENT = 0x2
DIGCF_DEVICEINTERFACE = 0x10
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wintypes.DWORD),
                ("Reserved", ctypes.c_size_t)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT), ("ProductID", wintypes.USHORT),
                ("VersionNumber", wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT), ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT), ("Reserved", wintypes.USHORT * 17),
                ("NumberLinkCollectionNodes", wintypes.USHORT), ("NumberInputButtonCaps", wintypes.USHORT),
                ("NumberInputValueCaps", wintypes.USHORT), ("NumberInputDataIndices", wintypes.USHORT),
                ("NumberOutputButtonCaps", wintypes.USHORT), ("NumberOutputValueCaps", wintypes.USHORT),
                ("NumberOutputDataIndices", wintypes.USHORT), ("NumberFeatureButtonCaps", wintypes.USHORT),
                ("NumberFeatureValueCaps", wintypes.USHORT), ("NumberFeatureDataIndices", wintypes.USHORT)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t), ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]


@dataclass(frozen=True)
class HidInfo:
    path: str
    vid: int
    pid: int
    usage_page: int
    usage: int
    input_len: int
    output_len: int
    feature_len: int
    product: str = ""
    serial: str = ""

    @property
    def is_bluetooth(self) -> bool:
        # Interfaces HID por Bluetooth clássico vêm do serviço 00001124 (HID) no BTHENUM
        return "00001124-0000-1000-8000-00805f9b34fb" in self.path.lower()


_libs = None


def _load():
    global _libs
    if _libs is not None:
        return _libs
    if not IS_WINDOWS:
        _libs = False
        return _libs
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        sapi = ctypes.WinDLL("setupapi", use_last_error=True)
        hid = ctypes.WinDLL("hid", use_last_error=True)
    except OSError:
        _libs = False
        return _libs

    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateEventW.restype = wintypes.HANDLE
    k32.ResetEvent.argtypes = [wintypes.HANDLE]
    k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                             ctypes.POINTER(OVERLAPPED)]
    k32.ReadFile.restype = wintypes.BOOL
    k32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                              ctypes.POINTER(OVERLAPPED)]
    k32.WriteFile.restype = wintypes.BOOL
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wintypes.DWORD),
                                        wintypes.BOOL]
    k32.GetOverlappedResult.restype = wintypes.BOOL
    k32.CancelIo.argtypes = [wintypes.HANDLE]
    k32.CancelIo.restype = wintypes.BOOL

    sapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    sapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    sapi.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID),
                                                 wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
    sapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    sapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                      ctypes.c_void_p, wintypes.DWORD,
                                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    sapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    sapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

    hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
    hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
    hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
    hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
    hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
    hid.HidP_GetCaps.restype = ctypes.c_long
    hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_GetProductString.restype = wintypes.BOOLEAN
    hid.HidD_GetSerialNumberString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_GetSerialNumberString.restype = wintypes.BOOLEAN
    hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_SetFeature.restype = wintypes.BOOLEAN
    hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_GetFeature.restype = wintypes.BOOLEAN
    _libs = (k32, sapi, hid)
    return _libs


def available() -> bool:
    return bool(_load())


def _open(path: str, access: int):
    k32, _sapi, _hid = _load()
    h = k32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING,
                        FILE_FLAG_OVERLAPPED, None)
    if not h or h == INVALID_HANDLE_VALUE:
        return None
    return h


def _string(fn, h) -> str:
    buf = ctypes.create_unicode_buffer(128)
    try:
        if fn(h, buf, ctypes.sizeof(buf)):
            return buf.value.strip()
    except OSError:
        pass
    return ""


def enumerate_hid(vendor_ids: Optional[set] = None) -> list[HidInfo]:
    """Interfaces HID presentes (filtradas por VID, se dado). Falhas em uma interface só a pulam."""
    libs = _load()
    if not libs:
        return []
    k32, sapi, hid = libs
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    devs = sapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not devs or devs == INVALID_HANDLE_VALUE:
        return []
    out: list[HidInfo] = []
    try:
        index = 0
        while True:
            ifdata = SP_DEVICE_INTERFACE_DATA()
            ifdata.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not sapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid), index, ctypes.byref(ifdata)):
                break
            index += 1
            need = wintypes.DWORD(0)
            sapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(ifdata), None, 0, ctypes.byref(need), None)
            if need.value <= 0:
                continue
            buf = ctypes.create_string_buffer(need.value + 4)
            # cbSize de SP_DEVICE_INTERFACE_DETAIL_DATA_W: 8 em 64 bits, 6 em 32 bits
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not sapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(ifdata), buf, need.value + 4, None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            info = _describe(path, vendor_ids)
            if info is not None:
                out.append(info)
    finally:
        sapi.SetupDiDestroyDeviceInfoList(devs)
    return out


def _describe(path: str, vendor_ids: Optional[set]) -> Optional[HidInfo]:
    k32, _sapi, hid = _load()
    h = _open(path, 0)
    if h is None:
        return None
    try:
        attrs = HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
        if not hid.HidD_GetAttributes(h, ctypes.byref(attrs)):
            return None
        if vendor_ids is not None and attrs.VendorID not in vendor_ids:
            return None
        pp = ctypes.c_void_p()
        caps = HIDP_CAPS()
        if hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
            try:
                hid.HidP_GetCaps(pp, ctypes.byref(caps))
            finally:
                hid.HidD_FreePreparsedData(pp)
        return HidInfo(
            path=path, vid=attrs.VendorID, pid=attrs.ProductID, usage_page=caps.UsagePage, usage=caps.Usage,
            input_len=caps.InputReportByteLength, output_len=caps.OutputReportByteLength,
            feature_len=caps.FeatureReportByteLength,
            product=_string(hid.HidD_GetProductString, h), serial=_string(hid.HidD_GetSerialNumberString, h),
        )
    finally:
        k32.CloseHandle(h)


class HidHandle:
    """Uma interface HID aberta para leitura (e escrita, se pedida) com tempo limite em cada operação."""

    def __init__(self, info: HidInfo, write: bool = False):
        self.info = info
        libs = _load()
        if not libs:
            raise OSError("HID indisponível")
        self._k32 = libs[0]
        self._hid = libs[2]
        access = GENERIC_READ | (GENERIC_WRITE if write else 0)
        self._h = _open(info.path, access)
        if self._h is None:
            raise OSError(f"não abriu {info.path}")
        self._event = self._k32.CreateEventW(None, True, False, None)
        self._pending = None   # (OVERLAPPED, buffer) de uma leitura ainda em curso

    def close(self):
        if self._h is not None:
            if self._pending is not None:
                self._k32.CancelIo(self._h)
                n = wintypes.DWORD(0)
                self._k32.GetOverlappedResult(self._h, ctypes.byref(self._pending[0]), ctypes.byref(n), True)
                self._pending = None
            self._k32.CloseHandle(self._h)
            self._h = None
        if self._event:
            self._k32.CloseHandle(self._event)
            self._event = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def read(self, timeout_ms: int) -> Optional[bytes]:
        """Um relatório de entrada, ou None se nada chegou no tempo. A leitura pendente continua para a próxima."""
        k32 = self._k32
        if self._pending is None:
            size = max(1, int(self.info.input_len) or 64)
            buf = ctypes.create_string_buffer(size)
            ov = OVERLAPPED()
            k32.ResetEvent(self._event)
            ov.hEvent = self._event
            n = wintypes.DWORD(0)
            ok = k32.ReadFile(self._h, buf, size, ctypes.byref(n), ctypes.byref(ov))
            if not ok and ctypes.get_last_error() != ERROR_IO_PENDING:
                return None
            self._pending = (ov, buf)
        ov, buf = self._pending
        if k32.WaitForSingleObject(self._event, max(0, int(timeout_ms))) != WAIT_OBJECT_0:
            return None
        n = wintypes.DWORD(0)
        ok = k32.GetOverlappedResult(self._h, ctypes.byref(ov), ctypes.byref(n), False)
        self._pending = None
        if not ok:
            return None
        return buf.raw[: n.value]

    def set_feature(self, data: bytes) -> bool:
        """Envia um relatório de recurso (o primeiro byte é o id), completado até o tamanho da coleção."""
        size = max(len(data), int(self.info.feature_len) or len(data))
        buf = ctypes.create_string_buffer(bytes(data).ljust(size, b"\x00"), size)
        return bool(self._hid.HidD_SetFeature(self._h, buf, size))

    def write(self, data: bytes, timeout_ms: int = 300) -> bool:
        k32 = self._k32
        size = max(len(data), int(self.info.output_len) or len(data))
        buf = ctypes.create_string_buffer(bytes(data).ljust(size, b"\x00"), size)
        ev = k32.CreateEventW(None, True, False, None)
        try:
            ov = OVERLAPPED()
            ov.hEvent = ev
            n = wintypes.DWORD(0)
            ok = k32.WriteFile(self._h, buf, size, ctypes.byref(n), ctypes.byref(ov))
            if not ok:
                if ctypes.get_last_error() != ERROR_IO_PENDING:
                    return False
                if k32.WaitForSingleObject(ev, timeout_ms) != WAIT_OBJECT_0:
                    k32.CancelIo(self._h)
                    k32.GetOverlappedResult(self._h, ctypes.byref(ov), ctypes.byref(n), True)
                    return False
            return bool(k32.GetOverlappedResult(self._h, ctypes.byref(ov), ctypes.byref(n), False))
        finally:
            k32.CloseHandle(ev)


class FeatureHandle:
    """Uma coleção aberta só para relatórios de recurso. Tenta leitura+escrita e, se o Windows segurar a coleção
    (a de mouse/teclado do sistema), abre sem acesso: HidD_SetFeature/HidD_GetFeature funcionam assim também."""

    def __init__(self, info: HidInfo):
        self.info = info
        libs = _load()
        if not libs:
            raise OSError("HID indisponível")
        self._k32, self._hid = libs[0], libs[2]
        self._h = _open(info.path, GENERIC_READ | GENERIC_WRITE) or _open(info.path, 0)
        if self._h is None:
            raise OSError(f"não abriu {info.path}")

    def close(self):
        if self._h is not None:
            self._k32.CloseHandle(self._h)
            self._h = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def set_feature(self, data: bytes) -> bool:
        size = max(len(data), int(self.info.feature_len) or len(data))
        buf = ctypes.create_string_buffer(bytes(data).ljust(size, b"\x00"), size)
        return bool(self._hid.HidD_SetFeature(self._h, buf, size))

    def get_feature(self, report_id: int = 0) -> Optional[bytes]:
        size = max(1, int(self.info.feature_len))
        buf = ctypes.create_string_buffer(size)
        buf[0] = report_id
        if not self._hid.HidD_GetFeature(self._h, buf, size):
            return None
        return buf.raw


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID), ("DevInst", wintypes.DWORD),
                ("Reserved", ctypes.c_size_t)]


DIGCF_ALLCLASSES = 0x4
SPDRP_FRIENDLYNAME = 0xC


def bluetooth_names() -> dict[str, str]:
    """Nome amigável de cada dispositivo Bluetooth clássico presente, por endereço (12 hex minúsculos).

    É o nome que o sistema mostra em Configurações ("GuliKit Controller XW"), que costuma ser melhor do que a
    string do HID ("Xbox Bluetooth Gamepad"). Qualquer falha devolve o que já deu certo (ou vazio).
    """
    libs = _load()
    if not libs:
        return {}
    _k32, sapi, _hid = libs
    try:
        sapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
        sapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
        sapi.SetupDiEnumDeviceInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(SP_DEVINFO_DATA)]
        sapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
        sapi.SetupDiGetDeviceInstanceIdW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA),
                                                     wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        sapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
        sapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA),
                                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                                           ctypes.c_void_p, wintypes.DWORD,
                                                           ctypes.POINTER(wintypes.DWORD)]
        sapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
    except (AttributeError, OSError):
        return {}
    devs = sapi.SetupDiGetClassDevsW(None, "BTHENUM", None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not devs or devs == INVALID_HANDLE_VALUE:
        return {}
    out: dict[str, str] = {}
    try:
        index = 0
        while True:
            data = SP_DEVINFO_DATA()
            data.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not sapi.SetupDiEnumDeviceInfo(devs, index, ctypes.byref(data)):
                break
            index += 1
            idbuf = ctypes.create_unicode_buffer(256)
            if not sapi.SetupDiGetDeviceInstanceIdW(devs, ctypes.byref(data), idbuf, 256, None):
                continue
            parts = idbuf.value.split("\\")
            # BTHENUM\DEV_<endereço>\...: o próprio dispositivo (os serviços têm {guid}_VID&... no lugar)
            if len(parts) < 2 or not parts[1].upper().startswith("DEV_"):
                continue
            mac = parts[1][4:].lower()
            namebuf = ctypes.create_unicode_buffer(256)
            if sapi.SetupDiGetDeviceRegistryPropertyW(devs, ctypes.byref(data), SPDRP_FRIENDLYNAME, None, namebuf,
                                                      ctypes.sizeof(namebuf), None) and namebuf.value.strip():
                out[mac] = namebuf.value.strip()
    finally:
        sapi.SetupDiDestroyDeviceInfoList(devs)
    return out
