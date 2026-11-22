"""Battery Widget: layout responsivo, leitura dos protocolos, carência de quem some, e o movimento (anima, termina
limpo, sem animações vai direto, e o contêiner muda de tamanho sem "dente")."""

import time
import unittest

from PySide6.QtWidgets import QApplication

from unittest import mock

from app.services.battery import hid_win, logitech, sony, switch_pro, vxe, xinput
from app.services.battery.models import KIND_CONTROLLER, KIND_KEYBOARD, KIND_MOUSE, BatteryDevice
from app.services.battery.service import DeviceTracker
from app.widgets.battery import layout as lay
from app.widgets.battery.card_state import FACE_HOVER, FACE_ICON, BatteryState, Options

_app = QApplication.instance() or QApplication([])


def devs(n, charging_ids=()):
    kinds = (KIND_MOUSE, KIND_KEYBOARD, KIND_CONTROLLER)
    return [BatteryDevice(f"d{i}", f"Device {i}", kinds[i % 3], 10.0 + 8 * i, charging=f"d{i}" in charging_ids)
            for i in range(n)]


def run(state, frames=600, dt=1 / 120):
    """Avança até assentar; devolve as alturas e larguras do cartão a cada quadro."""
    hs, ws = [], []
    for _ in range(frames):
        busy = state.step(dt)
        hs.append(state.H.x)
        ws.append(state.W.x)
        if not busy:
            break
    return hs, ws


def monotonic(values, tol=0.5):
    """Só cresce ou só diminui (tolerância de meio pixel): sem encolher-e-crescer."""
    if len(values) < 2:
        return True
    up = values[-1] >= values[0]
    best = values[0]
    for v in values:
        if up:
            if v < best - tol:
                return False
            best = max(best, v)
        else:
            if v > best + tol:
                return False
            best = min(best, v)
    return True


class LayoutTests(unittest.TestCase):
    def test_equal_space_edge_between_edge(self):
        L = lay.compute(6, 300, 262)
        self.assertEqual((L.cols, L.rows), (3, 2))
        self.assertFalse(L.grown)
        xs = sorted({round(x, 3) for x, _y in L.cells})
        self.assertAlmostEqual(xs[0], L.gap_x, places=3)                     # borda esquerda
        self.assertAlmostEqual(xs[1] - (xs[0] + L.d), L.gap_x, places=3)     # entre
        self.assertAlmostEqual(L.W - (xs[-1] + L.d), L.gap_x, places=3)      # borda direita

    def test_one_alone_two_in_a_row_tall_stacks(self):
        one = lay.compute(1, 300, 262)
        self.assertAlmostEqual(one.cells[0][0] + one.d / 2, 150.0, places=3)  # no meio
        two = lay.compute(2, 300, 262)
        self.assertEqual((two.cols, two.rows), (2, 1))                       # Clima: lado a lado
        tall = lay.compute(2, 300, 417)
        self.assertEqual((tall.cols, tall.rows), (1, 2))                     # alto: um em cima do outro

    def test_too_many_devices_grow_the_card_and_keep_52(self):
        L = lay.compute(8, 300, 262)
        self.assertTrue(L.grown)
        self.assertEqual(L.d, lay.D_MIN)
        self.assertGreater(L.W * L.H, 300 * 262)
        for n in range(1, 15):
            self.assertGreaterEqual(lay.compute(n, 300, 262).d, lay.D_MIN - 1e-6)

    def test_odd_last_row_centered_or_left(self):
        center = lay.compute(5, 300, 262, odd=lay.ODD_CENTER)
        left = lay.compute(5, 300, 262, odd=lay.ODD_LEFT)
        last_c = [x for x, y in center.cells[3:]]
        last_l = [x for x, y in left.cells[3:]]
        self.assertAlmostEqual(last_l[0], left.gap_x, places=3)
        self.assertAlmostEqual((last_c[0] + last_c[1] + center.d) / 2, center.W / 2, places=3)

    def test_optical_vertical_space_is_equal(self):
        """Do texto, não da caixa da linha: linha de base do título -> anel = linha de base do nome -> anel de baixo =
        linha de base do último nome -> borda (sem nomes: da borda do anel; sem título: da borda de cima). Medido
        com as métricas reais da fonte do app, como o pintor desenha."""
        from PySide6.QtGui import QFont, QFontMetricsF

        from app.core.typography import init_app_font
        from app.widgets.battery.card_painter import HEAD_LH, HEAD_TOP, _baseline, _font

        init_app_font()
        title_base = _baseline(HEAD_TOP, HEAD_LH, QFontMetricsF(_font(16.0, QFont.Weight.Medium)))
        for n, size in ((2, (300, 262)), (6, (300, 262)), (6, (300, 417)), (4, (440, 200)), (1, (260, 220))):
            for header in (True, False):
                for names in (True, False):
                    L = lay.compute(n, *size, header=header, names=names)
                    ty = L.typo(names)
                    fm = QFontMetricsF(_font(ty.fs))
                    edges = []
                    prev = title_base if header else 0.0
                    for row in range(L.rows):
                        ring_top = L.cells[row * L.cols][1]
                        edges.append(ring_top - prev)
                        prev = (_baseline(ring_top + L.d + ty.gap, ty.lh, fm) if names else ring_top + L.d)
                    edges.append(L.H - prev)
                    msg = f"n={n} size={size} header={header} names={names}: {edges}"
                    border = [edges[-1]] + ([] if header else [edges[0]])
                    inner = edges[1:-1] + ([edges[0]] if header else [])
                    for b in border:                               # borda nunca menor que a margem do título
                        self.assertGreater(b, lay.EDGE - 1.0, msg)
                    if inner:
                        self.assertLess(max(inner) - min(inner), 1.5, msg)
                    if min(border) > lay.EDGE + 1.0:                # com folga: tudo igual, como antes
                        self.assertLess(max(edges) - min(edges), 1.5, msg)

    def test_tight_card_keeps_the_bottom_margin_like_the_title(self):
        """Caso real: 3 dispositivos num cartão apertado. A borda de baixo fica com a margem que o título tem em
        cima (topo das letras), e os anéis encolhem para isso."""
        L = lay.compute(3, 260, 240)
        self.assertAlmostEqual(L.edge_y, lay.EDGE, places=3)
        self.assertGreaterEqual(L.gap_y, lay.M * L.d - 1e-6)

    def test_column_switch_has_hysteresis(self):
        """Arrastando o canto, a troca 3 <-> 2 colunas acontece em larguras diferentes na ida e na volta, e mexer
        poucos pixels em volta do ponto de troca não fica alternando (o cartão pulava entre 1 e 2 linhas)."""
        def sweep(widths, H=262):
            prev, switches = None, []
            for W in widths:
                L = lay.compute(3, W, H, prefer=prev)
                if prev is not None and L.cols != prev:
                    switches.append(W)
                prev = L.cols
            return prev, switches

        _c, down = sweep(range(480, 200, -1))
        _c, up = sweep(range(200, 481))
        self.assertEqual(len(down), 1)
        self.assertEqual(len(up), 1)
        self.assertGreater(up[0] - down[0], 10)                              # faixa entre as duas trocas
        jitter = [down[0] + dx for dx in (0, 2, -1, 3, 1, -2, 2, 0)] * 3
        cols, switches = sweep([down[0] - 1] + jitter)
        self.assertEqual(switches, [])

    def test_never_grows_past_the_pointer_when_another_layout_fits(self):
        """Caso real: 3 dispositivos, 268 x 240. Três numa linha pediriam anel < 52 e empurrariam o cartão para além
        do ponteiro; duas linhas cabem, então ficam duas linhas."""
        L = lay.compute(3, 268, 240)
        self.assertFalse(L.grown)
        self.assertEqual((L.W, L.H), (268, 240))
        for W in range(190, 480, 2):                     # de 190 para cima sempre cabe sem crescer, qualquer que
            for prefer in (None, 1, 2, 3):               # seja o layout na tela
                L = lay.compute(3, W, 240, prefer=prefer)
                self.assertFalse(L.grown, f"W={W} prefer={prefer}")
                self.assertEqual((L.W, L.H), (W, 240))

    def test_without_header_and_names_rings_get_bigger(self):
        full = lay.compute(6, 300, 262)
        bare = lay.compute(6, 300, 262, header=False, names=False)
        self.assertGreaterEqual(bare.d, full.d)
        self.assertEqual(bare.top, 0.0)


class ProtocolTests(unittest.TestCase):
    def test_dualsense_usb_and_bluetooth(self):
        usb = bytearray(64)
        usb[0], usb[53] = 0x01, 0x07                 # descarregando, nível 7
        self.assertEqual(sony.parse_dualsense(bytes(usb)), (75.0, False))
        bt = bytearray(78)
        bt[0], bt[54] = 0x31, 0x13                   # carregando, nível 3
        self.assertEqual(sony.parse_dualsense(bytes(bt)), (35.0, True))
        bt[54] = 0x2A                                # cheia
        self.assertEqual(sony.parse_dualsense(bytes(bt)), (100.0, False))
        simple = bytes([0x01] + [0] * 9)             # Bluetooth modo simples: sem bateria
        self.assertIsNone(sony.parse_dualsense(simple))

    def test_dualshock4(self):
        usb = bytearray(64)
        usb[0], usb[30] = 0x01, 0x05
        self.assertEqual(sony.parse_ds4(bytes(usb), bluetooth=False), (55.0, False))
        usb[30] = 0x1B                               # no cabo, cheia
        self.assertEqual(sony.parse_ds4(bytes(usb), bluetooth=False), (100.0, False))
        bt = bytearray(78)
        bt[0], bt[32] = 0x11, 0x14                   # no cabo, carregando
        self.assertEqual(sony.parse_ds4(bytes(bt), bluetooth=True), (45.0, True))

    def test_switch_pro_levels_and_charging(self):
        rep = bytearray(49)
        rep[0] = 0x30
        for status, expected in ((0x80, (90.0, False)), (0x60, (65.0, False)), (0x40, (40.0, False)),
                                 (0x20, (15.0, False)), (0x00, (5.0, False)), (0x91, (90.0, True)),
                                 (0x70, (65.0, True)), (0x61, (65.0, False))):   # 0x61: nibble baixo = conexão
            rep[2] = status
            self.assertEqual(switch_pro.parse_report(bytes(rep)), expected, hex(status))

    def test_switch_pro_real_report_from_8bitdo_pro3(self):
        """Relatório 0x30 capturado do 8BitDo Pro 3 em modo Switch por Bluetooth (byte 2 = 0x60: média)."""
        real = bytes.fromhex("30be600000000080f997800bae00f9fece0f05001800")
        self.assertEqual(switch_pro.parse_report(real), (65.0, False))

    def test_switch_pro_ignores_reports_without_battery(self):
        self.assertIsNone(switch_pro.parse_report(bytes([0x3F, 0x00, 0x60] + [0] * 9)))   # modo simples
        self.assertIsNone(switch_pro.parse_report(bytes([0x30, 0x01])))                   # curto demais
        self.assertIsNone(switch_pro.parse_report(b""))
        self.assertIsNone(switch_pro.parse_report(bytes([0x30, 0x00, 0xA0])))             # nível inexistente

    @staticmethod
    def _switch_info(pid=0x2009, vid=0x057E, usage=0x05, serial="e417d8efad7a"):
        return hid_win.HidInfo(path=f"\\\\?\\hid#{serial}", vid=vid, pid=pid, usage_page=0x01, usage=usage,
                               input_len=362, output_len=49, feature_len=0, product="Wireless Gamepad",
                               serial=serial)

    def test_switch_pro_read_devices(self):
        class FakeHandle:
            reports = [bytes([0x3F, 0, 0x80]), bytes([0x30, 5, 0x91] + [0] * 46)]

            def __init__(self, info):
                self.queue = list(self.reports)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, timeout_ms):
                return self.queue.pop(0) if self.queue else None

        hids = [self._switch_info(),
                self._switch_info(pid=0x0CE6, vid=0x054C, serial="sony"),         # outro fabricante: ignorado
                self._switch_info(usage=0x06, serial="teclado")]                  # não é o gamepad: ignorado
        with mock.patch.object(hid_win, "HidHandle", FakeHandle):
            out = switch_pro.read_devices(hids)
        self.assertEqual(len(out), 1)
        dev = out[0]
        self.assertEqual((dev.name, dev.kind, dev.source), ("Pro Controller", KIND_CONTROLLER, "switch"))
        self.assertEqual((dev.percent, dev.charging, dev.approximate), (90.0, True, True))
        self.assertEqual(dev.id, "switch:e417d8efad7a")

    def test_switch_pro_unknown_charge_when_only_simple_reports(self):
        class SimpleHandle:
            def __init__(self, info):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, timeout_ms):
                return bytes([0x3F, 0, 0x80])

        with mock.patch.object(hid_win, "HidHandle", SimpleHandle):
            out = switch_pro.read_devices([self._switch_info()])
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0].percent)
        self.assertFalse(out[0].approximate)

    def test_two_switch_controllers_get_numbered_names(self):
        class Handle:
            def __init__(self, info):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, timeout_ms):
                return bytes([0x30, 0, 0x80] + [0] * 46)

        hids = [self._switch_info(serial="bbbb"), self._switch_info(serial="aaaa")]
        with mock.patch.object(hid_win, "HidHandle", Handle):
            out = switch_pro.read_devices(hids)
        self.assertEqual([d.name for d in out], ["Pro Controller 1", "Pro Controller 2"])
        self.assertEqual([d.id for d in out], ["switch:aaaa", "switch:bbbb"])

    def test_vxe_request_matches_the_atk_app(self):
        """O pedido capturado do hub.atk.pro (comando 04, checksum 49) e os outros comandos que ele mandou."""
        self.assertEqual(vxe.build_request(), bytes.fromhex("0804000000000000000000000000000049"))
        self.assertEqual(vxe.build_request(0x12), bytes.fromhex("081200000000000000000000000000003b"))
        self.assertEqual(vxe.build_request(0x1D), bytes.fromhex("081d000000000000000000000000000030"))

    def test_vxe_real_reply(self):
        """Resposta capturada com o mouse em 45% (0x2D), tensão 0x0EF1 = 3825 mV."""
        real = bytes.fromhex("0804000000022d000ef10000000000001b")
        self.assertEqual(len(real), 17)
        self.assertEqual(vxe.parse_reply(real), (45.0, False, 3825))

    def test_vxe_charging_flag_and_bounds(self):
        rep = bytearray(vxe.PACKET_LEN)
        rep[0], rep[1], rep[6], rep[7], rep[8], rep[9] = 0x08, 0x04, 80, 1, 0x10, 0x00
        rep[16] = vxe._checksum(bytes(rep))
        self.assertEqual(vxe.parse_reply(bytes(rep)), (80.0, True, 4096))
        rep[6] = 101                                  # fora de 0-100: descarta
        rep[16] = vxe._checksum(bytes(rep))
        self.assertIsNone(vxe.parse_reply(bytes(rep)))

    def test_vxe_rejects_other_replies(self):
        good = bytes.fromhex("0804000000022d000ef10000000000001b")
        self.assertIsNone(vxe.parse_reply(good[:-1]))                               # curto
        self.assertIsNone(vxe.parse_reply(good[:-1] + b"\x00"))                     # checksum errado
        self.assertIsNone(vxe.parse_reply(bytes([0x08, 0x12]) + bytes(15)))         # outro comando
        self.assertIsNone(vxe.parse_reply(bytes([0x02]) + good[1:]))                # outro relatório
        self.assertIsNone(vxe.parse_reply(None))

    @staticmethod
    def _vxe_info(pid=0xF58A, vid=0x3554, page=0xFF02, path="a"):
        return hid_win.HidInfo(path=f"\\\\?\\hid#vxe{path}", vid=vid, pid=pid, usage_page=page, usage=0x02,
                               input_len=17, output_len=17, feature_len=0, product="VXE NordicMouse 1K Dongle")

    def test_vxe_read_devices_ignores_stale_reports_and_other_collections(self):
        battery = bytes.fromhex("0804000000022d000ef10000000000001b")
        other = bytes([0x08, 0x12] + [0] * 14 + [0x3B])          # resposta de outro comando: ignorada

        class FakeHandle:
            instances = []

            def __init__(self, info, write=False):
                self.writes = []
                self.queue = [bytes([0x08, 0x04] + [0] * 15)]    # relatório antigo, esvaziado antes do pedido
                FakeHandle.instances.append(self)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def write(self, data, timeout_ms=300):
                self.writes.append(bytes(data))
                self.queue += [other, battery]
                return True

            def read(self, timeout_ms):
                return self.queue.pop(0) if self.queue else None

        hids = [self._vxe_info(),
                self._vxe_info(page=0xFF04, path="feature"),     # outra coleção do dongle: ignorada
                self._vxe_info(pid=0x1234, path="outro")]        # PID desconhecido: ignorado
        with mock.patch.object(hid_win, "HidHandle", FakeHandle):
            out = vxe.read_devices(hids)
        self.assertEqual(len(out), 1)
        dev = out[0]
        self.assertEqual((dev.name, dev.kind, dev.source), ("VXE Mouse", KIND_MOUSE, "vxe"))
        self.assertEqual((dev.percent, dev.charging, dev.approximate), (45.0, False, False))
        self.assertEqual(FakeHandle.instances[0].writes, [vxe.build_request()])

    def test_vxe_no_reply_hides_the_mouse(self):
        """Mouse dormindo não responde: sai da lista (como os da Logitech), sem cartão cinza."""
        class Silent:
            def __init__(self, info, write=False):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def write(self, data, timeout_ms=300):
                return True

            def read(self, timeout_ms):
                return None

        with mock.patch.object(hid_win, "HidHandle", Silent):
            out = vxe.read_devices([self._vxe_info()])
        self.assertEqual(out, [])

    def test_vxe_real_wired_reply_is_charging(self):
        """Resposta do R1 PRO MAX no cabo (F58C): 80%, carregando, 4021 mV (tensão mais alta com a carga)."""
        real = bytes.fromhex("0804000000025001" "0fb5" "000000000000" "32")
        self.assertEqual(len(real), 17)
        self.assertEqual(vxe.parse_reply(real), (80.0, True, 4021))

    @staticmethod
    def _vxe_fake_by_pid(replies):
        """Handle falso: cada PID responde (ou fica mudo) conforme `replies`."""

        class Handle:
            def __init__(self, info, write=False):
                self.reply = replies.get(info.pid)
                self.queue = []

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def write(self, data, timeout_ms=300):
                if self.reply is not None:
                    self.queue.append(self.reply)
                return True

            def read(self, timeout_ms):
                return self.queue.pop(0) if self.queue else None

        return Handle

    def test_vxe_wired_mouse_replaces_the_silent_dongle_without_duplicating(self):
        wired = bytes.fromhex("0804000000025001" "0fb5" "000000000000" "32")
        handle = self._vxe_fake_by_pid({0xF58C: wired})                 # dongle mudo, mouse no cabo responde
        hids = [self._vxe_info(), self._vxe_info(pid=0xF58C, path="cabo")]
        with mock.patch.object(hid_win, "HidHandle", handle):
            out = vxe.read_devices(hids)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0].name, out[0].percent, out[0].charging), ("VXE Mouse", 80.0, True))
        self.assertTrue(out[0].id.endswith("hid#vxea"))                 # fica com o id do dongle, não o do cabo

    def test_vxe_wired_alone_and_wireless_alone(self):
        wired = bytes.fromhex("0804000000025001" "0fb5" "000000000000" "32")
        wireless = bytes.fromhex("0804000000022d000ef10000000000001b")
        with mock.patch.object(hid_win, "HidHandle", self._vxe_fake_by_pid({0xF58C: wired})):
            out = vxe.read_devices([self._vxe_info(pid=0xF58C, path="cabo")])
        self.assertEqual([(d.percent, d.charging) for d in out], [(80.0, True)])
        with mock.patch.object(hid_win, "HidHandle", self._vxe_fake_by_pid({0xF58A: wireless})):
            out = vxe.read_devices([self._vxe_info()])
        self.assertEqual([(d.percent, d.charging) for d in out], [(45.0, False)])

    def test_vxe_dongle_with_reading_and_second_wired_mouse_stay_separate(self):
        wired = bytes.fromhex("0804000000025001" "0fb5" "000000000000" "32")
        wireless = bytes.fromhex("0804000000022d000ef10000000000001b")
        handle = self._vxe_fake_by_pid({0xF58A: wireless, 0xF58C: wired})
        hids = [self._vxe_info(), self._vxe_info(pid=0xF58C, path="cabo")]
        with mock.patch.object(hid_win, "HidHandle", handle):
            out = vxe.read_devices(hids)
        self.assertEqual(sorted(d.percent for d in out), [45.0, 80.0])
        self.assertEqual(len({d.id for d in out}), 2)
        self.assertEqual(sorted(d.name for d in out), ["VXE Mouse 1", "VXE Mouse 2"])

    def test_logitech_hidpp(self):
        req = logitech.build_request(1, 0x00, 0, b"\x10\x04")
        self.assertEqual(len(req), 20)
        self.assertEqual(req[:6], bytes([0x11, 1, 0x00, logitech.SW_ID, 0x10, 0x04]))
        ok = bytes([0x11, 1, 0x00, logitech.SW_ID, 0x07]) + bytes(15)
        self.assertTrue(logitech.match_reply(ok, 1, 0x00, 0))
        other_app = bytes([0x11, 1, 0x00, 0x01, 0x07]) + bytes(15)
        self.assertIsNone(logitech.match_reply(other_app, 1, 0x00, 0))
        err = bytes([0x11, 1, 0xFF, 0x00, logitech.SW_ID, 0x05]) + bytes(14)
        self.assertFalse(logitech.match_reply(err, 1, 0x00, 0))
        self.assertEqual(logitech.parse_unified_battery(bytes([15, 2, 0, 0])), (15.0, False, False))
        self.assertEqual(logitech.parse_unified_battery(bytes([0, 4, 1, 1])), (60.0, True, True))
        self.assertEqual(logitech.parse_unified_battery(bytes([80, 8, 3, 1])), (100.0, False, False))
        self.assertEqual(logitech.parse_battery_status(bytes([50, 20, 1])), (50.0, True, False))
        self.assertIsNone(logitech.parse_battery_status(bytes([50, 20, 6])))

    def test_logitech_late_reply_never_answers_the_next_question(self):
        """Bug real: a resposta atrasada de uma pergunta ao Root virava a resposta da seguinte (teclado com 15%
        no lugar de 90%). Cada pergunta usa outro software id e a fila é esvaziada antes de escrever."""

        class FakeHandle:
            def __init__(self):
                self.queue = []
                self.sent = []

            def write(self, data, timeout_ms=300):
                self.sent.append(bytes(data))
                req = bytes(data)
                # Antes da resposta certa, chega a resposta ATRASADA da pergunta anterior (outro software id)
                if len(self.sent) > 1:
                    prev = self.sent[-2]
                    self.queue.append(bytes([0x11, prev[1], prev[2], prev[3], 0x08]) + bytes(15))
                self.queue.append(bytes([0x11, req[1], req[2], req[3], 0x5A, 0x08, 0x01]) + bytes(13))
                return True

            def read(self, timeout_ms):
                return self.queue.pop(0) if self.queue else None

        ch = logitech._Channel.__new__(logitech._Channel)
        ch.long, ch.short, ch._sw_next = FakeHandle(), None, 0
        first = ch.ask(1, 0x00, 0, b"\x10\x04")
        second = ch.ask(1, 0x00, 0, b"\x10\x00")      # mesmo formato da anterior: só o software id as separa
        self.assertEqual(first[0], 0x5A)
        self.assertEqual(second[:3], bytes([0x5A, 0x08, 0x01]))   # não o 0x08 da resposta atrasada
        self.assertNotEqual(ch.long.sent[0][3] & 0x0F, ch.long.sent[1][3] & 0x0F)
        stale = bytes([0x11, 1, 0x00, 0x08]) + bytes(16)
        self.assertIsNone(logitech.match_reply(stale, 1, 0x00, 0, sw=0x09))

    def test_xinput_levels(self):
        self.assertIsNone(xinput.battery_from_info(0x01, 3))              # com fio: sem bateria
        self.assertEqual(xinput.battery_from_info(xinput.BATTERY_TYPE_NIMH, 2), 55.0)


class TrackerTests(unittest.TestCase):
    def test_missing_device_stays_for_grace_then_leaves(self):
        tr = DeviceTracker(grace=2)
        a, b = devs(2)
        self.assertEqual([d.id for d in tr.update([a, b])], ["d0", "d1"])
        self.assertEqual(len(tr.update([a])), 2)
        self.assertEqual(len(tr.update([a])), 2)
        self.assertEqual([d.id for d in tr.update([a])], ["d0"])


class MotionTests(unittest.TestCase):
    def test_new_device_animates_and_ends_clean(self):
        st = BatteryState(animated=True)
        st.set_devices(devs(3))
        run(st)
        st.set_devices(devs(4))
        cell = st.cells["d3"]
        self.assertLess(cell.alpha.x, 0.05)                    # nasce invisível
        self.assertGreater(cell.y.x, cell.y.t)                 # e abaixo (sobe)
        st.step(1 / 120)
        self.assertTrue(0.0 < cell.alpha.x < 1.0)              # no meio: animando, não pulou
        run(st)
        self.assertFalse(st.busy())
        self.assertAlmostEqual(cell.alpha.x, 1.0, places=3)
        self.assertAlmostEqual(cell.y.x, cell.y.t, places=2)

    def test_removed_device_fades_then_goes(self):
        st = BatteryState(animated=True)
        st.set_devices(devs(4))
        run(st)
        st.set_devices(devs(3))
        self.assertIn("d3", st.cells)                          # ainda saindo
        self.assertTrue(st.cells["d3"].leaving)
        run(st)
        self.assertNotIn("d3", st.cells)

    def test_charging_dot_grows_in_and_out_without_overshoot(self):
        st = BatteryState(animated=True)
        st.set_devices(devs(2))
        run(st)
        for on in (True, False):
            st.set_devices(devs(2, charging_ids=("d1",) if on else ()))
            ch = st.cells["d1"].charge
            start = ch.x
            st.step(1 / 120)
            self.assertTrue(0.0 < ch.x < 1.0)                  # no meio: o espaço da bolinha abre aos poucos
            seen = [start]
            for _ in range(600):
                busy = st.step(1 / 120)
                seen.append(ch.x)
                if not busy:
                    break
            self.assertTrue(monotonic(seen, tol=0.001))        # o nome desliza num sentido só, sem voltar
            self.assertTrue(all(-0.001 <= v <= 1.001 for v in seen))
            self.assertEqual(ch.x, 1.0 if on else 0.0)         # termina exatamente no alvo
            self.assertFalse(st.busy())
        self.assertEqual(st.cells["d0"].charge.x, 0.0)         # vizinho não mexe

    def test_charging_dot_is_immediate_without_animations(self):
        st = BatteryState(animated=False)
        st.set_devices(devs(1))
        st.set_devices(devs(1, charging_ids=("d0",)))
        self.assertEqual(st.cells["d0"].charge.x, 1.0)
        st.set_devices(devs(1))
        self.assertEqual(st.cells["d0"].charge.x, 0.0)

    def test_without_animations_everything_is_immediate(self):
        st = BatteryState(animated=False)
        st.set_devices(devs(5))
        self.assertFalse(st.step(1 / 60))
        for i, dev_id in enumerate(st.order):
            x, y = st.layout.cells[i]
            self.assertEqual((st.cells[dev_id].x.x, st.cells[dev_id].y.x), (x, y))
        st.set_devices(devs(2))
        st.step(1 / 60)
        self.assertEqual(sorted(st.cells), ["d0", "d1"])

    def test_container_grows_and_shrinks_without_a_dent(self):
        st = BatteryState(animated=True)
        st.set_devices(devs(3))
        run(st)
        st.set_devices(devs(9))                                # passa do limite: o cartão cresce
        hs, ws = run(st)
        self.assertGreater(st.H.x * st.W.x, 300 * 262)
        self.assertTrue(monotonic(hs) and monotonic(ws), "o contêiner encolheu e cresceu de novo")
        st.set_devices(devs(2))
        hs, ws = run(st)
        self.assertTrue(monotonic(hs) and monotonic(ws))

    @staticmethod
    def _drag(n, path, animated=True):
        """Arrasta o canto pelo caminho (um quadro de 120 Hz por movimento); devolve o estado e o pior de cada quadro:
        quanto o cartão andou num quadro, quanto um anel visível saiu do cartão e quanto dois anéis se sobrepuseram."""
        st = BatteryState(animated=animated, base_w=path[0][0], base_h=path[0][1])
        st.set_devices(devs(n))
        run(st)
        worst = {"step_w": 0.0, "step_h": 0.0, "out": 0.0, "overlap": 0.0}
        pw, ph = st.W.x, st.H.x
        for w, h in path:
            st.set_base_size(w, h, direct=True)
            st.step(1 / 120)
            worst["step_w"] = max(worst["step_w"], abs(st.W.x - pw))
            worst["step_h"] = max(worst["step_h"], abs(st.H.x - ph))
            pw, ph = st.W.x, st.H.x
            d = st.D.x
            shown = [c for c in st.cells.values() if not c.leaving and c.alpha.x > 0.5]
            for c in shown:
                worst["out"] = max(worst["out"], -c.x.x, c.x.x + d - st.W.x, c.y.x + d - st.H.x)
            for i, a in enumerate(shown):
                for b in shown[i + 1:]:
                    gap = ((a.x.x - b.x.x) ** 2 + (a.y.x - b.y.x) ** 2) ** 0.5
                    worst["overlap"] = max(worst["overlap"], d - gap)
        return st, worst

    def test_corner_drag_keeps_card_on_pointer_and_rings_inside(self):
        """O vídeo do bug: arrastando o canto, o cartão pulava de altura e um anel cruzava o cartão por cima do
        vizinho e saía pela borda. Agora: o cartão anda só o que o ponteiro andou, nenhum anel sai, nenhum cruza."""
        widths = list(range(480, 170, -3)) + list(range(170, 481, 3))
        for n, H in ((2, 262), (3, 240), (3, 262), (4, 262), (5, 240)):
            st, worst = self._drag(n, [(w, H) for w in widths])
            msg = f"n={n} H={H} {worst}"
            self.assertLessEqual(worst["step_w"], 3.0 + 0.5, msg)              # sem pulo de largura
            self.assertEqual(worst["step_h"], 0.0, msg)                        # arrasto horizontal: altura parada
            self.assertLessEqual(worst["out"], 0.5, msg)
            self.assertLessEqual(worst["overlap"], 0.5, msg)
            self.assertGreater(st.hops, 0, msg)                                # passou pela troca de grade
        diagonal = [(300 - i * 1.5, 262 - i) for i in range(80)] + [(180 + i * 2, 182 + i * 0.3) for i in range(120)]
        st, worst = self._drag(3, diagonal)
        self.assertLessEqual(max(worst["step_w"], worst["step_h"]), 3.0, worst)
        self.assertLessEqual(worst["out"], 0.5, worst)
        many = [(w, 262) for w in widths]                                      # cartão empurrado (anéis no mínimo)
        st, worst = self._drag(8, many)
        self.assertLessEqual(worst["out"], 0.5, worst)
        self.assertLessEqual(worst["overlap"], 0.5, worst)

    def test_row_change_fades_out_and_rises_in_then_ends_clean(self):
        st = BatteryState(animated=True, base_w=360, base_h=262)
        st.set_devices(devs(3))
        run(st)
        self.assertEqual(st.layout.rows, 1)
        for w in range(360, 230, -3):                                          # estreita até virar 2 linhas
            st.set_base_size(w, 262, direct=True)
            st.step(1 / 120)
            if st.layout.rows == 2:
                break
        self.assertEqual(st.layout.rows, 2)
        hopped = sorted(k.split("\x00")[0] for k, c in st.cells.items() if c.leaving)
        self.assertIn("d2", hopped)                     # trocou de linha: uma cópia esmaece onde ele estava
        self.assertNotIn("d0", hopped)                  # quem quase não anda só desliza
        moved = st.cells["d2"]
        self.assertLess(moved.alpha.x, 0.5)                                    # e ele reaparece no lugar novo
        self.assertGreater(moved.y.x, moved.y.t)                               # subindo, não cruzando
        run(st)
        self.assertFalse(st.busy())
        self.assertEqual(sorted(st.cells), ["d0", "d1", "d2"])                 # cópias removidas
        self.assertEqual((moved.alpha.x, moved.x.x, moved.y.x), (1.0, moved.x.t, moved.y.t))

    def test_corner_drag_without_animations_is_immediate(self):
        st, worst = self._drag(3, [(w, 262) for w in range(360, 200, -5)], animated=False)
        self.assertEqual(st.hops, 0)
        self.assertEqual(sorted(st.cells), ["d0", "d1", "d2"])
        for i, dev_id in enumerate(st.order):
            self.assertEqual((st.cells[dev_id].x.x, st.cells[dev_id].y.x), st.layout.cells[i])

    def test_hover_switches_the_face_with_motion(self):
        st = BatteryState(animated=True, options=Options(face=FACE_HOVER))
        st.set_devices(devs(2))
        run(st)
        st.set_hovered(True)
        st.step(1 / 120)
        self.assertTrue(0.0 < st.face_pct.x < 1.0)
        run(st)
        self.assertAlmostEqual(st.face_pct.x, 1.0, places=2)
        st.set_options(Options(face=FACE_ICON))
        run(st)
        self.assertAlmostEqual(st.face_pct.x, 0.0, places=2)   # "ícone" ignora o mouse


class CountToggleTests(unittest.TestCase):
    def test_count_fades_out_and_back(self):
        st = BatteryState(animated=True)
        st.set_devices(devs(3))
        run(st)
        st.set_options(Options(count=False))
        st.step(1 / 120)
        self.assertTrue(0.0 < st.count_alpha.x < 1.0)          # esmaece, não some no corte
        run(st)
        self.assertEqual(st.count_alpha.x, 0.0)
        st.set_options(Options(count=True))
        run(st)
        self.assertEqual(st.count_alpha.x, 1.0)

    def test_count_fades_with_width_instead_of_cutting(self):
        """Estreitando o cartão, "N dispositivos" esmaece ao longo de alguns px em vez de sumir de uma vez."""
        from app.widgets.battery.card_painter import COUNT_FADE, count_fit

        self.assertEqual(count_fit(-5.0), 0.0)
        self.assertEqual(count_fit(COUNT_FADE + 5.0), 1.0)
        values = [count_fit(s / 2) for s in range(-10, int(COUNT_FADE * 2) + 10)]
        self.assertTrue(monotonic(values, tol=0.0))
        self.assertLess(max(b - a for a, b in zip(values, values[1:])), 0.05)   # sem degrau

    def test_count_without_animations_is_immediate(self):
        st = BatteryState(animated=False)
        st.set_options(Options(count=False))
        self.assertEqual(st.count_alpha.x, 0.0)

    def test_option_reads_from_config(self):
        cfg = {"count": False}
        self.assertFalse(Options.from_config(lambda k, d=None: cfg.get(k, d)).count)
        self.assertTrue(Options.from_config(lambda k, d=None: d).count)


class CardTests(unittest.TestCase):
    def test_free_resize_changes_shape_and_relayouts(self):
        from app.widgets.battery.battery_card import BatteryCard

        card = BatteryCard(size=(300, 262))
        try:
            card.state.animated = False
            card.set_devices(devs(6))
            self.assertEqual((card.state.layout.cols, card.state.layout.rows), (3, 2))
            card.set_base_size(300, 417)
            self.assertEqual((card.state.layout.cols, card.state.layout.rows), (2, 3))
            self.assertEqual(card.card_size(), (300, 417))
        finally:
            card.close()
            card.deleteLater()

    def test_size_busy_only_while_the_card_size_moves(self):
        """O alinhador do anchor espera o tamanho assentar: o arco enchendo ou o hover não contam como tamanho."""
        from app.widgets.battery.battery_card import BatteryCard

        card = BatteryCard(size=(300, 262))
        try:
            card.state.animated = True
            card.state.set_devices(devs(3))
            run(card.state)
            card.state.set_devices([BatteryDevice(d.id, d.name, d.kind, 90.0) for d in devs(3)])   # arco anda
            card.state.set_hovered(True)                                                           # face anda
            self.assertTrue(card.state.busy())
            self.assertFalse(card.is_scale_animating())
            card.state.set_base_size(420, 262)                                                     # tamanho anda
            self.assertTrue(card.is_scale_animating())
            run(card.state)
            self.assertFalse(card.is_scale_animating())
        finally:
            card.close()
            card.deleteLater()

    def test_painter_runs_for_every_option(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter

        from app.widgets.battery.card_painter import THEME_BLACK, THEME_DARK, THEME_LIGHT, paint_battery_card
        from app.widgets.battery.card_state import FACES, LABELS, SHOWS

        st = BatteryState(animated=False)
        st.set_devices(devs(5, charging_ids=("d1",)) + [BatteryDevice("u", "Unknown", KIND_CONTROLLER, None)])
        img = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
        for face in FACES:
            for label in LABELS:
                for show in SHOWS:
                    st.set_options(Options(face=face, label=label, show=show))
                    st.step(0.0)
                    for theme in (THEME_DARK, THEME_LIGHT, THEME_BLACK):
                        p = QPainter(img)
                        paint_battery_card(p, QRectF(0, 0, st.W.x, st.H.x), st, theme=theme, now=time.perf_counter())
                        p.end()
        empty = BatteryState(animated=False)
        p = QPainter(img)
        paint_battery_card(p, QRectF(0, 0, 300, 262), empty)
        p.end()


if __name__ == "__main__":
    unittest.main()
