"""
Regras de duração do Timer (lógica pura).

A duração configurada é 0 (zerado) ou, no mínimo, 10 s. Valores de 1 a 9 s não existem:
o ajuste "pula" de 10 s para 0 e de 0 para 10 s, para o usuário nunca cair num valor em que o
play não funciona sem entender o motivo.
"""

MIN_RUN_SECONDS = 10
MAX_SECONDS = 86400 * 24


def normalize_duration(seconds) -> int:
    """Duração válida mais próxima: 0, ou entre 10 s e o máximo."""
    s = int(seconds)
    if s <= 0:
        return 0
    if s < MIN_RUN_SECONDS:
        return MIN_RUN_SECONDS
    return min(s, MAX_SECONDS)


def step_duration(base: int, change: int) -> int:
    """
    Aplica um passo de ajuste (rolagem) respeitando a regra 0 ou >= 10 s.

    Subindo: de 0 vai a 10 s. Descendo: passos grandes param em 10 s primeiro; só de 10 s
    (ou menos) o próximo passo para baixo zera.
    """
    new = min(int(base) + int(change), MAX_SECONDS)
    if change > 0:
        return MIN_RUN_SECONDS if 0 < new < MIN_RUN_SECONDS or new <= 0 else new
    if new >= MIN_RUN_SECONDS:
        return new
    return MIN_RUN_SECONDS if base > MIN_RUN_SECONDS else 0
