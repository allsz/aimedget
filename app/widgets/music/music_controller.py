from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
from app.services.media_worker import WindowsMediaWorker
from app.widgets.music.skins.vinyl_skin import VinylMusicSkin


class MusicWidgetController(QObject):
    """
    Controlador do Music Widget:
    - Instancia o `WindowsMediaWorker` (único serviço em background).
    - Gerencia a skin ativa (por padrão `VinylMusicSkin`, preparado para alternar entre futuras skins).
    - Conecta os sinais de mídia e comandos da skin ao worker.
    """
    AVAILABLE_SKINS = {
        "vinyl": VinylMusicSkin,
    }

    def __init__(self, skin_name: str = "vinyl", media_worker: WindowsMediaWorker | None = None):
        super().__init__()
        self.media_worker = media_worker or WindowsMediaWorker()
        self.skin = None
        self.set_skin(skin_name)

    def set_skin(self, skin_name: str):
        skin_cls = self.AVAILABLE_SKINS.get(skin_name, VinylMusicSkin)
        old_pos = None

        if self.skin is not None:
            old_pos = self.skin.pos()
            try:
                self.media_worker.media_updated.disconnect(self.skin.on_media_updated)
                self.skin.command_requested.disconnect(self.media_worker.send_command)
            except Exception:
                pass
            self.skin.close()
            self.skin.deleteLater()

        self.skin = skin_cls()
        self.media_worker.media_updated.connect(self.skin.on_media_updated)
        self.skin.command_requested.connect(self.media_worker.send_command)

        if old_pos is not None:
            self.skin.move(old_pos)
        else:
            self.center_on_screen()

    def center_on_screen(self):
        app = QApplication.instance()
        if app and app.primaryScreen() and self.skin:
            screen = app.primaryScreen().geometry()
            x = (screen.width() - self.skin.width()) // 2
            y = (screen.height() - self.skin.height()) // 2
            self.skin.move(x, y)

    def show(self):
        if self.skin:
            self.skin.show()

    def hide(self):
        if self.skin:
            self.skin.hide()

