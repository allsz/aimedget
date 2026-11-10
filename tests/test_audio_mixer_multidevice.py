"""
AudioMixerService com vários dispositivos de saída (caso real: Chrome roteado para o fone com uma sessão parada nas
caixas). Sem COM de verdade: o construtor é isolado e as partes de COM são trocadas por falsos.
  python tests/test_audio_mixer_multidevice.py
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.services import audio_mixer_service as ams
from app.services.audio_mixer_service import AudioMixerService
from app.services.mixer_sessions import SessionReading

_app = QApplication.instance() or QApplication([])

CAIXAS, FONE = "dev-caixas", "dev-fone"
CHROME = r"c:\program files\google\chrome\application\chrome.exe"


def make_service() -> AudioMixerService:
    """Serviço sem hook de teclado, sem COM e sem timers rodando."""
    with mock.patch.object(AudioMixerService, "_install_volume_key_hook", lambda self: None), \
         mock.patch.object(AudioMixerService, "_suppress_native_osd_window", lambda self: None), \
         mock.patch.object(AudioMixerService, "_init_com_interfaces", lambda self: None), \
         mock.patch.object(AudioMixerService, "refresh_sessions", lambda self: None), \
         mock.patch.object(AudioMixerService, "get_master_volume", lambda self: 50), \
         mock.patch.object(AudioMixerService, "get_master_mute", lambda self: False):
        svc = AudioMixerService()
    svc._fast_timer.stop()
    svc._session_timer.stop()
    svc._default_dev_id = CAIXAS
    return svc


def reading(dev, active=False):
    return SessionReading(device_id=dev, volume=50, muted=False, active=active)


class RouteResolutionTests(unittest.TestCase):
    def setUp(self):
        self.svc = make_service()
        self.calls = []
        self.svc.set_route_resolver(lambda app_id: (self.calls.append(app_id), FONE)[1])

    def test_route_is_asked_only_when_it_decides_something(self):
        two_paused = [reading(CAIXAS), reading(FONE)]
        self.assertEqual(self.svc._routed_device(CHROME, two_paused), FONE)
        self.assertIsNone(self.svc._routed_device("x", [reading(CAIXAS)]))                       # 1 dispositivo
        self.assertIsNone(self.svc._routed_device("y", [reading(CAIXAS, True), reading(FONE)]))  # já tocando
        self.assertEqual(self.calls, [CHROME])

    def test_route_is_cached_for_five_seconds(self):
        two = [reading(CAIXAS), reading(FONE)]
        with mock.patch.object(ams.time, "perf_counter", return_value=100.0):
            self.svc._routed_device(CHROME, two)
        with mock.patch.object(ams.time, "perf_counter", return_value=104.0):
            self.svc._routed_device(CHROME, two)
        self.assertEqual(len(self.calls), 1)
        with mock.patch.object(ams.time, "perf_counter", return_value=106.0):
            self.svc._routed_device(CHROME, two)
        self.assertEqual(len(self.calls), 2)

    def test_default_or_failing_resolver_means_no_route(self):
        two = [reading(CAIXAS), reading(FONE)]
        self.svc.set_route_resolver(lambda app_id: "__default__")
        self.assertIsNone(self.svc._routed_device(CHROME, two))
        self.svc.set_route_resolver(lambda app_id: 1 / 0)
        self.assertIsNone(self.svc._routed_device("outro", two))

    def test_user_changing_the_route_takes_effect_immediately(self):
        two = [reading(CAIXAS), reading(FONE)]
        self.svc._routed_device(CHROME, two)                          # cache: fone
        self.svc.on_app_route_changed(CHROME, "output", "__default__")
        self.assertIsNone(self.svc._routed_device(CHROME, two))       # sem perguntar de novo
        self.svc.on_app_route_changed(CHROME, "output", FONE)
        self.assertEqual(self.svc._routed_device(CHROME, two), FONE)
        self.svc.on_app_route_changed(CHROME, "input", "mic")          # entrada não muda a saída
        self.assertEqual(self.svc._routed_device(CHROME, two), FONE)
        self.assertEqual(len(self.calls), 1)


class ApplyToAllDevicesTests(unittest.TestCase):
    def test_volume_and_mute_go_to_the_app_sessions_on_every_device(self):
        svc = make_service()
        sessions = {"mgr-caixas": [CHROME, "steam.exe"], "mgr-fone": [CHROME]}

        def fake_for_each(mgr, _proc_map, visit, include_expired=False):
            for app_id in sessions[mgr]:
                visit(app_id, "", False, None, f"svol:{mgr}:{app_id}", 0)

        writes = []
        with mock.patch.object(svc, "_device_managers", return_value=[(CAIXAS, "mgr-caixas"), (FONE, "mgr-fone")]), \
             mock.patch.object(svc, "_for_each_session", side_effect=fake_for_each), \
             mock.patch.object(svc, "_write_session", side_effect=lambda svol, v, m: writes.append((svol, v, m))), \
             mock.patch.object(ams, "get_parent_process_map", return_value={}):
            n = svc._apply_to_matching_sessions(CHROME, volume=30)
            svc._apply_to_matching_sessions(CHROME, mute=True)

        self.assertEqual(n, 2)
        self.assertEqual(writes[:2], [(f"svol:mgr-caixas:{CHROME}", 30, None), (f"svol:mgr-fone:{CHROME}", 30, None)])
        self.assertEqual([w[2] for w in writes[2:]], [True, True])
        self.assertFalse(any("steam" in w[0] for w in writes))

    def test_no_devices_changes_nothing(self):
        svc = make_service()
        with mock.patch.object(svc, "_device_managers", return_value=[]):
            self.assertEqual(svc._apply_to_matching_sessions(CHROME, volume=10), 0)


class DefaultDeviceChangeTests(unittest.TestCase):
    def test_switching_the_windows_default_reopens_the_master_volume_once(self):
        svc = make_service()
        reinit = []
        with mock.patch.object(svc, "_current_default_device_id", return_value=FONE), \
             mock.patch.object(svc, "_init_com_interfaces", side_effect=lambda: reinit.append(1)):
            svc._check_default_device(10.0)
            svc._check_default_device(10.5)    # menos de 1 s depois: nem consulta
        self.assertEqual(reinit, [1])

    def test_same_default_or_no_device_does_nothing(self):
        svc = make_service()
        for current in (CAIXAS, ""):
            with mock.patch.object(svc, "_current_default_device_id", return_value=current), \
                 mock.patch.object(svc, "_init_com_interfaces") as init:
                svc._default_check_at = 0.0
                svc._check_default_device(100.0)
            init.assert_not_called()


if __name__ == "__main__":
    unittest.main()
