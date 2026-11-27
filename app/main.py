import os
import sys

def _app_user_model_id() -> str:
    """Identidade fixa do app na barra de tarefas.
    - Release (.exe): "Aimedget.Hub" (mesmo ID do atalho no Menu Iniciar em installer/Aimedget.iss).
    - Desenvolvimento (python app/main.py): "Aimedget.Hub.Dev", separado do atalho instalado para que
      o Windows exiba o ícone DEV da janela em vez do ícone do python.exe ou do Aimedget instalado.
    """
    return "Aimedget.Hub" if getattr(sys, "frozen", False) else "Aimedget.Hub.Dev"


# Define o App ID para a barra de tarefas antes de criar o QApplication
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_app_user_model_id())
    except Exception:
        pass

# Garante que a raiz do projeto esteja no sys.path mesmo executando `python app/main.py` diretamente
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core import startup_trace   # só biblioteca padrão: pode (e deve) vir antes dos imports pesados

startup_trace.mark("python_start")

from PySide6.QtWidgets import QApplication
from app.core.console import make_console_safe
from app.core.crash_reporter import install_crash_reporter
from app.core.single_instance import SingleInstance

startup_trace.mark("qt_imported")


def main():
    make_console_safe()   # primeiro: um print com título de música em japonês/emoji não pode matar uma thread
    install_crash_reporter()
    app = QApplication(sys.argv)
    startup_trace.mark("qapplication")

    # Se chamado com --minimized ou --tray (ex: arranque do Windows), mantém o Hub na bandeja
    start_minimized = (
        "--minimized" in sys.argv
        or "--tray" in sys.argv
        or "-m" in sys.argv
    )

    # Instância única: se o Aimedget já está aberto, só pede para ele mostrar o Hub e encerra. Vem ANTES de fontes, ícones
    # e do resto dos módulos do app: a segunda cópia não paga nada disso.
    instance = SingleInstance(app)
    if instance.notify_running(show=not start_minimized):
        return
    instance.listen()

    # O resto dos módulos do app só é importado agora (a cópia que encerra acima nunca os carrega)
    from app.core.typography import init_app_font, get_ui_font
    from app.hub.hub_icon import create_aimedget_icon
    from app.hub.hub_window import AimedgetHubWindow
    from app.hub.service_bridge import get_service_bridge
    startup_trace.mark("app_imported")

    init_app_font()
    app.setFont(get_ui_font(16))
    app.setWindowIcon(create_aimedget_icon())

    from app.core import screen_debug   # AIMEDGET_SCREEN_DEBUG=1 (ou =observe): registro de trocas de monitor
    screen_debug.install()

    # Temas que vêm com o app vão para a pasta de temas do usuário (uma vez; antes dos flyouts lerem os temas)
    from app.core.bundled_themes import seed_bundled_themes
    seed_bundled_themes()

    # Inicializa todos os serviços integrados (Música, Lock Keys e Mixer)
    bridge = get_service_bridge()
    startup_trace.mark("bridge_created")
    bridge.start_all()
    app.aboutToQuit.connect(bridge.cleanup_all)
    startup_trace.mark("widgets_started")

    # Janela Hub Central com System Tray. Minimizado (arranque do Windows): o Hub não é montado agora, só a bandeja;
    # as páginas sobem quando o Hub abre pela primeira vez, ou sozinhas quando a CPU já se acalmou.
    hub_window = AimedgetHubWindow(defer_ui=start_minimized)
    bridge.manage_music_skins_requested.connect(hub_window.show_music_skins)
    bridge.manage_weather_cities_requested.connect(hub_window.show_weather_cities)
    bridge.configure_widget_requested.connect(hub_window.show_widget_page)

    instance.show_requested.connect(hub_window.show_and_activate)
    if start_minimized:
        # Monta o Hub escondido só quando a CPU do sistema acalmar (no logon o Windows ainda está subindo tudo)
        from app.core.idle_gate import IdleGate
        hub_window._idle_gate = IdleGate(hub_window.prebuild_ui, parent=hub_window)
        hub_window._idle_gate.start()
    else:
        hub_window.show_and_activate()

    startup_trace.mark("ready")
    startup_trace.finish("minimized" if start_minimized else "normal")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
