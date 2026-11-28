"""
Tema (tokens visuais) da skin Capa Empilhada do widget de Música. Mesmo esquema dos temas de flyout: a skin
(formato, pilha de capas, animações) é definida em código; o tema só muda a aparência. Os temas ficam em:

    %LOCALAPPDATA%/Aimedget/themes/music/<tema>/theme.json   (+ imagens ao lado)

Exemplo (todas as chaves são opcionais):

    {
      "name": "Lavanda",
      "card_bg":        "#f3ecff",
      "title":          "#2a1640",
      "subtitle":       "#8a5cc7",
      "button_top":     "#e4d4ff",
      "button_bottom":  "#faf6ff",
      "button_shadow":  "#38704aa0",
      "accent":         "#9b5de5",
      "accent_muted":   "#b892ea",
      "progress_track": "#7dffffff",
      "progress_fill":  "#ffffff",
      "adaptive":       false,
      "background": {"image": "fundo.png", "fit": "cover"},
      "stickers": [{"image": "estrela.svg", "anchor": "top-right", "x": -30, "y": 24, "width": 34}]
    }

- Sem tema (ou sem nenhuma cor da paleta), a skin continua tirando a paleta da capa do álbum, como sempre.
- Com alguma cor da paleta, a paleta passa a ser FIXA (as cores ausentes vêm da paleta coral original). Para
  manter a paleta da capa e só acrescentar fundo/figurinhas/barra, use `"adaptive": true`.
- Medidas das figurinhas em px do widget no tamanho padrão (490 x 240); elas acompanham o redimensionamento.
"""

import json
import math
import os
from dataclasses import dataclass, replace

from PySide6.QtGui import QColor

from app.core.theme_art import ANCHORS, Background, Sticker
from app.core.theme_loader import ThemeLoader, parse_tokens
from app.core.widget_theme import MAX_ART_MARGIN, drop_unsupported, parse_bool, widget_stickers
from app.widgets.music.skins.stack_palette import PastelStackTheme, get_default_pastel_theme

LABEL = "music"
CARD_SIZE = (490.0, 240.0)   # tamanho do widget com escala 1 (canvas 980 x 480 pela metade)

# chave do JSON -> campo da PastelStackTheme
_PALETTE_KEYS = {
    "card_bg": "card_bg",
    "title": "title_color",
    "subtitle": "subtitle_color",
    "button_top": "btn_grad_tl",
    "button_bottom": "btn_grad_br",
    "button_shadow": "btn_shadow",
    "accent": "accent_main",
    "accent_muted": "accent_muted",
}
_OTHER_COLORS = ("progress_track", "progress_fill")


@dataclass(frozen=True, eq=False)
class StackTheme:
    """Os padrões reproduzem exatamente a skin original (paleta tirada da capa, barra branca)."""
    palette: PastelStackTheme | None = None    # None = paleta adaptativa (da capa do álbum)
    progress_track: QColor | None = None       # None = trilho translúcido original
    progress_fill: QColor | None = None        # None = branco
    background: Background | None = None
    stickers: tuple[Sticker, ...] = ()

    @property
    def adaptive(self) -> bool:
        return self.palette is None


DEFAULT_THEME = StackTheme()


def theme_from_dict(data: dict, base_dir: str | None = None) -> StackTheme:
    """Monta um tema a partir de um dict, ignorando chaves desconhecidas e valores inválidos."""
    color_keys = tuple(_PALETTE_KEYS) + _OTHER_COLORS
    changes = drop_unsupported(
        parse_tokens(data, base_dir, LABEL, color_keys, extra_keys=("adaptive",), render_boost=2.0), LABEL)
    palette_changes = {_PALETTE_KEYS[k]: changes.pop(k) for k in list(changes) if k in _PALETTE_KEYS}
    adaptive = parse_bool(data, "adaptive", default=not palette_changes, label=LABEL)
    if not adaptive:
        changes["palette"] = replace(get_default_pastel_theme(), **palette_changes)
    if "stickers" in changes:
        changes["stickers"] = widget_stickers(changes["stickers"], LABEL)
    return replace(DEFAULT_THEME, **changes)


_loader = ThemeLoader("music", DEFAULT_THEME, theme_from_dict, LABEL)


def max_installed_sticker_overflow() -> float:
    """
    Maior folga (em px lógicos de CARD_SIZE) pedida pelas figurinhas de todos os temas instalados.
    Lê só o JSON (sem decodificar PNG/SVG) para que a janela translúcida já nasça com margem suficiente
    e nunca precise chamar SetWindowPos/redimensionar ao alternar Padrão <-> Exclusivo (evita o salto de 1 frame no DWM).
    """
    card_w, card_h = CARD_SIZE
    best = 0.0
    for info in _loader.list_themes():
        if info.id == "default":
            continue
        found = _loader._theme_file_and_dir(info.id)
        if not found:
            continue
        theme_file, _ = found
        try:
            with open(theme_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        stickers = data.get("stickers")
        if not isinstance(stickers, list):
            continue
        for item in stickers:
            if not isinstance(item, dict):
                continue
            anchor = item.get("anchor", "center")
            ax, ay = ANCHORS.get(anchor, (0.5, 0.5))
            x = float(item.get("x", 0.0) or 0.0)
            y = float(item.get("y", 0.0) or 0.0)
            w = float(item.get("width", 0.0) or 0.0)
            h = float(item.get("height", w) or w)
            if w <= 0.0 and h > 0.0:
                w = h
            if w <= 0.0:
                continue
            # Folga de sombra assada nas figurinhas (DEFAULT_STICKER_SHADOW blur=1.6, dy=1.6 -> ~5px)
            pad = 6.0 if item.get("shadow", True) is not False else 0.0
            tw, th = w + 2.0 * pad, h + 2.0 * pad
            a = math.radians(float(item.get("rotation", 0.0) or 0.0))
            hw = (abs(tw * math.cos(a)) + abs(th * math.sin(a))) * 0.5
            hh = (abs(tw * math.sin(a)) + abs(th * math.cos(a))) * 0.5
            cx = card_w * ax + x
            cy = card_h * ay + y
            best = max(best, hw - cx, cx + hw - card_w, hh - cy, cy + hh - card_h)
    return best

theme_path = _loader.path
load_user_theme = _loader.load
reset_cache = _loader.reset

loader = _loader  # descoberta/seleção de temas (usado pelo Hub)
