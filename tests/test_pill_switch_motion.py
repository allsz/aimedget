import time
import unittest

from PySide6.QtWidgets import QApplication

from app.hub.components import pill_switch as ps

_app = QApplication.instance() or QApplication([])


def _run(sw, limit=3.0):
    end = time.monotonic() + limit
    while sw._timer.isActive() and time.monotonic() < end:
        _app.processEvents()
        time.sleep(0.005)


class PillSwitchMotionTests(unittest.TestCase):
    def test_animates_and_settles(self):
        sw = ps.PillSwitch()
        ps.animations_enabled = lambda: True
        sw.setChecked(True)
        self.assertTrue(sw._timer.isActive())
        self.assertLess(sw._thumb_position, 1.0)       # não pulou
        self.assertGreater(sw._stretch.v, 0.0)         # chutou o esticar
        _run(sw)
        self.assertEqual(sw._thumb_position, 1.0)
        self.assertEqual(sw._stretch.x, 0.0)
        self.assertFalse(sw._timer.isActive())

    def test_without_animations_is_instant(self):
        sw = ps.PillSwitch()
        orig = ps.animations_enabled
        ps.animations_enabled = lambda: False
        try:
            sw.setChecked(True)
        finally:
            ps.animations_enabled = orig
        self.assertEqual(sw._thumb_position, 1.0)
        self.assertFalse(sw._timer.isActive())

    def test_set_checked_not_animated_snaps(self):
        sw = ps.PillSwitch()
        sw.set_checked(True, animated=False)
        self.assertEqual(sw._thumb_position, 1.0)
        self.assertFalse(sw._timer.isActive())


if __name__ == "__main__":
    unittest.main()
