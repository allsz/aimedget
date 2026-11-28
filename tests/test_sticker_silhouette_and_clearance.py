"""Testes de detecção de pixels opacos, folga lateral na faixa da barra de volume e brilho por silhueta."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication

from app.core.theme_art import Sticker, bake_silhouette_glow, opaque_bounds, visual_bounds

_app = QApplication.instance() or QApplication(sys.argv)


def _padded_pixmap(size=40, pad=10, color=QColor("#ff6600")) -> QPixmap:
    """Pixmap transparente de `size x size` com quadrado opaco centralizado com margem `pad`."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.fillRect(pad, pad, size - 2 * pad, size - 2 * pad, color)
    p.end()
    return QPixmap.fromImage(img)


class StickerSilhouetteAndClearanceTests(unittest.TestCase):
    def test_opaque_bounds_ignores_transparent_padding(self):
        pm = _padded_pixmap(size=40, pad=10)
        ob = opaque_bounds(pm)
        self.assertAlmostEqual(ob.left(), 0.25, places=2)
        self.assertAlmostEqual(ob.top(), 0.25, places=2)
        self.assertAlmostEqual(ob.width(), 0.50, places=2)
        self.assertAlmostEqual(ob.height(), 0.50, places=2)

    def test_visual_bounds_vertical_band_clears_side_sticker_but_ignores_corner(self):
        pm = _padded_pixmap(size=40, pad=10)  # opaco ocupa metade central (20x20 dentro de 40x40)
        ob = opaque_bounds(pm)
        # Figurinha no canto superior direito (fora da faixa central da barra de volume)
        corner = Sticker(pixmap=pm, anchor="top-right", x=10.0, y=-5.0, width=40.0, height=40.0, opaque_rect=ob)
        # Figurinha na lateral direita central (como o Shooky)
        middle = Sticker(pixmap=pm, anchor="right", x=12.0, y=0.0, width=40.0, height=40.0, opaque_rect=ob)

        card = QRectF(50.0, 50.0, 200.0, 100.0)
        y_band = (70.0, 130.0)  # faixa de 60% centrada no cartão

        # Só com figurinha no canto superior: faixa vertical não expande a direita
        vis_corner = visual_bounds((corner,), card, 200.0, 100.0, y_band=y_band)
        self.assertAlmostEqual(vis_corner.right(), card.right(), places=1)

        # Com figurinha na lateral central: expande até o último pixel opaco (250 + 12 + 10 = 272), não a borda transparente (282)
        vis_middle = visual_bounds((corner, middle), card, 200.0, 100.0, y_band=y_band)
        self.assertAlmostEqual(vis_middle.right(), 272.0, places=1)
        self.assertAlmostEqual(vis_middle.top(), card.top(), places=1)
        self.assertAlmostEqual(vis_middle.bottom(), card.bottom(), places=1)

    def test_silhouette_glow_wraps_outside_sticker_and_never_cuts_through_it(self):
        pm = _padded_pixmap(size=40, pad=0)  # quadrado opaco 40x40
        st = Sticker(pixmap=pm, anchor="right", x=10.0, y=0.0, width=40.0, height=40.0,
                     opaque_rect=QRectF(0.0, 0.0, 1.0, 1.0))
        card = QRectF(40.0, 40.0, 120.0, 80.0)
        shape = QPainterPath()
        shape.addRoundedRect(card, 16.0, 16.0)

        halo = bake_silhouette_glow(220, 160, shape, (st,), card, 120.0, 80.0, extent=12.0)

        # Dentro do cartão: transparente (DestinationOut)
        self.assertEqual(halo.pixelColor(100, 80).alpha(), 0)
        # Dentro da parte da figurinha que sai pela direita do cartão (x=160..190, y=60..100): transparente!
        self.assertEqual(halo.pixelColor(175, 80).alpha(), 0)
        # Logo fora da borda direita da figurinha (x=193, y=80): brilho visível!
        self.assertGreater(halo.pixelColor(193, 80).alpha(), 20)
        # Logo acima da figurinha (x=175, y=56): brilho visível!
        self.assertGreater(halo.pixelColor(175, 56).alpha(), 20)


if __name__ == "__main__":
    unittest.main()
