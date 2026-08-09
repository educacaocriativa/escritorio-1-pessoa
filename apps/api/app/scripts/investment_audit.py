"""Confere o principal das aplicações: o que a coluna congelada diz × o que os movimentos dizem.

    docker compose exec api python -m app.scripts.investment_audit

**Não existe `--fix`, e a ausência é a decisão.** A Onda 2b-ii substituiu o backfill do design-mãe
§6.2 — o único `UPDATE` sobre dado existente do épico, exposto à armadilha do `FORCE ROW LEVEL
SECURITY` (o `UPDATE` filtrado a zero linhas **em silêncio**, que o SQLite dos testes não pega) —
por *auditoria + ato do dono*. Uma flag de correção reintroduziria exatamente o que a onda existe
para não fazer, e alguém a rodaria no deploy sem ler a saída.

O que fazer com uma divergência: **o dono corrige por ato na tela** — declarando o saldo de abertura
da conta de aplicação, ou registrando o aporte que faltou como transferência. É o mesmo mecanismo
pelo qual a Onda 2b-i vinculou a aplicação legada, já validado em campo.

⚠️ **Isolamento:** itera a tabela GLOBAL `tenants` e abre `tenant_session` por tenant (RLS fixada),
mesmo padrão de `merge_duplicate_clients` e `migrate_attachments_to_s3`. Uma consulta em tabela com
RLS **sem** tenant devolve zero linhas **sem erro** — foi assim que a sondagem de `phone_key` em
produção quase virou um "está tudo limpo" falso. Por isso a saída imprime **quantos tenants foram
varridos**: `0 aplicações em 0 tenants` e `0 aplicações em 7 tenants` são resultados diferentes, e o
primeiro é um defeito deste script, não um banco limpo.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db, tenant_session
from app.modules.auth.models import Tenant
from app.modules.investments import service as inv_service

logger = logging.getLogger("e1p.investment_audit")


def auditar(db: Session) -> list[dict]:
    """Uma linha por aplicação do tenant da sessão. **Só lê.**

    `coluna_cents` lê `principal_cents` de propósito — é o único lugar do repositório autorizado a
    fazê-lo, e é por isso que este arquivo vive em `app/scripts/` e não em `app/modules/`: o gate
    `test_investments_principal_gate.py` varre só os módulos.
    """
    contas = inv_service.list_accounts(db)
    derivados = inv_service.principais_derivados(db, contas)
    linhas: list[dict] = []
    for a in contas:
        derivado = derivados[a.id]
        linhas.append(
            {
                "id": a.id,
                "name": a.name,
                "coluna_cents": a.principal_cents,
                "derivado_cents": derivado,
                # `None` (inafirmável) NÃO é divergência: é ausência de comparação. Tratá-lo como
                # divergente mandaria o dono caçar um erro que não existe — o modo de falha que o
                # épico chama de "pior do que ficar calado".
                "diverge": derivado is not None and derivado != a.principal_cents,
            }
        )
    return linhas


def _tenant_ids() -> list[str]:
    gen = get_db()
    db = next(gen)
    try:
        return [t.id for t in db.scalars(select(Tenant)).all()]
    finally:
        gen.close()


def _reais(cents: int | None) -> str:
    if cents is None:
        return "não sei"
    inteiro, centavos = divmod(abs(cents), 100)
    sinal = "-" if cents < 0 else ""
    return f"{sinal}R$ {inteiro:,}".replace(",", ".") + f",{centavos:02d}"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("=== Auditoria do principal das aplicações (Onda 2b-ii) — SÓ LEITURA ===")

    tenants = _tenant_ids()
    total = divergentes = 0
    for tenant_id in tenants:
        with tenant_session(tenant_id) as db:
            for linha in auditar(db):
                total += 1
                if not linha["diverge"]:
                    continue
                divergentes += 1
                logger.info("")
                logger.info("  %s (tenant %s)", linha["name"], tenant_id)
                logger.info("    principal na coluna : %s", _reais(linha["coluna_cents"]))
                logger.info("    principal calculado : %s", _reais(linha["derivado_cents"]))
                logger.info(
                    "    -> declare o saldo de abertura da conta de aplicação, ou registre o "
                    "aporte que faltou como transferência"
                )

    logger.info("")
    logger.info(
        "%d aplicação(ões) em %d tenant(s); %d com divergência.", total, len(tenants), divergentes
    )
    if not tenants:
        logger.warning(
            "NENHUM tenant varrido — isto é um defeito deste script, não um banco limpo."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
