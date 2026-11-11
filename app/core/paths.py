import logging
import os
import shutil
import sys

logger = logging.getLogger(__name__)

APP_DATA_NAME = "Aimedget"
LEGACY_APP_DATA_NAME = "WindowsRedesign"   # nome antigo do projeto; migrado para APP_DATA_NAME na primeira abertura
_migration_done = False


def _local_appdata() -> str:
    return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")


def migrate_legacy_data_dir(base: str | None = None) -> str:
    """
    Traz os dados da pasta antiga (%LOCALAPPDATA%/WindowsRedesign) para a nova (%LOCALAPPDATA%/Aimedget) e devolve
    a pasta que o app deve usar. Nunca sobrescreve nada: se a nova não existe, a antiga é renomeada; se as duas
    existem, só passam os itens que a nova ainda não tem. Se algo falhar (arquivo em uso, permissão), o app segue
    usando a pasta antiga em vez de perder as configurações do usuário.
    """
    base = base or _local_appdata()
    new_dir = os.path.join(base, APP_DATA_NAME)
    old_dir = os.path.join(base, LEGACY_APP_DATA_NAME)
    if not os.path.isdir(old_dir):
        return new_dir
    try:
        if not os.path.exists(new_dir):
            os.rename(old_dir, new_dir)
            return new_dir
        for entry in os.listdir(old_dir):
            target = os.path.join(new_dir, entry)
            if not os.path.exists(target):
                shutil.move(os.path.join(old_dir, entry), target)
        try:
            os.rmdir(old_dir)   # só remove se ficou vazia
        except OSError:
            pass
        return new_dir
    except OSError as exc:
        logger.warning("Não foi possível migrar %s para %s (%s); continuando com a pasta antiga", old_dir, new_dir, exc)
        return old_dir


def get_app_data_dir() -> str:
    """Pasta de dados do usuário (configurações, temas, cache). Migra a pasta antiga uma vez por execução."""
    global _migration_done
    base = _local_appdata()
    if not _migration_done:
        _migration_done = True
        return migrate_legacy_data_dir(base)
    new_dir = os.path.join(base, APP_DATA_NAME)
    old_dir = os.path.join(base, LEGACY_APP_DATA_NAME)
    # Migração que falhou antes: continua na antiga enquanto a nova não existir
    return old_dir if (os.path.isdir(old_dir) and not os.path.exists(new_dir)) else new_dir


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


