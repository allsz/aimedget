"""Battery Widget: layout responsivo, leitura dos protocolos, carência de quem some, e o movimento (anima, termina
limpo, sem animações vai direto, e o contêiner muda de tamanho sem "dente")."""

import time
import unittest

from PySide6.QtWidgets import QApplication

from app.services.battery import logitech, sony, xinput
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
