"""Ancorar o widget de música: a janela ganha a folga do brilho num passo só, sem o cartão sair do lugar um quadro."""

import unittest

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin

_app = QApplication.instance() or QApplication([])


class _Geometry(QObject):
    """Anota a posição do cartão na tela a cada Move/Resize que a janela recebe."""

    def __init__(self, skin):
        super().__init__()
        self.skin, self.seen = skin, []

    def eventFilter(self, obj, ev):
        if obj is self.skin and ev.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            g = self.skin.geometry()
            m = self.skin.art_margin
            self.seen.append((g.x() + m, g.y() + m, g.width() - 2 * m))
        return False


class MusicAnchorRoomTests(unittest.TestCase):
    def _skin(self):
        skin = CapaEmpilhadaSkin(scale=0.6)
        skin.move_card_to(400, 300)
        skin.show()
        _app.processEvents()
        return skin

    def test_glow_room_keeps_the_card_still_in_every_step(self):
        skin = self._skin()
        try:
            origin, size = skin.card_origin(), skin._card_size()
            spy = _Geometry(skin)
            skin.installEventFilter(spy)
            skin.anchor_glow_room(True)
            _app.processEvents()
            self.assertGreaterEqual(skin.art_margin, skin.ANCHOR_GLOW_ROOM)
            self.assertEqual(skin.size().width(), size[0] + 2 * skin.art_margin)
            self.assertEqual(skin.card_origin(), origin)
            for x, y, _w in spy.seen:                    # nenhum passo intermediário com o cartão deslocado
                self.assertEqual((x, y), (origin.x(), origin.y()))
            skin.anchor_glow_room(False)
            _app.processEvents()
            self.assertEqual(skin.card_origin(), origin)
            for x, y, _w in spy.seen:
                self.assertEqual((x, y), (origin.x(), origin.y()))
        finally:
            skin.close()

    def test_glow_room_during_the_appear_animation_keeps_the_rest_position(self):
        skin = CapaEmpilhadaSkin(scale=0.6)
        try:
            skin.move_card_to(400, 300)
            from unittest import mock
            with mock.patch("app.core.widget_animator.animations_enabled", return_value=True):
                skin.animator.show(400)
                skin.anchor_glow_room(True)
                self.assertEqual(skin.card_origin().x(), 400)
                self.assertEqual(skin.card_origin().y(), 300)
                skin.animator.settle()
            self.assertEqual(skin.card_origin().x(), 400)
            self.assertEqual(skin.card_origin().y(), 300)
        finally:
            skin.close()


class EverySkinDrawsInsideItsCardTests(unittest.TestCase):
    """O print do bug: Fullcover/Vinyl/Ripple desenhavam em (0, 0) e ignoravam a margem; o brilho (que segue o cartão
    que o anchor enxerga) saía 16 px deslocado e os botões respondiam fora do lugar."""

    def test_painting_and_hit_boxes_follow_the_card_rect(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QImage
        from app.widgets.music.skins.fullcover_skin import FullCoverSkin
        from app.widgets.music.skins.ripple_skin import RippleSkin
        from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

        for cls in (FullCoverSkin, RippleSkin, VinylMusicSkin, CapaEmpilhadaSkin):
            with self.subTest(skin=cls.__name__):
                skin = cls(scale=0.5)
                try:
                    card = skin.card_rect()
                    self.assertGreater(card.left(), 0)             # há folga em volta (a do brilho, fixa)
                    width_before = skin.width()
                    skin.anchor_glow_room(True)
                    self.assertEqual(skin.width(), width_before)   # ancorar não muda o tamanho da janela
                    img = QImage(skin.size(), QImage.Format.Format_ARGB32_Premultiplied)
                    img.fill(Qt.GlobalColor.transparent)
                    skin.render(img)
                    self.assertEqual(img.pixelColor(2, 2).alpha(), 0)                         # margem vazia
                    inside = card.center().toPoint()
                    self.assertGreater(img.pixelColor(inside).alpha(), 200)                  # cartão no lugar
                    # o botão principal responde onde está desenhado (coordenadas do cartão + margem)
                    m = skin.art_margin
                    main = skin.rect_main.center()
                    from PySide6.QtGui import QMouseEvent
                    from PySide6.QtCore import QEvent
                    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(main.x() + m, main.y() + m),
                                     QPointF(main.x() + m, main.y() + m), Qt.MouseButton.NoButton,
                                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
                    if cls is not CapaEmpilhadaSkin:
                        self.assertEqual(skin._hit_test(skin.card_pos(ev)), "main")
                finally:
                    skin.close()


if __name__ == "__main__":
    unittest.main()
