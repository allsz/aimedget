"""
PerformanceService - Coleta nativa e leve de métricas de hardware no Windows (CPU, GHz, GPU, VRAM, RAM).

- 100% APIs nativas via ctypes (kernel32, pdh, dxgi, winreg): zero dependências externas, zero WMI.
- Roda em uma thread dedicada em 1 Hz (1 amostra/s) e só fica ativa enquanto o widget estiver visível.
- Degrada com elegância fora do Windows ou em ambientes sem GPU dedicada (valores opcionais como None).
"""

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import re
import sys
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

IS_WINDOWS = sys.platform == "win32"
SAMPLE_INTERVAL_S = 1.0

_PDH_FMT_DOUBLE = 0x00000200
_PDH_MORE_DATA = 0x800007D2
_DXGI_ADAPTER_FLAG_SOFTWARE = 2


@dataclass(frozen=True)
class PerformanceSnapshot:
    cpu_pct: Optional[float] = None
    cpu_ghz: Optional[float] = None
    gpu_pct: Optional[float] = None
    gpu_name: str = ""
    vram_pct: Optional[float] = None
    vram_used_gb: Optional[float] = None
    vram_total_gb: Optional[float] = None
    ram_pct: Optional[float] = None
    ram_used_gb: Optional[float] = None
    ram_total_gb: Optional[float] = None
    pid_3d_gpu: tuple[tuple[int, float], ...] = ()


# --- Funções puras (fáceis de testar sem hardware) ---


def compute_cpu_percent(
    prev: Optional[tuple[int, int, int]],
    curr: tuple[int, int, int],
) -> Optional[float]:
    """Calcula uso total de CPU (0..100) a partir de dois tuples (idle, kernel, user) de GetSystemTimes."""
    if prev is None:
        return None
    d_idle = curr[0] - prev[0]
    d_kernel = curr[1] - prev[1]
    d_user = curr[2] - prev[2]
    total = d_kernel + d_user
    if total <= 0:
        return 0.0
    busy = max(0, total - d_idle)
    return min(100.0, max(0.0, (busy / total) * 100.0))


def shorten_gpu_name(name: str) -> str:
    """Enxuga prefixos longos ('NVIDIA GeForce RTX 3080 Ti' -> 'RTX 3080 Ti') para caber no cartão."""
    clean = (name or "").strip()
    for prefix in ("NVIDIA GeForce ", "NVIDIA ", "AMD Radeon(TM) ", "AMD Radeon ", "Intel(R) ", "Intel "):
        if clean.startswith(prefix):
            clean = clean[len(prefix):].strip()
            break
    clean = re.sub(r"\s*\(TM\)|\s*\(R\)", "", clean).strip()
    return clean


def aggregate_gpu_utilization(
    items: list[tuple[str, float]],
    luid_token: str = "",
) -> Optional[float]:
    r"""
    Agrega `\GPU Engine(*)\Utilization Percentage` como o Gerenciador de Tarefas:
    soma por tipo de engine (`engtype_3D`, `engtype_VideoEncode`, etc.) e devolve o pico (0..100).
    """
    if not items:
        return None
    luid_low = luid_token.lower()
    by_engine: dict[str, float] = {}
    matched_any = False
    for name, value in items:
        if luid_low and luid_low not in name.lower():
            continue
        matched_any = True
        idx = name.rfind("engtype_")
        engine = name[idx + 8:] if idx >= 0 else "other"
        by_engine[engine] = by_engine.get(engine, 0.0) + max(0.0, float(value))
    if not matched_any:
        return None
    peak = max(by_engine.values(), default=0.0)
    return min(100.0, max(0.0, peak))


_PID_RE = re.compile(r"pid_(\d+)_", re.IGNORECASE)


def extract_pid_3d_utilization(
    items: list[tuple[str, float]],
    luid_token: str = "",
    min_pct: float = 0.5,
) -> dict[int, float]:
    """Extrai uso da engine 3D por PID a partir dos mesmos itens PDH já coletados (custo extra zero)."""
    if not items:
        return {}
    luid_low = luid_token.lower()
    per_pid: dict[int, float] = {}
    for name, value in items:
        low = name.lower()
        if "engtype_3d" not in low:
            continue
        if luid_low and luid_low not in low:
            continue
        m = _PID_RE.search(low)
        if not m:
            continue
        val = max(0.0, float(value))
        if val <= 0.0:
            continue
        pid = int(m.group(1))
        per_pid[pid] = per_pid.get(pid, 0.0) + val
    return {pid: min(100.0, v) for pid, v in per_pid.items() if v >= min_pct}


def match_vram_usage(
    items: list[tuple[str, float]],
    luid_token: str = "",
) -> Optional[float]:
    """Extrai o uso dedicado de VRAM (em bytes) do adaptador principal."""
    if not items:
        return None
    luid_low = luid_token.lower()
    if luid_low:
        for name, value in items:
            if luid_low in name.lower():
                return max(0.0, float(value))
    return max((max(0.0, float(v)) for _n, v in items), default=None)


# --- Estruturas e leitores Win32 ---


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint),
        ("DeviceId", ctypes.c_uint),
        ("SubSysId", ctypes.c_uint),
        ("Revision", ctypes.c_uint),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
        ("Flags", ctypes.c_uint),
    ]


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _PDH_FMT_COUNTERVALUE)]


def _filetime_int(ft: _FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _read_cpu_base_mhz() -> float:
    if not IS_WINDOWS:
        return 0.0
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            mhz, _ = winreg.QueryValueEx(key, "~MHz")
            return float(mhz)
    except OSError:
        return 0.0


def _detect_primary_gpu() -> tuple[str, int, str]:
    """Retorna (nome_curto, vram_total_bytes, luid_token) da GPU física principal via DXGI."""
    if not IS_WINDOWS:
        return "", 0, ""
    try:
        dxgi = ctypes.WinDLL("dxgi")
        iid = _GUID(
            0x770AAE78, 0xF26F, 0x4DBA,
            (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
        )
        factory = ctypes.c_void_p()
        if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0 or not factory.value:
            return "", 0, ""

        vtbl = ctypes.cast(
            ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p)).contents,
            ctypes.POINTER(ctypes.c_void_p),
        )
        enum_adapters1 = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
        )(vtbl[12])
        release_factory = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])

        best = ("", 0, "")
        idx = 0
        try:
            while True:
                adapter = ctypes.c_void_p()
                if enum_adapters1(factory, idx, ctypes.byref(adapter)) != 0 or not adapter.value:
                    break
                avtbl = ctypes.cast(
                    ctypes.cast(adapter, ctypes.POINTER(ctypes.c_void_p)).contents,
                    ctypes.POINTER(ctypes.c_void_p),
                )
                get_desc1 = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_DXGI_ADAPTER_DESC1)
                )(avtbl[10])
                release_adapter = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(avtbl[2])
                desc = _DXGI_ADAPTER_DESC1()
                try:
                    if get_desc1(adapter, ctypes.byref(desc)) == 0:
                        if not (desc.Flags & _DXGI_ADAPTER_FLAG_SOFTWARE):
                            vram = int(desc.DedicatedVideoMemory)
                            luid = f"luid_0x{desc.AdapterLuid.HighPart & 0xFFFFFFFF:08X}_0x{desc.AdapterLuid.LowPart:08X}"
                            if not best[0] or vram > best[1]:
                                best = (shorten_gpu_name(desc.Description), vram, luid)
                finally:
                    release_adapter(adapter)
                idx += 1
        finally:
            release_factory(factory)
        return best
    except Exception:
        return "", 0, ""


class _Win32Sampler:
    """Mantém a query PDH aberta enquanto o widget está visível e lê todos os contadores em 1 chamada."""

    def __init__(self):
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if IS_WINDOWS else None
        self._pdh = ctypes.WinDLL("pdh", use_last_error=True) if IS_WINDOWS else None
        self._prev_cpu: Optional[tuple[int, int, int]] = None
        self._base_mhz = _read_cpu_base_mhz()
        self._gpu_name, self._vram_total_bytes, self._gpu_luid = _detect_primary_gpu()

        self._query = wintypes.HANDLE()
        self._c_cpu_perf = wintypes.HANDLE()
        self._c_gpu_eng = wintypes.HANDLE()
        self._c_vram = wintypes.HANDLE()
        self._pdh_ready = False
        self._open_pdh()

    def _open_pdh(self):
        if not self._pdh:
            return
        try:
            if (self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) & 0xFFFFFFFF) != 0:
                return
            self._pdh.PdhAddEnglishCounterW(
                self._query, r"\Processor Information(_Total)\% Processor Performance", 0, ctypes.byref(self._c_cpu_perf)
            )
            self._pdh.PdhAddEnglishCounterW(
                self._query, r"\GPU Engine(*)\Utilization Percentage", 0, ctypes.byref(self._c_gpu_eng)
            )
            self._pdh.PdhAddEnglishCounterW(
                self._query, r"\GPU Adapter Memory(*)\Dedicated Usage", 0, ctypes.byref(self._c_vram)
            )
            self._pdh.PdhCollectQueryData(self._query)
            self._pdh_ready = True
        except Exception:
            self._pdh_ready = False

    def close(self):
        if self._pdh and self._query.value:
            try:
                self._pdh.PdhCloseQuery(self._query)
            except Exception:
                pass
            self._query = wintypes.HANDLE()
            self._pdh_ready = False

    def _read_cpu_times(self) -> Optional[tuple[int, int, int]]:
        if not self._kernel32:
            return None
        idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
        if not self._kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return (_filetime_int(idle), _filetime_int(kernel), _filetime_int(user))

    def _read_ram(self) -> tuple[Optional[float], Optional[float], Optional[float]]:
        if not self._kernel32:
            return None, None, None
        ms = _MEMORYSTATUSEX(dwLength=ctypes.sizeof(_MEMORYSTATUSEX))
        if not self._kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)) or ms.ullTotalPhys == 0:
            return None, None, None
        total_gb = ms.ullTotalPhys / (1024.0 ** 3)
        used_gb = (ms.ullTotalPhys - ms.ullAvailPhys) / (1024.0 ** 3)
        pct = min(100.0, max(0.0, (used_gb / total_gb) * 100.0))
        return pct, used_gb, total_gb

    def _read_pdh_scalar(self, counter: wintypes.HANDLE) -> Optional[float]:
        if not self._pdh or not counter.value:
            return None
        val = _PDH_FMT_COUNTERVALUE()
        rc = self._pdh.PdhGetFormattedCounterValue(counter, _PDH_FMT_DOUBLE, None, ctypes.byref(val)) & 0xFFFFFFFF
        if rc != 0 or val.CStatus != 0:
            return None
        return float(val.doubleValue)

    def _read_pdh_array(self, counter: wintypes.HANDLE) -> list[tuple[str, float]]:
        if not self._pdh or not counter.value:
            return []
        buf_size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        rc = (
            self._pdh.PdhGetFormattedCounterArrayW(
                counter, _PDH_FMT_DOUBLE, ctypes.byref(buf_size), ctypes.byref(count), None
            )
            & 0xFFFFFFFF
        )
        if rc != _PDH_MORE_DATA or buf_size.value == 0:
            return []
        buf = (ctypes.c_byte * buf_size.value)()
        rc = (
            self._pdh.PdhGetFormattedCounterArrayW(
                counter, _PDH_FMT_DOUBLE, ctypes.byref(buf_size), ctypes.byref(count), ctypes.byref(buf)
            )
            & 0xFFFFFFFF
        )
        if rc != 0:
            return []
        items = ctypes.cast(buf, ctypes.POINTER(_PDH_FMT_COUNTERVALUE_ITEM_W))
        out = []
        for i in range(count.value):
            if items[i].FmtValue.CStatus == 0:
                out.append((items[i].szName or "", float(items[i].FmtValue.doubleValue)))
        return out

    def prime(self):
        """Primeira leitura (base para deltas de CPU e PDH)."""
        self._prev_cpu = self._read_cpu_times()

    def sample(self) -> PerformanceSnapshot:
        curr_cpu = self._read_cpu_times()
        cpu_pct = compute_cpu_percent(self._prev_cpu, curr_cpu) if curr_cpu is not None else None
        if curr_cpu is not None:
            self._prev_cpu = curr_cpu

        ram_pct, ram_used_gb, ram_total_gb = self._read_ram()

        cpu_ghz: Optional[float] = None
        gpu_pct: Optional[float] = None
        pid_3d: tuple[tuple[int, float], ...] = ()
        vram_pct: Optional[float] = None
        vram_used_gb: Optional[float] = None
        vram_total_gb: Optional[float] = (
            self._vram_total_bytes / (1024.0 ** 3) if self._vram_total_bytes > 0 else None
        )

        if self._pdh_ready and self._pdh:
            try:
                if (self._pdh.PdhCollectQueryData(self._query) & 0xFFFFFFFF) == 0:
                    perf_pct = self._read_pdh_scalar(self._c_cpu_perf)
                    if perf_pct is not None and self._base_mhz > 0:
                        cpu_ghz = (self._base_mhz * (perf_pct / 100.0)) / 1000.0

                    gpu_items = self._read_pdh_array(self._c_gpu_eng)
                    gpu_pct = aggregate_gpu_utilization(gpu_items, self._gpu_luid)
                    pid_3d = tuple(extract_pid_3d_utilization(gpu_items, self._gpu_luid).items())

                    vram_items = self._read_pdh_array(self._c_vram)
                    used_bytes = match_vram_usage(vram_items, self._gpu_luid)
                    if used_bytes is not None:
                        vram_used_gb = used_bytes / (1024.0 ** 3)
                        if self._vram_total_bytes > 0:
                            vram_pct = min(100.0, max(0.0, (used_bytes / self._vram_total_bytes) * 100.0))
            except Exception:
                pass

        return PerformanceSnapshot(
            cpu_pct=cpu_pct,
            cpu_ghz=cpu_ghz,
            gpu_pct=gpu_pct,
            gpu_name=self._gpu_name,
            vram_pct=vram_pct,
            vram_used_gb=vram_used_gb,
            vram_total_gb=vram_total_gb,
            ram_pct=ram_pct,
            ram_used_gb=ram_used_gb,
            ram_total_gb=ram_total_gb,
            pid_3d_gpu=pid_3d,
        )


class PerformanceService(QObject):
    """Worker em segundo plano que emite `snapshot_ready` a cada 1 segundo enquanto ativo."""

    snapshot_ready = Signal(object)   # PerformanceSnapshot

    def __init__(self, parent=None, interval_s: float = SAMPLE_INTERVAL_S):
        super().__init__(parent)
        self._interval_s = max(0.25, float(interval_s))
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="AimedgetPerfSampler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread = None

    def _run(self):
        sampler = _Win32Sampler()
        try:
            sampler.prime()
            # Primeira leitura rápida (~250ms) para o cartão não ficar vazio por 1s inteiro ao abrir
            if self._stop_event.wait(0.25):
                return
            while not self._stop_event.is_set():
                snap = sampler.sample()
                if not self._stop_event.is_set():
                    self.snapshot_ready.emit(snap)
                if self._stop_event.wait(self._interval_s):
                    break
        finally:
            sampler.close()
