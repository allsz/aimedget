import os
import sys

# Em ambiente Windows congelado (.exe), define o App ID para a barra de tarefas
# e garante que o diretório de trabalho seja consistente
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("matthew.aimedget.app.1.0")
    except Exception:
        pass

# Garante que a raiz do projeto esteja no sys.path mesmo executando `python app/main.py` diretamente
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtWidgets import QApplication
from app.core.console import make_console_safe
from app.core.crash_reporter import install_crash_reporter
from app.core.typography import init_app_font, get_ui_font
from app.hub.hub_icon import create_aimedget_icon
from app.hub.hub_window import AimedgetHubWindow
from app.hub.service_bridge import get_service_bridge


def main():
    make_console_safe()   # primeiro: um print com título de música em japonês/emoji não pode matar uma thread
    install_crash_reporter()
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("Aimedget")   # sufixo dos títulos de diálogo; o Hub usa título vazio e fica sem ele
    init_app_font()
    app.setFont(get_ui_font(16))
    app.setWindowIcon(create_aimedget_icon())

    # Inicializa todos os serviços integrados (Música, Lock Keys e Mixer)
    bridge = get_service_bridge()
    bridge.start_all()
    app.aboutToQuit.connect(bridge.cleanup_all)

    # Janela Hub Central com System Tray
    hub_window = AimedgetHubWindow()
    bridge.manage_music_skins_requested.connect(hub_window.show_music_skins)

    # Se chamado com --minimized ou --tray (ex: arranque do Windows), mantém o Hub na bandeja
    start_minimized = (
        "--minimized" in sys.argv
        or "--tray" in sys.argv
        or "-m" in sys.argv
    )
    if not start_minimized:
        hub_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

