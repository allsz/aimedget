"""
Tema (tokens visuais) do flyout de Caps/Num Lock.

Um tema é só dados: cores e raio. O container (formato, tamanho, animação do cadeado) continua
definido em código; o tema só muda a aparência. O arquivo do usuário fica em:

    %LOCALAPPDATA%/WindowsRedesign/themes/keylock/theme.json

e é relido a cada vez que o flyout aparece (edite, aperte Caps Lock e veja). Exemplo:

    {
      "card_bg":   "#3b1d4a",
      "border":    "#6a3d82",
      "text":      "#ffffff",
      "icon":      "#ffffff",
      "off_color": "#4a3355",
      "on_color":  "#b46cff",
      "radius":    14,
      "scale":     1.4,
      "auto_scale": true,
      "shadow":    {"color": "#9646198c", "blur": 13, "dy": 5},
      "background": {"image": "fundo.png", "fit": "cover"},
      "stickers": [{"image": "estrela.svg", "anchor": "top-right", "x": -4, "y": -6, "width": 22,
                    "layer": "above", "shadow": true},
                   {"image": "led-aceso.svg", "anchor": "top-left", "x": 18, "y": 12, "state": "on"}],
      "indicator": "none", "show_icon": false, "label_align": "center", "label_size": 18,
      "label_case": "lower", "text_off": "#9a9aa0", "size": [140, 52]
    }

- `scale` é o tamanho do flyout numa tela 1440p (1 = tamanho normal). Com `"auto_scale": true` ele se adapta
  às outras resoluções, mantendo a mesma proporção da tela (1080p = 75%, 4K a 100% = 150%, ...); sem isso,
  o tamanho é fixo em pixels. O tema Padrão não escala sozinho.

As imagens ficam na mesma pasta do theme.json (ver app/core/theme_art.py para todas as opções).
Chaves ausentes ou inválidas caem no valor padrão; um arquivo quebrado nunca impede o flyout de abrir.
"""

import logging
from dataclasses import dataclass, replace

from PySide6.QtGui import QColor

from PySide6.QtWidgets import QApplication

from app.core.screen_metrics import get_screen_scale_ratio
from app.core.theme_art import Background, CardShadow, Sticker, issue_scope, report_issue
from app.core.theme_loader import ThemeLoader, color_field, parse_tokens

logger = logging.getLogger(__name__)

RADIUS_RANGE = (0.0, 25.0)  # a altura padrão do card é 50: acima disso a pílula vira círculo
SCALE_RANGE = (0.75, 3.0)
LABEL_SIZE_RANGE = (8.0, 40.0)
SIZE_WIDTH_RANGE = (60.0, 400.0)    # `size` [largura, altura] do cartão, em px antes de `scale`
SIZE_HEIGHT_RANGE = (30.0, 200.0)
INDICATORS = ("bar", "none")
LABEL_ALIGNS = ("left", "center")
LABEL_CASES = ("none", "lower", "upper")


@dataclass(frozen=True)
class KeyLockTheme:
    """Tokens visuais. Os padrões reproduzem exatamente a aparência original."""
    card_bg: QColor = color_field(30, 30, 30, 248)
    border: QColor = color_field(55, 55, 55)
    text: QColor = color_field(255, 255, 255)
    icon: QColor = color_field(255, 255, 255)
    off_color: QColor = color_field(41, 65, 77)    # pílula com a tecla desligada
    on_color: QColor = color_field(76, 194, 255)   # pílula com a tecla ligada (cor de ativação)
    radius: float = 8.0
    scale: float = 1.0                      # aumenta o flyout inteiro (card, texto, cadeado, figurinhas)
    auto_scale: bool = False                # True: `scale` vale para 1440p e se adapta às outras telas
    shadow: CardShadow | None = None        # sombra suave do card (None = a sombra original)
    background: Background | None = None   # imagem de fundo do card
    stickers: tuple[Sticker, ...] = ()      # figurinhas (até 12)
    # --- layout (o que aparece dentro do cartão) ---
    indicator: str = "bar"                  # "bar" = barrinha de baixo; "none" = sem barrinha (o estado vai na arte)
    show_icon: bool = True                  # False = sem o cadeado
    label_align: str = "left"               # "left" (ao lado do cadeado) ou "center" (no meio do cartão)
    label_size: float = 14.0                # tamanho da letra do nome da tecla
    label_case: str = "none"                # "none" = como o app escreve; "lower" = minúsculas; "upper" = MAIÚSCULAS
    text_off: QColor | None = None          # cor do nome com a tecla desligada (None = a mesma de `text`)
    size: tuple[float, float] | None = None  # [largura, altura] fixas do cartão (None = automático: 50 de altura)


DEFAULT_THEME = KeyLockTheme()

_COLOR_KEYS = ("card_bg", "border", "text", "text_off", "icon", "off_color", "on_color")
_LAYOUT_KEYS = ("indicator", "show_icon", "label_align", "label_size", "label_case", "size")


def theme_from_dict(data: dict, base_dir: str | None = None) -> KeyLockTheme:
    """
    Monta um tema a partir de um dict, ignorando chaves desconhecidas e valores inválidos.
    `base_dir` é a pasta do tema (de onde saem as imagens); sem ela, fundo e figurinhas são ignorados.
    """
    auto = data.get("auto_scale")
    if "auto_scale" in data and not isinstance(auto, bool):
        with issue_scope(label="keylock"):
            report_issue("'auto_scale' precisa ser true ou false, mas veio %r (usando false)", auto)
        auto = False
    # Com escala automática, as figurinhas já são preparadas para o tamanho que terão NESTA tela
    boost = screen_ratio() if auto else 1.0
    with issue_scope(label="keylock"):
        size = _parse_size(data.get("size")) if "size" in data else None
        layout = _parse_layout(data)
    radius_range = RADIUS_RANGE if size is None else (0.0, max(RADIUS_RANGE[1], size[1] / 2.0))
    changes = parse_tokens(data, base_dir, "keylock", _COLOR_KEYS, radius_range, SCALE_RANGE, render_boost=boost,
                           extra_numbers={"label_size": LABEL_SIZE_RANGE},
                           extra_keys=("auto_scale",) + _LAYOUT_KEYS, sticker_states=True)
    if auto:
        changes["auto_scale"] = True
    changes.update(layout)
    if size is not None:
        changes["size"] = size
    return replace(DEFAULT_THEME, **changes)


def _parse_size(raw) -> tuple[float, float] | None:
    ok = (isinstance(raw, list) and len(raw) == 2
          and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw))
    if not ok:
        report_issue("'size' precisa ser [largura, altura], como [140, 52], mas veio %r (usando o tamanho automático)", raw)
        return None
    w, h = float(raw[0]), float(raw[1])
    cw = max(SIZE_WIDTH_RANGE[0], min(SIZE_WIDTH_RANGE[1], w))
    ch = max(SIZE_HEIGHT_RANGE[0], min(SIZE_HEIGHT_RANGE[1], h))
    if (cw, ch) != (w, h):
        report_issue("'size' fora do limite (%s x %s; largura %d a %d, altura %d a %d): usando %s x %s",
                     raw[0], raw[1], *SIZE_WIDTH_RANGE, *SIZE_HEIGHT_RANGE, cw, ch)
    return cw, ch


def _parse_layout(data: dict) -> dict:
    """indicator, show_icon, label_align, label_case (valores válidos); label_size e size são tratados à parte."""
    out: dict = {}
    for key, options in (("indicator", INDICATORS), ("label_align", LABEL_ALIGNS), ("label_case", LABEL_CASES)):
        if key in data:
            if data[key] in options:
                out[key] = data[key]
            else:
                report_issue("'%s' inválido: %r (use %s; usando o padrão)", key, data[key], ", ".join(options))
    if "show_icon" in data:
        if isinstance(data["show_icon"], bool):
            out["show_icon"] = data["show_icon"]
        else:
            report_issue("'show_icon' precisa ser true ou false, mas veio %r (usando true)", data["show_icon"])
    return out


def screen_ratio() -> float:
    """Tamanho da tela principal em relação a 1440p (1080p = 0,75; 4K a 100% = 1,5). 1.0 se não houver tela."""
    app = QApplication.instance()
    screen = app.primaryScreen() if app else None
    return get_screen_scale_ratio(screen=screen) if screen else 1.0


def effective_scale(theme: KeyLockTheme) -> float:
    """Escala realmente aplicada ao flyout nesta tela: a do tema, vezes a razão da tela se `auto_scale`."""
    return theme.scale * (screen_ratio() if theme.auto_scale else 1.0)


# O cache também depende da tela: se a resolução muda, as figurinhas são preparadas de novo
_loader = ThemeLoader("keylock", DEFAULT_THEME, theme_from_dict, "keylock", context=lambda: round(screen_ratio(), 2))

theme_path = _loader.path
load_user_theme = _loader.load
reset_cache = _loader.reset

loader = _loader  # descoberta/seleção de temas (usado pelo Hub)
