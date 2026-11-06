import os
import sys


def get_base_dir() -> str:
    """
    Retorna o diretório raiz do projeto.
    Suporta tanto execução em desenvolvimento quanto empacotado em .exe via PyInstaller (sys._MEIPASS).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


BASE_DIR = get_base_dir()
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
VINYL_ASSETS_DIR = os.path.join(ASSETS_DIR, "files", "vinyl-widget", "assets")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "Inter-Variable.ttf")


def get_vinyl_asset(filename: str) -> str:
    """Retorna o caminho absoluto para um asset SVG da skin de Vinil."""
    return os.path.join(VINYL_ASSETS_DIR, filename)

