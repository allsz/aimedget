"""Leitor genérico de Bluetooth: agrupamento por endereço, só conectados, tipo, aproximado e o pulo dos leitores
próprios. Os nós imitam o que o Windows devolveu num PC real (fone QCY conectado, WH-1000XM4 e celular não)."""

import unittest

from app.services.battery import bluetooth as bt
from app.services.battery import service as svc
from app.services.battery.hid_win import HidInfo
from app.services.battery.models import (
    KIND_CONTROLLER,
    KIND_HEADSET,
    KIND_MOUSE,
    KIND_OTHER,
    KIND_PHONE,
    BatteryDevice,
)

QCY_DEV = r"BTHENUM\Dev_84AC609EBDE8\7&2584258&0&BluetoothDevice_84AC609EBDE8"
QCY_AG = r"BTHENUM\{0000111e-0000-1000-8000-00805f9b34fb}_VID&000105d6_PID&000a\7&2584258&0&84AC609EBDE8_C00000000"
XM4_DEV = r"BTHENUM\Dev_88C9E84928A6\7&2584258&0&BluetoothDevice_88C9E84928A6"
XM4_AG = r"BTHENUM\{0000111e-0000-1000-8000-00805f9b34fb}_VID&0002054c_PID&0d58\7&2584258&0&88C9E84928A6_C00000000"
PHONE_DEV = r"BTHENUM\Dev_90B62214CAFE\7&2584258&0&BluetoothDevice_90B62214CAFE"
PHONE_LE = r"BTHLE\Dev_90b62214cafe\7&273dc2f7&0&90b62214cafe"
PHONE_HF = r"BTHENUM\{0000111f-0000-1000-8000-00805f9b34fb}_VID&00010075_PID&0100\7&2584258&0&90B62214CAFE_C00000000"
MX_LE = r"BTHLE\Dev_dba3dd9cafc0\7&273dc2f7&0&dba3dd9cafc0"

HEADSET_CAT = "Communication.Headset.Bluetooth"


def qcy(connected=True, battery=100):
    return [bt.Node(QCY_DEV, connected=connected, name="QCY-T13 ANC", category=HEADSET_CAT, class_of_device=2360324),
            bt.Node(QCY_AG, battery=battery)]


class AddressTests(unittest.TestCase):
    def test_device_and_service_ids(self):
        self.assertEqual(bt.address_of(QCY_DEV), "84ac609ebde8")
        self.assertEqual(bt.address_of(QCY_AG), "84ac609ebde8")
        self.assertEqual(bt.address_of(MX_LE), "dba3dd9cafc0")
        self.assertIsNone(bt.address_of(r"BTH\MS_BTHBRB\6&13f39242&0&1"))

    def test_device_node_and_service(self):
        self.assertTrue(bt.is_device_node(QCY_DEV))
        self.assertFalse(bt.is_device_node(QCY_AG))
        self.assertEqual(bt.service_of(QCY_AG), bt.HFP_AG)
        self.assertEqual(bt.service_of(QCY_DEV), "")


class BuildTests(unittest.TestCase):
    def test_connected_headset_shows_parent_name_approximate(self):
        out = bt.build_devices(qcy())
        self.assertEqual(out, [BatteryDevice(id="bt:84ac609ebde8", name="QCY-T13 ANC", kind=KIND_HEADSET,
                                             percent=100.0, approximate=True, source=bt.SOURCE)])

    def test_disconnected_device_with_stale_battery_is_hidden(self):
        nodes = [bt.Node(XM4_DEV, connected=False, name="WH-1000XM4", category=HEADSET_CAT),
                 bt.Node(XM4_AG, battery=50)]
        self.assertEqual(bt.build_devices(nodes), [])
        self.assertEqual(bt.build_devices(qcy(connected=False)), [])

    def test_no_battery_no_device(self):
        nodes = [bt.Node(QCY_DEV, connected=True, name="QCY-T13 ANC"), bt.Node(QCY_AG)]
        self.assertEqual(bt.build_devices(nodes), [])

    def test_invalid_battery_ignored(self):
        self.assertEqual(bt.build_devices(qcy(battery=255)), [])

    def test_service_without_parent_ignored(self):
        self.assertEqual(bt.build_devices([bt.Node(QCY_AG, battery=80)]), [])

    def test_phone_merges_classic_and_le_nodes(self):
        # O nó LE (desconectado, categoria "Unknown") não pode esconder o clássico conectado
        nodes = [bt.Node(PHONE_DEV, connected=True, name="Matthew's Phone", category="Communication.Phone"),
                 bt.Node(PHONE_LE, connected=False, name="Matthew's Phone", category="Unknown"),
                 bt.Node(PHONE_HF, battery=80)]
        out = bt.build_devices(nodes)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].kind, KIND_PHONE)
        self.assertEqual(out[0].percent, 80.0)

    def test_le_device_battery_is_exact(self):
        nodes = [bt.Node(MX_LE, battery=60, connected=True, name="MX Master 3S", category="Input.Mouse")]
        out = bt.build_devices(nodes)
        self.assertEqual((out[0].kind, out[0].approximate), (KIND_MOUSE, False))

    def test_skip_by_address(self):
        self.assertEqual(bt.build_devices(qcy(), skip={"84AC609EBDE8"}), [])

    def test_missing_name_falls_back(self):
        nodes = [bt.Node(QCY_DEV, connected=True), bt.Node(QCY_AG, battery=40)]
        self.assertEqual(bt.build_devices(nodes)[0].name, "Bluetooth")


class KindTests(unittest.TestCase):
    def test_category_wins(self):
        self.assertEqual(bt.kind_from("Input.Gaming", None, ()), KIND_CONTROLLER)
        self.assertEqual(bt.kind_from("Communication.Phone", 2360324, ()), KIND_PHONE)

    def test_class_of_device_fallback(self):
        self.assertEqual(bt.kind_from("", 2360324, ()), KIND_HEADSET)      # QCY: áudio/headset
        self.assertEqual(bt.kind_from("", 5898764, ()), KIND_PHONE)        # celular
        self.assertEqual(bt.kind_from("", 0x000580, ()), KIND_MOUSE)       # periférico/apontador

    def test_hands_free_service_fallback(self):
        self.assertEqual(bt.kind_from("", None, {bt.HFP_AG}), KIND_HEADSET)
        self.assertEqual(bt.kind_from("", None, {bt.HFP_HF}), KIND_PHONE)
        self.assertEqual(bt.kind_from("Unknown", None, ()), KIND_OTHER)


def hid(path, vid, serial=""):
    return HidInfo(path=path, vid=vid, pid=1, usage_page=1, usage=2, input_len=0, output_len=0, feature_len=0,
                   serial=serial)


SONY_BT = hid(r"\\?\hid#{00001124-0000-1000-8000-00805f9b34fb}_vid&0002054c_pid&0ce6#8&1&0&0000#{4d1e}", 0x054C,
              serial="a0b1c2d3e4f5")
LOGI_LE = hid(r"\\?\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&02046d_pid&b034_rev&0011_dba3dd9cafc0&col01"
              r"#9&1&0&0000#{4d1e}", 0x046D)
LOGI_USB = hid(r"\\?\hid#vid_046d&pid_c083&mi_01&col03#7&64b27c6&0&0002#{4d1e}", 0x046D, serial="017F38513837")


class SkipTests(unittest.TestCase):
    def test_hid_addresses_bluetooth_only(self):
        self.assertEqual(bt.hid_addresses([SONY_BT, LOGI_LE, LOGI_USB]),
                         {"a0b1c2d3e4f5": 0x054C, "dba3dd9cafc0": 0x046D})

    def test_skip_only_when_dedicated_reader_delivered(self):
        logi = BatteryDevice(id="logi:x:1", name="MX Master 3S", kind=KIND_MOUSE, percent=60.0, source="logitech")
        self.assertEqual(svc.bluetooth_skip([LOGI_LE], [logi]), {"dba3dd9cafc0"})
        # Leitor próprio não entregou nada: o número do Windows serve de reserva
        self.assertEqual(svc.bluetooth_skip([LOGI_LE], []), set())

    def test_sony_headset_not_skipped_by_dualsense(self):
        # Um DualSense lido pelo leitor Sony não esconde um fone Sony (sem interface HID por Bluetooth)
        ds = BatteryDevice(id="sony:a", name="DualSense", kind=KIND_CONTROLLER, percent=50.0, source="sony")
        self.assertEqual(svc.bluetooth_skip([SONY_BT], [ds]), {"a0b1c2d3e4f5"})
        self.assertNotIn("88c9e84928a6", svc.bluetooth_skip([SONY_BT], [ds]))


class TrackerTests(unittest.TestCase):
    def test_disconnect_leaves_without_grace(self):
        t = svc.DeviceTracker()
        buds = bt.build_devices(qcy())
        self.assertEqual(len(t.update(buds)), 1)
        t.update([])                                  # primeira falta: pede confirmação
        self.assertTrue(t.unconfirmed())
        self.assertEqual(t.update([]), [])            # segunda: sai, sem as leituras de carência dos dongles


if __name__ == "__main__":
    unittest.main()
