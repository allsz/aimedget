""""Configurar" no menu de cada widget: chega ao Hub como pedido de abrir a página daquele widget."""
import unittest

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


class ConfigureRequestRoutingTests(unittest.TestCase):
    def test_hub_show_widget_page_selects_page_and_shows(self):
        from unittest import mock
        from app.hub.hub_window import AimedgetHubWindow
        fake = mock.Mock()
        AimedgetHubWindow.show_widget_page(fake, "battery")
        fake.sidebar.select_page.assert_called_once_with("battery")
        fake.show_and_activate.assert_called_once()

    def test_bridge_maps_each_controller_to_its_page(self):
        from PySide6.QtCore import QObject, Signal
        from app.hub.service_bridge import HubServiceBridge

        class Ctl(QObject):
            configure_requested = Signal()

        bridge = HubServiceBridge.__new__(HubServiceBridge)
        QObject.__init__(bridge)
        pages = ("music", "timer", "weather", "performance", "storage", "battery")
        for pid in pages:
            setattr(bridge, f"{pid}_controller", Ctl())
        got = []
        bridge.configure_widget_requested.connect(got.append)
        bridge._wire_configure_requests()
        for pid in pages:
            getattr(bridge, f"{pid}_controller").configure_requested.emit()
        self.assertEqual(got, list(pages))

    def test_label_in_both_languages(self):
        from app.core import i18n
        self.assertEqual(i18n.TRANSLATIONS["pt"]["menu_configure_widget"], "Configurar")
        self.assertEqual(i18n.TRANSLATIONS["en"]["menu_configure_widget"], "Configure")


if __name__ == "__main__":
    unittest.main()
