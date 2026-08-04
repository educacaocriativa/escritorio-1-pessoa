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
from app.modules.payables import service as payables_service
from app.modules.receivables import service as receivables_service
from app.modules.whatsapp_inbox import service as whatsapp_inbox_service
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

    Uma falha em um tenant (ou numa das QUATRO etapas) é logada e NÃO trava o sweep dos demais
    (IV2) — o erro é acumulado na chave `errors` do resultado. Cada etapa abre sessão SEPARADA por
    tenant, para que uma falha numa não impeça as seguintes.

    ⚠️ **`now` é injetável e vale para TODAS as etapas.** A etapa 4 (Story 8.14) o converte para
    data de calendário e o repassa como `today`: um contador preso ao relógio da máquina não é
    testável, e um segundo relógio dentro do sweep faria as etapas discordarem sobre que dia é hoje.
    """
    result = {
        "tenants_checked": 0,
        "funnel_resumed": 0,
        "notifications_processed": 0,
        "whatsapp_media_processed": 0,
        # Story 8.14 + 8.15 — quantos lançamentos `scheduled` viraram `paid` porque o dia chegou.
        #
        # ⚠️ **É a SOMA dos dois lados do dinheiro (contas a pagar + cobranças), e a escolha é
        # deliberada** (a 8.15 deixou a decisão ao @dev, exigindo que ela ficasse registrada). O
        # contador responde a **uma** pergunta — *"quantos lançamentos com dia marcado tiveram o
        # dia chegado neste sweep?"* — e ela não se parte por módulo: são dois SELECTs da mesma
        # regra, na mesma etapa, na mesma sessão de tenant. Dois contadores nomeados dariam três
        # números para uma informação (os dois mais a soma, que qualquer leitor faria de cabeça) e
        # quebrariam os consumidores existentes deste dicionário sem nada em troca — este número é
        # observabilidade de sweep, não número de dinheiro. Quem precisar da separação a tem na
        # trilha de auditoria (`payable.scheduled_promoted` × `receivable.scheduled_promoted`),
        # que é o lugar onde a granularidade tem consumidor real.
        "scheduled_promoted": 0,
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

        # Etapa 3 — mídia pendente do inbox de WhatsApp (sessão SEPARADA das outras duas).
        try:
            with tenant_session_factory(tenant_id) as db:
                media_processed = whatsapp_inbox_service.process_pending_media(
                    db, tenant_id=tenant_id
                )
            result["whatsapp_media_processed"] += media_processed
        except Exception as exc:  # noqa: BLE001 — idem: isola a falha por tenant (IV2)
            logger.exception("[worker] mídia do whatsapp falhou tenant=%s", tenant_id)
            result["errors"].append(
                {"tenant_id": tenant_id, "stage": "whatsapp_media", "error": str(exc)}
            )

        # Etapa 4 — promoção `scheduled → paid` das contas a pagar cujo dia chegou (Story 8.14
        # AC10). Sessão SEPARADA das outras três, mesmo formato, mesmo isolamento de falha.
        #
        # ⚠️ **A CORRETUDE DOS NÚMEROS NÃO DEPENDE DESTA ETAPA — e isso é decisão de arquitetura,
        # não sorte.** O movimento bancário já nasceu com `posted_at` = a data agendada, e tanto o
        # saldo derivado quanto a Projeção de Caixa são função da **data**, não do status
        # materializado (ver `payables.service.promote_scheduled` e `projection._window_sums`). Com
        # o worker parado uma semana, nenhum número fica errado: só o rótulo "Agendada" da Fila e o
        # `scheduled_cents` do resumo ficam velhos. Quem for tentado a fazer alguma soma depender
        # daqui está prestes a transformar um enfeite em componente crítico.
        #
        # ⚠️ **[Story 8.15] A chamada de `receivables` entrou NESTA MESMA ETAPA**, não numa quinta:
        # é a mesma pergunta ("já chegou o dia?") sobre os dois lados do dinheiro, e uma etapa
        # própria seria a mesma regra em dois lugares — com dois isolamentos de falha, dois
        # contadores e duas chances de uma receber a próxima correção e a outra não. As duas
        # varreduras moram nos módulos que conhecem a regra (`payables`/`receivables`
        # `promote_scheduled`, mesma assinatura); o worker só **orquestra**.
        try:
            with tenant_session_factory(tenant_id) as db:
                hoje = now.date() if now else None
                promovidas = payables_service.promote_scheduled(
                    db, tenant_id=tenant_id, actor=actor, today=hoje
                )
                promovidas += receivables_service.promote_scheduled(
                    db, tenant_id=tenant_id, actor=actor, today=hoje
                )
            result["scheduled_promoted"] += promovidas
        except Exception as exc:  # noqa: BLE001 — idem: isola a falha por tenant (IV2)
            logger.exception("[worker] promoção de agendadas falhou tenant=%s", tenant_id)
            result["errors"].append(
                {"tenant_id": tenant_id, "stage": "scheduled_promote", "error": str(exc)}
            )

    logger.info(
        "[worker] sweep: tenants=%s funil_resumido=%s notificacoes=%s midia_whatsapp=%s "
        "agendadas_promovidas=%s erros=%s",
        result["tenants_checked"],
        result["funnel_resumed"],
        result["notifications_processed"],
        result["whatsapp_media_processed"],
        result["scheduled_promoted"],
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
