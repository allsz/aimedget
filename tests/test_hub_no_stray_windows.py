"""Construir o Hub não pode abrir rótulos/seções soltos como janelas (o "piscar de pop-ups" ao iniciar):
setVisible(True) num widget ainda sem pai o transforma numa janela própria."""
import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from app.hub.hub_window import AimedgetHubWindow


class _Spy(QObject):
    def __init__(self):
        super().__init__()
        self.windows = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.windows.append(type(obj).__name__)
        return False


def test_building_the_hub_shows_no_loose_child_widgets_as_windows():
    app = QApplication.instance() or QApplication(sys.argv)
    spy = _Spy()
    app.installEventFilter(spy)
    try:
        hub = AimedgetHubWindow()
        app.processEvents()
        assert spy.windows == [], spy.windows
        hub.show()
        app.processEvents()
        assert set(spy.windows) <= {"AimedgetHubWindow"}, spy.windows
        hub.close()
        hub.deleteLater()
    finally:
        app.removeEventFilter(spy)
