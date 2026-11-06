import os
import sys

# Garante que a raiz do projeto esteja no sys.path mesmo executando `python app/main.py` diretamente
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtWidgets import QApplication
from app.core.typography import init_app_font, get_ui_font
from app.widgets.music.music_controller import MusicWidgetController


def main():
    app = QApplication(sys.argv)
    init_app_font()
    app.setFont(get_ui_font(16))

    # Módulo 1: Music Widget (controlado pelo MusicWidgetController)
    music_controller = MusicWidgetController(skin_name="vinyl")
    music_controller.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

