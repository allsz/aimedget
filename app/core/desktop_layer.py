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
WM_DPICHANGED = 0x02E0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
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
    if not _is_raise(pos.hwndInsertAfter) and owner_of(own_hwnd) == desktop_host():
        # Uma janela específica como vizinha: é o Windows levando o cartão junto com o desktop (dono). Reescrever
        # aqui, com o desktop ainda no meio do movimento, deixava um cartão atrás dele (piscada).
        return
    pos.hwndInsertAfter = insert_after_for(own_hwnd)


def _is_raise(insert_after) -> bool:
    """HWND_TOP/BOTTOM/TOPMOST/NOTOPMOST (clique, ativação, raise_()), e não "logo abaixo de tal janela"."""
    value = ctypes.c_ssize_t(insert_after or 0).value
    return value in (HWND_TOP, HWND_BOTTOM, -1, -2)


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

# --- Mover várias janelas de uma vez (grupo de widgets ancorados) ---

if IS_WINDOWS:
    _u32 = ctypes.WinDLL("user32", use_last_error=True)   # instância própria: argtypes só destas chamadas
    _u32.BeginDeferWindowPos.argtypes = [ctypes.c_int]
    _u32.BeginDeferWindowPos.restype = wintypes.HANDLE
    _u32.DeferWindowPos.argtypes = [wintypes.HANDLE, wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _u32.DeferWindowPos.restype = wintypes.HANDLE
    _u32.EndDeferWindowPos.argtypes = [wintypes.HANDLE]
    _u32.EndDeferWindowPos.restype = wintypes.BOOL
    _u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u32.GetWindowRect.restype = wintypes.BOOL
    _u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _u32.GetCursorPos.restype = wintypes.BOOL


def native_window_rect(hwnd: int):
    """(esquerda, topo) da janela em px físicos, ou None."""
    if not IS_WINDOWS or not hwnd:
        return None
    rect = wintypes.RECT()
    if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top


def native_window_box(hwnd: int):
    """(esquerda, topo, largura, altura) da janela em px físicos, ou None."""
    if not IS_WINDOWS or not hwnd:
        return None
    rect = wintypes.RECT()
    if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def native_cursor_pos():
    """(x, y) do cursor em px físicos contínuos entre todos os monitores, ou None."""
    if not IS_WINDOWS:
        return None
    pt = wintypes.POINT()
    if not _u32.GetCursorPos(ctypes.byref(pt)):
        return None
    return pt.x, pt.y


def defer_move(moves) -> bool:
    """
    Move várias janelas num só lote (`[(hwnd, x, y)]`, px físicos): o Windows aplica todas de uma vez, então um
    grupo arrastado nunca aparece com os membros um quadro separados. False se o lote falhou (quem chama move uma
    por vez). Sem mudar a ordem Z nem ativar nada.
    """
    if not IS_WINDOWS or not moves:
        return False
    handle = _u32.BeginDeferWindowPos(len(moves))
    if not handle:
        return False
    flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    for hwnd, x, y in moves:
        handle = _u32.DeferWindowPos(handle, hwnd, None, int(x), int(y), 0, 0, flags)
        if not handle:
            return False
    return bool(_u32.EndDeferWindowPos(handle))


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


# --- Dono = desktop: o Windows nunca põe o desktop por cima do cartão ---
#
# Clicar no desktop (menu de contexto, "Atualizar") o ativa, e o Windows pode subi-lo por cima dos cartões fixados.
# O guarda os devolvia ao lugar ~2 ms depois do aviso, mas se o DWM compusesse um quadro nesse meio-tempo o cartão
# sumia por um quadro (piscada; medido num notebook na bateria). Uma janela "possuída" fica sempre acima da dona, e o
# Windows aplica isso na mesma operação que move a dona: com o desktop como dono, não há intervalo.
# Se o Explorer reiniciar, o Windows só desfaz o vínculo (janelas de outra thread não são destruídas com a dona); o
# guarda refaz com o desktop novo (`ensure_desktop_owner`).

if IS_WINDOWS:
    _u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t

GWLP_HWNDPARENT = -8
GW_OWNER = 4


def owner_of(own_hwnd: int) -> int:
    if not IS_WINDOWS or not own_hwnd:
        return 0
    return _user32.GetWindow(own_hwnd, GW_OWNER) or 0


def set_owner(own_hwnd: int, owner_hwnd: int):
    """Troca a janela dona (GWLP_HWNDPARENT numa janela de primeiro nível muda a dona, não o pai)."""
    if not IS_WINDOWS or not own_hwnd:
        return
    _u32.SetWindowLongPtrW(own_hwnd, GWLP_HWNDPARENT, owner_hwnd or 0)


def ensure_desktop_owner(own_hwnd: int) -> bool:
    """Garante o desktop atual como dono. True se precisou trocar (primeira vez ou Explorer reiniciou)."""
    host = desktop_host()
    if not host or owner_of(own_hwnd) == host:
        return False
    set_owner(own_hwnd, host)
    return True


def apply_layer(own_hwnd: int, desktop: bool):
    """Põe a janela no nível pedido: logo acima do desktop (com ele como dono), ou sempre no topo."""
    if desktop:
        set_topmost(own_hwnd, False)
        ensure_desktop_owner(own_hwnd)
        send_to_desktop_layer(own_hwnd)
    else:
        if owner_of(own_hwnd) == desktop_host():
            set_owner(own_hwnd, 0)
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
