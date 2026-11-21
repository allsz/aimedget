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
"""

from dataclasses import dataclass, field, replace

from PySide6.QtGui import QColor

from app.core.theme_art import Background, Sticker
from app.core.theme_loader import parse_tokens
from app.core.widget_theme import drop_unsupported, widget_stickers
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


DEFAULT_NOTHING_THEME = NothingDotTheme()


def nothing_theme_from_dict(data: dict, base_dir: str | None = None, label: str = "nothing") -> NothingDotTheme:
    """Monta um NothingDotTheme a partir de um dict, ignorando chaves desconhecidas e valores inválidos."""
    changes = drop_unsupported(parse_tokens(data, base_dir, label, COLOR_KEYS, render_boost=2.0), label)
    if "stickers" in changes:
        changes["stickers"] = widget_stickers(changes["stickers"], label)
    return replace(DEFAULT_NOTHING_THEME, **changes)
