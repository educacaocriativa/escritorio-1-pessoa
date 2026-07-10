"""Worker durável (Story 4.3): run_sweep dispara o tick do funil + processa a fila, por tenant.

Usa a sessão SQLite compartilhada (fixture `db`) via injeção de `session_factory`/
`tenant_session_factory` — mesmo idioma do `conftest.py::_override_factory`. Cobre: retomada de
funil pelo worker (IV1), processamento da fila, no-op idempotente, isolamento de falha por
etapa/tenant (IV2) e exclusão do tenant "platform".
"""
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import worker
from app.modules.auth.models import Tenant
from app.modules.notifications import service as notif_service
from app.modules.notifications.models import Notification
from app.worker import _tenant_ids, run_sweep


def _cm_factory(db):
    """Context manager que devolve a sessão de teste SEM fechá-la (compartilhada).

    Serve tanto como `session_factory()` (sem args) quanto `tenant_session_factory(tenant_id)`.
    """

    @contextmanager
    def _cm(*_args, **_kwargs):
        yield db

    return _cm


def _make_tenant(db, *, slug, document="00000000000191"):
    tenant = Tenant(slug=slug, legal_name=f"{slug} SA", document=document)
    db.add(tenant)
    db.flush()
    return tenant


# --- Funil resume via worker (usa a máquina HTTP p/ montar funil + enroll) ------------------

REGISTER = {
    "legal_name": "Worker SA",
    "document": "55544433000108",
    "slug": "workersa",
    "email": "worker@example.com",
    "name": "Dona Worker",
    "password": "senha-bem-comprida",
}


def _node(nid, key, action="", config=None):
    return {"id": nid, "type": "funnelNode",
            "data": {"key": key, "action": action, "label": key, "config": config or {}}}


def _edge(src, tgt):
    return {"id": f"{src}-{tgt}", "source": src, "target": tgt}


def test_run_sweep_resumes_due_funnel(client: TestClient, db):
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    cid = client.post("/crm/clients", json={"name": "Contato"}, headers=headers).json()["id"]
    nodes = [
        _node("n1", "esperar", config={"delay_seconds": 0}),
        _node("n2", "tag", "add_tag", config={"tag": "resumido"}),
    ]
    edges = [_edge("n1", "n2")]
    fid = client.post(
        "/funnels", json={"name": "Fluxo", "nodes": nodes, "edges": edges}, headers=headers
    ).json()["id"]
    run = client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers).json()
    assert run["status"] == "waiting"

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["tenants_checked"] == 1
    assert result["funnel_resumed"] == 1
    assert result["errors"] == []
    done = client.get(f"/funnels/runs/{run['id']}", headers=headers).json()
    assert done["status"] == "done"


# --- Fila de notificações via worker --------------------------------------------------------

def test_run_sweep_processes_pending_notification(db):
    tenant = _make_tenant(db, slug="notif")
    notif_service.enqueue(
        db, tenant_id=tenant.id, channel="whatsapp", recipient="d@e.com", message="oi"
    )
    db.commit()

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["tenants_checked"] == 1
    assert result["notifications_processed"] == 1
    assert result["errors"] == []
    assert db.scalar(select(Notification)).status != "pending"


def test_run_sweep_noop_is_idempotent(db):
    _make_tenant(db, slug="vazio")
    cm = _cm_factory(db)

    first = run_sweep(session_factory=cm, tenant_session_factory=cm)
    second = run_sweep(session_factory=cm, tenant_session_factory=cm)

    for res in (first, second):
        assert res["tenants_checked"] == 1
        assert res["funnel_resumed"] == 0
        assert res["notifications_processed"] == 0
        assert res["errors"] == []


def test_run_sweep_isolates_stage_failure(db, monkeypatch):
    # tick lança para o tenant, mas a etapa da fila (sessão separada) ainda roda — e o sweep
    # não morre: o erro é acumulado em `errors` (IV2).
    tenant = _make_tenant(db, slug="falha")
    notif_service.enqueue(
        db, tenant_id=tenant.id, channel="whatsapp", recipient="d@e.com", message="oi"
    )
    db.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("tick explodiu")

    monkeypatch.setattr(worker.funnels_engine, "tick", _boom)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["notifications_processed"] == 1  # a fila rodou mesmo com o tick falhando
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "tick"
    assert result["errors"][0]["tenant_id"] == tenant.id


def test_tenant_ids_excludes_platform(db):
    _make_tenant(db, slug="platform", document="00000000000000")  # tenant interno da plataforma
    real = _make_tenant(db, slug="real")
    db.commit()

    ids = _tenant_ids(db)
    assert ids == [real.id]


def test_run_sweep_continues_across_tenants(db, monkeypatch):
    # Dois tenants com fila; o tick sempre falha, mas AMBOS têm a fila processada e o loop não para.
    t1 = _make_tenant(db, slug="t1", document="00000000000191")
    t2 = _make_tenant(db, slug="t2", document="00000000000272")
    for t in (t1, t2):
        notif_service.enqueue(
            db, tenant_id=t.id, channel="whatsapp", recipient="d@e.com", message="oi"
        )
    db.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("tick explodiu")

    monkeypatch.setattr(worker.funnels_engine, "tick", _boom)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["tenants_checked"] == 2
    assert result["notifications_processed"] == 2
    assert len(result["errors"]) == 2  # um erro de tick por tenant, nenhum trava o sweep
