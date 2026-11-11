"""
Peças comuns aos temas de WIDGET (Música / Timer), que usam o mesmo motor dos temas de flyout (cores, fundo,
figurinhas; ver theme_loader.py e theme_art.py).

Diferença em relação aos flyouts: por padrão a janela do widget tem exatamente o tamanho do cartão. Quando o tema
tem figurinhas que passam da borda, o widget ganha uma MARGEM transparente em volta do cartão (`art_margin_px`), só
o suficiente para a arte não ser cortada; sem figurinhas para fora, nada muda. Não há nada ATRÁS do cartão:
figurinhas com `"layer": "behind"` viram `"below"` (entre o fundo e o conteúdo) e `shadow` é ignorada, ambos com aviso.
"""

import math
from dataclasses import replace

from app.core.theme_art import Sticker, issue_scope, overflow_margins, report_issue

MAX_ART_MARGIN = 48   # px: limite da margem transparente em volta do cartão (figurinhas além disso são cortadas)


def art_margin_px(stickers, card_w: float, card_h: float, k: float = 1.0, free: float = 0.0) -> int:
    """
    Margem (px, igual nos quatro lados) que a janela precisa para as figurinhas que passam da borda do cartão.
    `card_w`/`card_h` em px lógicos do tema, `k` = px de tela por px lógico, `free` = folga que a janela já tem
    (ex.: a margem da sombra do Timer). 0 se nenhuma figurinha sai do cartão.
    """
    if not stickers:
        return 0
    reach = max(overflow_margins(stickers, None, card_w, card_h)) * k - free
    return int(min(MAX_ART_MARGIN, max(0, math.ceil(reach))))


def drop_unsupported(changes: dict, label: str) -> dict:
    """Tira de `changes` o que é comum aos temas mas não existe nos widgets (a sombra do cartão: a janela do widget
    não tem margem para ela), com aviso. Devolve o próprio `changes`."""
    if changes.pop("shadow", None) is not None:
        with issue_scope(label=label):
            report_issue("'shadow' não existe nos widgets (a janela tem o tamanho exato do cartão): ignorada")
    return changes


def widget_stickers(stickers: tuple[Sticker, ...], label: str) -> tuple[Sticker, ...]:
    """Converte a camada "behind" (inexistente nos widgets) em "below"."""
    if not any(st.layer == "behind" for st in stickers):
        return stickers
    with issue_scope(label=label):
        report_issue("'layer': 'behind' não existe nos widgets (não há espaço atrás do cartão): usando 'below'")
    return tuple(replace(st, layer="below") if st.layer == "behind" else st for st in stickers)


def parse_bool(data: dict, key: str, default: bool, label: str) -> bool:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool):
        return value
    with issue_scope(label=label):
        report_issue("'%s' precisa ser true ou false, mas veio %r (usando %s)", key, value, str(default).lower())
    return default
