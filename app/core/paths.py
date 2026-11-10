import os
import sys


def get_base_dir() -> str:
    """
    Retorna o diretório raiz do projeto.
    Suporta tanto execução em desenvolvimento quanto empacotado em .exe via PyInstaller (sys._MEIPASS ou pasta do executável).
    """
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


BASE_DIR = get_base_dir()
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
VINYL_ASSETS_DIR = os.path.join(ASSETS_DIR, "files", "vinyl-widget", "assets")
FISICAL_BUTTONS_DIR = os.path.join(ASSETS_DIR, "icons", "fisical_buttons")
PROVIDER_ICONS_DIR = os.path.join(ASSETS_DIR, "icons", "providers")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "Inter-Variable.ttf")
APP_ICON_WITH_BG_SVG = os.path.join(ASSETS_DIR, "icons", "aimedget_icon_with_bg.svg")
APP_ICON_CLEAN_SVG = os.path.join(ASSETS_DIR, "icons", "aimedget_icon_clean.svg")
APP_ICON_SVG = APP_ICON_CLEAN_SVG  # Ícone sem fundo (transparente) para uso interno do app
APP_ICON_ICO = os.path.join(ASSETS_DIR, "icons", "aimedget_icon.ico")  # Ícone com fundo para OS/Barra de Tarefas
APP_ICON_PNG = os.path.join(ASSETS_DIR, "icons", "aimedget_icon_with_bg.png")


def get_vinyl_asset(filename: str) -> str:
    """Retorna o caminho absoluto para um asset SVG da skin de Vinil."""
    return os.path.join(VINYL_ASSETS_DIR, filename)


def get_fisical_button_asset(filename: str) -> str:
    """Retorna o caminho absoluto para os botões físicos (play, pause, prev, next)."""
    return os.path.join(FISICAL_BUTTONS_DIR, filename)


def get_provider_icon_path(provider: str) -> str:
    """Retorna o caminho do SVG do provedor oficial (spotify, youtube_music, apple_music, etc.)."""
    return os.path.join(PROVIDER_ICONS_DIR, f"{provider}.svg")


