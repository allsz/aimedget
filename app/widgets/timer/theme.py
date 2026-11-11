"""
Tema (tokens visuais) da skin Aimedget do Timer. Mesmo esquema dos temas de flyout: a skin (formato, botões,
dígitos) é definida em código; o tema só muda a aparência. Os temas ficam em:

    %LOCALAPPDATA%/Aimedget/themes/timer/<tema>/theme.json   (+ imagens ao lado)

Exemplo (todas as chaves são opcionais):

    {
      "name": "Lavanda",
      "card_bg":      "#f3ecff",
      "border":       "#d9c6f7",
      "text":         "#2a1640",
      "muted_text":   "#8a74a8",
      "accent":       "#9b5de5",
      "accent_hover": "#8a4bd6",
      "on_accent":    "#ffffff",
      "button_bg":    "#e8dcfb",
      "icon":         "#4a2d6e",
      "select_border": "#ffffff",
      "background": {"image": "fundo.png", "fit": "cover"},
      "stickers": [{"image": "estrela.svg", "anchor": "top-right", "x": -14, "y": 14, "width": 22}]
    }

- O Timer segue o modo claro/escuro e a cor de destaque do app; o tema troca SÓ as cores que definir.
  Um tema só com figurinhas mantém as cores do app; um tema com todas as cores tem visual fixo.
- `select_border`: cor da volta de luz ao clicar num número (padrão: branca no tema escuro, escura no claro).
- `accent` sem `accent_hover`: o hover é o próprio `accent` um pouco mais escuro.
- Medidas das figurinhas em px do cartão no tamanho padrão (148 x 148); elas acompanham o redimensionamento.
"""

from dataclasses import dataclass, replace

from PySide6.QtGui import QColor

from app.core.theme_art import Background, Sticker
from app.core.theme_loader import ThemeLoader, parse_tokens
from app.core.widget_theme import drop_unsupported, widget_stickers
from app.hub.theme import HubTheme

LABEL = "timer"

# chave do JSON -> campo do HubTheme que a skin usa para aquela parte
_COLOR_TO_HUB = {
    "card_bg": "panel",          # fundo do cartão
    "border": "line",            # borda do cartão
    "text": "text",              # dígitos
    "muted_text": "mute",        # rótulo (TEMPORIZADOR), dois-pontos, X de fechar
    "accent": "accent",          # botão play, alarme, dígito sob o mouse
    "accent_hover": "accent_hover",
    "on_accent": "ink",          # ícone play/pause sobre o destaque
    "button_bg": "panel2",       # botão de reiniciar
    "icon": "body",              # seta do botão de reiniciar
}


# cores que não viram campo do HubTheme: a skin as usa direto
EXTRA_COLOR_KEYS = ("select_border",)


@dataclass(frozen=True, eq=False)
class TimerTheme:
    """Sem nenhuma cor: o Timer usa as cores do app (o visual original)."""
    colors: tuple[tuple[str, QColor], ...] = ()   # (campo do HubTheme, cor)
    background: Background | None = None
    stickers: tuple[Sticker, ...] = ()
    select_border: QColor | None = None

    def apply_to(self, hub: HubTheme) -> HubTheme:
        """As cores do app com as do tema por cima."""
        if not self.colors:
            return hub
        return replace(hub, **{field: color.name(QColor.NameFormat.HexArgb) for field, color in self.colors})


DEFAULT_THEME = TimerTheme()


def theme_from_dict(data: dict, base_dir: str | None = None) -> TimerTheme:
    """Monta um tema a partir de um dict, ignorando chaves desconhecidas e valores inválidos."""
    changes = drop_unsupported(parse_tokens(data, base_dir, LABEL, tuple(_COLOR_TO_HUB) + EXTRA_COLOR_KEYS, render_boost=2.0), LABEL)
    colors = {k: changes.pop(k) for k in list(changes) if k in _COLOR_TO_HUB}
    if "accent" in colors and "accent_hover" not in colors:
        colors["accent_hover"] = colors["accent"].darker(110)
    if "stickers" in changes:
        changes["stickers"] = widget_stickers(changes["stickers"], LABEL)
    changes["colors"] = tuple((_COLOR_TO_HUB[k], c) for k, c in colors.items())
    return replace(DEFAULT_THEME, **changes)


_loader = ThemeLoader("timer", DEFAULT_THEME, theme_from_dict, LABEL)

theme_path = _loader.path
load_user_theme = _loader.load
reset_cache = _loader.reset

loader = _loader  # descoberta/seleção de temas (usado pelo Hub)
