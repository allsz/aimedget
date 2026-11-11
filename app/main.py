import os
import sys

# Em ambiente Windows congelado (.exe), define o App ID para a barra de tarefas
# e garante que o diretório de trabalho seja consistente
if sys.platform == "win32":
    try:
        import ctypes
        # Identidade fixa do app na barra de tarefas (atalhos fixados, agrupamento de janelas). Sem versão: mudar o
        # ID a cada versão quebraria os atalhos que o usuário fixou. O instalador usa o mesmo ID no atalho do Menu
        # Iniciar (installer/Aimedget.iss), para as notificações e o atalho caírem no mesmo grupo.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Aimedget.Hub")
    except Exception:
        pass

# Garante que a raiz do projeto esteja no sys.path mesmo executando `python app/main.py` diretamente
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtWidgets import QApplication
from app.core.console import make_console_safe
from app.core.crash_reporter import install_crash_reporter
from app.core.single_instance import SingleInstance
from app.core.typography import init_app_font, get_ui_font
from app.hub.hub_icon import create_aimedget_icon
from app.hub.hub_window import AimedgetHubWindow
from app.hub.service_bridge import get_service_bridge


def main():
    make_console_safe()   # primeiro: um print com título de música em japonês/emoji não pode matar uma thread
    install_crash_reporter()
    app = QApplication(sys.argv)
    init_app_font()
    app.setFont(get_ui_font(16))
    app.setWindowIcon(create_aimedget_icon())

    # Se chamado com --minimized ou --tray (ex: arranque do Windows), mantém o Hub na bandeja
    start_minimized = (
        "--minimized" in sys.argv
        or "--tray" in sys.argv
        or "-m" in sys.argv
    )

    # Instância única: se o Aimedget já está aberto, só pede para ele mostrar o Hub e encerra
    instance = SingleInstance(app)
    if instance.notify_running(show=not start_minimized):
        return
    instance.listen()

    # Temas que vêm com o app vão para a pasta de temas do usuário (uma vez; antes dos flyouts lerem os temas)
    from app.core.bundled_themes import seed_bundled_themes
    seed_bundled_themes()

    # Inicializa todos os serviços integrados (Música, Lock Keys e Mixer)
    bridge = get_service_bridge()
    bridge.start_all()
    app.aboutToQuit.connect(bridge.cleanup_all)

    # Janela Hub Central com System Tray
    hub_window = AimedgetHubWindow()
    bridge.manage_music_skins_requested.connect(hub_window.show_music_skins)

    instance.show_requested.connect(hub_window.show_and_activate)
    if not start_minimized:
        hub_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

