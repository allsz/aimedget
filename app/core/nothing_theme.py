"""
Tokens visuais compartilhados para temas das skins Nothing Dot (Clima e Desempenho).

Um tema é só dados (`theme.json` + imagens opcionais ao lado):
  - `card_bg`: fundo fosco do cartão (padrão #161616)
  - `border`: contorno fino de 1 px (padrão branco 9%)
  - `text`: texto principal (padrão #ffffff)
  - `muted_text`: subtítulos e rodapé (padrão branco 57%)
  - `dot_on`: pontos acesos da matriz / temperatura (padrão #ffffff)
  - `dot_off`: pontos apagados da grade (padrão branco 14%)
  - `accent`: cor de destaque Nothing (padrão #D71921 — grau °, pico vivo, paginação)
  - `background`: imagem opcional de fundo
  - `stickers`: figurinhas opcionais (até 12)

Tema embutido "Aimedget" (`APP_NOTHING_THEME`): em vez de cores fixas, segue o app (fundo off-white do app `bg`,
como o widget de Baterias; texto, linhas e cor de destaque, no modo claro, escuro ou true dark). As cores saem de `resolve_nothing_theme(tema, hub)` na hora
de pintar, então a miniatura do Hub e o widget acompanham uma troca de aparência sem reabrir nada.
"""

from dataclasses import dataclass, field, replace
from functools import lru_cache

from PySide6.QtGui import QColor

from app.core.theme_art import Background, Sticker
from app.core.theme_loader import parse_tokens
from app.core.widget_theme import drop_unsupported, widget_stickers
from app.hub.theme import HubTheme
from app.ui_components.dot_matrix import NOTHING_BG, NOTHING_RED

COLOR_KEYS = ("card_bg", "border", "text", "muted_text", "dot_on", "dot_off", "accent")


@dataclass(frozen=True, eq=False)
class NothingDotTheme:
    card_bg: QColor = field(default_factory=lambda: QColor(NOTHING_BG))
    border: QColor = field(default_factory=lambda: QColor(255, 255, 255, 23))
    text: QColor = field(default_factory=lambda: QColor(255, 255, 255, 255))
    muted_text: QColor = field(default_factory=lambda: QColor(255, 255, 255, 145))
    dot_on: QColor = field(default_factory=lambda: QColor(255, 255, 255, 248))
    dot_off: QColor = field(default_factory=lambda: QColor(255, 255, 255, 36))
    accent: QColor = field(default_factory=lambda: QColor(NOTHING_RED))
    background: Background | None = None
    stickers: tuple[Sticker, ...] = ()
    follows_app: bool = False   # tema embutido "Aimedget": as cores vêm do app (ver resolve_nothing_theme)


DEFAULT_NOTHING_THEME = NothingDotTheme()
APP_NOTHING_THEME = NothingDotTheme(follows_app=True)


def _alpha(hex_color: str, alpha: int) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


@lru_cache(maxsize=16)
def nothing_theme_from_hub(hub: HubTheme) -> NothingDotTheme:
    """As cores do app na linguagem Nothing: fundo do app (off-white no claro), texto e destaque do Hub; pontos
    apagados no tom do texto."""
    return NothingDotTheme(
        card_bg=QColor(hub.bg),
        border=QColor(hub.line),
        text=QColor(hub.text),
        muted_text=_alpha(hub.text, 145),
        dot_on=QColor(hub.text),
        dot_off=_alpha(hub.text, 36),
        accent=QColor(hub.accent),
    )


def resolve_nothing_theme(theme: NothingDotTheme, hub: HubTheme) -> NothingDotTheme:
    """O tema com as cores de fato: o "Aimedget" vira as cores do app `hub`; os outros ficam como estão."""
    return nothing_theme_from_hub(hub) if theme.follows_app else theme


def nothing_theme_from_dict(data: dict, base_dir: str | None = None, label: str = "nothing") -> NothingDotTheme:
    """Monta um NothingDotTheme a partir de um dict, ignorando chaves desconhecidas e valores inválidos."""
    changes = drop_unsupported(parse_tokens(data, base_dir, label, COLOR_KEYS, render_boost=2.0), label)
    if "stickers" in changes:
        changes["stickers"] = widget_stickers(changes["stickers"], label)
    return replace(DEFAULT_NOTHING_THEME, **changes)
