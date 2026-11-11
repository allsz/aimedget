"""
Custo do app parado na bandeja: a varredura das sessões de áudio (~12 ms cada) só roda com o mixer na tela, e quem
precisa da lista com o mixer fechado (roda do mouse no Music Widget) recebe uma lista recente sob demanda.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication


class SessionScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        from app.services.audio_mixer_service import AudioMixerService

        cls.svc = AudioMixerService()

    @classmethod
    def tearDownClass(cls):
        cls.svc.stop()

    def setUp(self):
        self.svc.set_live_sessions(False)
        self.calls = 0
        original = type(self.svc).refresh_sessions

        def counting(svc_self=self.svc):
            self.calls += 1
            original(svc_self)

        self.svc.refresh_sessions = counting

    def tearDown(self):
        del self.svc.refresh_sessions

    def test_idle_does_not_scan(self):
        self.assertFalse(self.svc._session_timer.isActive())
        self.assertLessEqual(self.svc._fast_timer.interval(), 100)   # teclas e volume externo seguem responsivos

    def test_live_while_mixer_is_on_screen(self):
        self.svc.set_live_sessions(True)
        self.assertTrue(self.svc._session_timer.isActive())
        self.assertEqual(self.calls, 1)   # varre na hora de abrir: a lista não aparece velha
        self.svc.set_live_sessions(False)
        self.assertFalse(self.svc._session_timer.isActive())

    def test_fresh_sessions_rescan_only_when_stale(self):
        self.svc._sessions_at = time.perf_counter()
        self.svc.get_fresh_sessions()
        self.assertEqual(self.calls, 0)
        self.svc._sessions_at = time.perf_counter() - 5.0
        self.svc.get_fresh_sessions()
        self.assertEqual(self.calls, 1)


class MixerVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_mixer_reports_when_it_appears_and_leaves(self):
        from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout

        m = VolumeMixerFlyout()
        seen = []
        m.visibility_changed.connect(seen.append)
        m.show()
        m.hide()
        self.assertEqual(seen, [True, False])


if __name__ == "__main__":
    unittest.main()
