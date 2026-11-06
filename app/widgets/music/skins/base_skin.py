from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget
from app.core.typography import init_app_font
from app.core.colorimetry import (
    ThemePalette,
    get_default_palette,
    extract_palette_from_image,
)


class BaseMusicSkin(QWidget):
    """
    Classe base para qualquer Skin do Music Widget.
    Fornece:
    - Configuração de janela flutuante transparente sem bordas
    - Sinal unificado `command_requested(action, value)` para enviar comandos ao MediaWorker
    - Estado comum de faixa (título, artista, duração, tempo atual, capa do álbum e paleta adaptativa)
    """
    command_requested = Signal(str, object)

    def __init__(self, width: int, height: int):
        super().__init__()
        init_app_font()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(width, height)
        self.setMouseTracking(True)

        # Estado base da mídia
        self.title_text = "Main Theme"
        self.artist_text = "MD Studio"
        self.duration = 222.0
        self.current_time = 0.0
        self.is_playing = False
        self.album_pixmap = None
        self._last_thumb_bytes = b""
        self._drag_pos = QPoint()

        # Estado de Colorimetria Dinâmica (Passo 4)
        self.current_palette: ThemePalette = get_default_palette()
        self.target_palette: ThemePalette = get_default_palette()

    def _update_and_cache_cover(self, thumb_bytes: bytes) -> bool:
        """
        Atualiza o QPixmap da capa e extrai automaticamente a nova paleta de cores dominante
        sempre que os bytes da imagem mudam.
        """
        if thumb_bytes != self._last_thumb_bytes:
            self._last_thumb_bytes = thumb_bytes
            if thumb_bytes:
                img = QImage.fromData(thumb_bytes)
                if not img.isNull():
                    self.album_pixmap = QPixmap.fromImage(img)
                    self.target_palette = extract_palette_from_image(img)
                else:
                    self.album_pixmap = None
                    self.target_palette = get_default_palette()
            else:
                self.album_pixmap = None
                self.target_palette = get_default_palette()
            return True
        return False

    def on_media_updated(self, title: str, artist: str, is_playing: bool, pos: float, dur: float, thumb_bytes: bytes):
        """Implementado pelas subclasses para reagir à atualização do WindowsMediaWorker."""
        raise NotImplementedError

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        s = max(0, int(seconds))
        return f"{s // 60}:{s % 60:02d}"
