"""Quando perguntar — a Regra do Silêncio do V1 aplicada a perguntar em vez de a avisar.

Duas regras, e nenhuma delas é sobre CONTEÚDO:

1. **Uma pergunta por gancho por dia, no produto inteiro.** Não uma por tela: uma. Um produto
   que interroga em três telas diferentes na mesma sessão é ignorado na quarta.
2. **Pulada fica 7 dias em quarentena.** Nunca some — continua no `/config` —, mas para de ser
   empurrada. Sem quarentena, um "depois" acidental vira interrogatório; com quarentena
   infinita, um toque errado perde a pergunta para sempre.

**O núcleo é a exceção declarada** e não passa pela regra 1: é uma sequência anunciada, com fim
visível, que a pessoa entrou sabendo que ia atravessar. Interrupção não anunciada e sequência
anunciada não cansam igual — o que cansa é a primeira.

⚠️ **Módulo PURO.** `hoje` e `fuso` entram por parâmetro, sempre. Quem os deriva é o router, com
`hoje_do_tenant(db)` e `tenant_timezone(db)`. Um default que lesse o relógio aqui é exatamente
por onde o dono no Acre passa a ser interrogado duas vezes no mesmo dia — e a regressão passaria
meses despercebida, porque em São Paulo funciona.

⚠️ **`fuso` não é decoração.** `answered_at` é `timestamptz`, e `.date()` nele devolve a data em
UTC. Um dono em UTC−3 respondendo às 22h produz carimbo de 01h do dia SEGUINTE em UTC: comparado
cru com `hoje`, a cota do dia não é reconhecida e ele é perguntado de novo na mesma noite. Por
isso a data do carimbo passa por `local_date` — a mesma porta que `hoje_do_tenant` usa.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.tz import local_date
from app.modules.dna import catalog, service

QUARENTENA_DIAS = 7
GANCHO_NUCLEO = "nucleo"


def pendente(
    db: Session, *, gancho: str, hoje: date, fuso: str | None = None
) -> catalog.Pergunta | None:
    """A pergunta a fazer neste gancho hoje, ou `None` se for dia de silêncio."""
    if gancho == GANCHO_NUCLEO:
        faltando = faltantes(db, gancho=GANCHO_NUCLEO)
        return faltando[0] if faltando else None

    registro = service.linhas(db)

    # Regra 1: qualquer registro de hoje já gastou a cota do dia.
    if any(_dia(linha.answered_at, fuso) == hoje for linha in registro.values()):
        return None

    for pergunta in catalog.PERGUNTAS:
        if pergunta.gancho != gancho:
            continue
        linha = registro.get(pergunta.key)
        if linha is None:
            return pergunta
        if (
            linha.value is None
            and (hoje - _dia(linha.answered_at, fuso)).days >= QUARENTENA_DIAS
        ):
            return pergunta  # saiu da quarentena
    return None


def faltantes(db: Session, *, gancho: str) -> list[catalog.Pergunta]:
    """As perguntas do gancho ainda sem RESPOSTA — puladas contam como faltantes.

    Sem cadência: é o que a tela do núcleo e a aba de `/config` usam, onde a pessoa escolheu
    estar e a interrupção não existe.
    """
    respondidas = set(service.respostas(db))
    if gancho == GANCHO_NUCLEO:
        return [catalog.POR_KEY[key] for key in catalog.NUCLEO if key not in respondidas]
    return [p for p in catalog.PERGUNTAS if p.gancho == gancho and p.key not in respondidas]


def _dia(quando: datetime, fuso: str | None) -> date:
    """A data do carimbo NO FUSO DO DONO. Não deriva 'hoje' — lê o dia de um instante dado."""
    return local_date(quando, fuso)
