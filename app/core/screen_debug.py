"""
Diagnóstico de troca de monitores (só observa; desligado por padrão).

Liga com a variável de ambiente AIMEDGET_SCREEN_DEBUG=1. Grava em `<crash_reports>/screen_debug.log`:
- as telas (pelo Qt e pelo Win32: nome do dispositivo, retângulo físico, área útil, DPI, principal) a cada mudança;
- os sinais do Qt (tela entrou/saiu, principal mudou, geometria mudou), com o horário em ms;
- as mensagens do Windows que cada widget recebe: WM_DISPLAYCHANGE, WM_SETTINGCHANGE, WM_DPICHANGED,
  WM_GETDPISCALEDSIZE e WM_WINDOWPOSCHANGING/CHANGED (com x, y, tamanho e flags). As de posição ficam num buffer e
  só são gravadas perto de uma troca de tela (os 3 s anteriores e os 10 s seguintes), para não lotar o arquivo
  com arrastes e animações. Cada uma diz se veio do nosso código Python (pilha com arquivos do app) ou de fora
  (Windows ou o Qt por conta própria);
- a posição de cada widget (Qt e janela nativa) a cada 100 ms nos 10 s após uma troca, só quando muda.

Com AIMEDGET_SCREEN_DEBUG=1 a correção do ScreenWatcher continua ligada e o log mostra o que ela fez (WATCHER,
REMEMBER). Com AIMEDGET_SCREEN_DEBUG=observe o ScreenWatcher NÃO move nada (só registra o que faria): assim o log
mostra o que o Windows e o Qt fazem sozinhos.
"""

from __future__ import annotations

import collections
import ctypes
import os
import sys
import time
import traceback
from ctypes import wintypes
from typing import Optional

ENV = "AIMEDGET_SCREEN_DEBUG"
BURST_S = 10.0       # depois de uma troca de tela: tudo é gravado por esse tempo
BEFORE_S = 3.0       # buffer de mensagens de posição antes da troca
POLL_MS = 100

WM_WINDOWPOSCHANGING = 0x0046
WM_WINDOWPOSCHANGED = 0x0047
WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_DPICHANGED = 0x02E0
WM_GETDPISCALEDSIZE = 0x02E4
_NAMES = {
    WM_WINDOWPOSCHANGING: "WM_WINDOWPOSCHANGING", WM_WINDOWPOSCHANGED: "WM_WINDOWPOSCHANGED",
    WM_SETTINGCHANGE: "WM_SETTINGCHANGE", WM_DISPLAYCHANGE: "WM_DISPLAYCHANGE",
    WM_DPICHANGED: "WM_DPICHANGED", WM_GETDPISCALEDSIZE: "WM_GETDPISCALEDSIZE",
}
_POS_MSGS = (WM_WINDOWPOSCHANGING, WM_WINDOWPOSCHANGED)
_SWP = {0x1: "NOSIZE", 0x2: "NOMOVE", 0x4: "NOZORDER", 0x10: "NOACTIVATE", 0x20: "FRAMECHANGED",
        0x40: "SHOWWINDOW", 0x80: "HIDEWINDOW", 0x200: "NOOWNERZORDER", 0x400: "NOSENDCHANGING",
        0x4000: "ASYNCWINDOWPOS", 0x1000: "DEFERERASE"}


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND), ("x", ctypes.c_int),
                ("y", ctypes.c_int), ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", ctypes.c_uint)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def enabled() -> bool:
    return os.environ.get(ENV, "") not in ("", "0")


def observe_only() -> bool:
    """AIMEDGET_SCREEN_DEBUG=observe: só registra; o ScreenWatcher não move nada."""
    return os.environ.get(ENV, "").strip().lower() == "observe"


_t0 = time.perf_counter()
_file = None
_buffer: collections.deque = collections.deque(maxlen=400)
_burst_until = 0.0
_poller = None
_last_widgets: dict = {}


def _now_ms() -> float:
    return (time.perf_counter() - _t0) * 1000.0


def _path() -> str:
    from app.core.crash_reporter import get_crash_reports_dir
    return os.path.join(get_crash_reports_dir(), "screen_debug.log")


def _write(line: str):
    global _file
    if _file is None:
        _file = open(_path(), "a", encoding="utf-8", buffering=1)
    _file.write(line + "\n")


def log(event: str, text: str = "", t: Optional[float] = None):
    if not enabled():
        return
    _write(f"{(t if t is not None else _now_ms()):10.1f}  {event:<22} {text}")


def _in_burst() -> bool:
    return time.perf_counter() < _burst_until


def _rect(r) -> str:
    return f"({r.left},{r.top} {r.right - r.left}x{r.bottom - r.top})"


# --- Telas ---


def _win32_monitors() -> list:
    if sys.platform != "win32":
        return []
    out = []
    user32 = ctypes.windll.user32
    try:
        shcore = ctypes.windll.shcore
    except OSError:
        shcore = None
    proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                wintypes.LPARAM)

    def cb(hmon, _hdc, _rc, _lp):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        dpi = ""
        if shcore is not None:
            dx, dy = ctypes.c_uint(), ctypes.c_uint()
            if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                dpi = f"dpi={dx.value}"
        out.append(f"{info.szDevice} mon={_rect(info.rcMonitor)} work={_rect(info.rcWork)} {dpi}"
                   f"{' PRIMARY' if info.dwFlags & 1 else ''}")
        return 1

    user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
    return out


def log_screens(reason: str):
    if not enabled():
        return
    from PySide6.QtGui import QGuiApplication

    log("SCREENS", f"--- {reason} ---")
    primary = QGuiApplication.primaryScreen()
    for s in QGuiApplication.screens():
        g, a = s.geometry(), s.availableGeometry()
        log("  qt", f"{s.name()!r} model={s.model()!r} serial={s.serialNumber()!r} "
                    f"geo=({g.x()},{g.y()} {g.width()}x{g.height()}) avail=({a.x()},{a.y()} {a.width()}x{a.height()}) "
                    f"dpr={s.devicePixelRatio()}{' PRIMARY' if s is primary else ''}")
    for line in _win32_monitors():
        log("  win32", line)


# --- Widgets ---


def _widget_lines() -> dict:
    from app.core import anchor_manager as am

    mgr = am._manager
    out = {}
    if mgr is None:
        return out
    for key, w in list(mgr._windows.items()):
        if not am._alive(w):
            continue
        native = ""
        if sys.platform == "win32":
            r = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(int(w.winId()), ctypes.byref(r)):
                native = _rect(r)
        handle = w.windowHandle()
        scr = handle.screen().name() if handle is not None and handle.screen() is not None else "?"
        c = am.card_rect(w)
        out[key] = (f"vis={int(w.isVisible())} qt_pos=({w.x()},{w.y()}) card=({c.l:.0f},{c.t:.0f} {c.w:.0f}x{c.h:.0f}) "
                    f"native={native} screen={scr!r} dpr={w.devicePixelRatioF()} "
                    f"group={'+'.join(mgr.group_of(key).keys())} anchored={int(mgr.group_of(key).anchored)}")
    return out


def log_widgets(reason: str, only_changed: bool = False):
    global _last_widgets
    if not enabled():
        return
    lines = _widget_lines()
    changed = {k: v for k, v in lines.items() if _last_widgets.get(k) != v}
    if only_changed and not changed:
        return
    log("WIDGETS", f"--- {reason} ---")
    for k, v in (changed if only_changed else lines).items():
        log(f"  {k}", v)
    _last_widgets = lines


# --- Troca de tela ---


def screen_event(what: str):
    """Um sinal do Qt (tela entrou/saiu, principal mudou, geometria mudou)."""
    if not enabled():
        return
    _start_burst(f"qt: {what}")


def _start_burst(reason: str):
    global _burst_until
    first = not _in_burst()
    _burst_until = time.perf_counter() + BURST_S
    if first:
        cutoff = _now_ms() - BEFORE_S * 1000.0
        early = [e for e in _buffer if e[0] >= cutoff]
        if early:
            log("BUFFER", f"--- mensagens de posição nos {BEFORE_S:.0f} s antes de: {reason} ---")
            for t, ev, text in early:
                log(ev, text, t=t)
        _buffer.clear()
    log("EVENT", reason)
    log_screens(reason)
    log_widgets(reason)
    if _poller is not None and not _poller.isActive():
        _poller.start()


def _poll():
    if not _in_burst():
        log_widgets("fim da janela de observação")
        log("EVENT", "fim da janela de observação")
        _poller.stop()
        return
    log_widgets("posição mudou", only_changed=True)


# --- Mensagens nativas ---


def _origin() -> str:
    """De onde veio a mensagem: nosso Python (arquivos do app na pilha) ou o laço de eventos (Windows/Qt)."""
    frames = [f for f in traceback.extract_stack()[:-3] if os.sep + "app" + os.sep in f.filename
              and "screen_debug" not in f.filename and not f.filename.endswith("main.py")]
    if not frames:
        return "origem=FORA (Windows/Qt)"
    return "origem=APP " + " < ".join(f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in frames[-4:][::-1])


def native(widget, message):
    """Chamada no nativeEvent dos widgets. Nunca altera a mensagem."""
    if not enabled():
        return
    try:
        msg = wintypes.MSG.from_address(int(message))
    except (TypeError, ValueError, OSError):
        return
    m = msg.message
    if m not in _NAMES:
        return
    key = getattr(widget, "ANCHOR_KEY", None) or type(widget).__name__
    name = _NAMES[m]
    if m in _POS_MSGS:
        wp = WINDOWPOS.from_address(msg.lParam)
        flags = "|".join(v for b, v in _SWP.items() if wp.flags & b) or "0"
        if wp.flags & 0x3 == 0x3:
            return          # nem move nem redimensiona (só ordem Z): não interessa aqui
        text = f"[{key}] x={wp.x} y={wp.y} cx={wp.cx} cy={wp.cy} flags={flags} {_origin()}"
        if _in_burst():
            log(name, text)
        else:
            _buffer.append((_now_ms(), name, text))
        return
    if m == WM_DISPLAYCHANGE:
        text = f"[{key}] bpp={msg.wParam} {msg.lParam & 0xFFFF}x{(msg.lParam >> 16) & 0xFFFF}"
    elif m == WM_DPICHANGED:
        r = wintypes.RECT.from_address(msg.lParam)
        text = f"[{key}] dpi={msg.wParam & 0xFFFF} suggested={_rect(r)}"
    elif m == WM_SETTINGCHANGE:
        area = ""
        if msg.lParam:
            try:
                area = ctypes.wstring_at(msg.lParam, 64)
            except OSError:
                area = "?"
        text = f"[{key}] wParam=0x{msg.wParam:X} area={area!r}"
    else:
        text = f"[{key}] dpi={msg.wParam}"
    if m in (WM_DISPLAYCHANGE, WM_DPICHANGED) or (m == WM_SETTINGCHANGE and msg.wParam == 0x2F):  # SPI_SETWORKAREA
        _start_burst(f"{name} {text}")
    else:
        log(name, text)


# --- Ligar ---


def install():
    """Chamada no main, depois do QApplication. Sem a variável de ambiente, não faz nada."""
    global _poller
    if not enabled():
        return
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication

    _poller = QTimer()
    _poller.setInterval(POLL_MS)
    _poller.timeout.connect(_poll)
    app = QGuiApplication.instance()

    def watch(s):
        s.geometryChanged.connect(lambda r, n=s.name(): screen_event(f"geometryChanged {n!r} -> "
                                                                     f"({r.x()},{r.y()} {r.width()}x{r.height()})"))

    app.screenAdded.connect(lambda s: (watch(s), screen_event(f"screenAdded {s.name()!r}")))
    app.screenRemoved.connect(lambda s: screen_event(f"screenRemoved {s.name()!r}"))
    app.primaryScreenChanged.connect(lambda s: screen_event(f"primaryScreenChanged -> {s.name()!r}"))
    for s in app.screens():
        watch(s)
    log("START", f"diagnóstico ligado (pid {os.getpid()}); arquivo {_path()}")
    log_screens("início")
    QTimer.singleShot(5000, lambda: log_widgets("5 s após abrir"))
