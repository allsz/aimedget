import sys
import unittest
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.widgets.music.music_controller import MusicWidgetController
from app.hub.service_bridge import HubServiceBridge
from app.hub.pages import MusicPage

app = QApplication.instance() or QApplication(sys.argv)


class DummyMediaWorker:
    def __init__(self):
        self._last_is_playing = False
        self._last_title = ""
        self._last_artist = ""

    def send_command(self, cmd):
        pass


class TestMusicAutoLaunch(unittest.TestCase):
    def setUp(self):
        self._orig_mode = config_manager.get_music_launch_mode()
        self._orig_hide = config_manager.is_auto_hide_enabled()
        self._orig_enabled = config_manager.is_music_enabled()

    def tearDown(self):
        config_manager.set_music_launch_mode(self._orig_mode)
        config_manager.set_auto_hide_enabled(self._orig_hide)
        config_manager.set_music_enabled(self._orig_enabled)

    def test_config_manager_auto_launch(self):
        config_manager.set_auto_launch_enabled(True)
        self.assertTrue(config_manager.is_auto_launch_enabled())
        self.assertEqual(config_manager.get_music_launch_mode(), "auto")

        config_manager.set_auto_launch_enabled(False)
        self.assertFalse(config_manager.is_auto_launch_enabled())
        self.assertEqual(config_manager.get_music_launch_mode(), "manual")

    def test_auto_launch_standby_on_start(self):
        """No modo auto, ao iniciar o controller sem música tocando, o widget fica em standby (oculto)."""
        config_manager.set_auto_launch_enabled(True)
        config_manager.set_music_enabled(True)

        worker = DummyMediaWorker()
        worker._last_is_playing = False
        worker._last_title = "Nenhuma mídia ativa"

        controller = MusicWidgetController(skin_name="capa_empilhada")
        controller.media_worker = worker

        controller.start()
        self.assertFalse(controller.skin.isVisible())

        # Ao receber sinal de música tocando, deve abrir
        controller._handle_auto_launch_lifecycle(
            title="Blinding Lights",
            artist="The Weeknd",
            is_playing=True,
            pos=10.0,
            dur=200.0,
            thumb_bytes=b"",
        )
        self.assertTrue(controller.skin.isVisible())

        # Cleanup
        controller.skin.close()

    def test_manual_mode_shows_on_start(self):
        """No modo manual, ao iniciar o controller, o widget deve abrir imediatamente."""
        config_manager.set_auto_launch_enabled(False)
        config_manager.set_music_enabled(True)

        controller = MusicWidgetController(skin_name="capa_empilhada")
        controller.start()
        self.assertTrue(controller.skin.isVisible())

        controller.skin.close()

    def test_auto_hide_on_stop(self):
        """Com auto_hide ativado, ao receber 'Nenhuma mídia ativa', o widget se oculta."""
        config_manager.set_auto_launch_enabled(True)
        config_manager.set_auto_hide_enabled(True)
        config_manager.set_music_enabled(True)

        controller = MusicWidgetController(skin_name="capa_empilhada")
        controller.show()
        controller._has_played_since_shown = True
        self.assertTrue(controller.skin.isVisible())

        # Emite parada de música
        controller._handle_auto_launch_lifecycle(
            title="Nenhuma mídia ativa",
            artist="O que vamos ouvir hoje?",
            is_playing=False,
            pos=0.0,
            dur=0.0,
            thumb_bytes=b"",
        )
        self.assertFalse(controller.skin.isVisible())

        controller.skin.close()

    def test_music_page_switches_bound_to_config(self):
        """Testa se os switches na MusicPage leem e persistem as alterações no config_manager."""
        config_manager.set_auto_launch_enabled(True)
        config_manager.set_auto_hide_enabled(False)

        bridge = HubServiceBridge()
        page = MusicPage(parent=None)

        self.assertTrue(page.sw_auto_launch.isChecked())
        self.assertFalse(page.sw_auto_hide.isChecked())

        # Simula o clique do usuário para desativar abertura automática
        page.sw_auto_launch.setChecked(False)
        self.assertFalse(config_manager.is_auto_launch_enabled())

        # Simula o clique do usuário para ativar auto hide
        page.sw_auto_hide.setChecked(True)
        self.assertTrue(config_manager.is_auto_hide_enabled())


if __name__ == "__main__":
    unittest.main()
