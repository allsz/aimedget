import os
from PySide6.QtGui import QFont, QFontDatabase
from app.core.paths import FONT_PATH

APP_FONT_FAMILY = "Inter"


def init_app_font() -> str:
    """Garante que a fonte Inter seja registrada no sistema e usada globalmente."""
    global APP_FONT_FAMILY
    if os.path.exists(FONT_PATH):
        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                APP_FONT_FAMILY = families[0]
    return APP_FONT_FAMILY


def get_ui_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Helper unificado para aplicar a fonte Inter em todo o app com anti-aliasing de alta fidelidade."""
    font = QFont(APP_FONT_FAMILY)
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferQuality | QFont.StyleStrategy.PreferAntialias)
    return font

