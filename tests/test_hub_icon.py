"""Testes do ícone do Hub: garante que o selo vermelho DEV só aparece fora do build congelado (.exe)."""

import sys
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app.hub import hub_icon
from app.main import _app_user_model_id


def _has_dev_red_pixels(icon, size: int = 64) -> bool:
    """Confere se há pixels vermelhos do selo DEV no canto inferior direito do ícone."""
    img = icon.pixmap(size, size).toImage()
    start = size // 2
    for y in range(start, size):
        for x in range(start, size):
            c = img.pixelColor(x, y)
            if c.alpha() > 200 and c.red() >= 190 and c.green() <= 60 and c.blue() <= 60:
                return True
    return False


class TestHubIconDevGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self):
        hub_icon._cached_icon = None
        hub_icon._cached_dev = None

    def test_dev_build_draws_red_badge_and_uses_dev_aumid(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertTrue(hub_icon.is_dev_build())
            self.assertEqual(_app_user_model_id(), "Aimedget.Hub.Dev")
            icon = hub_icon.create_aimedget_icon(64)
            self.assertFalse(icon.isNull())
            self.assertTrue(_has_dev_red_pixels(icon, 64))

    def test_frozen_release_never_draws_dev_badge_and_uses_release_aumid(self):
        with patch.object(sys, "frozen", True, create=True):
            self.assertFalse(hub_icon.is_dev_build())
            self.assertEqual(_app_user_model_id(), "Aimedget.Hub")
            icon = hub_icon.create_aimedget_icon(64)
            self.assertFalse(icon.isNull())
            self.assertFalse(_has_dev_red_pixels(icon, 64))


if __name__ == "__main__":
    unittest.main()
