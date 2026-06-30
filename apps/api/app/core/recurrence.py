"""Avanço de datas para recorrência (semanal/mensal/anual), com clamp de dia no mês."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

MAX_OCCURRENCES = 60


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])  # 31/jan + 1 mês -> 28/29 fev
    return date(y, m, day)


def advance(d: date, recurrence: str, i: int) -> date:
    """A i-ésima ocorrência (i=0 é a própria data)."""
    if i <= 0:
        return d
    if recurrence == "weekly":
        return d + timedelta(weeks=i)
    if recurrence == "monthly":
        return add_months(d, i)
    if recurrence == "yearly":
        return add_months(d, 12 * i)
    return d


def occurrences(recurrence: str, count: int) -> int:
    """Quantas contas gerar: 1 se não recorre; senão count limitado a [1, MAX]."""
    if recurrence == "none":
        return 1
    return max(1, min(count, MAX_OCCURRENCES))
