"""
Páginas de conteúdo do Aimedget Hub. Cada página vive no próprio arquivo; este módulo só reexporta, para o
código e os testes que importam `app.hub.pages`.
"""

from app.hub.base_page import BaseHubPage, HubScrollArea
from app.hub.general_page import GeneralPage
from app.hub.keylock_page import LockKeysPage
from app.hub.music_page import MusicPage
from app.hub.overview_page import OverviewPage
from app.hub.timer_page import TimerPage
from app.hub.volume_page import VolumePage

__all__ = [
    "BaseHubPage", "GeneralPage", "HubScrollArea", "LockKeysPage", "MusicPage", "OverviewPage", "TimerPage",
    "VolumePage",
]
