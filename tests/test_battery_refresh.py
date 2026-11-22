"""Leitura rápida da bateria: rajada após avisos do sistema, leitura paralela e o filtro de eventos do Windows."""

import threading
import time
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication

from app.services.battery import service as svc
from app.services.battery import system_events as se
from app.services.battery.models import BatteryDevice
from app.services.battery.service import BatteryService, DeviceTracker

app = QCoreApplication.instance() or QCoreApplication([])
REAL_READ = getattr(svc, "real_read_all_sources", svc.read_all_sources)   # conftest troca a leitura por um stub


def dev(i, pct=50.0):
    return BatteryDevice(id=i, name=i, kind="mouse", percent=pct, charging=False, approximate=False, source="test")


class ScriptedReader:
    """Devolve a lista atual (mutável pelo teste) e anota quando cada leitura aconteceu."""

    def __init__(self, devices=()):
        self.devices = list(devices)
        self.times = []
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            self.times.append(time.monotonic())
            return list(self.devices)


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class BurstTests(unittest.TestCase):
    def make(self, reader, delays=(0.03, 0.1, 0.2, 0.3)):
        s = BatteryService(reader=reader, interval_s=60.0, burst_delays=delays, activity=lambda: None)
        self.addCleanup(s.stop)
        s.start()
        self.assertTrue(wait_until(lambda: s.reads >= 1))
        return s

    def test_event_reads_well_before_interval(self):
        r = ScriptedReader()
        s = self.make(r)
        r.devices = [dev("mouse")]
        t0 = time.monotonic()
        s.notify_change("device")
        self.assertTrue(wait_until(lambda: [d.id for d in s.last_devices] == ["mouse"], 1.0))
        self.assertLess(time.monotonic() - t0, 0.5)

    def test_late_device_after_resume_is_caught_by_burst(self):
        r = ScriptedReader()
        s = self.make(r)
        s.notify_change("resume")
        time.sleep(0.15)                       # primeiras leituras da rajada: ainda nada
        r.devices = [dev("dongle")]            # receptor volta depois
        self.assertTrue(wait_until(lambda: [d.id for d in s.last_devices] == ["dongle"], 1.0))

    def test_burst_events_debounce_into_one_read(self):
        r = ScriptedReader()
        s = self.make(r, delays=(0.1, 5.0))
        before = s.reads
        for _ in range(20):
            s.notify_change("device")
            time.sleep(0.002)
        time.sleep(0.25)
        self.assertEqual(s.reads - before, 1)

    def test_burst_stops_once_settled(self):
        r = ScriptedReader()
        s = self.make(r, delays=(0.02, 0.06, 0.1, 0.5, 0.6))
        r.devices = [dev("a")]
        s.notify_change("device")
        self.assertTrue(wait_until(lambda: not s.burst_pending(), 0.4))   # mudou, depois igual: acaba antes de 0.5
        reads = s.reads
        time.sleep(0.7)
        self.assertEqual(s.reads, reads)

    def test_stop_cancels_burst(self):
        r = ScriptedReader()
        s = self.make(r, delays=(0.2, 0.3))
        s.notify_change("device")
        s.stop()
        reads = s.reads
        time.sleep(0.4)
        self.assertFalse(s.burst_pending())
        self.assertEqual(s.reads, reads)

    def test_notify_ignored_when_not_running(self):
        s = BatteryService(reader=ScriptedReader(), burst_delays=(0.01,))
        s.notify_change("device")
        self.assertFalse(s.burst_pending())

    def test_burst_reads_do_not_spend_grace(self):
        r = ScriptedReader([dev("sleepy")])
        s = self.make(r, delays=(0.01, 0.03, 0.05, 0.07, 0.09))
        r.devices = []                          # mouse dormiu; outra coisa foi ligada
        s.notify_change("device")
        self.assertTrue(wait_until(lambda: not s.burst_pending(), 1.0))
        self.assertEqual([d.id for d in s.last_devices], ["sleepy"])

    def test_refresh_still_reads_now(self):
        r = ScriptedReader()
        s = self.make(r)
        n = s.reads
        s.refresh()
        self.assertTrue(wait_until(lambda: s.reads > n, 0.5))


class ActivityProbeTests(unittest.TestCase):
    """Mouse desligado com o dongle no PC: o Windows não avisa quando ele volta; mexer em algo dispara a leitura."""

    def make(self, reader, ticks, gap=0.1, ttl=60.0):
        s = BatteryService(reader=reader, interval_s=60.0, burst_delays=(), activity=lambda: ticks[0],
                           activity_check_s=0.02, activity_gap_s=gap, missing_ttl_s=ttl)
        self.addCleanup(s.stop)
        s.start()
        self.assertTrue(wait_until(lambda: s.reads >= 1))
        return s

    def test_activity_reads_when_a_known_device_is_missing(self):
        r = ScriptedReader([dev("vxe")])
        ticks = [100]
        s = self.make(r, ticks)
        r.devices = []
        s.refresh()                                   # mouse desligado: some da leitura
        self.assertTrue(wait_until(lambda: s.missing_ids() == {"vxe"}))
        time.sleep(0.1)                               # sem mexer em nada: nenhuma leitura extra
        n = s.reads
        time.sleep(0.15)
        self.assertEqual(s.reads, n)
        r.devices = [dev("vxe", 80)]                  # liga o mouse e clica
        ticks[0] = 200
        self.assertTrue(wait_until(lambda: s.reads > n, 0.5))
        self.assertTrue(wait_until(lambda: not s.missing_ids(), 0.5))
        self.assertEqual(s.last_devices[0].percent, 80)

    def test_no_probe_when_nothing_is_missing(self):
        r = ScriptedReader([dev("a")])
        ticks = [1]
        s = self.make(r, ticks)
        n = s.reads
        for i in range(10):
            ticks[0] = i + 2
            time.sleep(0.03)
        self.assertEqual(s.reads, n)

    def test_activity_reads_are_throttled(self):
        r = ScriptedReader([dev("x")])
        ticks = [0]
        s = self.make(r, ticks, gap=0.25)
        r.devices = []
        s.refresh()
        self.assertTrue(wait_until(lambda: s.missing_ids() == {"x"}))
        n = s.reads
        end = time.monotonic() + 0.6
        while time.monotonic() < end:                 # usuário mexendo o tempo todo
            ticks[0] += 1
            time.sleep(0.01)
        self.assertLessEqual(s.reads - n, 3)

    def test_missing_device_is_forgotten_after_ttl(self):
        r = ScriptedReader([dev("old")])
        s = self.make(r, [0], ttl=0.05)
        r.devices = []
        s.refresh()
        self.assertTrue(wait_until(lambda: s.reads >= 2))
        time.sleep(0.1)
        s.refresh()
        self.assertTrue(wait_until(lambda: not s.missing_ids(), 0.5))


def ctrl(i, source="sony"):
    return BatteryDevice(id=i, name=i, kind="controller", percent=50.0, charging=False, approximate=False,
                         source=source)


class DisconnectTests(unittest.TestCase):
    def make(self, reader):
        s = BatteryService(reader=reader, interval_s=60.0, burst_delays=(0.02, 0.05), activity=lambda: None,
                           confirm_delay_s=0.05)
        self.addCleanup(s.stop)
        s.start()
        self.assertTrue(wait_until(lambda: s.reads >= 1))
        return s

    def test_controller_leaves_fast_after_disconnect_event(self):
        r = ScriptedReader([ctrl("ds"), dev("mouse")])
        s = self.make(r)
        r.devices = [dev("mouse")]
        t0 = time.monotonic()
        s.notify_change("device")                      # Bluetooth desconectou
        self.assertTrue(wait_until(lambda: [d.id for d in s.last_devices] == ["mouse"], 1.0))
        self.assertLess(time.monotonic() - t0, 0.5)

    def test_controller_hiccup_does_not_remove_it(self):
        r = ScriptedReader([ctrl("ds")])
        s = self.make(r)
        updates = []
        s.devices_updated.connect(lambda devs: updates.append([d.id for d in devs]))
        r.devices = []
        s.notify_change("device")
        time.sleep(0.03)
        r.devices = [ctrl("ds")]                       # voltou antes da confirmação
        time.sleep(0.3)
        self.assertEqual([d.id for d in s.last_devices], ["ds"])
        self.assertNotIn([], updates)

    def test_manual_refresh_drops_silent_dongle_device(self):
        r = ScriptedReader([dev("vxe")])
        s = self.make(r)
        r.devices = []
        s.refresh()
        self.assertTrue(wait_until(lambda: s.last_devices == [], 0.5))

    def test_regular_poll_keeps_grace_for_dongle_devices(self):
        tr = DeviceTracker(grace=2)
        tr.update([dev("vxe")])
        self.assertEqual([d.id for d in tr.update([])], ["vxe"])
        self.assertEqual([d.id for d in tr.update([])], ["vxe"])
        self.assertEqual(tr.update([]), [])

    def test_streaming_needs_two_misses(self):
        tr = DeviceTracker(grace=2)
        tr.update([ctrl("x", "xinput")])
        self.assertEqual([d.id for d in tr.update([], count_misses=False)], ["x"])
        self.assertTrue(tr.unconfirmed())
        self.assertEqual(tr.update([], count_misses=False), [])
        self.assertFalse(tr.unconfirmed())


class TrackerMissTests(unittest.TestCase):
    def test_no_miss_counting_still_adds_and_updates(self):
        tr = DeviceTracker(grace=0)
        tr.update([dev("a", 10)])
        out = tr.update([dev("b")], count_misses=False)
        self.assertEqual(sorted(d.id for d in out), ["a", "b"])
        out = tr.update([dev("b")])
        self.assertEqual([d.id for d in out], ["b"])


def chg(i, pct, charging):
    return BatteryDevice(id=i, name=i, kind="controller", percent=pct, charging=charging, approximate=False,
                         source="sony")


class ChargingSteadyTests(unittest.TestCase):
    """Carga andando para trás só vale confirmada; ligar/desligar o cabo vale na hora."""

    def shown(self, tr, *readings, **kw):
        return [(d.percent, d.charging) for r in readings for d in tr.update([r], **kw)]

    def test_rising_while_charging_and_falling_while_discharging_pass_at_once(self):
        tr = DeviceTracker()
        self.assertEqual(self.shown(tr, chg("ds", 45, True), chg("ds", 55, True), chg("ds", 65, True)),
                         [(45, True), (55, True), (65, True)])
        tr = DeviceTracker()
        self.assertEqual(self.shown(tr, chg("ds", 65, False), chg("ds", 55, False)), [(65, False), (55, False)])

    def test_plug_and_unplug_show_at_once(self):
        tr = DeviceTracker()
        self.assertEqual(self.shown(tr, chg("ds", 45, False), chg("ds", 45, True), chg("ds", 45, False)),
                         [(45, False), (45, True), (45, False)])

    def test_trickle_at_the_end_of_charge_does_not_blink(self):
        """Perto do fim o DualSense alterna "carregando 95%" e "cheio": o cartão fica no cheio."""
        tr = DeviceTracker()
        seq = [chg("ds", 95, True), chg("ds", 100, False), chg("ds", 95, True), chg("ds", 100, False),
               chg("ds", 95, True), chg("ds", 100, False)]
        self.assertEqual(self.shown(tr, *seq)[1:], [(100, False)] * 5)

    def test_level_jitter_while_discharging_is_held(self):
        tr = DeviceTracker()
        seq = [chg("m", 55, False), chg("m", 45, False), chg("m", 55, False), chg("m", 45, False)]
        self.assertEqual(self.shown(tr, *seq), [(55, False), (45, False), (45, False), (45, False)])

    def test_backwards_change_sticks_when_repeated(self):
        tr = DeviceTracker()
        seq = [chg("ds", 100, False), chg("ds", 95, True), chg("ds", 95, True)]   # plugou de verdade, já cheio
        self.assertEqual(self.shown(tr, *seq), [(100, False), (100, False), (95, True)])

    def test_manual_refresh_shows_the_raw_reading(self):
        tr = DeviceTracker()
        tr.update([chg("m", 45, False)])
        self.assertEqual(self.shown(tr, chg("m", 55, False), drop_missing=True), [(55, False)])

    def test_unknown_charge_passes_through(self):
        tr = DeviceTracker()
        self.assertEqual(self.shown(tr, chg("x", None, False), chg("x", 50, False), chg("x", None, True)),
                         [(None, False), (50, False), (None, True)])

    def test_device_that_left_and_came_back_is_not_held(self):
        tr = DeviceTracker()
        tr.update([chg("ds", 20, False)])
        tr.update([], count_misses=False)
        tr.update([], count_misses=False)              # controle saiu
        self.assertEqual(self.shown(tr, chg("ds", 90, False)), [(90, False)])   # carregou em outro lugar


class ChargingIntervalTests(unittest.TestCase):
    def make(self, reader):
        s = BatteryService(reader=reader, interval_s=60.0, charging_interval_s=0.05, burst_delays=(0.01,),
                           activity=lambda: None)
        self.addCleanup(s.stop)
        s.start()
        self.assertTrue(wait_until(lambda: s.reads >= 1))
        return s

    def test_reads_often_while_charging_and_slow_again_after(self):
        r = ScriptedReader([chg("ds", 45, True)])
        s = self.make(r)
        self.assertTrue(wait_until(lambda: s.reads >= 4, 1.0))       # 60 s de intervalo: só chegaria aqui carregando
        r.devices = [chg("ds", 45, False)]                           # tirou o cabo
        self.assertTrue(wait_until(lambda: not s.last_devices[0].charging, 1.0))
        time.sleep(0.1)
        n = s.reads
        time.sleep(0.25)
        self.assertEqual(s.reads, n)

    def test_cable_seen_in_a_burst_read_brings_the_next_poll_forward(self):
        r = ScriptedReader([chg("ds", 45, False)])
        s = self.make(r)
        time.sleep(0.1)
        n = s.reads
        self.assertEqual(n, 1)
        r.devices = [chg("ds", 45, True)]
        s.notify_change("device")                                    # plugou o cabo
        self.assertTrue(wait_until(lambda: s.reads >= n + 3, 1.0))   # rajada + leituras de carga, sem esperar 60 s

    def test_percent_climbs_on_screen_while_charging(self):
        r = ScriptedReader([chg("ds", 45, True)])
        s = self.make(r)
        r.devices = [chg("ds", 55, True)]
        self.assertTrue(wait_until(lambda: s.last_devices[0].percent == 55, 1.0))
        r.devices = [chg("ds", 100, False)]                          # cheio
        self.assertTrue(wait_until(lambda: (s.last_devices[0].percent, s.last_devices[0].charging) == (100, False),
                                   1.0))


class ParallelReadTests(unittest.TestCase):
    def test_sources_run_in_parallel_and_order_is_fixed(self):
        def slow(name):
            def fn(*_a):
                time.sleep(0.2)
                return [dev(name)]
            return fn
        seen_claimed = {}

        def gaming(hids, claimed):
            seen_claimed.update(claimed)
            return [dev("gaming")]

        with mock.patch.object(svc.xinput, "read_devices", slow("xinput")), \
                mock.patch.object(svc.hid_win, "enumerate_hid", lambda _v: []), \
                mock.patch.object(svc.sony, "read_devices", slow("sony")), \
                mock.patch.object(svc.switch_pro, "read_devices", slow("switch")), \
                mock.patch.object(svc.logitech, "read_devices", slow("logitech")), \
                mock.patch.object(svc.vxe, "read_devices", slow("vxe")), \
                mock.patch.object(svc.gaming_input, "read_devices", gaming), \
                mock.patch.object(svc.bluetooth, "read_devices", lambda skip: [dev("bluetooth")]), \
                mock.patch.object(svc, "claimed_by_vendor", lambda devs: {"n": len(devs)}):
            t0 = time.monotonic()
            out = REAL_READ()
            elapsed = time.monotonic() - t0
        self.assertEqual([d.id for d in out],
                         ["xinput", "sony", "switch", "logitech", "vxe", "gaming", "bluetooth"])
        self.assertLess(elapsed, 0.6)           # em série seriam 1.0 s
        self.assertEqual(seen_claimed, {"n": 5})   # a leitura do Windows vê tudo das outras

    def test_broken_source_does_not_break_others(self):
        def boom(*_a):
            raise RuntimeError("x")
        with mock.patch.object(svc.xinput, "read_devices", boom), \
                mock.patch.object(svc.hid_win, "enumerate_hid", boom), \
                mock.patch.object(svc.sony, "read_devices", lambda h: [dev("sony")]), \
                mock.patch.object(svc.switch_pro, "read_devices", boom), \
                mock.patch.object(svc.logitech, "read_devices", lambda h: []), \
                mock.patch.object(svc.vxe, "read_devices", lambda h: []), \
                mock.patch.object(svc.gaming_input, "read_devices", lambda h, c: []), \
                mock.patch.object(svc.bluetooth, "read_devices", boom), \
                self.assertLogs("app.services.battery.service", "ERROR"):
            out = REAL_READ()
        self.assertEqual([d.id for d in out], ["sony"])


class SystemEventTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(se.classify(se.WM_DEVICECHANGE, se.DBT_DEVNODES_CHANGED), "device")
        self.assertEqual(se.classify(se.WM_DEVICECHANGE, se.DBT_DEVICEARRIVAL), "device")
        self.assertEqual(se.classify(se.WM_POWERBROADCAST, se.PBT_APMRESUMEAUTOMATIC), "resume")
        self.assertEqual(se.classify(se.WM_POWERBROADCAST, se.PBT_APMRESUMESUSPEND), "resume")
        self.assertIsNone(se.classify(se.WM_POWERBROADCAST, 0x0004))   # indo dormir: nada
        self.assertIsNone(se.classify(0x0010, 0))

    @unittest.skipUnless(__import__("sys").platform == "win32", "Windows")
    def test_filter_parses_native_msg(self):
        from ctypes import addressof, wintypes
        got = []
        f = se.SystemEventFilter(got.append)
        msg = wintypes.MSG()
        msg.message = se.WM_POWERBROADCAST
        msg.wParam = se.PBT_APMRESUMEAUTOMATIC
        self.assertEqual(f.nativeEventFilter(b"windows_generic_MSG", addressof(msg)), (False, 0))
        msg.message = 0x0010
        f.nativeEventFilter(b"windows_generic_MSG", addressof(msg))
        self.assertEqual(got, ["resume"])


if __name__ == "__main__":
    unittest.main()
