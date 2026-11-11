"""
Ponto de entrada compatível para o Music Widget.
O código monolítico foi refatorado seguindo a diretriz `.agents/skills/modular-architecture/SKILL.md`:
- `app/core/paths.py` & `app/core/typography.py`: Caminhos (compatíveis com .exe) e fonte Inter global
- `app/services/media_worker.py`: Worker assíncrono Windows GSMTC (sem código de UI)
- `app/ui_components/pill_button.py`: Componente visual reutilizável (.pill)
- `app/widgets/music/skins/vinyl_skin.py`: Skin de Vinil com física 33 RPM e listener exclusivo `tonearm_landed`
- `app/widgets/music/music_controller.py`: Controlador que conecta o MediaWorker à skin ativa
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services.media_worker import WindowsMediaWorker
from app.widgets.music.skins.vinyl_skin import VinylMusicSkin
from app.main import main


class MusicWidget(VinylMusicSkin):
    """Wrapper de compatibilidade direta que já conecta o VinylMusicSkin ao WindowsMediaWorker."""

    def __init__(self):
        super().__init__()
        self.media_worker = WindowsMediaWorker()
        self.media_worker.media_updated.connect(self.on_media_updated)
        self.command_requested.connect(self.media_worker.send_command)


if __name__ == "__main__":
    main()
