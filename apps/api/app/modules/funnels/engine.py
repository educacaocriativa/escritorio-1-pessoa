"""Motor de automação do funil: executa o grafo inteiro a partir de um gatilho.

Conceitos:
- **Inscrição (gatilho):** `enroll` coloca um contato no funil e dispara a jornada.
- **Runtime do grafo:** `_drive` anda pelos nós seguindo as arestas, executando a AÇÃO REAL de
  cada nó (reaproveita `service.run_node` — cria cliente/cobrança/proposta, envia mensagem...).
- **Espera:** o nó `esperar` pausa a jornada (status=waiting) até `resume_at`.
- **Agendador:** `tick` retoma as jornadas cujo `resume_at` já venceu. Um cron (ou a tela) chama
  o tick periodicamente — não há worker em background ainda (ver core/events.py).
- **Condicional (`se-ou`):** escolhe o ramo por uma condição simples (tem tag / pagou / sempre).

Idempotência/segurança: limite de passos por execução evita laço infinito; falha de ação marca
a jornada como `failed` com a mensagem, sem derrubar a request.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.crm.models import Client
from app.modules.funnels import service
from app.modules.funnels.models import (
    RUN_CANCELLED,
    RUN_DONE,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_WAITING,
    Funnel,
    FunnelRun,
)
from app.modules.receivables.models import Charge

MAX_STEPS_PER_DRIVE = 100  # guarda anti-ciclo: nº máx. de nós processados numa tacada
_UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}


def _now() -> datetime:
    return datetime.now(UTC)


# ── Leitura do grafo ────────────────────────────────────────────────────────
def _node(funnel: Funnel, node_id: str | None) -> dict | None:
    for n in funnel.nodes:
        if n.get("id") == node_id:
            return n
    return None


def _out_edges(funnel: Funnel, node_id: str) -> list[dict]:
    return [e for e in funnel.edges if e.get("source") == node_id]


def _entry_node_id(funnel: Funnel) -> str | None:
    """Nó de entrada = aquele sem nenhuma aresta chegando (o gatilho). Cai no 1º nó se ambíguo."""
    if not funnel.nodes:
        return None
    targets = {e.get("target") for e in funnel.edges}
    for n in funnel.nodes:
        if n.get("id") not in targets:
            return n.get("id")
    return funnel.nodes[0].get("id")


# ── Espera / params / condição ──────────────────────────────────────────────
def _delay_seconds(config: dict) -> int:
    if "delay_seconds" in config:
        raw, unit = config.get("delay_seconds", 0), "seconds"
    elif "delay_minutes" in config:
        raw, unit = config.get("delay_minutes", 0), "minutes"
    else:
        raw, unit = config.get("delay_value", 0), config.get("delay_unit", "minutes")
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        value = 0
    return max(0, value * _UNIT_SECONDS.get(unit, 60))


def _params(data: dict) -> dict:
    """Monta os params da ação a partir do `config` do nó (configurado no builder)."""
    cfg = data.get("config") or {}
    action = data.get("action", "")
    label = data.get("label", "")
    if action == "add_tag":
        return {"tag": cfg.get("tag", "")}
    if action == "create_quote":
        return {"title": cfg.get("title") or label or "Proposta",
                "amount_cents": cfg.get("amount_cents", 0)}
    if action == "create_charge":
        return {"method": cfg.get("method", "boleto"),
                "description": cfg.get("description") or label or "Cobrança",
                "amount_cents": cfg.get("amount_cents", 0)}
    if action in ("send_email", "send_message"):
        return {"message": cfg.get("body") or cfg.get("message", "")}
    if action == "create_client":
        return {"name": cfg.get("name", "")}
    return {}


def _condition_true(db: Session, run: FunnelRun, config: dict) -> bool:
    """Avalia a condição de um nó `se-ou`. v1: tem-tag / pagou / sempre."""
    field = (config.get("field") or "always").strip()
    if field == "always" or not field:
        return True
    client = db.get(Client, run.client_id) if run.client_id else None
    if client is None:
        return False
    if field == "has_tag":
        return (config.get("value") or "") in (client.tags or [])
    if field == "is_paid":
        paid = db.scalars(
            select(Charge).where(Charge.client_id == client.id, Charge.status == "paid")
        ).first()
        return paid is not None
    return False


def _pick_next(db: Session, funnel: Funnel, run: FunnelRun, node: dict) -> str | None:
    """Próximo nó. Em `se-ou` escolhe o ramo pela condição (handle 'sim'/'nao' ou ordem)."""
    outs = _out_edges(funnel, node["id"])
    if not outs:
        return None
    data = node.get("data") or {}
    if data.get("key") == "se-ou" and len(outs) >= 1:
        truthy = _condition_true(db, run, data.get("config") or {})
        wanted = "sim" if truthy else "nao"
        for e in outs:
            if (e.get("sourceHandle") or "").lower() in (wanted, wanted[:1]):
                return e.get("target")
        # sem handles nomeados: 1ª aresta = sim, 2ª = não
        idx = 0 if truthy else min(1, len(outs) - 1)
        return outs[idx].get("target")
    return outs[0].get("target")


# ── Log ─────────────────────────────────────────────────────────────────────
def _log(run: FunnelRun, node: dict, status: str, message: str) -> None:
    data = node.get("data") or {}
    step = {
        "node_id": node.get("id"),
        "key": data.get("key", ""),
        "action": data.get("action", ""),
        "status": status,
        "message": message,
        "at": _now().isoformat(),
    }
    run.steps = [*run.steps, step]  # reatribui p/ o SQLAlchemy marcar como sujo (JSON imutável)


# ── Núcleo: anda pelo grafo até esperar, terminar ou falhar ─────────────────
def _drive(db: Session, *, tenant_id: str, actor: str, funnel: Funnel, run: FunnelRun) -> None:
    steps = 0
    while run.status == RUN_RUNNING and run.current_node_id:
        if steps >= MAX_STEPS_PER_DRIVE:
            run.status = RUN_FAILED
            run.error = "Limite de passos atingido (possível ciclo no funil)"
            break
        steps += 1
        node = _node(funnel, run.current_node_id)
        if node is None:
            run.status = RUN_FAILED
            run.error = f"Nó '{run.current_node_id}' não existe no funil"
            break
        data = node.get("data") or {}
        key = data.get("key", "")

        # Nó de ESPERA: agenda a retomada e pausa.
        if key == "esperar":
            nxt = _pick_next(db, funnel, run, node)
            run.current_node_id = nxt
            if nxt is None:
                _log(run, node, "done", "Espera sem próximo nó — fim da jornada")
                run.status = RUN_DONE
                break
            run.resume_at = _now() + timedelta(seconds=_delay_seconds(data.get("config") or {}))
            run.status = RUN_WAITING
            _log(run, node, "wait", f"Aguardando até {run.resume_at.isoformat()}")
            break

        # Nó de AÇÃO REAL.
        action = data.get("action", "")
        if action == "create_client" and run.client_id:
            _log(run, node, "skipped", "Contato já está no CRM")
        elif action:
            try:
                result = service.run_node(
                    db, tenant_id=tenant_id, actor=actor, action=action,
                    client_id=run.client_id, params=_params(data),
                )
                _log(run, node, "ok", result.get("message", ""))
            except service.FunnelError as e:
                _log(run, node, "failed", str(e))
                run.status = RUN_FAILED
                run.error = str(e)
                break
        else:
            _log(run, node, "passthrough", data.get("label", key or "nó"))

        nxt = _pick_next(db, funnel, run, node)
        if nxt is None:
            run.status = RUN_DONE
            break
        run.current_node_id = nxt


# ── API do motor ────────────────────────────────────────────────────────────
def enroll(
    db: Session, *, tenant_id: str, actor: str, funnel_id: str,
    client_id: str | None, start_node_id: str | None = None,
) -> FunnelRun:
    funnel = service.get_funnel(db, funnel_id)
    if not funnel.nodes:
        raise service.FunnelError("Funil vazio: adicione nós antes de inscrever um contato", 422)
    if client_id and db.get(Client, client_id) is None:
        raise service.FunnelError("Contato não encontrado", 404)
    entry = start_node_id or _entry_node_id(funnel)
    if entry is None or _node(funnel, entry) is None:
        raise service.FunnelError("Funil sem nó de entrada válido", 422)

    run = FunnelRun(
        tenant_id=tenant_id, funnel_id=funnel_id, client_id=client_id,
        status=RUN_RUNNING, current_node_id=entry, steps=[],
    )
    db.add(run)
    db.flush()
    _drive(db, tenant_id=tenant_id, actor=actor, funnel=funnel, run=run)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="funnel.enroll", target=run.id)
    db.commit()
    db.refresh(run)
    return run


def tick(db: Session, *, tenant_id: str, actor: str, now: datetime | None = None) -> dict:
    """Retoma as jornadas cujo `resume_at` já venceu. Chamado por cron ou pela tela."""
    moment = now or _now()
    due = list(db.scalars(
        select(FunnelRun).where(
            FunnelRun.status == RUN_WAITING, FunnelRun.resume_at <= moment
        )
    ).all())
    resumed = 0
    for run in due:
        funnel = db.get(Funnel, run.funnel_id)
        if funnel is None:
            run.status = RUN_FAILED
            run.error = "Funil foi removido"
            continue
        run.status = RUN_RUNNING
        run.resume_at = None
        _drive(db, tenant_id=tenant_id, actor=actor, funnel=funnel, run=run)
        resumed += 1
    db.commit()
    return {"resumed": resumed, "checked": len(due)}


def list_runs(
    db: Session, *, funnel_id: str | None = None, client_id: str | None = None
) -> list[FunnelRun]:
    stmt = select(FunnelRun).order_by(FunnelRun.created_at.desc())
    if funnel_id:
        stmt = stmt.where(FunnelRun.funnel_id == funnel_id)
    if client_id:
        stmt = stmt.where(FunnelRun.client_id == client_id)
    return list(db.scalars(stmt).all())


def get_run(db: Session, run_id: str) -> FunnelRun:
    run = db.get(FunnelRun, run_id)
    if run is None:
        raise service.FunnelError("Jornada não encontrada", 404)
    return run


def cancel_run(db: Session, *, run_id: str, tenant_id: str, actor: str) -> FunnelRun:
    run = get_run(db, run_id)
    if run.status in (RUN_DONE, RUN_CANCELLED, RUN_FAILED):
        raise service.FunnelError("Jornada já encerrada", 409)
    run.status = RUN_CANCELLED
    run.resume_at = None
    audit.record(db, tenant_id=tenant_id, actor=actor, action="funnel.run.cancel", target=run.id)
    db.commit()
    db.refresh(run)
    return run
