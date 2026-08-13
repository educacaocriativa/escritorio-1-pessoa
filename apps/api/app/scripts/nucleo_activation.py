"""Lê o rastro de ativação do núcleo do DNA: quem abriu, quanto respondeu, quem abandonou.

    docker compose exec api python -m app.scripts.nucleo_activation

**Não existe `--fix`, e a ausência é a decisão** — a mesma de `investment_audit.py`: com uma flag
de correção, alguém a roda no deploy sem ler a saída. Aqui não haveria sequer o que corrigir: o
rastro é evidência, e "corrigir" evidência é reescrever história.

**Instrumentar, não analisar.** Este script não decide nada, não tem limiar e não diz quantos
tenants bastam. A spec recusou escrever um "leia quando houver 20 tenants" porque seria número sem
evidência (Artigo IV) — a decisão de ler é do fundador. Enquanto a contagem for 2, a resposta à
pergunta da dívida ("o núcleo ajudou ou atrapalhou?") vem de conversar com as duas pessoas reais;
o rastro existe para o dia em que isso deixar de ser verdade.

⚠️ **Isolamento — e por que este script NÃO roda sob `e1p_root`.** Ele itera a tabela GLOBAL
`tenants` (sem RLS) e abre `tenant_session` por tenant, exatamente como `investment_audit.py`,
`merge_duplicate_clients` e `migrate_attachments_to_s3`. O perigo é real e é outro: uma consulta a
tabela com RLS por uma sessão **sem** tenant devolve zero linhas **sem erro** — foi assim que a
sondagem de `phone_key` em produção quase virou um "está tudo limpo" falso. As duas saídas para
isso são o papel que faz bypass **ou** a GUC fixada por tenant, e elas se EXCLUEM: sob `e1p_root`
a policy não se aplica, e como nenhuma query deste repositório filtra tenant à mão (Regra de Ouro
nº 1) cada tenant reportaria os eventos de todos os outros. Se algum dia este script precisar do
papel de bypass, ele precisa ganhar `WHERE tenant_id` explícito no mesmo commit.

Por isso a saída imprime **quantos tenants foram varridos**: `0 passagens em 0 tenants` e
`0 passagens em 7 tenants` são resultados diferentes, e o primeiro é um defeito deste script, não
um produto que ninguém usou.

⚠️ **Fuso:** todo horário sai por `format_datetime_br` no fuso do tenant. Um `open` às 22h em
UTC−3 é 01h do dia seguinte em UTC, e um relatório de ativação que trocasse o dia estaria medindo
outra coisa.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.core.tz import format_datetime_br
from app.db.session import get_db, tenant_session
from app.modules.auth.models import Tenant
from app.modules.dna import eventos
from app.modules.settings.service import tenant_timezone

logger = logging.getLogger("e1p.nucleo_activation")


@dataclass(frozen=True)
class Passagem:
    """Uma passagem pelo núcleo: de um `open` até o `abandon` (ou até o fim do rastro).

    `exibidas` é o denominador VISTO, lido do `target` do `open` — não é `len(catalog.NUCLEO)`.
    `faltantes` devolve só as não respondidas, então na segunda visita a pessoa vê 4 e não 6; e
    `catalog.NUCLEO` pode crescer, o que viraria todo "k de 6" histórico em "k de 7"
    retroativamente. O progresso (`respondidas`/`puladas`) é DERIVADO dos eventos, e nada de
    derivado é guardado — mesmo princípio de `last_interaction_at` nunca ser coluna.
    """

    abertura: datetime
    exibidas: int
    respondidas: int = 0
    puladas: int = 0
    fim: datetime | None = None

    @property
    def abandonou(self) -> bool:
        return self.fim is not None


def entradas_do_dna(db: Session) -> list[AuditEntry]:
    """Toda a trilha do DNA do tenant da sessão, em ordem.

    ⚠️ O desempate por `id` entrega **estabilidade**, não cronologia: `created_at` tem
    `server_default=func.now()`, que no Postgres é o timestamp da TRANSAÇÃO. Cada evento do DNA
    nasce numa request própria, então na prática os carimbos são distintos — mas dentro do mesmo
    instante não existe "mais novo", e uma ordem arbitrária que MUDA entre duas chamadas idênticas
    seria pior (a lição do histórico de saques da Onda 3).
    """
    return list(
        db.scalars(
            select(AuditEntry)
            .where(AuditEntry.action.startswith(eventos.PREFIXO))
            .order_by(AuditEntry.created_at, AuditEntry.id)
        ).all()
    )


def _origem(entrada: AuditEntry) -> str:
    """A porta de entrada da resposta, lida do `target` (`<source>:<pergunta>`)."""
    return entrada.target.split(":", 1)[0]


def _com(p: Passagem, **campos) -> Passagem:
    """`Passagem` é frozen de propósito: a evidência não é editada no meio da varredura."""
    return Passagem(
        abertura=campos.get("abertura", p.abertura),
        exibidas=campos.get("exibidas", p.exibidas),
        respondidas=campos.get("respondidas", p.respondidas),
        puladas=campos.get("puladas", p.puladas),
        fim=campos.get("fim", p.fim),
    )


def derivar(entradas: Sequence[AuditEntry]) -> list[Passagem]:
    """As passagens pelo núcleo. **Pura** — recebe já ordenado, não lê banco nem relógio.

    Resposta fora de uma passagem aberta é ignorada de propósito: gancho e `/config` acontecem o
    tempo todo, e contá-los inventaria passagem onde não houve abertura. É esse recorte que faz o
    `source` no `target` pagar a conta.
    """
    passagens: list[Passagem] = []
    aberta: Passagem | None = None

    for e in entradas:
        if e.action == eventos.ACTION_OPEN:
            if aberta is not None:
                passagens.append(aberta)
            aberta = Passagem(
                abertura=e.created_at, exibidas=int(e.target) if e.target.isdigit() else 0
            )
        elif e.action == eventos.ACTION_ABANDON:
            if aberta is not None:
                passagens.append(_com(aberta, fim=e.created_at))
                aberta = None
        elif aberta is not None and _origem(e) == "nucleo":
            if e.action == eventos.ACTION_SAVE:
                aberta = _com(aberta, respondidas=aberta.respondidas + 1)
            elif e.action == eventos.ACTION_SKIP:
                aberta = _com(aberta, puladas=aberta.puladas + 1)

    if aberta is not None:
        passagens.append(aberta)
    return passagens


def respostas_por_origem(entradas: Sequence[AuditEntry]) -> dict[str, int]:
    """Quantas respostas vieram de cada porta. **Pura.**

    A instrumentação NÃO é escopada só ao núcleo, e é isso que produz evidência sobre a quarentena
    de 7 dias e o "uma por dia" — a meia dívida da spec §0.1. Sai de graça: `responder`/`pular` já
    recebiam `source`.
    """
    contagem: dict[str, int] = {}
    for e in entradas:
        if e.action in (eventos.ACTION_SAVE, eventos.ACTION_SKIP):
            origem = _origem(e)
            contagem[origem] = contagem.get(origem, 0) + 1
    return contagem


def situacao_do_fim(p: Passagem, fuso: str | None) -> str:
    """Como a passagem terminou, **dita por extenso**. Pura.

    ⚠️ A primeira versão imprimia a data crua (`12/08/2026 08:47`) quando havia abandono, ao lado
    de `sem abandono registrado` quando não havia. Quem lesse o relatório meses depois não tinha
    como saber o que aquela data solta significava — só descobria comparando as duas linhas.
    **É a classe de erro que este projeto mais paga: o artefato cujo consumidor é um humano num
    ciclo futuro, e humano não levanta `TypeError`.** Achado no primeiro uso real em produção
    (2026-08-13), lendo a saída com o fundador.

    Existe como função separada por isso: é a única frase do script que um humano tem de
    interpretar, e agora ela tem consumidor mecânico.
    """
    if p.fim is None:
        return "sem abandono registrado"
    return f"abandonou em {format_datetime_br(p.fim, fuso)}"


def rodape(*, passagens: int, tenants: int, abandonos: int) -> str:
    return (
        f"{passagens} passagem(ns) pelo núcleo em {tenants} tenant(s); "
        f"{abandonos} abandonada(s)."
    )


def _tenants() -> list[tuple[str, str]]:
    """`(id, slug)` de todos os tenants. `tenants` é GLOBAL e não tem RLS."""
    gen = get_db()
    db = next(gen)
    try:
        return [(t.id, t.slug) for t in db.scalars(select(Tenant)).all()]
    finally:
        gen.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("=== Ativação do núcleo do DNA (Vima V2) — SÓ LEITURA ===")

    tenants = _tenants()
    total = abandonos = 0
    for tenant_id, slug in tenants:
        with tenant_session(tenant_id) as db:
            entradas = entradas_do_dna(db)
            if not entradas:
                continue
            fuso = tenant_timezone(db)
            passagens = derivar(entradas)
            total += len(passagens)
            abandonos += sum(1 for p in passagens if p.abandonou)

            logger.info("")
            logger.info("  %s (tenant %s) — fuso %s", slug, tenant_id, fuso)
            for n, p in enumerate(passagens, start=1):
                fim = situacao_do_fim(p, fuso)
                logger.info(
                    "    passagem %d: abriu %s com %d pergunta(s) à vista",
                    n,
                    format_datetime_br(p.abertura, fuso),
                    p.exibidas,
                )
                logger.info(
                    "      respondidas %d · puladas %d · %s", p.respondidas, p.puladas, fim
                )
            origens = respostas_por_origem(entradas)
            if origens:
                logger.info(
                    "    respostas por origem: %s",
                    " · ".join(f"{k} {v}" for k, v in sorted(origens.items())),
                )

    logger.info("")
    logger.info(rodape(passagens=total, tenants=len(tenants), abandonos=abandonos))
    if not tenants:
        logger.warning(
            "NENHUM tenant varrido — isto é um defeito deste script, não um produto sem uso."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
