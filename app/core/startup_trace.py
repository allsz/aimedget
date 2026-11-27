"""
Registro do tempo de inicialização: quanto o app leva do início do PROCESSO até cada etapa.

Cada partida acrescenta UMA linha a %LOCALAPPDATA%/Aimedget/startup_timing.log (mantém as últimas 40), por exemplo:

    2026-11-26 08:01:12 | v1.1.2 frozen | minimized | boot+38s logon+9s | proc->python=412 imports=655 qapp=720 ... ready=2210

- `logon+Ns`: há quanto tempo o usuário entrou. Se o app abre com `logon+` alto no arranque, foi o Windows que
  demorou a lançá-lo (e não o app a subir).
- `boot+Ns`: há quanto tempo o Windows estava ligado. Partida do logon = número pequeno (a máquina ainda disputa
  disco e CPU com os outros apps); abrir à mão depois = número grande. É o que separa "partida fria" de "morna".
- `proc->python`: do processo existir até o primeiro código Python do app (bootloader, descompactação, interpretador).
- Os demais valores são milissegundos acumulados desde a criação do processo (não desde o `main`).

Custo: um par de chamadas de relógio por etapa e uma gravação de uma linha no fim. Nunca levanta exceção.
"""

from __future__ import annotations

import os
import sys
import time

_LOG_NAME = "startup_timing.log"
_KEEP_LINES = 40

_marks: list[tuple[str, float]] = []
_start_wall = time.time()
_start_perf = time.perf_counter()
_proc_offset_ms: float | None = None   # quanto o processo já tinha vivido quando este módulo carregou
_finished = False
_extras: list[str] = []
_last_stamp = ""


def _process_age_ms() -> float | None:
    """Idade do processo (ms) pela hora de criação que o próprio Windows guarda. None fora do Windows."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k32.GetProcessTimes.restype = wintypes.BOOL
        creation, exit_, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(k32.GetCurrentProcess(), ctypes.byref(creation), ctypes.byref(exit_),
                                   ctypes.byref(kernel), ctypes.byref(user)):
            return None
        now = wintypes.FILETIME()
        k32.GetSystemTimeAsFileTime(ctypes.byref(now))

        def _ticks(ft) -> int:
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

        return max(0.0, (_ticks(now) - _ticks(creation)) / 10_000.0)   # unidades de 100 ns
    except Exception:
        return None


def _uptime_s() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        return int(k32.GetTickCount64() // 1000)
    except Exception:
        return None


def _since_logon_s() -> int | None:
    """Segundos desde que a sessão do usuário entrou (logon). No arranque do Windows diz quanto o Windows esperou
    antes de lançar o app; None se o Windows não informar."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _WTSINFOW(ctypes.Structure):
            _fields_ = [
                ("State", ctypes.c_int), ("SessionId", wintypes.DWORD),
                ("IncomingBytes", wintypes.DWORD), ("OutgoingBytes", wintypes.DWORD),
                ("IncomingFrames", wintypes.DWORD), ("OutgoingFrames", wintypes.DWORD),
                ("IncomingCompressedBytes", wintypes.DWORD), ("OutgoingCompressedBytes", wintypes.DWORD),
                ("WinStationName", ctypes.c_wchar * 32), ("Domain", ctypes.c_wchar * 17),
                ("UserName", ctypes.c_wchar * 21),
                ("ConnectTime", ctypes.c_int64), ("DisconnectTime", ctypes.c_int64),
                ("LastInputTime", ctypes.c_int64), ("LogonTime", ctypes.c_int64), ("CurrentTime", ctypes.c_int64),
            ]

        wts = ctypes.windll.wtsapi32
        buf = ctypes.c_void_p()
        size = wintypes.DWORD()
        WTS_CURRENT_SESSION, WTS_SESSION_INFO = 0xFFFFFFFF, 24
        wts.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
        if not wts.WTSQuerySessionInformationW(None, WTS_CURRENT_SESSION, WTS_SESSION_INFO,
                                               ctypes.byref(buf), ctypes.byref(size)):
            return None
        try:
            info = ctypes.cast(buf, ctypes.POINTER(_WTSINFOW)).contents
            if info.LogonTime <= 0 or info.CurrentTime < info.LogonTime:
                return None
            return int((info.CurrentTime - info.LogonTime) // 10_000_000)   # unidades de 100 ns
        finally:
            wts.WTSFreeMemory(buf)
    except Exception:
        return None


_proc_offset_ms = _process_age_ms()


def mark(name: str) -> None:
    """Anota uma etapa. Chamar de novo com o mesmo nome apenas acrescenta outra anotação."""
    _marks.append((name, time.perf_counter()))


def _fmt_extra(name: str, value_ms: float) -> str:
    return f"{name}={value_ms:.0f}"


def amend(name: str, value_ms: float) -> None:
    """Acrescenta um valor avulso (ex.: custo de montar o Hub). Antes de `finish` entra na linha; depois, é
    anexado à linha já gravada desta partida."""
    text = _fmt_extra(name, value_ms)
    if not _finished:
        _extras.append(text)
        return
    try:
        path = _log_path()
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if lines and lines[-1].startswith(_last_stamp):
            lines[-1] += " " + text
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def _log_path() -> str:
    from app.core.paths import get_app_data_dir

    return os.path.join(get_app_data_dir(), _LOG_NAME)


def _line(label: str) -> str:
    from app.core.version import __version__

    off = _proc_offset_ms or 0.0
    parts = []
    if _proc_offset_ms is not None:
        parts.append(f"proc->python={_proc_offset_ms:.0f}")
    for name, t in _marks:
        parts.append(f"{name}={(t - _start_perf) * 1000 + off:.0f}")
    parts.extend(_extras)
    up = _uptime_s()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_start_wall))
    build = "frozen" if getattr(sys, "frozen", False) else "dev"
    lg = _since_logon_s()
    boot = (f"boot+{up}s" if up is not None else "boot+?") + (f" logon+{lg}s" if lg is not None else " logon+?")
    return f"{stamp} | v{__version__} {build} | {label} | {boot} | " + " ".join(parts)


def finish(label: str) -> str | None:
    """Fecha a medição desta partida (só a primeira chamada vale) e grava a linha. Devolve a linha, ou None."""
    global _finished, _last_stamp
    if _finished:
        return None
    _finished = True
    try:
        line = _line(label)
        _last_stamp = line.split(" | ", 1)[0]
    except Exception:
        return None
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        old: list[str] = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                old = f.read().splitlines()
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join((old + [line])[-_KEEP_LINES:]) + "\n")
    except Exception:
        pass
    return line
