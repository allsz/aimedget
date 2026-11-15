"""
Tema (tokens visuais) do flyout de Volume / Mixer. Mesmo esquema do Caps Lock: o container (tamanho, gaveta,
animações) é definido em código; o tema só muda a aparência. O arquivo do usuário fica em:

    %LOCALAPPDATA%/Aimedget/themes/mixer/theme.json

e é relido sempre que o flyout aparece. Exemplo (todas as chaves são opcionais):

    {
      "card_bg":    "#3b1d4a",
      "border":     "#6a3d82",
      "text":       "#ffffff",
      "muted_text": "#b9a3c9",
      "icon":       "#ffffff",
      "accent":     "#b46cff",
      "radius":     14,
      "shadow":     {"color": "#9646198c", "blur": 22, "dy": 9},
      "divider":    "#69ffffff",
      "on_accent":  "#6a35c9",
      "switch_on":  "#b68cf5",
      "drawer_bg":  "#e65a2d96",
      "thumb_outer": "#ffffff",
      "background": {"image": "fundo.png", "fit": "cover"},
      "stickers": [{"image": "estrela.png", "anchor": "top-right", "x": -4, "y": -6, "width": 22}]
    }

- `accent` é a cor de ativação: parte preenchida dos sliders, botão do slider, aba ativa (Saída/Entrada)
  e destaque do ícone do app com a gaveta aberta. O botão do slider acompanha o `accent`, a menos que
  você defina `thumb` à parte.
- Forma própria (`tilt`, `plates`, `digits`, `slider_style`): ver theme_shape.py, neste pacote.
- Fundo e figurinhas: ver app/core/theme_art.py. O card do Mixer cresce e encolhe com a gaveta; as
  âncoras `bottom-*` acompanham a base do card em movimento.
"""

from dataclasses import dataclass, replace

from PySide6.QtGui import QColor

from app.core.theme_art import Background, CardShadow, Sticker
from app.core.theme_art import issue_scope
from app.core.theme_loader import ThemeLoader, color_field, parse_tokens
from app.widgets.volume_mixer.theme_shape import (
    SLIDER_HEIGHT_RANGE, SLIDER_SLANT_RANGE, SLIDER_TAPER_RANGE, TILT_RANGE, Digits, Header, Plate, parse_digits,
    parse_header, parse_plates, parse_slider_style,
)

RADIUS_RANGE = (0.0, 25.0)
EXTRA_NUMBERS = {
    "button_radius": (0.0, 13.0),
    "tilt": TILT_RANGE, "slider_height": SLIDER_HEIGHT_RANGE, "slider_slant": SLIDER_SLANT_RANGE,
    "slider_taper": SLIDER_TAPER_RANGE,
}
# Forma própria do mixer (ver theme_shape.py); as que não são número são lidas em theme_from_dict
_SHAPE_KEYS = ("tilt", "slider_height", "slider_slant", "slider_taper", "slider_style", "plates", "digits", "header")


@dataclass(frozen=True)
class MixerTheme:
    """Tokens visuais. Os padrões reproduzem exatamente a aparência original."""
    card_bg: QColor = color_field(30, 30, 30, 248)
    border: QColor = color_field(55, 55, 55)
    text: QColor = color_field(255, 255, 255)           # números de volume
    muted_text: QColor = color_field(150, 150, 150)     # números quando o áudio está mudo
    icon: QColor = color_field(255, 255, 255)           # alto-falante e seta do cabeçalho
    accent: QColor = color_field(84, 175, 244)          # cor de ativação (trilho, aba ativa, destaques)
    thumb: QColor = color_field(77, 178, 255)           # miolo do botão do slider
    # Partes que antes tinham cor fixa
    thumb_outer: QColor = color_field(69, 69, 69)       # disco externo do botão do slider
    thumb_border: QColor = color_field(54, 54, 54)      # borda desse disco
    track_inactive: QColor = color_field(153, 153, 153) # parte vazia do trilho
    button_bg: QColor = color_field(44, 44, 44)         # botão da seta (^ / v)
    button_hover: QColor = color_field(56, 56, 56)
    button_pressed: QColor = color_field(36, 36, 36)
    button_border: QColor = color_field(52, 52, 52)
    button_radius: float = 5.0                          # 13 = redondo
    divider: QColor = color_field(49, 49, 49)           # linha entre o cabeçalho e a lista de apps
    on_accent: QColor = color_field(255, 255, 255)      # texto sobre a cor de ativação (aba Saída/Entrada ativa)
    switch_on: QColor = color_field(84, 175, 244)       # interruptores de dispositivo ligados
    # Gaveta de roteamento (aberta ao clicar no ícone de um app)
    drawer_bg: QColor = color_field(36, 36, 36, 250)
    drawer_border: QColor = color_field(54, 54, 54)
    tabs_bg: QColor = color_field(25, 25, 25, 220)      # trilho das abas Saída / Entrada
    tabs_border: QColor = color_field(50, 50, 50)
    radius: float = 8.0
    shadow: CardShadow | None = None                    # sombra suave do card (None = a sombra original)
    background: Background | None = None
    stickers: tuple[Sticker, ...] = ()
    # Forma própria (theme_shape.py)
    tilt: float = 0.0                                   # inclinação do card inteiro, em graus
    slider_style: str = "fluent"                        # "fluent" (trilho fino + botão) ou "bar" (faixa lisa)
    slider_height: float = 4.0                          # altura do trilho / da faixa
    slider_slant: float = 0.0                           # pontas inclinadas da faixa (fração da altura)
    slider_taper: float = 1.0                           # faixa em cunha: altura da ponta direita / da esquerda
    header: Header | None = None                        # onde ficam a faixa principal e o botão da seta
    plates: tuple[Plate, ...] = ()                      # placas coloridas atrás do card
    digits: Digits | None = None                        # número do volume principal desenhado com imagem


DEFAULT_THEME = MixerTheme()

_COLOR_KEYS = (
    "card_bg", "border", "text", "muted_text", "icon", "accent", "thumb",
    "thumb_outer", "thumb_border", "track_inactive",
    "button_bg", "button_hover", "button_pressed", "button_border", "divider",
    "on_accent", "switch_on", "drawer_bg", "drawer_border", "tabs_bg", "tabs_border",
)


def theme_from_dict(data: dict, base_dir: str | None = None) -> MixerTheme:
    """Monta um tema a partir de um dict, ignorando chaves desconhecidas e valores inválidos."""
    changes = parse_tokens(data, base_dir, "mixer", _COLOR_KEYS, RADIUS_RANGE, extra_numbers=EXTRA_NUMBERS,
                           extra_keys=("slider_style", "plates", "digits", "header"))
    with issue_scope(label="mixer"):
        header = parse_header(data.get("header"))
        if header is not None:
            changes["header"] = header
        if "slider_style" in data:
            style = parse_slider_style(data["slider_style"])
            if style is not None:
                changes["slider_style"] = style
        plates = parse_plates(data.get("plates"))
        if plates:
            changes["plates"] = plates
        if base_dir is not None:
            digits = parse_digits(data.get("digits"), base_dir)
            if digits is not None:
                changes["digits"] = digits
    # Quem muda só o `accent` espera o botão do slider na mesma cor (o padrão é um azul ligeiramente diferente)
    if "accent" in changes and "thumb" not in changes:
        changes["thumb"] = changes["accent"]
    if "accent" in changes and "switch_on" not in changes:
        changes["switch_on"] = changes["accent"]
    return replace(DEFAULT_THEME, **changes)


def _app_theme() -> MixerTheme:
    from app.core.app_theme import app_mixer_theme   # tardio: app_theme importa este módulo
    return app_mixer_theme()


_loader = ThemeLoader("mixer", DEFAULT_THEME, theme_from_dict, "mixer", app_theme=_app_theme)

theme_path = _loader.path
load_user_theme = _loader.load
reset_cache = _loader.reset

loader = _loader  # descoberta/seleção de temas (usado pelo Hub)
