"""
VirtualDesktopWatcher - avisa quando o usuário troca de área de trabalho virtual (Ctrl+Win+←/→, Visão de Tarefas).

O Windows não tem um aviso público para isso (a interface de notificação existe, mas é não documentada e muda entre
versões). O caminho estável é o registro: `CurrentVirtualDesktop` (GUID da área atual) e `VirtualDesktopIDs` (todas,
na ordem da Visão de Tarefas) mudam a cada troca. Uma thread espera a mudança com RegNotifyChangeKeyValue, sem
consultar em laço; medido: o aviso chega 60–85 ms depois do atalho, no começo do deslize do Windows.

O sentido sai das posições na lista: +1 = foi para a direita (os apps saem pela esquerda), -1 = para a esquerda.
Só roda enquanto alguém pediu (`acquire`/`release`).
"""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops"
_HKCU = 0x80000001
_KEY_NOTIFY_QUERY = 0x0010 | 0x0001
_REG_NOTIFY_CHANGE_LAST_SET = 0x4
_WAIT_OBJECT_0 = 0


def read_state() -> tuple[bytes, list[bytes]] | None:
    """(GUID atual, GUIDs na ordem) ou None se o Windows não expõe (sem áreas virtuais ainda, outra versão)."""
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as key:
            current, _ = winreg.QueryValueEx(key, "CurrentVirtualDesktop")
            ids, _ = winreg.QueryValueEx(key, "VirtualDesktopIDs")
    except OSError:
        return None
    if not isinstance(current, bytes) or not isinstance(ids, bytes):
        return None
    return current, [ids[i:i + 16] for i in range(0, len(ids) - 15, 16)]


def switch_direction(before: tuple[bytes, list[bytes]] | None, after: tuple[bytes, list[bytes]] | None) -> int:
    """+1/-1 se a área atual mudou (sentido pela posição na lista), 0 se não houve troca."""
    if not before or not after or before[0] == after[0]:
        return 0
    old_current, old_ids = before
    new_current, new_ids = after
    if new_current not in new_ids:
        return 0
    new_index = new_ids.index(new_current)
    if old_current in new_ids:
        return 1 if new_index > new_ids.index(old_current) else -1
    # A área antiga foi apagada (Ctrl+Win+F4): o Windows vai para a vizinha da esquerda; se era a primeira, a da
    # direita ocupa a mesma posição na lista nova.
    old_index = old_ids.index(old_current) if old_current in old_ids else new_index
    return -1 if new_index < old_index else 1


class VirtualDesktopWatcher(QObject):
    switched = Signal(int)   # sentido: +1 direita, -1 esquerda (entregue na thread do Qt)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._users = 0
        self._thread: threading.Thread | None = None
        self._stop: threading.Event | None = None
        self._wake = None

    def is_running(self) -> bool:
        return self._thread is not None

    def acquire(self):
        self._users += 1
        if self._users == 1:
            self._start()

    def release(self):
        if self._users == 0:
            return
        self._users -= 1
        if self._users == 0:
            self._halt()

    # --- Internos ---

    def _start(self):
        if sys.platform != "win32" or read_state() is None:
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.restype = wintypes.HANDLE
        self._wake = kernel32.CreateEventW(None, False, False, None)   # acorda a thread para sair
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop, self._wake), daemon=True,
                                        name="virtual-desktop-watcher")
        self._thread.start()

    def _halt(self):
        if self._thread is None:
            return
        self._stop.set()
        ctypes.windll.kernel32.SetEvent(wintypes.HANDLE(self._wake))
        self._thread.join(timeout=1.0)
        ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(self._wake))
        self._thread = self._stop = self._wake = None

    def _run(self, stop: threading.Event, wake):
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.restype = wintypes.HANDLE
        key = wintypes.HKEY()
        if advapi32.RegOpenKeyExW(wintypes.HKEY(_HKCU), _KEY, 0, _KEY_NOTIFY_QUERY, ctypes.byref(key)) != 0:
            return
        changed = kernel32.CreateEventW(None, False, False, None)
        handles = (wintypes.HANDLE * 2)(changed, wake)
        state = read_state()
        try:
            while not stop.is_set():
                if advapi32.RegNotifyChangeKeyValue(key, False, _REG_NOTIFY_CHANGE_LAST_SET,
                                                    wintypes.HANDLE(changed), True) != 0:
                    return
                if kernel32.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF) != _WAIT_OBJECT_0:
                    return   # pedido de parada (ou erro)
                new_state = read_state()
                direction = switch_direction(state, new_state)
                state = new_state or state
                if direction and not stop.is_set():
                    self.switched.emit(direction)   # conexão automática: chega enfileirado na thread do Qt
        finally:
            advapi32.RegCloseKey(key)
            kernel32.CloseHandle(wintypes.HANDLE(changed))


_watcher: VirtualDesktopWatcher | None = None


def virtual_desktop_watcher() -> VirtualDesktopWatcher:
    """Um só vigia para o app inteiro."""
    global _watcher
    if _watcher is None:
        _watcher = VirtualDesktopWatcher()
    return _watcher
