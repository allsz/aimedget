"""
Mídia de demonstração dos previews de skins: a mesma capa em todas, o fundo sem laranja (o logo não entra na paleta)
e a galeria de temas da Capa Empilhada continua mostrando o visual do tema, não o da miniatura.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from app.widgets.music.skins.preview_media import preview_media


def _dominant_hue_is_orange(img) -> bool:
    n = 0
    for y in range(0, img.height(), 8):
        for x in range(0, img.width(), 8):
            h, s, v, _ = img.pixelColor(x, y).getHsvF()
            if s > 0.5 and v > 0.5 and 0.05 <= h <= 0.12:
                n += 1
    return n > 6


class PreviewMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_backdrop_has_no_orange_but_cover_has_the_logo(self):
        media = preview_media()
        self.assertFalse(_dominant_hue_is_orange(media.backdrop))   # a paleta sai daqui: sem laranja
        self.assertTrue(_dominant_hue_is_orange(media.cover))       # o logo (laranja oficial) está na capa
        self.assertIs(preview_media(), media)                        # desenhada uma vez só

    def test_every_skin_thumbnail_uses_it_and_none_stays_default_blue(self):
        from app.core.colorimetry import get_default_palette
        from app.widgets.music.skins import specs

        specs._cached_instances.clear()
        for spec in specs.init_music_skin_specs():
            skin = specs._get_headless(spec.id, {
                "vinyl": lambda: __import__("app.widgets.music.skins.vinyl_skin", fromlist=["VinylMusicSkin"]).VinylMusicSkin,
                "fullcover": lambda: __import__("app.widgets.music.skins.fullcover_skin", fromlist=["FullCoverSkin"]).FullCoverSkin,
                "ripple": lambda: __import__("app.widgets.music.skins.ripple_skin", fromlist=["RippleSkin"]).RippleSkin,
                "capa_empilhada": lambda: __import__("app.widgets.music.skins.capa_empilhada_skin", fromlist=["CapaEmpilhadaSkin"]).CapaEmpilhadaSkin,
            }[spec.id])
            self.assertIsNotNone(skin.album_pixmap, spec.id)
            if not hasattr(skin, "pastel_theme"):   # a Capa Empilhada usa a paleta pastel, não a de fundo escuro
                self.assertNotEqual(skin.current_palette.stop2.name(), get_default_palette().stop2.name(), spec.id)

    def test_stack_theme_gallery_is_untouched_by_the_demo_media(self):
        from app.widgets.music.skins import stack_theme, stack_theme_specs

        spec = stack_theme_specs.make_theme_spec("x", "X", stack_theme.DEFAULT_THEME)
        size = spec.natural_size(spec.mock_state())
        # o tema padrão não tem arte para fora do cartão: a miniatura do tema é o cartão 490x240, como sempre
        self.assertEqual((int(size.width()), int(size.height())), (490, 240))


if __name__ == "__main__":
    unittest.main()
