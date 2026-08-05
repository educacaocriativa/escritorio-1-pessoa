"""Mescla os contatos duplicados que já existiam antes da PR #76 (`absorb_lead`).

    docker compose exec api python -m app.scripts.merge_duplicate_clients            # dry-run
    docker compose exec api python -m app.scripts.merge_duplicate_clients --apply    # executa

**Dry-run é o padrão, de propósito.** A mescla apaga linhas e não tem desfazer: `--apply` só
depois de ler a lista. O mesmo comando roda quantas vezes for preciso — na segunda passada não
há mais grupo e ele termina em silêncio.

Só agrupa cards com **mesmo telefone normalizado E mesmo nome**. `phone_key` sozinho não serve
como critério: ele não é único de propósito (marido e mulher compartilham telefone, ver
`crm/service._find_existing`), e juntar duas pessoas num card é pior que o duplicado.

Isolamento de tenant: itera a tabela GLOBAL `tenants` e abre `tenant_session` por tenant (RLS
fixada), mesmo padrão de `migrate_attachments_to_s3`. Nunca cruza dados entre tenants.
"""
from __future__ import annotations

import logging
import sys

from sqlalchemy import select

from app.db.session import get_db, tenant_session
from app.modules.auth.models import Tenant
from app.modules.crm import merge

logger = logging.getLogger("e1p.merge_duplicate_clients")


def _list_tenant_ids() -> list[str]:
    gen = get_db()
    db = next(gen)
    try:
        return [t.id for t in db.scalars(select(Tenant)).all()]
    finally:
        gen.close()


def main(apply: bool) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    modo = "APLICANDO" if apply else "DRY-RUN (nada será alterado)"
    logger.info("=== Mescla de contatos duplicados — %s ===", modo)

    total_grupos = total_absorvidos = 0
    for tenant_id in _list_tenant_ids():
        with tenant_session(tenant_id) as db:
            grupos = merge.find_duplicate_groups(db)
            if not grupos:
                continue
            logger.info("\ntenant %s — %d grupo(s):", tenant_id, len(grupos))
            for grupo in grupos:
                total_grupos += 1
                total_absorvidos += len(grupo.absorvidos)
                logger.info(
                    "  %s (%s) — fica %s [%s, criado %s], absorve %d:",
                    grupo.nome, grupo.phone_key, grupo.sobrevivente.id[:8],
                    grupo.sobrevivente.source, grupo.sobrevivente.created_at,
                    len(grupo.absorvidos),
                )
                for absorvido in grupo.absorvidos:
                    logger.info(
                        "      %s [%s, criado %s]",
                        absorvido.id[:8], absorvido.source, absorvido.created_at,
                    )
                if apply:
                    resultado = merge.merge_clients(
                        db, tenant_id=tenant_id, actor="script:merge_duplicate_clients",
                        survivor_id=grupo.sobrevivente.id,
                        absorbed_ids=[c.id for c in grupo.absorvidos],
                    )
                    db.commit()
                    movidos = resultado["movidos"]
                    logger.info(
                        "      -> movido: %s",
                        ", ".join(f"{t}={n}" for t, n in sorted(movidos.items())) or "nada",
                    )

    if total_grupos == 0:
        logger.info("\nNenhum duplicado encontrado.")
    elif apply:
        logger.info("\n%d grupo(s), %d card(s) absorvido(s).", total_grupos, total_absorvidos)
    else:
        logger.info(
            "\n%d grupo(s), %d card(s) seriam absorvidos. Rode com --apply para executar.",
            total_grupos, total_absorvidos,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
