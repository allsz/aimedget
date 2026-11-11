"""
Regras do modo Alarme do Timer (lógica pura).

O alarme é um horário do dia (segundos desde a meia-noite, 00:00:00 a 23:59:59). Ao iniciar, a contagem vai até a
PRÓXIMA ocorrência desse horário: hoje, ou amanhã se ele já passou. A contagem usa o relógio do Windows (não um
acumulador), então continua certa depois de o PC dormir ou de o widget ficar escondido.
"""

import datetime

DAY_SECONDS = 24 * 3600
ALARM_FIELD_MAX = {"hours": 23, "minutes": 59, "seconds": 59}


def normalize_alarm_time(seconds) -> int:
    """Qualquer valor vira um horário do dia (dá a volta na meia-noite)."""
    return int(seconds) % DAY_SECONDS


def step_alarm_time(base: int, change: int) -> int:
    """Passo da rolagem: 23:59 + 1 min vira 00:00, e 00:00 - 1 min vira 23:59."""
    return normalize_alarm_time(int(base) + int(change))


def alarm_field_accepts(segment: str, digits: str) -> bool:
    """True se o número digitado cabe no campo do horário (horas até 23, minutos e segundos até 59)."""
    return int(digits or 0) <= ALARM_FIELD_MAX[segment]


def compose_alarm_time(fields: dict[str, int]) -> int:
    return normalize_alarm_time(fields["hours"] * 3600 + fields["minutes"] * 60 + fields["seconds"])


def next_alarm(now: datetime.datetime, alarm_time: int) -> datetime.datetime:
    """A próxima vez em que o relógio marca `alarm_time` depois de `now` (hoje, ou amanhã se já passou)."""
    hours, rem = divmod(normalize_alarm_time(alarm_time), 3600)
    minutes, seconds = divmod(rem, 60)
    target = now.replace(hour=hours, minute=minutes, second=seconds, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def default_alarm_time(now: datetime.datetime) -> int:
    """Primeira vez no modo Alarme: a próxima hora cheia (ex.: às 14:20 sugere 15:00)."""
    return ((now.hour + 1) % 24) * 3600


def format_clock(alarm_time: int) -> str:
    """'07:30' (ou '07:30:15' quando há segundos), para o rótulo do widget."""
    hours, rem = divmod(normalize_alarm_time(alarm_time), 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if seconds else f"{hours:02d}:{minutes:02d}"
