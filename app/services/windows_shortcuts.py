"""
Atalhos que o próprio Windows usa. O seletor de atalho avisa antes de gravar um deles: alguns o Windows atende mesmo
com o nosso hook engolindo a tecla (Win+Alt+B liga/desliga o HDR de qualquer jeito), então quem escolhe é o usuário.

Ficam de fora os da Game Bar (Win+Alt+G/R/T/M...): o usuário pode trocá-los lá, e o hook do app já ganha deles.
"""

from typing import Optional

from app.core.i18n import t
from app.services.hotkey_service import HotkeyParser

# (modificadores, tecla) -> chave do texto em i18n
_RESERVED = {
    ("win", "A"): "winkey_quick_settings",
    ("win", "B"): "winkey_tray",
    ("win", "C"): "winkey_copilot",
    ("win", "D"): "winkey_desktop",
    ("win", "E"): "winkey_explorer",
    ("win", "G"): "winkey_game_bar",
    ("win", "H"): "winkey_voice_typing",
    ("win", "I"): "winkey_settings",
    ("win", "K"): "winkey_cast",
    ("win", "L"): "winkey_lock",
    ("win", "M"): "winkey_minimize_all",
    ("win", "N"): "winkey_notifications",
    ("win", "P"): "winkey_project",
    ("win", "Q"): "winkey_search",
    ("win", "R"): "winkey_run",
    ("win", "S"): "winkey_search",
    ("win", "T"): "winkey_taskbar",
    ("win", "U"): "winkey_accessibility",
    ("win", "V"): "winkey_clipboard",
    ("win", "W"): "winkey_widgets",
    ("win", "X"): "winkey_quick_link",
    ("win", "Z"): "winkey_snap",
    ("win", "Space"): "winkey_input_language",
    ("win+shift", "S"): "winkey_screenshot",
    ("win+ctrl", "D"): "winkey_new_desktop",
    ("win+alt", "B"): "winkey_hdr",
    ("win+alt", "D"): "winkey_date_time",
}


def _key(hotkey: str) -> tuple:
    mods, _vk, char = HotkeyParser.parse(hotkey)
    order = ("win", "ctrl", "alt", "shift")
    return "+".join(m for m in order if mods[m]), char


def windows_use(hotkey: str) -> Optional[str]:
    """O que o Windows faz com este atalho (texto curto, no idioma atual), ou None se ele estiver livre."""
    key = _RESERVED.get(_key(hotkey))
    return t(key) if key else None
