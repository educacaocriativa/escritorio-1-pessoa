"""Story 7.9 — teste unitário DIRETO de core/recurrence.py (clamp de dia, ano bissexto).

Exercita `add_months`/`advance`/`occurrences` diretamente (sem passar por PayableCreate/
ChargeCreate/HTTP), cobrindo os cantos de data historicamente propensos a bug: clamp de dia
31→fevereiro, ano bissexto, fim de mês. Sem I/O, sem banco, sem dependência externa (só stdlib).
100% aditiva — nenhuma mudança de produção esperada.
"""
from datetime import date

from app.core.recurrence import MAX_OCCURRENCES, add_months, advance, occurrences

# --- AC1: add_months / clamp / bissexto ------------------------------------------


def test_add_months_clamps_day_31_to_february_common_year() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)  # 2026 não bissexto


def test_add_months_clamps_day_31_to_february_leap_year() -> None:
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # 2024 bissexto


def test_add_months_crosses_year_boundary() -> None:
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_add_months_clamps_across_multiple_months_end_of_month() -> None:
    # jan 31 + 3 meses = abril, que só tem 30 dias (clamp não é exclusivo de fevereiro).
    assert add_months(date(2026, 1, 31), 3) == date(2026, 4, 30)


def test_advance_yearly_leap_day_clamps_to_next_year() -> None:
    # recorrência anual a partir de 29/fev bissexto → ano não-bissexto (clamp p/ 28/fev).
    assert advance(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)


# --- AC2: advance / occurrences isolados -----------------------------------------


def test_advance_weekly() -> None:
    assert advance(date(2026, 1, 5), "weekly", 3) == date(2026, 1, 26)


def test_advance_monthly_delegates_to_add_months_clamp() -> None:
    assert advance(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)


def test_advance_zero_index_returns_same_date() -> None:
    d = date(2026, 3, 10)
    assert advance(d, "monthly", 0) == d  # i <= 0 → a própria ocorrência "0"


def test_advance_unknown_recurrence_returns_same_date() -> None:
    d = date(2026, 3, 10)
    # Fallback final de advance: string de recorrência não reconhecida → data inalterada.
    assert advance(d, "recorrencia-inexistente", 3) == d


def test_occurrences_none_recurrence_always_returns_one() -> None:
    assert occurrences("none", 5) == 1


def test_occurrences_clamps_to_max_60() -> None:
    assert occurrences("monthly", 999) == MAX_OCCURRENCES == 60


def test_occurrences_clamps_minimum_to_one() -> None:
    assert occurrences("monthly", 0) == 1
    assert occurrences("monthly", -5) == 1
