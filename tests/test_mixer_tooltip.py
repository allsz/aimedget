"""Nome do app no mixer ao passar no ícone: não pode piscar ao cruzar a faixa vazia entre dois ícones."""

import sys
import unittest
from unittest import mock

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

import app.widgets.volume_mixer.mixer_flyout as mf
from app.services.audio_mixer_service import AppAudioSession
from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout


class MixerTooltipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.m = VolumeMixerFlyout()
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        self.m.on_sessions_updated([AppAudioSession("a", "Alfa", 50, False, img),
                                    AppAudioSession("b", "Beta", 50, False, img)])
        self.m.is_expanded = True                       # gaveta aberta, sem esperar a animação
        self.m._apply_window_canvas_size(expanded_canvas=True)
        self.m._expand_t = 1.0
        self.m._anim_card_h = self.m._target_expanded_height()
        p = mock.patch.object(mf, "QToolTip")
        self.tip = p.start()
        self.addCleanup(p.stop)

    def _icon_center(self, i):
        card = self.m._card_rect()
        x0, y = card.left(), card.top() + (self.m.FIRST_ROW_OFFSET_Y - self.m.ROW_PITCH * 0.5)
        for row in self.m._rows[:i]:
            y += row.get_total_height()
        return QPointF(x0 + 24.0, y + self.m._rows[i].MAIN_ROW_CY)

    def _move(self, pt):
        ev = QMouseEvent(QMouseEvent.Type.MouseMove, pt, self.m.mapToGlobal(pt.toPoint()), Qt.MouseButton.NoButton,
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        self.m.mouseMoveEvent(ev)

    def test_name_is_shown_on_the_icon(self):
        self._move(self._icon_center(0))
        self.assertEqual(self.tip.showText.call_args.args[1], "Alfa")

    def test_crossing_the_gap_does_not_hide_at_once(self):
        a, b = self._icon_center(0), self._icon_center(1)
        self._move(a)
        self._move(QPointF(a.x(), (a.y() + b.y()) / 2))     # faixa vazia entre os dois ícones
        self.tip.hideText.assert_not_called()               # antes escondia na hora (fade-out + fade-in = pisca)
        self._move(b)
        self.assertEqual(self.tip.showText.call_args.args[1], "Beta")
        self.assertFalse(self.m._tip_hide_timer.isActive())  # o sumiço agendado foi cancelado
        self.tip.hideText.assert_not_called()

    def test_leaving_the_icons_hides_it_after_a_short_delay(self):
        self._move(self._icon_center(0))
        self._move(QPointF(150.0, self._icon_center(0).y()))   # sobre o slider, fora do ícone
        self.assertTrue(self.m._tip_hide_timer.isActive())
        self.m._tip_hide_timer.timeout.emit()
        self.tip.hideText.assert_called()

    def test_leaving_the_flyout_hides_it_immediately(self):
        self._move(self._icon_center(0))
        self.m.leaveEvent(None)
        self.tip.hideText.assert_called()
        self.assertFalse(self.m._tip_hide_timer.isActive())


if __name__ == "__main__":
    unittest.main()
