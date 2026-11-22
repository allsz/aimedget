"""
Formato do tempo exibido no Timer (puro, sem Qt além de QRectF), compartilhado pelas skins.

- Temporizador e Alarme: HH:MM:SS.
- Cronômetro abaixo de 1 h: MM:SS:cc (minutos, segundos e centésimos).
- Cronômetro a partir de 1 h: HH:MM:SS (os centésimos saem de cena e as horas entram).

Os dois formatos têm 6 dígitos, então o tempo ocupa a mesma largura no cartão nos dois.

A troca entre eles não acontece "no corte": `morph` (0..1, movido por uma mola nas skins) abre/fecha a largura dos
campos que entram/saem, e o texto deles aparece/some junto. 0 = MM:SS:cc, 1 = HH:MM:SS.
"""

from typing import Callable

from PySide6.QtCore import QRectF

SLOT_KEYS = ("hours", "colon1", "minutes", "colon2", "seconds", "colon3", "centis")
COLON_KEYS = ("colon1", "colon2", "colon3")
HOUR_SECONDS = 3600.0
MORPH_SPRING = (280.0, 34.0)   # fecha/abre campos sem passar do ponto (a mesma de fechar fileiras, CLOSE)


def is_compact(mode: str, seconds: float) -> bool:
    """True no Cronômetro abaixo de 1 h (formato MM:SS:cc)."""
    return mode == "stopwatch" and seconds < HOUR_SECONDS


def morph_target(mode: str, seconds: float) -> float:
    """Para onde o formato quer ir: 0 = MM:SS:cc, 1 = HH:MM:SS."""
    return 0.0 if is_compact(mode, seconds) else 1.0


def slot_texts(mode: str, seconds: float) -> dict[str, str]:
    """Texto de cada campo. Vale para os dois formatos: o campo que não aparece só fica com largura zero."""
    seconds = max(0.0, float(seconds))
    if mode == "stopwatch":
        tot, centis = divmod(int(seconds * 100.0), 100)   # corta (não arredonda): 59,996 s ainda é 00:59:99
    else:
        tot, centis = int(round(seconds)), 0
    return {
        "hours": f"{tot // 3600:02d}", "colon1": ":",
        "minutes": f"{(tot % 3600) // 60:02d}", "colon2": ":",
        "seconds": f"{tot % 60:02d}", "colon3": ":",
        "centis": f"{centis:02d}",
    }


def slot_visibility(morph: float) -> dict[str, float]:
    """0..1 de cada campo: horas e o ':' depois delas crescem com o morph; centésimos e o ':' antes deles, com o resto."""
    m = max(0.0, min(1.0, float(morph)))
    return {"hours": m, "colon1": m, "minutes": 1.0, "colon2": 1.0, "seconds": 1.0, "colon3": 1.0 - m,
            "centis": 1.0 - m}


def cell_advance(cell: float) -> Callable[[str], float]:
    """Largura de um número com cada dígito numa célula fixa (o texto não balança quando os números mudam)."""
    return lambda text: cell * len(text)


def layout_slots(center_x: float, top: float, height: float, digit_w: Callable[[str], float], colon_w: float,
                 texts: dict[str, str], vis: dict[str, float]) -> dict[str, QRectF]:
    """Retângulos dos campos, o conjunto centrado em `center_x`. `digit_w(texto)` dá a largura cheia de um número; a
    largura de cada campo é multiplicada pela sua visibilidade."""
    widths = {k: (colon_w if k in COLON_KEYS else digit_w(texts[k])) * vis[k] for k in SLOT_KEYS}
    x = center_x - sum(widths.values()) / 2.0
    rects = {}
    for k in SLOT_KEYS:
        rects[k] = QRectF(x, top, widths[k], height)
        x += widths[k]
    return rects
