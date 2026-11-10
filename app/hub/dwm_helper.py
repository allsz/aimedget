"""
Utilitário para aplicar personalizações nativas do Windows 11 DWM (Desktop Window Manager):
- DWMWA_CAPTION_COLOR (35): Colore a barra de título nativa com a cor exata do app.
- DWMWA_TEXT_COLOR (36): Define a cor dos títulos e ícones.
- DWMWA_WINDOW_CORNER_PREFERENCE (33): Garante cantos arredondados nativos do Windows 11 (DWMWCP_ROUND).
- DWMWA_USE_IMMERSIVE_DARK_MODE (20): Sincroniza o modo escuro no frame do Windows.
"""

import ctypes
from ctypes import byref, c_int
import sys

# Constantes da DWM API do Windows
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

# Cantos arredondados (Windows 11)
DWMWCP_ROUND = 2


def hex_to_bgr_int(hex_color: str) -> int:
    """Converte '#RRGGBB' para o inteiro BGR esperado pela Win32 API."""
    hex_clean = hex_color.lstrip("#")
    if len(hex_clean) == 6:
        r = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        b = int(hex_clean[4:6], 16)
        return (b << 16) | (g << 8) | r
    return 0


def apply_windows_dwm_titlebar(hwnd: int, bg_hex: str, text_hex: str, is_dark: bool):
    """
    Aplica as cores nativas e cantos arredondados na janela do Windows 11.
    Garante ícones ultra-nítidos vetorizados do sistema, suporte a Snap Layouts
    e sombra nativa sem perder os cantos redondos.
    """
    if sys.platform != "win32":
        return

    try:
        dwmapi = ctypes.WinDLL("dwmapi")

        # 1. Cantos arredondados nativos do Windows 11
        corner_val = c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, byref(corner_val), 4)

        # 2. Modo escuro imersivo no frame
        dark_val = c_int(1 if is_dark else 0)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(dark_val), 4)

        # 3. Cor da barra de título fundida com o fundo
        bgr_color = c_int(hex_to_bgr_int(bg_hex))
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, byref(bgr_color), 4)

        # 4. Cor do texto do título
        bgr_text = c_int(hex_to_bgr_int(text_hex))
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, byref(bgr_text), 4)

    except Exception:
        pass
