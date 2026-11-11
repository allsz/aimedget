"""
Regras de duração do Timer (lógica pura).

A duração configurada é 0 (zerado) ou, no mínimo, 10 s. Valores de 1 a 9 s não existem:
o ajuste "pula" de 10 s para 0 e de 0 para 10 s, para o usuário nunca cair num valor em que o
play não funciona sem entender o motivo.
"""

MIN_RUN_SECONDS = 10
MAX_SECONDS = 99 * 3600 + 59 * 60 + 59   # 99:59:59: o campo das horas tem dois dígitos


def normalize_duration(seconds) -> int:
    """Duração válida mais próxima: 0, ou entre 10 s e o máximo."""
    s = int(seconds)
    if s <= 0:
        return 0
    if s < MIN_RUN_SECONDS:
        return MIN_RUN_SECONDS
    return min(s, MAX_SECONDS)


FIELD_MAX = {"hours": 99, "minutes": 59, "seconds": 59}   # teto de cada campo ao digitar


def split_duration(total: int) -> dict[str, int]:
    """Os três campos do relógio (horas, minutos, segundos) de uma duração em segundos."""
    total = max(0, int(total))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return {"hours": hours, "minutes": minutes, "seconds": seconds}


def typed_field_accepts(segment: str, digits: str) -> bool:
    """True se o número digitado cabe no campo (horas até 99, minutos e segundos até 59)."""
    return int(digits or 0) <= FIELD_MAX[segment]


def compose_duration(fields: dict[str, int]) -> int:
    """Duração dos três campos (0, ou entre 10 s e 99:59:59)."""
    return normalize_duration(fields["hours"] * 3600 + fields["minutes"] * 60 + fields["seconds"])


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
