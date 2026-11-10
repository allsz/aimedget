"""
Modos de repetição do Music Widget (lógica pura).

Semântica da interface (o que o ícone mostra):
    0 = desligado, 1 = repetir playlist, 2 = repetir faixa (ícone com "1").

Semântica do Windows (GSMTC, MediaPlaybackAutoRepeatMode):
    0 = None, 1 = Track, 2 = List.

Os dois eram confundidos: o widget enviava 1 ("playlist" no ícone) e o Windows entendia "faixa".
Aqui a tradução é explícita nos dois sentidos.

A ordem do ciclo ao clicar varia por player: o Spotify liga primeiro a repetição da faixa e
depois a da playlist; os demais, primeiro a playlist e depois a faixa.
"""

REPEAT_OFF = 0
REPEAT_LIST = 1    # playlist
REPEAT_TRACK = 2   # faixa

_UI_TO_GSMTC = {REPEAT_OFF: 0, REPEAT_LIST: 2, REPEAT_TRACK: 1}
_GSMTC_TO_UI = {0: REPEAT_OFF, 1: REPEAT_TRACK, 2: REPEAT_LIST}

_DEFAULT_CYCLE = (REPEAT_OFF, REPEAT_LIST, REPEAT_TRACK)
_PROVIDER_CYCLES = {
    "spotify": (REPEAT_OFF, REPEAT_TRACK, REPEAT_LIST),
}


def ui_to_gsmtc(ui_mode: int) -> int:
    return _UI_TO_GSMTC.get(int(ui_mode), 0)


def gsmtc_to_ui(gsmtc_mode) -> int:
    """Modo do Windows -> modo da interface; -1 se o player não informa (ex.: players web)."""
    if gsmtc_mode is None:
        return -1
    try:
        return _GSMTC_TO_UI.get(int(gsmtc_mode), -1)
    except (TypeError, ValueError):
        return -1


def repeat_cycle(provider: str) -> tuple[int, ...]:
    return _PROVIDER_CYCLES.get((provider or "").lower(), _DEFAULT_CYCLE)


def next_repeat_mode(provider: str, current: int) -> int:
    """Próximo modo da interface ao clicar, na ordem do player."""
    cycle = repeat_cycle(provider)
    try:
        idx = cycle.index(int(current))
    except ValueError:
        return cycle[1]
    return cycle[(idx + 1) % len(cycle)]
