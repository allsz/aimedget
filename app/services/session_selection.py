"""
Escolha da sessão de mídia que o Music Widget exibe (lógica pura, sem winsdk).

Problema que resolve: com dois players abertos (um tocando, outro pausado), na troca de faixa
do player ativo o Windows o reporta por instantes com título vazio ou status "mudando". Pela
pontuação pura o player pausado vencia por um ciclo e "injetava" a capa dele na tela.

Regras:
1. Quem está TOCANDO tem prioridade sobre quem está pausado, qualquer que seja a pontuação-base.
2. Estabilidade ("sticky"): a sessão atual só perde o lugar para outra que esteja TOCANDO.
   Um player pausado nunca a desbanca.
3. Falha transitória: se a sessão atual deixa de parecer música por instantes (título vazio na
   troca de faixa) OU some da lista do Windows (o Chrome recria a sessão entre faixas), o widget
   SEGURA o estado atual por `grace` segundos em vez de cair para outro player. Passado o
   prazo, a sessão é liberada.
"""

from dataclasses import dataclass
from typing import Any

PLAYING = "playing"
CHANGING = "changing"   # o Windows reporta isso durante a troca de faixa
PAUSED = "paused"
OTHER = "other"

DEFAULT_GRACE_S = 3.0   # cobre a troca de faixa de players web (a sessão pode sumir por ~1 s)


@dataclass
class SessionCandidate:
    key: str                 # AUMID (minúsculo) do app de origem
    is_music: bool
    score: int               # pontuação-base (tipo de player)
    status: str              # playing | changing | paused | other
    payload: Any = None      # dados da sessão (usados por quem chama)


def _rank(c: SessionCandidate, sticky_key: str | None) -> tuple[int, int, int]:
    """Maior é melhor: tocando > pontuação > ser a sessão atual (desempate)."""
    is_playing = c.status == PLAYING or (c.key == sticky_key and c.status == CHANGING)
    return (1 if is_playing else 0, c.score, 1 if c.key == sticky_key else 0)


def _best(pool: list[SessionCandidate], sticky_key: str | None) -> SessionCandidate | None:
    best = None
    for c in pool:
        if best is None or _rank(c, sticky_key) > _rank(best, sticky_key):
            best = c
    return best


def pick_session(
    candidates: list[SessionCandidate],
    sticky_key: str | None,
    sticky_ok_at: float,
    now: float,
    grace: float = DEFAULT_GRACE_S,
) -> tuple[SessionCandidate | None, bool]:
    """
    Retorna (sessão escolhida, segurar).
    `segurar=True` significa: não há troca nem dado novo; mantenha o que já está na tela.
    `sticky_ok_at` é o último instante em que a sessão atual foi reconhecida como música.
    """
    music = [c for c in candidates if c.is_music]
    if not sticky_key:
        return _best(music, None), False

    sticky = next((c for c in candidates if c.key == sticky_key), None)
    challengers = [c for c in music if c.key != sticky_key and c.status == PLAYING]

    if sticky is not None and sticky.is_music:
        return _best([sticky] + challengers, sticky_key), False

    # A sessão atual sumiu da lista ou deixou de parecer música (troca de faixa). Só um player
    # que esteja TOCANDO de fato pode assumir; um pausado nunca "vaza" nesse intervalo.
    if now - sticky_ok_at <= grace:
        if challengers:
            return _best(challengers, sticky_key), False
        return None, True
    return _best(music, None), False
