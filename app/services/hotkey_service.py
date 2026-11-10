"""
HotkeyService - Serviço de Atalhos Globais de Teclado para o Aimedget.
Utiliza hook de baixo nível do Windows (WH_KEYBOARD_LL) para garantir que
combinações como Win+Alt+M e Win+Alt+T funcionem de forma confiável e sem conflito,
mesmo quando outros programas ou a área de trabalho estão em foco.
"""

import ctypes
from ctypes import wintypes
import logging
from typing import Callable, Dict, Tuple
from PySide6.QtCore import QObject, Signal, QTimer

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class HotkeyParser:
    """Tradutor e normalizador de atalhos em strings amigáveis para códigos virtuais Win32."""

    MOD_MAP = {
        "win": "win",
        "windows": "win",
        "meta": "win",
        "alt": "alt",
        "ctrl": "ctrl",
        "control": "ctrl",
        "shift": "shift",
    }

    @classmethod
    def parse(cls, hotkey_str: str) -> Tuple[Dict[str, bool], int | None, str]:
        """
        Retorna (dict_modifiers, vk_code, key_char).
        Ex: 'Win+Alt+M' -> ({'win': True, 'alt': True, 'ctrl': False, 'shift': False}, 77, 'M')
        """
        parts = [p.strip().lower() for p in hotkey_str.split("+") if p.strip()]
        mods = {"win": False, "alt": False, "ctrl": False, "shift": False}
        key_vk = None
        key_char = ""

        for p in parts:
            if p in cls.MOD_MAP:
                mods[cls.MOD_MAP[p]] = True
            elif len(p) == 1 and p.isalnum():
                key_vk = ord(p.upper())
                key_char = p.upper()
            elif p.startswith("f") and p[1:].isdigit():
                f_num = int(p[1:])
                if 1 <= f_num <= 12:
                    key_vk = 0x6F + f_num
                    key_char = p.upper()
            elif p in ("space", "espaço"):
                key_vk = 0x20
                key_char = "Space"

        return mods, key_vk, key_char

    @classmethod
    def format_display(cls, hotkey_str: str) -> str:
        """Formata para exibição em badges: ex: 'Win + Alt + M'."""
        mods, _, char = cls.parse(hotkey_str)
        tokens = []
        if mods["win"]:
            tokens.append("Win")
        if mods["ctrl"]:
            tokens.append("Ctrl")
        if mods["alt"]:
            tokens.append("Alt")
        if mods["shift"]:
            tokens.append("Shift")
        if char:
            tokens.append(char)
        return " + ".join(tokens) if tokens else hotkey_str


class HotkeyService(QObject):
    """
    Gerenciador unificado de atalhos globais de teclado no Windows.
    Executa no loop de mensagens do Qt e dispara chamadas na thread principal.
    """

    hotkey_triggered = Signal(str)  # action_id

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._hook = None
        self._bindings: Dict[str, Tuple[Dict[str, bool], int, Callable]] = {}
        self._c_callback = None
        self._install_hook()

    def _install_hook(self):
        if not user32:
            return
        try:
            self._c_callback = HOOKPROC(self._low_level_proc)
            self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._c_callback, None, 0)
            if self._hook:
                logger.info("HotkeyService: Hook WH_KEYBOARD_LL instalado com sucesso.")
            else:
                logger.warning("HotkeyService: Falha ao instalar hook WH_KEYBOARD_LL.")
        except Exception as e:
            logger.error("HotkeyService: Erro ao instalar hook: %s", e)

    def _low_level_proc(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN) and user32:
            try:
                kb = KBDLLHOOKSTRUCT.from_address(lParam)
                vk = kb.vkCode

                # Lê o estado das teclas modificadoras no exato momento da tecla
                is_win = bool(user32.GetAsyncKeyState(VK_LWIN) & 0x8000 or user32.GetAsyncKeyState(VK_RWIN) & 0x8000)
                is_alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                is_ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                is_shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)

                for action_id, (target_mods, target_vk, callback) in list(self._bindings.items()):
                    if vk == target_vk:
                        if (
                            is_win == target_mods["win"]
                            and is_alt == target_mods["alt"]
                            and is_ctrl == target_mods["ctrl"]
                            and is_shift == target_mods["shift"]
                        ):
                            # Atalho correspondente encontrado!
                            self.hotkey_triggered.emit(action_id)
                            if callback:
                                QTimer.singleShot(0, callback)
                            # Retorna 1 para consumir a tecla e evitar conflitos no Windows
                            return 1
            except Exception as e:
                logger.debug("HotkeyService proc error: %s", e)

        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam) if user32 and self._hook else 0

    def register(self, action_id: str, hotkey_str: str, callback: Callable):
        """Registra ou atualiza um atalho global."""
        mods, vk, char = HotkeyParser.parse(hotkey_str)
        if vk is None:
            logger.warning("HotkeyService: Atalho inválido '%s' para '%s'", hotkey_str, action_id)
            return False

        self._bindings[action_id] = (mods, vk, callback)
        logger.info("HotkeyService: Registrado '%s' -> %s (VK=%s)", action_id, hotkey_str, vk)
        return True

    def unregister(self, action_id: str):
        """Remove o registro de um atalho."""
        self._bindings.pop(action_id, None)

    def cleanup(self):
        """Desinstala o hook do Windows de forma limpa."""
        if user32 and self._hook:
            try:
                user32.UnhookWindowsHookEx(self._hook)
                logger.info("HotkeyService: Hook WH_KEYBOARD_LL desinstalado.")
            except Exception:
                pass
            self._hook = None


_global_hotkey_service = None


def get_hotkey_service() -> HotkeyService:
    global _global_hotkey_service
    if _global_hotkey_service is None:
        _global_hotkey_service = HotkeyService()
    return _global_hotkey_service
