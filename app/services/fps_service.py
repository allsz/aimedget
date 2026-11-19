"""
FpsService - Contador de FPS opcional (somente durante jogos) baseado no Intel PresentMon (MIT).

- Zero injeção de DLL / 100% seguro para anti-cheats (usa ETW via PresentMon).
- Só inicia o PresentMon quando detecta um jogo 3D em tela cheia/borderless ou Lossless Scaling em primeiro plano;
  na área de trabalho fica completamente desligado (0% de uso de CPU).
- Suporte dedicado a Lossless Scaling (`LosslessScaling.exe`): lê o FPS de saída (gerado) e, quando o jogo base
  também está ativo na GPU 3D, reporta ambos (`base_fps` / `fps`).
- Checagem e concessão de permissão independentes do idioma do Windows via SID bem conhecido `S-1-5-32-559`
  (Performance Log Users / Usuários de log de desempenho).
"""

from collections import deque
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import getpass
import os
import subprocess
import sys
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from app.core.paths import get_presentmon_path

IS_WINDOWS = sys.platform == "win32"

_SID_ADMIN = "S-1-5-32-544"
_SID_PERF_LOG_USERS = "S-1-5-32-559"
_SESSION_NAME = "AimedgetFPS"
_LOSSLESS_EXE = "losslessscaling.exe"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MONITOR_DEFAULTTONEAREST = 2
_GRACE_STOP_S = 3.0

# Apps de desktop/navegadores/IDEs/wallpapers que usam aceleração 3D sem serem jogos
_IGNORED_EXECUTABLES = frozenset({
    "explorer.exe", "dwm.exe", "shellexperiencehost.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "lockapp.exe", "applicationframehost.exe", "systemsettings.exe", "taskmgr.exe",
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe",
    "code.exe", "cursor.exe", "windsurf.exe", "antigravity.exe", "antigravity ide.exe",
    "devenv.exe", "idea64.exe", "pycharm64.exe", "rider64.exe",
    "windowsterminal.exe", "powershell.exe", "cmd.exe",
    "python.exe", "pythonw.exe", "aimedget.exe",
    "discord.exe", "spotify.exe", "slack.exe", "teams.exe", "ms-teams.exe",
    "notion.exe", "figma.exe", "telegram.exe", "whatsapp.exe",
    "obs64.exe", "vlc.exe", "mpv.exe",
    "wallpaper64.exe", "wallpaper32.exe", "webwallpaper32.exe",
    "snippingtool.exe", "screenclippinghost.exe", "sharex.exe", "gamebar.exe",
    "steamwebhelper.exe", "epicwebhelper.exe",
})


@dataclass(frozen=True)
class FpsReading:
    fps: Optional[float] = None
    base_fps: Optional[float] = None
    app_name: str = ""
    is_lossless_scaling: bool = False


@dataclass(frozen=True)
class GameTarget:
    pid: int
    exe_name: str
    is_lossless_scaling: bool = False
    base_pid: Optional[int] = None
    extra_pids: tuple[int, ...] = ()


# --- Permissões do Windows (SID S-1-5-32-559, independente de idioma) ---


def _check_sid_membership(sid_str: str) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
        advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
        advapi32.CheckTokenMembership.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL)]
        advapi32.CheckTokenMembership.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]

        psid = ctypes.c_void_p()
        if not advapi32.ConvertStringSidToSidW(sid_str, ctypes.byref(psid)):
            return False
        try:
            member = wintypes.BOOL(0)
            if not advapi32.CheckTokenMembership(None, psid, ctypes.byref(member)):
                return False
            return bool(member.value)
        finally:
            kernel32.LocalFree(psid)
    except Exception:
        return False


def perf_log_users_group_name() -> str:
    """Resolve o nome localizado do grupo Performance Log Users (ex: 'Usuários de log de desempenho')."""
    if not IS_WINDOWS:
        return "Performance Log Users"
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
        advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
        advapi32.LookupAccountSidW.argtypes = [
            wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.LookupAccountSidW.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]

        psid = ctypes.c_void_p()
        if not advapi32.ConvertStringSidToSidW(_SID_PERF_LOG_USERS, ctypes.byref(psid)):
            return "Performance Log Users"
        try:
            name_buf = ctypes.create_unicode_buffer(256)
            dom_buf = ctypes.create_unicode_buffer(256)
            cch_name = wintypes.DWORD(256)
            cch_dom = wintypes.DWORD(256)
            sid_use = wintypes.DWORD(0)
            if advapi32.LookupAccountSidW(
                None, psid, name_buf, ctypes.byref(cch_name), dom_buf, ctypes.byref(cch_dom), ctypes.byref(sid_use)
            ):
                return name_buf.value or "Performance Log Users"
        finally:
            kernel32.LocalFree(psid)
    except Exception:
        pass
    return "Performance Log Users"


def has_etw_fps_permission() -> bool:
    """True se o usuário atual é Administrador ou membro de Performance Log Users."""
    return _check_sid_membership(_SID_ADMIN) or _check_sid_membership(_SID_PERF_LOG_USERS)


def request_fps_permission() -> bool:
    """
    Solicita UAC uma única vez para adicionar o usuário atual ao grupo Performance Log Users.
    Retorna True se o comando elevado foi disparado (exige novo login no Windows para efetivar no token).
    """
    if not IS_WINDOWS:
        return False
    group = perf_log_users_group_name()
    user = os.environ.get("USERNAME") or getpass.getuser()
    if not user:
        return False
    params = f'localgroup "{group}" "{user}" /add'
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "net", params, None, 0)
        return int(rc) > 32
    except Exception:
        return False


def fps_capability_status() -> str:
    """Retorna 'missing_binary' | 'needs_permission' | 'ready'."""
    if not get_presentmon_path():
        return "missing_binary"
    if not has_etw_fps_permission():
        return "needs_permission"
    return "ready"


# --- Detecção de jogo / Lossless Scaling em primeiro plano ---


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _exe_name_for_pid(pid: int) -> str:
    if not IS_WINDOWS or pid <= 0:
        return ""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return ""
    return ""


def _is_window_fullscreen(user32, hwnd: int) -> bool:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    mon = user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if not mon:
        return False
    mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return False
    mw = max(1, mi.rcMonitor.right - mi.rcMonitor.left)
    mh = max(1, mi.rcMonitor.bottom - mi.rcMonitor.top)
    ww = rect.right - rect.left
    wh = rect.bottom - rect.top
    return (ww >= mw * 0.95) and (wh >= mh * 0.95)


def _foreground_window_info() -> tuple[int, str, bool]:
    """Retorna (pid, exe_name, is_fullscreen_or_borderless) da janela em primeiro plano."""
    if not IS_WINDOWS:
        return 0, "", False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return 0, "", False
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return 0, "", False
        is_fs = _is_window_fullscreen(user32, hwnd)
        return int(pid.value), _exe_name_for_pid(int(pid.value)), is_fs
    except Exception:
        return 0, "", False


def _fullscreen_windows() -> list[tuple[int, str]]:
    """
    Lista janelas visíveis (não minimizadas) em tela cheia/borderless em QUALQUER monitor.
    Permite detectar jogos no monitor 1 mesmo quando o usuário clicou no monitor 2 (ou no widget),
    e jogos indie/2D/OpenGL que usam pouca GPU em placas fortes.
    """
    if not IS_WINDOWS:
        return []
    found: list[tuple[int, str]] = []
    seen: set[int] = set()
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            if not _is_window_fullscreen(user32, hwnd):
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            p = int(pid.value)
            if p <= 0 or p in seen:
                return True
            exe = _exe_name_for_pid(p)
            if not exe:
                return True
            seen.add(p)
            found.append((p, exe))
            return True

        user32.EnumWindows(enum_proc(_visit), 0)
    except Exception:
        pass
    return found


def _sibling_pids_for_exe(exe_name: str, main_pid: int, pid_exes: dict[int, str]) -> tuple[int, ...]:
    """Coleta PIDs extras com o mesmo executável (ex: subprocesso GPU de jogos Electron/Chromium/NW.js)."""
    low = (exe_name or "").lower()
    if not low:
        return ()
    extras = [p for p, e in pid_exes.items() if p != main_pid and (e or "").lower() == low]
    return tuple(extras[:3])


def _best_3d_game_pid(
    pid_3d_gpu: dict[int, float],
    pid_exes: dict[int, str],
    exclude_pid: int = 0,
    min_pct: float = 3.0,
) -> Optional[tuple[int, str]]:
    """Retorna (pid, exe_name) do processo não-ignorado com maior uso da engine 3D."""
    candidates: list[tuple[float, int, str]] = []
    for pid, pct in pid_3d_gpu.items():
        if pid == exclude_pid or pct < min_pct:
            continue
        exe = pid_exes.get(pid, "")
        if not exe or exe.lower() in _IGNORED_EXECUTABLES or exe.lower() == _LOSSLESS_EXE:
            continue
        candidates.append((pct, pid, exe))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _pct, pid, exe = candidates[0]
    return pid, exe


def detect_game_target(
    fg_pid: int,
    fg_exe: str,
    fg_fullscreen: bool,
    pid_3d_gpu: dict[int, float],
    pid_exes: Optional[dict[int, str]] = None,
    own_pid: int = 0,
    prev_target: Optional[GameTarget] = None,
    fullscreen_windows: Optional[list[tuple[int, str]]] = None,
) -> Optional[GameTarget]:
    """
    Decide se há um jogo ativo para monitorar com PresentMon:
    1. `LosslessScaling.exe` em primeiro plano (ou em tela cheia em algum monitor) -> LSFG + jogo base.
    2. Janela em primeiro plano em tela cheia/borderless (fora da lista de desktop) -> detecta mesmo jogos indie/2D
       ou OpenGL que reportem 0% de `engtype_3D` no PDH.
    3. Qualquer janela em tela cheia/borderless não-ignorada em outro monitor (ex: jogo no monitor 1 enquanto o
       usuário clica no widget ou na IDE no monitor 2).
    4. Jogo em modo janela com uso ativo de GPU 3D (>= 5%).
    5. Fallback: se o usuário clicou no widget, mantém o alvo anterior enquanto ativo.
    """
    exes = pid_exes or {}
    fs_wins = fullscreen_windows or []
    low = (fg_exe or "").lower()

    # 1. Lossless Scaling (em primeiro plano ou fullscreen em algum monitor)
    ls_pid = fg_pid if (fg_pid > 0 and low == _LOSSLESS_EXE) else 0
    if not ls_pid:
        for p, e in fs_wins:
            if (e or "").lower() == _LOSSLESS_EXE:
                ls_pid = p
                break
    if ls_pid:
        base = _best_3d_game_pid(pid_3d_gpu, exes, exclude_pid=ls_pid, min_pct=1.0)
        if base is not None:
            base_pid = base[0]
        else:
            # Procura outra janela fullscreen não-ignorada como jogo base
            fs_base = next(
                (p for p, e in fs_wins if p != ls_pid and (e or "").lower() not in _IGNORED_EXECUTABLES),
                None,
            )
            if fs_base is not None:
                base_pid = fs_base
            else:
                other = sorted(
                    ((u, p) for p, u in pid_3d_gpu.items() if p != ls_pid and u >= 1.0),
                    reverse=True,
                )
                base_pid = other[0][1] if other else None
        return GameTarget(pid=ls_pid, exe_name="LosslessScaling.exe", is_lossless_scaling=True, base_pid=base_pid)

    # 2. Janela em primeiro plano em tela cheia/borderless (não-ignorada) -> não exige 3D PDH!
    if fg_pid > 0 and fg_exe and fg_fullscreen and low not in _IGNORED_EXECUTABLES:
        return GameTarget(
            pid=fg_pid,
            exe_name=fg_exe,
            is_lossless_scaling=False,
            extra_pids=_sibling_pids_for_exe(fg_exe, fg_pid, exes),
        )

    # 3. Janela em tela cheia/borderless não-ignorada em QUALQUER monitor (ex: jogo no monitor 1, IDE no monitor 2)
    for p, e in fs_wins:
        if p == own_pid:
            continue
        if (e or "").lower() not in _IGNORED_EXECUTABLES:
            return GameTarget(
                pid=p,
                exe_name=e,
                is_lossless_scaling=False,
                extra_pids=_sibling_pids_for_exe(e, p, exes),
            )

    # 4. Jogo em modo janela em primeiro plano com uso 3D relevante
    if fg_pid > 0 and fg_exe and low not in _IGNORED_EXECUTABLES:
        fg_3d = pid_3d_gpu.get(fg_pid, 0.0)
        if fg_3d >= 5.0:
            bg_other = _best_3d_game_pid(pid_3d_gpu, exes, exclude_pid=fg_pid, min_pct=15.0)
            if bg_other is not None and pid_3d_gpu.get(bg_other[0], 0.0) > fg_3d * 3.0:
                return GameTarget(
                    pid=bg_other[0],
                    exe_name=bg_other[1],
                    extra_pids=_sibling_pids_for_exe(bg_other[1], bg_other[0], exes),
                )
            return GameTarget(
                pid=fg_pid,
                exe_name=fg_exe,
                extra_pids=_sibling_pids_for_exe(fg_exe, fg_pid, exes),
            )

    # 5. Clicou no próprio widget: mantém o jogo anterior se ainda estiver usando 3D
    if own_pid and fg_pid == own_pid and prev_target is not None:
        if pid_3d_gpu.get(prev_target.pid, 0.0) >= 0.5 or (
            prev_target.base_pid and pid_3d_gpu.get(prev_target.base_pid, 0.0) >= 0.5
        ):
            return prev_target

    # 6. Fallback final: jogo 3D em modo janela atrás de um app de desktop
    bg = _best_3d_game_pid(pid_3d_gpu, exes, exclude_pid=own_pid, min_pct=3.0)
    if bg is not None:
        return GameTarget(
            pid=bg[0],
            exe_name=bg[1],
            extra_pids=_sibling_pids_for_exe(bg[1], bg[0], exes),
        )

    return None


# --- Parser CSV do PresentMon (v1 e v2) ---


def parse_presentmon_header(header_line: str) -> dict[str, int]:
    """Mapeia nomes de colunas (em minúsculas) para índices."""
    cols = [c.strip().lower() for c in header_line.strip().split(",")]
    return {name: idx for idx, name in enumerate(cols) if name}


def parse_presentmon_row(
    line: str,
    col_map: dict[str, int],
) -> Optional[tuple[int, str, float, Optional[float]]]:
    """
    Extrai (pid, app_name, frame_ms, display_ms) de uma linha CSV do PresentMon.
    Suporta métricas v2 (`frametime`, `msbetweendisplaychange`) e v1 (`msbetweenpresents`).
    """
    parts = line.strip().split(",")
    if len(parts) < 4:
        return None
    try:
        app_idx = col_map.get("application", 0)
        pid_idx = col_map.get("processid", 1)
        frame_idx = col_map.get("frametime")
        if frame_idx is None:
            frame_idx = col_map.get("msbetweenpresents")
        disp_idx = col_map.get("msbetweendisplaychange")
        if frame_idx is None or max(app_idx, pid_idx, frame_idx) >= len(parts):
            return None

        app = parts[app_idx].strip()
        pid = int(parts[pid_idx].strip())
        frame_ms = float(parts[frame_idx].strip())
        disp_ms: Optional[float] = None
        if disp_idx is not None and disp_idx < len(parts):
            raw_disp = parts[disp_idx].strip()
            if raw_disp and raw_disp.lower() != "na":
                val = float(raw_disp)
                if val > 0.0:
                    disp_ms = val
        if frame_ms <= 0.0 and (disp_ms is None or disp_ms <= 0.0):
            return None
        return pid, app, frame_ms, disp_ms
    except (ValueError, IndexError):
        return None


def compute_rolling_fps(frame_times_ms: list[float]) -> Optional[float]:
    if not frame_times_ms:
        return None
    valid = [t for t in frame_times_ms if 0.5 <= t <= 2000.0]
    if not valid:
        return None
    avg_ms = sum(valid) / len(valid)
    return min(999.0, 1000.0 / avg_ms) if avg_ms > 0 else None


def pretty_app_name(exe_name: str) -> str:
    base = os.path.splitext(exe_name or "")[0]
    return base.replace("_", " ").strip()


# --- Serviço gerenciado (liga/desliga PresentMon apenas durante jogos) ---


class FpsService(QObject):
    reading_ready = Signal(object)   # FpsReading

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._active = False
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()
        self._current_target: Optional[GameTarget] = None
        self._last_game_seen_at: float = 0.0
        self._samples: dict[int, deque[tuple[float, float]]] = {}
        self._app_names: dict[int, str] = {}

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        if not self._enabled:
            self._stop_presentmon()
            self.reading_ready.emit(FpsReading())

    def set_widget_visible(self, visible: bool):
        self._active = bool(visible)
        if not self._active:
            self._stop_presentmon()

    def on_gpu_pids(self, pid_3d_gpu: dict[int, float]):
        """Chamado a 1 Hz pelo controller com o mapa {pid: uso_3d_%} já coletado pelo PerformanceService."""
        if not self._enabled or not self._active:
            return
        exe_path = get_presentmon_path()
        if not exe_path or not has_etw_fps_permission():
            self._stop_presentmon()
            return

        fg_pid, fg_exe, fg_fs = _foreground_window_info()
        fs_wins = _fullscreen_windows()
        pid_exes = {pid: _exe_name_for_pid(pid) for pid in pid_3d_gpu}
        target = detect_game_target(
            fg_pid,
            fg_exe,
            fg_fs,
            pid_3d_gpu,
            pid_exes=pid_exes,
            own_pid=os.getpid(),
            prev_target=self._current_target,
            fullscreen_windows=fs_wins,
        )
        now = time.monotonic()

        if target is not None:
            self._last_game_seen_at = now
            if self._current_target is None or self._current_target.pid != target.pid:
                self._start_presentmon(exe_path, target)
            self._emit_current_reading(now)
        else:
            if self._current_target is not None:
                if now - self._last_game_seen_at >= _GRACE_STOP_S:
                    self._stop_presentmon()
                    self.reading_ready.emit(FpsReading())
                else:
                    self._emit_current_reading(now)
            else:
                self.reading_ready.emit(FpsReading())

    def _start_presentmon(self, exe_path: str, target: GameTarget):
        self._stop_presentmon()
        cmd = [
            exe_path,
            "--session_name", _SESSION_NAME,
            "--stop_existing_session",
            "--output_stdout",
            "--no_console_stats",
            "--no_track_input",
            "--no_track_gpu",
        ]
        if target.is_lossless_scaling:
            cmd += ["--process_id", str(target.pid)]
            if target.base_pid:
                cmd += ["--process_id", str(target.base_pid)]
        else:
            cmd += ["--process_id", str(target.pid)]
            for ep in target.extra_pids:
                cmd += ["--process_id", str(ep)]

        try:
            creation = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                creationflags=creation,
            )
        except OSError:
            return

        with self._lock:
            self._proc = proc
            self._current_target = target
            self._samples = {}
            self._app_names = {target.pid: pretty_app_name(target.exe_name)}
            self._stop_reader.clear()
            self._reader_thread = threading.Thread(
                target=self._read_loop, args=(proc, target), name="AimedgetFpsReader", daemon=True
            )
            self._reader_thread.start()

    def _read_loop(self, proc: subprocess.Popen, target: GameTarget):
        stdout = proc.stdout
        if stdout is None:
            return
        col_map: Optional[dict[str, int]] = None
        try:
            for line in stdout:
                if self._stop_reader.is_set():
                    break
                if not line.strip():
                    continue
                if col_map is None:
                    if "application" in line.lower() and "processid" in line.lower():
                        col_map = parse_presentmon_header(line)
                    continue
                parsed = parse_presentmon_row(line, col_map)
                if parsed is None:
                    continue
                pid, app, frame_ms, disp_ms = parsed
                # Para Lossless Scaling, MsBetweenDisplayChange reflete melhor a taxa real exibida
                ms = disp_ms if (target.is_lossless_scaling and pid == target.pid and disp_ms) else frame_ms
                if ms <= 0.0:
                    continue
                now = time.monotonic()
                with self._lock:
                    buf = self._samples.setdefault(pid, deque(maxlen=600))
                    buf.append((now, ms))
                    if app and app != "<unknown>":
                        self._app_names[pid] = pretty_app_name(app)
        except Exception:
            pass

    def _emit_current_reading(self, now: float):
        cutoff = now - 1.2
        with self._lock:
            target = self._current_target
            if target is None:
                return
            watched_pids = (target.pid,) + target.extra_pids
            main_ms: list[float] = []
            for wp in watched_pids:
                ms_list = [ms for ts, ms in self._samples.get(wp, ()) if ts >= cutoff]
                if len(ms_list) > len(main_ms):
                    main_ms = ms_list
            main_fps = compute_rolling_fps(main_ms)
            base_fps = None
            if target.is_lossless_scaling and target.base_pid:
                base_ms = [ms for ts, ms in self._samples.get(target.base_pid, ()) if ts >= cutoff]
                base_fps = compute_rolling_fps(base_ms)
                app_name = self._app_names.get(target.base_pid) or "LSFG"
            else:
                app_name = self._app_names.get(target.pid) or pretty_app_name(target.exe_name)

        self.reading_ready.emit(
            FpsReading(
                fps=main_fps,
                base_fps=base_fps,
                app_name=app_name,
                is_lossless_scaling=target.is_lossless_scaling,
            )
        )

    def _stop_presentmon(self):
        self._stop_reader.set()
        with self._lock:
            proc, self._proc = self._proc, None
            self._current_target = None
            self._samples = {}
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def stop(self):
        self._active = False
        self._stop_presentmon()
