import os
from PySide6.QtGui import QFont, QFontDatabase
from app.core.paths import FONT_PATH, ROUNDED_FONT_PATH

APP_FONT_FAMILY = "Inter"
ROUNDED_FONT_FAMILY = "Nunito"
_rounded_font_loaded = False


def init_app_font() -> str:
    """Garante que a fonte Inter (e a fonte arredondada Nunito) sejam registradas no sistema."""
    global APP_FONT_FAMILY
    if os.path.exists(FONT_PATH):
        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                APP_FONT_FAMILY = families[0]
    _ensure_rounded_font()
    return APP_FONT_FAMILY


def _ensure_rounded_font() -> str:
    global ROUNDED_FONT_FAMILY, _rounded_font_loaded
    if not _rounded_font_loaded:
        _rounded_font_loaded = True
        if os.path.exists(ROUNDED_FONT_PATH):
            font_id = QFontDatabase.addApplicationFont(ROUNDED_FONT_PATH)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    ROUNDED_FONT_FAMILY = families[0]
    return ROUNDED_FONT_FAMILY


def get_rounded_font(px: float, weight: QFont.Weight = QFont.Weight.ExtraBold,
                     letter_spacing: float = 0.0) -> QFont:
    """Fonte arredondada espessa (Nunito) usada no estilo circular do KeyLock OSD."""
    family = _ensure_rounded_font()
    font = QFont(family)
    font.setPixelSize(max(1, int(round(px))))
    font.setWeight(weight)
    if letter_spacing != 0.0:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    font.setStyleStrategy(
        QFont.StyleStrategy.PreferQuality
        | QFont.StyleStrategy.PreferAntialias
        | QFont.StyleStrategy.NoSubpixelAntialias
    )
    return font


def get_ui_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Helper unificado para aplicar a fonte Inter em todo o app com anti-aliasing de alta fidelidade."""
    font = QFont(APP_FONT_FAMILY)
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setStyleStrategy(
        QFont.StyleStrategy.PreferQuality
        | QFont.StyleStrategy.PreferAntialias
        | QFont.StyleStrategy.NoSubpixelAntialias
    )
    return font


def card_font(px: float, weight: QFont.Weight = QFont.Weight.Normal, tabular: bool = False,
              family: str | None = None, min_px: int = 1) -> QFont:
    """Fonte dos cartões desenhados à mão (Clima, Desempenho, Bateria): pixel exato, melhor qualidade e, em `tabular`,
    algarismos de mesma largura (tnum) para os números não dançarem ao mudar."""
    f = QFont(family or APP_FONT_FAMILY)
    f.setPixelSize(max(min_px, int(round(px))))
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferQuality | QFont.StyleStrategy.PreferAntialias)
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except Exception:   # Qt sem setFeature: segue sem tnum
            pass
    return f

