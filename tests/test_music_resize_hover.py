"""Regressão: cursor de redimensionamento deve voltar para ArrowCursor ao sair da alça para área vazia."""

import unittest

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
from app.widgets.music.skins.fullcover_skin import FullCoverSkin
from app.widgets.music.skins.ripple_skin import RippleSkin
from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

_app = QApplication.instance() or QApplication([])
SKINS = (CapaEmpilhadaSkin, FullCoverSkin, RippleSkin, VinylMusicSkin)


def _make(cls):
    try:
        return cls(scale=0.5)
    except TypeError:
        return cls()


def _move_mouse(widget, pos: QPointF):
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        pos,
        pos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseMoveEvent(event)


class ResizeHoverCursorTests(unittest.TestCase):
    def test_cursor_resets_when_leaving_resize_grip_to_empty_area(self):
        for cls in SKINS:
            with self.subTest(skin=cls.__name__):
                skin = _make(cls)
                grip_rect = skin.get_resize_grip_rect()
                grip_pos = QPointF(grip_rect.center())
                # Ponto neutro no canto superior esquerdo (fora de botões e da alça)
                empty_pos = QPointF(4.0, 4.0)
                self.assertFalse(skin.is_in_resize_grip(empty_pos))
                self.assertIsNone(skin._hit_test(empty_pos))

                _move_mouse(skin, grip_pos)
                self.assertTrue(skin._resize_hovered)
                self.assertEqual(skin.cursor().shape(), Qt.CursorShape.SizeFDiagCursor)

                _move_mouse(skin, empty_pos)
                self.assertFalse(skin._resize_hovered)
                self.assertEqual(skin.cursor().shape(), Qt.CursorShape.ArrowCursor)
