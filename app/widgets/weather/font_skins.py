"""
Skins do Weather Widget = troca de fonte. O cartão, as cores e o movimento são os mesmos; só a tipografia muda.

- "glass": a fonte do app (Inter), como na referência.
- Cada arquivo .ttf/.otf em `assets/fonts/weather/` vira uma skin com o nome da família da fonte. Para a skin no
  estilo Nothing basta colocar a fonte (ex.: a de matriz de pontos) nessa pasta; nada é adivinhado no código.
"""

import os
from dataclasses import dataclass

from PySide6.QtGui import QFontDatabase

from app.core.paths import ASSETS_DIR

DEFAULT_SKIN = "glass"
WEATHER_FONTS_DIR = os.path.join(ASSETS_DIR, "fonts", "weather")
_FONT_EXTS = (".ttf", ".otf")


@dataclass(frozen=True)
class FontSkin:
    id: str
    family: str     # "" = fonte do app
    title: str


_loaded: dict[str, FontSkin] = {}   # caminho -> skin (cada arquivo é registrado no Qt uma vez só)


def discover() -> list:
    """Skins de fonte disponíveis agora (relê a pasta: uma fonte nova aparece sem reiniciar o Hub)."""
    skins = [FontSkin(DEFAULT_SKIN, "", "Glass")]
    if not os.path.isdir(WEATHER_FONTS_DIR):
        return skins
    for name in sorted(os.listdir(WEATHER_FONTS_DIR)):
        if not name.lower().endswith(_FONT_EXTS):
            continue
        path = os.path.join(WEATHER_FONTS_DIR, name)
        skin = _loaded.get(path)
        if skin is None:
            font_id = QFontDatabase.addApplicationFont(path)
            families = QFontDatabase.applicationFontFamilies(font_id) if font_id != -1 else []
            if not families:
                continue
            skin = FontSkin(f"font:{os.path.splitext(name)[0]}", families[0], families[0])
            _loaded[path] = skin
        skins.append(skin)
    return skins


def skin_by_id(skin_id: str) -> FontSkin:
    for skin in discover():
        if skin.id == skin_id:
            return skin
    return discover()[0]
