"""Protocolo comum dos mouses 1K: só a tabela recebe pedidos, desconhecidos viram pista no log, famílias misturadas."""

import unittest
from unittest import mock

from app.services.battery import hid_win, mouse_1k

VXE_REPLY = bytes.fromhex("0804000000022d000ef10000000000001b")
AJAZZ_REPLY = bytes.fromhex("0904000000022d00000000000000000019")


def hid(vid, pid, page, path, inp=0, out=0, feat=0, product=""):
    return hid_win.HidInfo(path=path, vid=vid, pid=pid, usage_page=page, usage=2, input_len=inp, output_len=out,
                           feature_len=feat, product=product)


def ajazz_dongle(inst="7&aa&0"):
    base = r"\?\hid#vid_25a7&pid_fa7c&mi_01&col{:02d}#" + inst + "&{:04d}#{{x}}"
    return [hid(0x25A7, 0xFA7C, 0xFF01, base.format(5, 4), inp=17),
            hid(0x25A7, 0xFA7C, 0xFF02, base.format(7, 6), feat=17)]


VXE_DONGLE = hid(0x3554, 0xF58A, 0xFF02, r"\?\hid#vid_3554&pid_f58a&mi_01&col03#8&bb&0&0002#{x}", inp=17, out=17)


class Recorder:
    """Handle falso: anota quem foi aberto e o que foi enviado; responde conforme o VID."""
    opened, sent = [], []
    replies = {0x3554: VXE_REPLY, 0x25A7: AJAZZ_REPLY}
    queue = []

    def __init__(self, info, write=False):
        self.info = info
        Recorder.opened.append((info.vid, info.pid, info.usage_page))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _send(self, kind, data):
        Recorder.sent.append((kind, self.info.vid, bytes(data)))
        Recorder.queue.append(Recorder.replies[self.info.vid])
        return True

    def write(self, data, timeout_ms=300):
        return self._send("output", data)

    def set_feature(self, data):
        return self._send("feature", data)

    def read(self, timeout_ms):
        return Recorder.queue.pop(0) if Recorder.queue else None


def recording():
    Recorder.opened, Recorder.sent, Recorder.queue = [], [], []
    return mock.patch.object(hid_win, "HidHandle", Recorder)


class Mouse1KTests(unittest.TestCase):
    def test_every_family_uses_its_own_transport(self):
        with recording():
            out = mouse_1k.read_devices([VXE_DONGLE] + ajazz_dongle())
        self.assertEqual(sorted((d.source, d.percent) for d in out), [("ajazz", 45.0), ("vxe", 45.0)])
        self.assertEqual(sorted(Recorder.sent), [("feature", 0x25A7, mouse_1k.build_request()),
                                                 ("output", 0x3554, mouse_1k.build_request())])

    def test_vxe_card_id_keeps_the_full_path(self):
        with recording():
            out = mouse_1k.read_family(mouse_1k.VXE, [VXE_DONGLE])
        self.assertEqual(out[0].id, "vxe:" + VXE_DONGLE.path.lower())

    def test_unknown_lookalike_is_never_opened(self):
        lookalike = [hid(0x1234, 0x0001, 0xFF02, r"\?\hid#vid_1234&pid_0001&col07#9&cc&0&0006#{x}", feat=17),
                     hid(0x1234, 0x0001, 0xFF01, r"\?\hid#vid_1234&pid_0001&col05#9&cc&0&0004#{x}", inp=17)]
        with recording():
            self.assertEqual(mouse_1k.read_devices(lookalike), [])
        self.assertEqual(Recorder.opened, [])

    def test_present_ids_cover_silent_devices_with_the_card_id(self):
        with recording():
            out = mouse_1k.read_devices([VXE_DONGLE] + ajazz_dongle())
        present = mouse_1k.present_ids([VXE_DONGLE] + ajazz_dongle())
        self.assertEqual(present, {d.id for d in out})
        self.assertEqual(mouse_1k.present_ids([VXE_DONGLE]), {"vxe:" + VXE_DONGLE.path.lower()})

    def test_candidates_list_lookalikes_only(self):
        lookalike = hid(0x1234, 0x0001, 0xFF02, "p1", feat=17, product="Some Receiver")
        other = hid(0x1234, 0x0002, 0xFF00, "p2", inp=64)               # outra página, outro tamanho
        found = mouse_1k.candidates([lookalike, other, VXE_DONGLE] + ajazz_dongle())
        self.assertEqual(found, [(0x1234, 0x0001, "Some Receiver")])

    def test_candidates_are_logged_once_and_never_queried(self):
        lookalike = hid(0x1234, 0x0001, 0xFF02, "p1", feat=17, product="Some Receiver")
        calls = []
        with mock.patch.object(mouse_1k, "_logged_candidates", False), recording(), \
                self.assertLogs("app.services.battery.mouse_1k", "INFO") as logs:
            mouse_1k.log_candidates(lambda: calls.append(1) or [lookalike])
            mouse_1k.log_candidates(lambda: calls.append(1) or [lookalike])
        self.assertEqual(len(calls), 1)
        self.assertIn("1234:0001", logs.output[0])
        self.assertEqual(Recorder.opened, [])

    # Respostas reais do Redragon: dongle F5D5 a 5% (3262 mV) e o mouse no cabo F55E a 15%, carregando (3493 mV)
    REDRAGON_DONGLE_REPLY = bytes.fromhex("08040000000205000cbe00000000000078")
    REDRAGON_WIRED_REPLY = bytes.fromhex("0804000000020f010da500000000000085")
    RED_DONGLE = hid(0x3554, 0xF5D5, 0xFF02, r"\?\hid#vid_3554&pid_f5d5&mi_01&col05#7&13&0&0004#{x}", inp=17, out=17,
                     product="2.4G Wireless Receiver")
    RED_CABLE = hid(0x3554, 0xF55E, 0xFF02, r"\?\hid#vid_3554&pid_f55e&mi_01&col05#7&15&0&0004#{x}", inp=17, out=17,
                    product="3-Mode Mouse")

    @staticmethod
    def _by_pid(replies):
        """Handle falso que responde por PID (None = mudo)."""
        class Handle(Recorder):
            def _send(self, kind, data):
                reply = replies.get(self.info.pid)
                if reply is not None:
                    Recorder.queue.append(reply)
                return True
        Recorder.opened, Recorder.sent, Recorder.queue = [], [], []
        return mock.patch.object(hid_win, "HidHandle", Handle)

    def test_redragon_real_replies(self):
        self.assertEqual(mouse_1k.parse_reply(self.REDRAGON_DONGLE_REPLY), (5.0, False, 3262))
        self.assertEqual(mouse_1k.parse_reply(self.REDRAGON_WIRED_REPLY), (15.0, True, 3493))

    def test_redragon_dongle_reads_with_its_name(self):
        with self._by_pid({0xF5D5: self.REDRAGON_DONGLE_REPLY}):
            out = mouse_1k.read_devices([self.RED_DONGLE])
        self.assertEqual([(d.name, d.source, d.percent) for d in out], [("Redragon Mouse", "redragon", 5.0)])

    def test_redragon_on_the_cable_is_one_card_with_the_dongle(self):
        """Cenário real: no cabo o dongle fica mudo e o F55E responde. Um cartão só, com o id do dongle."""
        with self._by_pid({0xF55E: self.REDRAGON_WIRED_REPLY}):
            out = mouse_1k.read_devices([self.RED_DONGLE, self.RED_CABLE])
        self.assertEqual([(d.name, d.percent, d.charging) for d in out], [("Redragon Mouse", 15.0, True)])
        self.assertEqual(out[0].id, "redragon:" + self.RED_DONGLE.path.lower())
        self.assertEqual(mouse_1k.present_ids([self.RED_DONGLE, self.RED_CABLE]), {out[0].id})

    def test_redragon_cable_never_takes_a_silent_vxe_dongle(self):
        """VXE dormindo e Redragon no cabo, mesmo VID: famílias diferentes, o Redragon fica com o próprio cartão."""
        with self._by_pid({0xF55E: self.REDRAGON_WIRED_REPLY}):
            out = mouse_1k.read_devices([VXE_DONGLE, self.RED_CABLE])
        self.assertEqual([d.id for d in out], ["redragon:" + self.RED_CABLE.path.lower()])

    def test_broken_enumeration_does_not_raise(self):
        def boom():
            raise RuntimeError("x")
        with mock.patch.object(mouse_1k, "_logged_candidates", False):
            mouse_1k.log_candidates(boom)


if __name__ == "__main__":
    unittest.main()
