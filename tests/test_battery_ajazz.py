"""Mouses AJAZZ: pedido por relatório de recurso, resposta na outra coleção do dongle (pacotes reais do AJ139 PRO)."""

import unittest
from unittest import mock

from app.services.battery import ajazz, hid_win, mouse_1k
from app.services.battery.models import KIND_MOUSE

REAL_REQUEST = bytes.fromhex("0804000000000000000000000000000049")
REAL_REPLY = bytes.fromhex("0904000000022d000000000000000000" "19")   # 45%, sem cabo
WIRED_REPLY = bytes.fromhex("0904000000025f010000000000000000" "e6")  # 95%, carregando (mouse FA7B no cabo)


def info(page, col, inst="7&19ddc0ef&0", n=0, pid=0xFA7C, feature=0, inp=0):
    path = rf"\\?\hid#vid_25a7&pid_{pid:04x}&mi_01&col{col:02d}#{inst}&{n:04d}#{{4d1e55b2-f16f-11cf-88cb-001111000030}}"
    return hid_win.HidInfo(path=path, vid=ajazz.AJAZZ_VID, pid=pid, usage_page=page, usage=2,
                           input_len=inp, output_len=0, feature_len=feature, product="2.4G Wireless Receiver")


def dongle(inst="7&19ddc0ef&0"):
    return [info(0xFF01, 5, inst, 4, inp=17), info(0xFF04, 6, inst, 5, feature=8),
            info(0xFF02, 7, inst, 6, feature=17)]


class FakeHandle:
    """Coleção FF01 devolve o que estiver na fila; o set_feature na FF02 enfileira a resposta."""
    replies: dict = {}
    sent: list = []

    def __init__(self, info, write=False):
        self.info = info
        self.key = ajazz.device_key(info.path)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_feature(self, data):
        FakeHandle.sent.append((self.info.usage_page, bytes(data)))
        FakeHandle.queue.setdefault(self.key, []).extend(FakeHandle.replies.get(self.key, []))
        return True

    def read(self, timeout_ms):
        q = FakeHandle.queue.get(self.key, [])
        return q.pop(0) if q else None


def fake(replies, stale=()):
    FakeHandle.replies, FakeHandle.sent = replies, []
    FakeHandle.queue = {k: list(stale) for k in replies}
    return mock.patch.object(hid_win, "HidHandle", FakeHandle)


class AjazzTests(unittest.TestCase):
    def test_request_is_the_sent_packet(self):
        self.assertEqual(ajazz.build_request(), REAL_REQUEST)

    def test_real_reply(self):
        self.assertEqual(ajazz.parse_reply(REAL_REPLY), (45.0, False))

    def test_rejects_other_replies(self):
        self.assertIsNone(ajazz.parse_reply(REAL_REPLY[:-1]))
        self.assertIsNone(ajazz.parse_reply(REAL_REPLY[:-1] + b"\x00"))
        self.assertIsNone(ajazz.parse_reply(bytes([0x08]) + REAL_REPLY[1:]))    # id do VXE, não do AJAZZ
        self.assertIsNone(ajazz.parse_reply(None))

    def test_collections_of_one_dongle_share_a_key(self):
        keys = {ajazz.device_key(i.path) for i in dongle()}
        self.assertEqual(len(keys), 1)
        self.assertNotEqual(keys, {ajazz.device_key(i.path) for i in dongle("7&aaaa&0")})

    def test_reads_the_mouse_and_skips_stale_reports(self):
        key = ajazz.device_key(dongle()[0].path)
        with fake({key: [REAL_REPLY]}, stale=[bytes(17)]):
            out = ajazz.read_devices(dongle())
        self.assertEqual(len(out), 1)
        d = out[0]
        self.assertEqual((d.name, d.kind, d.source, d.percent, d.charging),
                         ("AJAZZ Mouse", KIND_MOUSE, "ajazz", 45.0, False))
        self.assertEqual(FakeHandle.sent, [(0xFF02, REAL_REQUEST)])            # o pedido vai na FF02

    def test_sleeping_mouse_is_hidden(self):
        key = ajazz.device_key(dongle()[0].path)
        with fake({key: []}):
            self.assertEqual(ajazz.read_devices(dongle()), [])

    def test_unknown_pid_and_half_dongle_are_ignored(self):
        with fake({}):
            self.assertEqual(ajazz.read_devices([i for i in dongle() if i.usage_page != 0xFF01]), [])
            self.assertEqual(ajazz.read_devices([info(0xFF02, 7, pid=0x1234, feature=17)]), [])

    def test_real_wired_reply_is_charging(self):
        self.assertEqual(ajazz.parse_reply(WIRED_REPLY), (95.0, True))

    def test_wired_mouse_alone(self):
        """Dongle fora do notebook, mouse carregando no cabo (FA7B): aparece sozinho, carregando."""
        wired = [info(0xFF01, 5, "7&cabo&0", 4, pid=0xFA7B, inp=17),
                 info(0xFF02, 7, "7&cabo&0", 6, pid=0xFA7B, feature=17)]
        with fake({ajazz.device_key(wired[0].path): [WIRED_REPLY]}):
            out = ajazz.read_devices(wired)
        self.assertEqual([(d.name, d.percent, d.charging) for d in out], [("AJAZZ Mouse", 95.0, True)])

    def test_wired_mouse_takes_the_silent_dongle_card(self):
        """Dongle ainda espetado mas mudo, mouse no cabo responde: um cartão só, com o id do dongle."""
        wired = [info(0xFF01, 5, "7&cabo&0", 4, pid=0xFA7B, inp=17),
                 info(0xFF02, 7, "7&cabo&0", 6, pid=0xFA7B, feature=17)]
        with fake({ajazz.device_key(dongle()[0].path): [], ajazz.device_key(wired[0].path): [WIRED_REPLY]}):
            out = ajazz.read_devices(dongle() + wired)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0].percent, out[0].charging), (95.0, True))
        self.assertEqual(out[0].id, "ajazz:" + ajazz.device_key(dongle()[0].path))

    def test_real_dongle_and_cable_together_give_one_card(self):
        """Pacotes reais com dongle e cabo ao mesmo tempo: o dongle responde nível 0 (mouse fora do ar), o cabo
        responde 95% carregando. Um cartão só, com o id do dongle."""
        dongle_zero = bytes.fromhex("09040000000200000000000000000000" "46")
        wired = [info(0xFF01, 5, "7&cabo&0", 4, pid=0xFA7B, inp=17),
                 info(0xFF02, 7, "7&cabo&0", 6, pid=0xFA7B, feature=17)]
        with fake({ajazz.device_key(dongle()[0].path): [dongle_zero],
                   ajazz.device_key(wired[0].path): [WIRED_REPLY]}):
            out = ajazz.read_devices(dongle() + wired)
        self.assertEqual([(d.name, d.percent, d.charging) for d in out], [("AJAZZ Mouse", 95.0, True)])
        self.assertEqual(out[0].id, "ajazz:" + ajazz.device_key(dongle()[0].path))

    def test_plugging_the_dongle_back_while_charging_leaves_one_card(self):
        """Mouse no cabo sozinho (cartão próprio) e então o dongle volta: a leitura passa para o cartão do dongle e o
        cartão do cabo sai na mesma leitura, sem esperar a carência (o cabo continua espetado)."""
        from app.services.battery.service import DeviceTracker
        dongle_zero = bytes.fromhex("09040000000200000000000000000000" "46")
        wired = [info(0xFF01, 5, "7&cabo&0", 4, pid=0xFA7B, inp=17),
                 info(0xFF02, 7, "7&cabo&0", 6, pid=0xFA7B, feature=17)]
        tracker = DeviceTracker()
        with fake({ajazz.device_key(wired[0].path): [WIRED_REPLY]}):
            first = ajazz.read_devices(wired)
            shown = tracker.update(first, present=mouse_1k.present_ids(wired))
        self.assertEqual(len(shown), 1)
        both = dongle() + wired
        with fake({ajazz.device_key(dongle()[0].path): [dongle_zero],
                   ajazz.device_key(wired[0].path): [WIRED_REPLY]}):
            second = ajazz.read_devices(both)
            shown = tracker.update(second, count_misses=False, present=mouse_1k.present_ids(both))
        self.assertEqual([(d.id, d.percent, d.charging) for d in shown],
                         [("ajazz:" + ajazz.device_key(dongle()[0].path), 95.0, True)])

    def test_dongle_zero_alone_hides_the_mouse(self):
        dongle_zero = bytes.fromhex("09040000000200000000000000000000" "46")
        with fake({ajazz.device_key(dongle()[0].path): [dongle_zero]}):
            self.assertEqual(ajazz.read_devices(dongle()), [])

    def test_two_dongles_get_numbers(self):
        a, b = dongle("7&aaaa&0"), dongle("7&bbbb&0")
        with fake({ajazz.device_key(a[0].path): [REAL_REPLY], ajazz.device_key(b[0].path): [REAL_REPLY]}):
            out = ajazz.read_devices(a + b)
        self.assertEqual([d.name for d in out], ["AJAZZ Mouse 1", "AJAZZ Mouse 2"])


if __name__ == "__main__":
    unittest.main()
