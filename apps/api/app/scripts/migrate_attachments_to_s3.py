"""Backfill: move os bytes dos Anexos legados (Postgres) para o object storage S3 (Story 3.5).

Executar dentro do container `api` DEPOIS de configurar as envs S3 (S3_BUCKET + credenciais):

    docker compose exec api python -m app.scripts.migrate_attachments_to_s3

Para cada tenant, seleciona os anexos com bytes no Postgres e sem chave de storage
(`storage_key IS NULL AND data IS NOT NULL`), sobe cada um para o bucket e zera o `data`.
IDEMPOTENTE: rodar de novo NÃO reprocessa linhas já migradas (o filtro exclui `storage_key`
já setado). Commit por lote (BATCH_SIZE) para não segurar uma transação gigante.

Isolamento de tenant: itera a tabela GLOBAL `tenants` via `get_db()` e, para cada tenant, abre
`tenant_session(tenant_id)` (RLS fixada) — nunca cruza dados entre tenants.
"""
from __future__ import annotations

import logging
import sys

from sqlalchemy import select

from app.core import storage
from app.db.session import get_db, tenant_session
from app.modules.attachments.models import Attachment
from app.modules.auth.models import Tenant

logger = logging.getLogger("e1p.migrate_attachments")

BATCH_SIZE = 50


def _list_tenant_ids() -> list[str]:
    """Lista todos os tenant_ids (tabela global `tenants`, sem RLS)."""
    gen = get_db()
    db = next(gen)
    try:
        return list(db.scalars(select(Tenant.id)))
    finally:
        gen.close()


def migrate_tenant(tenant_id: str) -> int:
    """Migra os anexos legados de um tenant. Retorna quantos foram movidos."""
    moved = 0
    with tenant_session(tenant_id) as db:
        stmt = select(Attachment).where(
            Attachment.storage_key.is_(None), Attachment.data.isnot(None)
        )
        pending = list(db.scalars(stmt))
        for i, att in enumerate(pending, start=1):
            key = storage.build_key(tenant_id, att.id, att.filename)
            storage.put_object(key, att.data or b"", att.content_type)
            att.storage_key = key
            att.data = None
            moved += 1
            if i % BATCH_SIZE == 0:
                db.commit()
        db.commit()
    return moved


def main() -> int:
    if not storage.is_configured():
        print(
            "S3_BUCKET não configurado — configure as envs S3 (S3_BUCKET + credenciais) antes "
            "de rodar o backfill.",
            file=sys.stderr,
        )
        return 1

    tenant_ids = _list_tenant_ids()
    total = 0
    for tid in tenant_ids:
        n = migrate_tenant(tid)
        total += n
        if n:
            print(f"tenant {tid}: {n} anexo(s) migrado(s) para o S3")
    print(f"Backfill concluído: {total} anexo(s) migrado(s) em {len(tenant_ids)} tenant(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
