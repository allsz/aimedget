"""Razer (protocolo do OpenRazer, sem aparelho para confirmar): pacote, escolha da coleção e leitura com falsos."""

import unittest
from unittest import mock

from app.services.battery import hid_win, razer
from app.services.battery.models import KIND_MOUSE


def info(pid=0x00B7, mi=0, feature=91, serial="", inst="a"):
    path = rf"\\?\hid#vid_1532&pid_{pid:04x}&mi_{mi:02d}&col01#8&{inst}&0&0000#{{x}}"
    return hid_win.HidInfo(path=path, vid=razer.RAZER_VID, pid=pid, usage_page=1, usage=2, input_len=8,
                           output_len=0, feature_len=feature, product="Razer", serial=serial)


def reply(tx, command_id, value, status=razer.STATUS_OK):
    pkt = bytearray(razer.build_request(tx, command_id))
    pkt[0] = status
    pkt[9] = value
    return bytes(pkt)


class FakeFeature:
    """Responde por comando; `busy` devolve "ocupado" antes da resposta."""
    answers: dict = {}
    busy = 0
    requests: list = []

    def __init__(self, info):
        self.info = info
        self.last = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_feature(self, data):
        FakeFeature.requests.append(bytes(data))
        self.last = data[1:]
        return True

    def get_feature(self, report_id=0):
        cmd = self.last[7]
        if FakeFeature.busy:
            FakeFeature.busy -= 1
            return b"\x00" + reply(self.last[1], cmd, 0, razer.STATUS_BUSY)
        if cmd not in FakeFeature.answers:
            return b"\x00" + reply(self.last[1], cmd, 0, 0x05)       # sem suporte
        return b"\x00" + reply(self.last[1], cmd, FakeFeature.answers[cmd])


def fake(answers, busy=0):
    FakeFeature.answers, FakeFeature.busy, FakeFeature.requests = answers, busy, []
    return mock.patch.object(hid_win, "FeatureHandle", FakeFeature)


class RazerProtocolTests(unittest.TestCase):
    def test_table_matches_openrazer_charge_level_list(self):
        self.assertEqual(len(razer.MODELS), 72)
        self.assertEqual({m.tx for m in razer.MODELS.values()}, {0x1F, 0x3F, 0xFF})
        self.assertEqual({p for p, m in razer.MODELS.items() if m.index == 3}, {0x00CB, 0x00E5, 0x00E6})

    def test_request_layout_and_crc(self):
        req = razer.build_request(0x1F, razer.CMD_BATTERY)
        self.assertEqual(len(req), 90)
        self.assertEqual(req[:8], bytes([0, 0x1F, 0, 0, 0, 0x02, 0x07, 0x80]))
        self.assertEqual(req[88], 0x02 ^ 0x07 ^ 0x80)               # XOR dos bytes 2..87
        self.assertEqual(req[89], 0)

    def test_parse_reply(self):
        self.assertEqual(razer.parse_reply(reply(0x1F, 0x80, 200), 0x80), 200)
        self.assertIsNone(razer.parse_reply(reply(0x1F, 0x80, 200, razer.STATUS_BUSY), 0x80))
        self.assertIsNone(razer.parse_reply(reply(0x1F, 0x84, 1), 0x80))       # outro comando
        self.assertIsNone(razer.parse_reply(reply(0x1F, 0x80, 1)[:50], 0x80))   # curto
        self.assertIsNone(razer.parse_reply(None, 0x80))

    def test_level_scale(self):
        self.assertEqual(razer.percent_from_level(255), 100)
        self.assertEqual(razer.percent_from_level(128), 50)
        self.assertEqual(razer.percent_from_level(0), 0)


class RazerReadTests(unittest.TestCase):
    def setUp(self):
        sleeps = mock.patch.object(razer.time, "sleep", lambda s: None)
        sleeps.start()
        self.addCleanup(sleeps.stop)

    def test_only_the_right_interface_with_a_90_byte_feature_report(self):
        good = info()
        wrong_if = info(mi=1, inst="b")
        wrong_len = info(feature=65, inst="c")
        unknown = info(pid=0x1234, inst="d")
        v4 = info(pid=0x00E6, mi=3, inst="e")                        # Viper V4 Pro usa a interface 3
        self.assertEqual(razer._endpoints([good, wrong_if, wrong_len, unknown, v4]), sorted(
            [good, v4], key=razer._card_key))

    def test_reads_level_and_charging(self):
        with fake({0x80: 128, 0x84: 1}):
            out = razer.read_devices([info()])
        self.assertEqual([(d.name, d.kind, d.source, d.percent, d.charging) for d in out],
                         [("Razer DeathAdder V3 Pro", KIND_MOUSE, "razer", 50.0, True)])
        self.assertEqual(FakeFeature.requests[0][0], 0)              # id 0 na frente
        self.assertEqual(len(FakeFeature.requests[0]), 91)
        self.assertEqual(FakeFeature.requests[0][2], 0x1F)           # transaction_id desse PID

    def test_busy_then_answer(self):
        with fake({0x80: 255, 0x84: 0}, busy=1):
            out = razer.read_devices([info()])
        self.assertEqual([(d.percent, d.charging) for d in out], [(100.0, False)])

    def test_aa_models_never_ask_charging(self):
        with fake({0x80: 255}):
            out = razer.read_devices([info(pid=0x0094)])             # Orochi V2 (pilhas)
        self.assertEqual([(d.percent, d.charging) for d in out], [(100.0, False)])
        self.assertEqual([r[8] for r in FakeFeature.requests], [0x80])

    def test_no_support_or_zero_hides_the_mouse(self):
        with fake({}):
            self.assertEqual(razer.read_devices([info()]), [])
        with fake({0x80: 0, 0x84: 0}):
            self.assertEqual(razer.read_devices([info()]), [])

    def test_present_ids_match_card_ids(self):
        with fake({0x80: 128, 0x84: 0}):
            out = razer.read_devices([info()])
        self.assertEqual(razer.present_ids([info()]), {out[0].id})


if __name__ == "__main__":
    unittest.main()
