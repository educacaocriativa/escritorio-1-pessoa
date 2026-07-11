"""Worker durável: dispara o `tick` do funil e processa a fila de notificações (Story 4.3).

Processo STANDALONE (fora da API HTTP), no mesmo espírito de `app.seed` — roda via
`python -m app.worker`. Resolve a dívida registrada em `funnels/engine.py` ("um cron ou a tela
chama o tick periodicamente — não há worker em background ainda") e em `core/events.py`
("integrações que precisam durar além da request devem ir para a fila quando o worker existir"):

- **Tick do funil:** retoma esperas vencidas periodicamente, sem depender de clique manual na tela
  nem do endpoint `POST /funnels/runs/tick` (que continua existindo — IV1).
- **Fila de notificações:** entrega os envios enfileirados (status="pending") fora do
  request/response HTTP, para que uma falha de envio não derrube a request de origem (IV2).

Idempotente por construção: `engine.tick` só toca runs `waiting` com `resume_at` vencido, e
`process_pending` só toca notificações `pending` — rodar um sweep sem nada pendente é um no-op.
RLS respeitada: cada tenant é processado dentro de `tenant_session(tenant_id)`; só a listagem de
tenants (tabela global `tenants`) usa uma sessão sem tenant.

Concorrência: assume UMA única réplica do container `worker` (sem lock distribuído). Escalar para
múltiplas réplicas exigiria `FOR UPDATE SKIP LOCKED` no `process_pending` — dívida futura.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal, tenant_session
from app.modules.auth.models import Tenant
from app.modules.funnels import engine as funnels_engine
from app.modules.notifications import service as notifications_service
from app.seed import PLATFORM_SLUG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("e1p.worker")


def _tenant_ids(db: Session) -> list[str]:
    """IDs de todos os tenants REAIS (exclui a plataforma interna). `tenants` é tabela global."""
    return list(db.scalars(select(Tenant.id).where(Tenant.slug != PLATFORM_SLUG)).all())


def run_sweep(
    *,
    session_factory=SessionLocal,
    tenant_session_factory=tenant_session,
    actor: str = "system:worker",
    now: datetime | None = None,
) -> dict:
    """Executa UM sweep: para cada tenant real, roda o tick do funil e processa a fila.

    Injeção de dependência por parâmetro (mesmo idioma de `get_tenant_session_factory` +
    `conftest.py::_override_factory`): os testes passam factories apontando à sessão SQLite
    compartilhada, sem depender de Postgres real.

    Uma falha em um tenant (ou numa das duas etapas) é logada e NÃO trava o sweep dos demais
    (IV2) — o erro é acumulado na chave `errors` do resultado. Tick e fila abrem sessões
    SEPARADAS por tenant, para que uma falha na primeira não impeça a segunda.
    """
    result = {
        "tenants_checked": 0,
        "funnel_resumed": 0,
        "notifications_processed": 0,
        "errors": [],
    }

    with session_factory() as db:
        tenant_ids = _tenant_ids(db)

    result["tenants_checked"] = len(tenant_ids)

    for tenant_id in tenant_ids:
        # Etapa 1 — tick do funil (sessão própria).
        try:
            with tenant_session_factory(tenant_id) as db:
                tick_result = funnels_engine.tick(
                    db, tenant_id=tenant_id, actor=actor, now=now
                )
            result["funnel_resumed"] += tick_result.get("resumed", 0)
        except Exception as exc:  # noqa: BLE001 — uma falha de tenant não trava o sweep (IV2)
            logger.exception("[worker] tick falhou tenant=%s", tenant_id)
            result["errors"].append({"tenant_id": tenant_id, "stage": "tick", "error": str(exc)})

        # Etapa 2 — fila de notificações (sessão SEPARADA da etapa 1).
        try:
            with tenant_session_factory(tenant_id) as db:
                processed = notifications_service.process_pending(db, tenant_id=tenant_id)
            result["notifications_processed"] += processed
        except Exception as exc:  # noqa: BLE001 — idem: isola a falha por tenant (IV2)
            logger.exception("[worker] fila falhou tenant=%s", tenant_id)
            result["errors"].append(
                {"tenant_id": tenant_id, "stage": "notifications", "error": str(exc)}
            )

    logger.info(
        "[worker] sweep: tenants=%s funil_resumido=%s notificacoes=%s erros=%s",
        result["tenants_checked"],
        result["funnel_resumed"],
        result["notifications_processed"],
        len(result["errors"]),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker durável do e1p (tick do funil + fila).")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Roda um único sweep e sai (útil para cron externo / smoke test).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=settings.worker_tick_interval_seconds,
        help="Segundos entre sweeps no modo loop (default: worker_tick_interval_seconds).",
    )
    args = parser.parse_args()

    if args.once:
        run_sweep()
        return

    logger.info("[worker] iniciando loop (intervalo=%ss)", args.interval)
    while True:
        try:
            run_sweep()
        except Exception:  # noqa: BLE001 — o loop nunca morre por causa de um sweep isolado
            logger.exception("[worker] sweep lançou; continuando o loop")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
