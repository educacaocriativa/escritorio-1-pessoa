"""Varredura de órfãos no object storage S3 (Story 6.1).

Encontra e (opcionalmente) remove objetos do storage S3-compatível que NÃO têm mais referência
viva no banco — lixo acumulado (uploads abortados, anexos de registros já excluídos) — SEM risco
de apagar arquivo em uso. Espelho de leitura/limpeza do backfill `migrate_attachments_to_s3`
(Story 3.5). Reusa estritamente `app.core.storage` (nenhuma chamada direta a `boto3` aqui).

Uso (dentro do container `api`, DEPOIS de configurar as envs S3):

    # Dry-run (PADRÃO — só relata, não apaga nada):
    docker compose exec api python -m app.scripts.scan_orphan_storage
    docker compose exec api python -m app.scripts.scan_orphan_storage --older-than 30

    # Remoção REAL (opt-in explícito):
    docker compose exec api python -m app.scripts.scan_orphan_storage --apply

SEGURANÇA: dry-run é o PADRÃO, não uma opção; `--apply` é opt-in explícito. `--older-than N`
(default 7, exige N > 0) só considera objetos com mais de N dias — não toca em uploads recentes
que possam estar em voo. Sem `S3_BUCKET` configurado, a rotina é um NO-OP informativo e retorna 0
(não há órfão possível fora do S3 quando tudo vive no Postgres via fallback) — diferente do
`migrate_attachments_to_s3`, que retorna 1 sem bucket (backfill sem destino não faz sentido).

────────────────────────────────────────────────────────────────────────────────────────────────
LEVANTAMENTO DE TABELAS QUE REFERENCIAM STORAGE (Story 6.1, Task 1 — MANTER ATUALIZADO):

Verificado no código (`app/modules/attachments/models.py`). Existem HOJE duas tabelas com bytes
de storage, e apenas UMA usa o S3:

  1. `Attachment` (RLS, por-tenant) — coluna `storage_key` (nullable). É a ÚNICA tabela cujos
     bytes podem viver no object storage S3. O conjunto de `storage_key` NÃO-nulos por tenant é
     a definição de "objeto vivo/referenciado" desta varredura.

  2. `PublicImage` (GLOBAL, sem RLS — logo/fotos de proposta/carrossel/site) — coluna
     `data: Mapped[bytes]` NÃO-nullable e SEM coluna `storage_key`. CONSTATAÇÃO: hoje ela grava
     os bytes SÓ no Postgres, NÃO usa o S3. Logo, não pode nem POSSUIR nem REFERENCIAR um objeto
     no bucket — cruzá-la aqui seria uma verificação inútil. Documentado (Task 1) em vez de
     assumir silenciosamente.

⚠️ REGRA (Story 6.1, Technical Constraints): se QUALQUER módulo novo passar a gravar em
`core/storage.py` (ganhar uma coluna tipo `storage_key`), esta lista E `_live_storage_keys()`
DEVEM ser atualizados — senão a varredura desatualiza em silêncio e pode marcar como órfão um
objeto ainda em uso (falso positivo destrutivo).
────────────────────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select

from app.core import storage
from app.db.session import get_db, tenant_session
from app.modules.attachments.models import Attachment
from app.modules.auth.models import Tenant

logger = logging.getLogger("e1p.scan_orphan_storage")

# Prefixo dos objetos de anexo de um tenant (mesmo do `storage.build_key`): isola a listagem por
# tenant no próprio path (IV2), em complemento à RLS do metadado.
ATTACHMENTS_PREFIX = "tenants/{tenant_id}/attachments/"

DEFAULT_OLDER_THAN_DAYS = 7


class OrphanCandidate(NamedTuple):
    tenant_id: str
    key: str
    last_modified: datetime


def _list_tenant_ids() -> list[str]:
    """Lista todos os tenant_ids (tabela global `tenants`, sem RLS) — igual ao backfill irmão."""
    gen = get_db()
    db = next(gen)
    try:
        return list(db.scalars(select(Tenant.id)))
    finally:
        gen.close()


def _live_storage_keys(tenant_id: str) -> set[str]:
    """Conjunto de `storage_key` VIVOS de um tenant (RLS ativa via `tenant_session` — IV2).

    Fonte única HOJE: `Attachment.storage_key` não-nulo. Ver o levantamento de tabelas no topo
    do módulo — se outra tabela passar a usar o S3, some as chaves dela aqui.
    """
    with tenant_session(tenant_id) as db:
        stmt = select(Attachment.storage_key).where(Attachment.storage_key.isnot(None))
        return {k for k in db.scalars(stmt) if k}


def find_orphans(older_than_days: int) -> list[OrphanCandidate]:
    """Cruza os objetos do bucket contra os `storage_key` vivos, por tenant.

    Para cada tenant: lista os objetos sob `tenants/{id}/attachments/` e marca como órfão todo
    objeto (a) sem `storage_key` vivo correspondente E (b) com mais de `older_than_days` dias.
    O escopo por prefixo garante que o scan de um tenant nunca avalia objeto de outro (IV2).
    """
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    orphans: list[OrphanCandidate] = []
    for tenant_id in _list_tenant_ids():
        live = _live_storage_keys(tenant_id)
        prefix = ATTACHMENTS_PREFIX.format(tenant_id=tenant_id)
        for obj in storage.list_objects(prefix):
            if obj.key in live:
                continue  # referenciado por anexo vivo — NUNCA é órfão (IV1)
            if obj.last_modified >= cutoff:
                continue  # recente demais — pode estar em voo (AC2)
            orphans.append(
                OrphanCandidate(tenant_id=tenant_id, key=obj.key, last_modified=obj.last_modified)
            )
    return orphans


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    def _positive_int(raw: str) -> int:
        try:
            val = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("--older-than deve ser um inteiro") from exc
        if val <= 0:
            raise argparse.ArgumentTypeError("--older-than deve ser > 0")
        return val

    parser = argparse.ArgumentParser(
        prog="scan_orphan_storage",
        description="Varre e (com --apply) remove objetos órfãos do object storage.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Remove de fato os órfãos confirmados. Sem esta flag = dry-run (só relata).",
    )
    parser.add_argument(
        "--older-than",
        type=_positive_int,
        default=DEFAULT_OLDER_THAN_DAYS,
        metavar="DIAS",
        help=f"Só considera objetos com mais de N dias (default {DEFAULT_OLDER_THAN_DAYS}, > 0).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not storage.is_configured():
        # NO-OP informativo: sem bucket, tudo vive no Postgres (fallback) — não há órfão de S3.
        print(
            "S3_BUCKET não configurado — storage roda em fallback Postgres; não há objeto no "
            "bucket para varrer. Nada a fazer."
        )
        return 0

    orphans = find_orphans(args.older_than)

    if not orphans:
        print(f"Nenhum órfão encontrado (idade > {args.older_than} dia(s)).")
        return 0

    mode = "APLICANDO remoção" if args.apply else "DRY-RUN (nada será removido)"
    print(
        f"{len(orphans)} objeto(s) órfão(s) encontrado(s) [{mode}], "
        f"idade > {args.older_than} dia(s):"
    )
    for cand in orphans:
        print(f"  [{cand.tenant_id}] {cand.key} (modificado em {cand.last_modified.isoformat()})")

    if not args.apply:
        print("Dry-run: nada foi removido. Rode com --apply para remover de fato.")
        return 0

    removed = 0
    for cand in orphans:
        try:
            storage.delete_object(cand.key)
            removed += 1
            print(f"  removido: {cand.key}")
        except Exception:  # noqa: BLE001 — fail-safe: uma remoção que falha não derruba o resto
            logger.exception("[scan_orphan_storage] falha ao remover objeto %s", cand.key)
    print(f"Remoção concluída: {removed}/{len(orphans)} órfão(s) removido(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
