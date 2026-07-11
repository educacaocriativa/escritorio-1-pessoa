"""Fuso horário por tenant — helper reutilizável pela Agenda e pelo Cockpit.

Toda data de negócio que vira evento de dia-inteiro (`all_day`) ou janela do dia precisa ser
ancorada na meia-noite REAL do fuso do tenant, convertida para UTC — não na meia-noite UTC crua
(ver a dívida de fuso registrada no CLAUDE.md §6.1 e a lição do bug de fuso da Agenda em §6.0).

`zoneinfo` é stdlib (Python 3.9+), mas depende de uma base IANA no SO. A imagem `python:3.13-slim`
e o ambiente de dev Windows não trazem essa base — por isso o pacote pip `tzdata` (puro-Python) é
dependência OBRIGATÓRIA (ver requirements.txt). Ainda assim, `tenant_zone` é fail-safe: um nome de
fuso inválido/corrompido nunca derruba a request, cai para o default.
"""
from __future__ import annotations

import zoneinfo
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TENANT_TIMEZONE = "America/Sao_Paulo"


def tenant_zone(tz_name: str | None) -> ZoneInfo:
    """Resolve o `ZoneInfo` do tenant, com fallback fail-safe para o fuso padrão.

    Um `tz_name` vazio/None ou um nome desconhecido (ex.: base IANA ausente ou valor corrompido
    no banco) NUNCA lança — cai para `DEFAULT_TENANT_TIMEZONE`. Se nem o default resolver (base
    IANA totalmente indisponível), aí sim propaga o erro (é um problema de infra, não de dado).
    """
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except zoneinfo.ZoneInfoNotFoundError:
            pass
    return ZoneInfo(DEFAULT_TENANT_TIMEZONE)


def day_window_utc(day: date, tz_name: str | None) -> tuple[datetime, datetime]:
    """Janela `[início, fim)` em UTC do dia-calendário `day` NO FUSO do tenant.

    Retorna a meia-noite local de `day` e a meia-noite local do dia seguinte, ambas convertidas
    para UTC. Para `America/Sao_Paulo` (UTC-3) o dia D vira `[D 03:00Z, D+1 03:00Z)`.
    """
    zone = tenant_zone(tz_name)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
