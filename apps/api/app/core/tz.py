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


def _aware(instant: datetime) -> datetime:
    """Garante um datetime *aware*, assumindo UTC quando vier naive.

    Não é paranoia: o SQLite dos testes devolve naive mesmo para uma coluna `timezone=True`
    (a mesma coerção já existia solta em `notifications/service.py`). Um `astimezone()` sobre
    naive usaria o fuso do SISTEMA — em um servidor UTC passaria despercebido e em uma máquina
    de dev no Brasil daria 3h de diferença. Aqui a convenção é explícita: naive == UTC.
    """
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)


def local_date(instant: datetime, tz_name: str | None) -> date:
    """A data de calendário de `instant` NO FUSO do tenant.

    É a primitiva de que "hoje" depende. Para `America/Sao_Paulo` (UTC−3), `2026-08-06T01:30Z`
    é `05/08` — a noite do dia 5, não o dia 6.
    """
    return _aware(instant).astimezone(tenant_zone(tz_name)).date()


def tenant_today(tz_name: str | None, *, now: datetime | None = None) -> date:
    """"Hoje" no fuso do tenant — a âncora que substitui `datetime.now(UTC).date()`.

    `now` é injetável **de propósito**, pelo mesmo motivo de `core/scheduling.status_por_data`:
    uma regra presa ao relógio da máquina não é testável. O default lê o relógio uma vez só.
    """
    return local_date(now if now is not None else datetime.now(UTC), tz_name)


def format_datetime_br(instant: datetime, tz_name: str | None) -> str:
    """`dd/mm/aaaa hh:mm` no fuso do tenant — para TEXTO QUE UM HUMANO LÊ.

    Existe porque `isoformat()` em mensagem de usuário é bug, não estilo: foi assim que a linha
    do tempo do Funil passou a exibir `Aguardando até 2026-08-05T11:11:32.812731+00:00`.
    Para persistir/trafegar (campo `at`, JSON de API) continue usando `isoformat()` em UTC —
    a conversão para o fuso é da BORDA de apresentação, nunca do armazenamento.
    """
    return _aware(instant).astimezone(tenant_zone(tz_name)).strftime("%d/%m/%Y %H:%M")


def format_date_br(day: date) -> str:
    """`dd/mm/aaaa` — data de calendário já é local por definição, não tem fuso a converter."""
    return day.strftime("%d/%m/%Y")


def day_window_utc(day: date, tz_name: str | None) -> tuple[datetime, datetime]:
    """Janela `[início, fim)` em UTC do dia-calendário `day` NO FUSO do tenant.

    Retorna a meia-noite local de `day` e a meia-noite local do dia seguinte, ambas convertidas
    para UTC. Para `America/Sao_Paulo` (UTC-3) o dia D vira `[D 03:00Z, D+1 03:00Z)`.
    """
    zone = tenant_zone(tz_name)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
