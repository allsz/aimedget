"""
Escolha da sessão que representa um app com sessões em vários dispositivos (caso real: Chrome roteado para o fone,
com uma sessão esquecida nas caixas).
  python tests/test_mixer_sessions.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.mixer_sessions import SessionReading, choose_primary

CAIXAS = "{0.0.0.00000000}.{dd9417dd}"   # padrão do Windows
FONE = "{0.0.0.00000000}.{e5704a64}"
OUTRO = "{0.0.0.00000000}.{aaaa}"


def r(dev, vol, active=False, muted=False):
    return SessionReading(device_id=dev, volume=vol, muted=muted, active=active)


class ChoosePrimaryTests(unittest.TestCase):
    def test_the_bug_case_paused_chrome_routed_to_headphones_shows_the_headphones_session(self):
        """Antes: mostrava 0 (sessão das caixas). Agora: 50 (a do fone, para onde foi roteado)."""
        readings = [r(CAIXAS, 0), r(FONE, 50)]
        self.assertEqual(choose_primary(readings, CAIXAS, routed_device_id=FONE).volume, 50)

    def test_the_playing_session_wins_even_without_routing_info(self):
        readings = [r(CAIXAS, 0), r(FONE, 50, active=True)]
        self.assertEqual(choose_primary(readings, CAIXAS).volume, 50)

    def test_playing_on_several_devices_prefers_routed_then_default(self):
        readings = [r(OUTRO, 10, active=True), r(CAIXAS, 20, active=True), r(FONE, 30, active=True)]
        self.assertEqual(choose_primary(readings, CAIXAS, FONE).volume, 30)
        self.assertEqual(choose_primary(readings, CAIXAS).volume, 20)

    def test_no_routing_and_nothing_playing_uses_the_default_device(self):
        readings = [r(FONE, 50), r(CAIXAS, 80)]
        self.assertEqual(choose_primary(readings, CAIXAS).volume, 80)

    def test_single_session_on_a_non_default_device(self):
        self.assertEqual(choose_primary([r(FONE, 42)], CAIXAS).volume, 42)

    def test_routed_device_without_a_session_falls_back_to_default(self):
        readings = [r(OUTRO, 10), r(CAIXAS, 20)]
        self.assertEqual(choose_primary(readings, CAIXAS, routed_device_id=FONE).volume, 20)

    def test_nothing_matches_takes_the_first(self):
        readings = [r(OUTRO, 10), r(FONE, 30)]
        self.assertEqual(choose_primary(readings, CAIXAS).volume, 10)

    def test_mute_comes_from_the_chosen_session(self):
        readings = [r(CAIXAS, 0, muted=True), r(FONE, 50, active=True, muted=False)]
        self.assertFalse(choose_primary(readings, CAIXAS).muted)

    def test_empty_is_an_error(self):
        with self.assertRaises(ValueError):
            choose_primary([], CAIXAS)


if __name__ == "__main__":
    unittest.main()
