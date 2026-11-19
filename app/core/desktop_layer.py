"""
"Fixar na área de trabalho": mantém uma janela no nível do desktop, logo acima do papel de parede e dos ícones,
abaixo de qualquer outra janela. Abrir um app cobre o widget; clicar no widget não o traz para a frente.

Como: a janela é posicionada (ordem Z) logo acima da janela que hospeda os ícones do desktop (a que contém
`SHELLDLL_DefView`: o `Progman` ou, com papel de parede em apresentação/Windows 11, um `WorkerW`), e cada tentativa
do Windows de mudar essa ordem (clique, ativação, `raise_()`) é corrigida em WM_WINDOWPOSCHANGING. Não basta
HWND_BOTTOM: ele pode pôr a janela atrás do próprio desktop, e ela some.

Só Win32 (ctypes), sem Qt: quem desenha chama `on_window_pos_changing()` no `nativeEvent` e `send_to_desktop_layer()`
ao mostrar.
"""

import ctypes
import os
import sys
from ctypes import wintypes

WM_WINDOWPOSCHANGING = 0x0046
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
GW_HWNDPREV = 3
HWND_TOP = 0
HWND_BOTTOM = 1

IS_WINDOWS = sys.platform == "win32"


class WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowExW.restype = wintypes.HWND
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetWindow.restype = wintypes.HWND
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, wintypes.UINT]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                       wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
    _user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, _WINEVENTPROC,
                                        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    _user32.SetWinEventHook.restype = wintypes.HANDLE
    _user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    try:
        _dwmapi = ctypes.WinDLL("dwmapi")
        _dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        _dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    except OSError:
        _dwmapi = None

GW_HWNDNEXT = 2
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
DWMWA_EXCLUDED_FROM_PEEK = 12
DWMWA_CLOAKED = 14
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
_MAX_WALK = 1024   # limite de janelas percorridas na pilha (proteção contra laço)

_host_cache = [0]


def _find_desktop_host() -> int:
    """A janela de primeiro nível que contém os ícones do desktop (0 se não achar)."""
    found = [0]

    def visit(hwnd, _lparam):
        if _user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            found[0] = hwnd or 0
            return False
        return True

    _user32.EnumWindows(_WNDENUMPROC(visit), 0)
    return found[0] or (_user32.FindWindowW("Progman", None) or 0)


def desktop_host() -> int:
    host = _host_cache[0]
    if not host or not _user32.IsWindow(host):   # o Explorer reiniciou (ou primeira vez)
        host = _find_desktop_host()
        _host_cache[0] = host
    return host


def insert_after_for(own_hwnd: int) -> int:
    """
    Valor de `hwndInsertAfter` que deixa `own_hwnd` logo acima do desktop. "Inserir depois de X" põe a janela logo
    ABAIXO de X, então X é a janela imediatamente acima do desktop (pulando a própria).
    """
    host = desktop_host()
    if not host:
        return HWND_BOTTOM   # sem desktop identificável: o fundo da pilha é o melhor possível
    above = _user32.GetWindow(host, GW_HWNDPREV) or 0
    if above == own_hwnd:   # já está no lugar: fica abaixo de quem está acima dela
        above = _user32.GetWindow(own_hwnd, GW_HWNDPREV) or 0
    return above or HWND_TOP


def on_window_pos_changing(lparam: int, own_hwnd: int):
    """Chame no WM_WINDOWPOSCHANGING da janela: corrige qualquer mudança de ordem Z para o nível do desktop."""
    if not IS_WINDOWS or not lparam:
        return
    pos = WINDOWPOS.from_address(lparam)
    if pos.flags & SWP_NOZORDER:
        return
    pos.hwndInsertAfter = insert_after_for(own_hwnd)


def send_to_desktop_layer(own_hwnd: int):
    """Leva a janela agora para o nível do desktop (ao ligar a opção ou ao mostrar)."""
    if not IS_WINDOWS or not own_hwnd:
        return
    _user32.SetWindowPos(own_hwnd, insert_after_for(own_hwnd), 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


# --- Sobreviver ao "Mostrar área de trabalho" (Win+D), como o Rainmeter ---
#
# O Win+D não minimiza janelas: ele traz a janela do desktop para a frente de todas. O cartão, que estava logo acima
# dela, fica escondido atrás. Quando o usuário volta (Win+D de novo), o desktop desce e o cartão, se tivesse sido
# trazido para a frente, ficaria por cima dos apps. A regra única que resolve os dois sentidos: o cartão tem de estar
# logo acima do desktop; se estiver abaixo dele, ou com uma janela de verdade no meio, volta para o lugar.
# (Lido no código do Rainmeter: System::CheckDesktopState / Skin::ChangeZPos, que fazem o mesmo com SetWindowPos.)


def _is_cloaked(hwnd: int) -> bool:
    """Janelas "encobertas" pelo DWM (apps UWP suspensos, outras áreas de trabalho virtuais): não aparecem."""
    if _dwmapi is None:
        return False
    value = ctypes.c_int(0)
    try:
        _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    except OSError:
        return False
    return bool(value.value)


def _covers(hwnd: int) -> bool:
    """A janela conta como "algo por cima do desktop"? Ignora invisíveis, encobertas e janelas-ferramenta (outros
    widgets de desktop, como skins do Rainmeter, são janelas-ferramenta: assim não brigamos pelo mesmo lugar)."""
    if not _user32.IsWindowVisible(hwnd) or _is_cloaked(hwnd):
        return False
    return not (_user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW)


def needs_replace(own_hwnd: int) -> bool:
    """True se o cartão saiu do lugar: escondido atrás do desktop (Win+D) ou com uma janela de verdade entre ele e o
    desktop (voltou do Win+D por cima dos apps)."""
    if not IS_WINDOWS or not own_hwnd or not _user32.IsWindow(own_hwnd):
        return False
    host = desktop_host()
    if not host:
        return False
    w = host
    for _ in range(_MAX_WALK):   # abaixo do desktop?
        w = _user32.GetWindow(w, GW_HWNDNEXT) or 0
        if not w:
            break
        if w == own_hwnd:
            return True
    w = host
    for _ in range(_MAX_WALK):   # alguma janela de verdade no meio?
        w = _user32.GetWindow(w, GW_HWNDPREV) or 0
        if not w or w == own_hwnd:
            return False
        if _covers(w):
            return True
    return False


def is_below_desktop(hwnd: int) -> bool:
    """A janela está ABAIXO do desktop na pilha? (Com o Win+D o desktop sobe por cima de tudo o que não é topmost.)"""
    if not IS_WINDOWS or not hwnd:
        return False
    host = desktop_host()
    w = host
    for _ in range(_MAX_WALK):
        w = _user32.GetWindow(w, GW_HWNDNEXT) or 0
        if not w:
            return False
        if w == hwnd:
            return True
    return False


def foreground_is_app_above_desktop() -> bool:
    """O primeiro plano é um app de verdade, acima do desktop? (Ao voltar do Win+D, ou ao abrir um app pela barra de
    tarefas, o Windows sai do modo "Mostrar área de trabalho" e o app em foco fica por cima do desktop.)"""
    if not IS_WINDOWS:
        return False
    fg = _user32.GetForegroundWindow() or 0
    host = desktop_host()
    if not fg or fg == host or not _covers(fg):
        return False
    w = host
    for _ in range(_MAX_WALK):
        w = _user32.GetWindow(w, GW_HWNDPREV) or 0
        if not w:
            return False
        if w == fg:
            return True
    return False


def set_excluded_from_peek(own_hwnd: int, excluded: bool):
    """O "espiar a área de trabalho" (canto da barra de tarefas) não esconde o cartão. Mesmo truque do Rainmeter."""
    if not IS_WINDOWS or not own_hwnd or _dwmapi is None:
        return
    value = ctypes.c_int(1 if excluded else 0)
    try:
        _dwmapi.DwmSetWindowAttribute(own_hwnd, DWMWA_EXCLUDED_FROM_PEEK, ctypes.byref(value), ctypes.sizeof(value))
    except OSError:
        pass


class ForegroundHook:
    """
    Avisa quando a janela em primeiro plano muda (o Win+D muda: o desktop vira o primeiro plano). Fora de contexto:
    o aviso chega pela fila de mensagens desta thread (a do Qt), sem injetar nada em outro processo.
    """

    def __init__(self, callback):
        self._proc = None
        self._hook = None
        if not IS_WINDOWS:
            return
        self._proc = _WINEVENTPROC(lambda *_args: callback())   # guardado: o ctypes não pode coletar o callback
        self._hook = _user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._proc,
                                             0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)

    def active(self) -> bool:
        return bool(self._hook)

    def close(self):
        if self._hook:
            _user32.UnhookWinEvent(self._hook)
        self._hook = None
        self._proc = None


HWND_TOPMOST = -1
HWND_NOTOPMOST = -2


def set_topmost(own_hwnd: int, topmost: bool):
    """
    Liga/desliga "sempre no topo" direto no Windows, na MESMA janela. Trocar a flag do Qt (setWindowFlags) recria a
    janela nativa, e uma janela translúcida recém-criada aparece preta por um quadro.
    """
    if not IS_WINDOWS or not own_hwnd:
        return
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    _user32.SetWindowPos(own_hwnd, HWND_TOPMOST if topmost else HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    if topmost and not (_user32.GetWindowLongW(own_hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST):
        # Às vezes o Windows ignora o HWND_TOPMOST (escolhe uma janela oculta do próprio app como vizinha e não muda
        # nada; medido ao soltar o cartão do desktop). O Rainmeter documenta o mesmo e força a troca: tirar do
        # topo e pôr de novo resolve.
        _user32.SetWindowPos(own_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        _user32.SetWindowPos(own_hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)


def apply_layer(own_hwnd: int, desktop: bool):
    """Põe a janela no nível pedido: logo acima do desktop, ou sempre no topo."""
    if desktop:
        set_topmost(own_hwnd, False)
        send_to_desktop_layer(own_hwnd)
    else:
        set_topmost(own_hwnd, True)


def z_order_above_desktop(own_hwnd: int) -> bool:
    """
    True se nada "de verdade" separa a janela do desktop (usado nos testes). Pelo caminho podem ficar janelas
    invisíveis do Windows (ex.: as de IME) e outros widgets de desktop (ex.: skins do Rainmeter): mesma regra de
    `needs_replace`, para os dois nunca discordarem.
    """
    if not IS_WINDOWS or not own_hwnd:
        return False
    w = desktop_host()
    for _ in range(_MAX_WALK):
        w = _user32.GetWindow(w, GW_HWNDPREV) or 0
        if not w:
            return False
        if w == own_hwnd:
            return True
        if _covers(w):
            return False
    return False
