"""Testes do MOTOR de automação do funil — inscrição (gatilho), runtime do grafo,
espera + agendador (tick), condicional (se-ou), estado por contato e isolamento."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Funil SA",
    "document": "55544433000177",
    "slug": "funilsa",
    "email": "funil@example.com",
    "name": "Dona Funil",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _node(nid, key, action="", config=None):
    return {"id": nid, "type": "funnelNode",
            "data": {"key": key, "action": action, "label": key, "config": config or {}}}


def _edge(src, tgt, handle=None):
    e = {"id": f"{src}-{tgt}", "source": src, "target": tgt}
    if handle:
        e["sourceHandle"] = handle
    return e


def _client_id(client, headers, name="Contato"):
    return client.post("/crm/clients", json={"name": name}, headers=headers).json()["id"]


def _funnel(client, headers, nodes, edges):
    return client.post(
        "/funnels", json={"name": "Fluxo", "nodes": nodes, "edges": edges}, headers=headers
    ).json()["id"]


def test_enroll_runs_until_wait_then_tick_resumes(client: TestClient, headers):
    cid = _client_id(client, headers, "João Jornada")
    nodes = [
        _node("n1", "lead", "create_client"),  # contato já existe → pulado
        _node("n2", "esperar", config={"delay_seconds": 0}),
        _node("n3", "whatsapp", "send_message", config={"body": "Olá, tudo bem? 🙂"}),
    ]
    edges = [_edge("n1", "n2"), _edge("n2", "n3")]
    fid = _funnel(client, headers, nodes, edges)

    run = client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers).json()
    # parou na espera, com o próximo nó (n3) agendado
    assert run["status"] == "waiting"
    assert run["current_node_id"] == "n3"
    assert any(s["status"] == "skipped" for s in run["steps"])  # lead pulado (já no CRM)
    assert run["resume_at"] is not None

    # agendador retoma a espera vencida (delay 0)
    tick = client.post("/funnels/runs/tick", headers=headers).json()
    assert tick["resumed"] == 1
    done = client.get(f"/funnels/runs/{run['id']}", headers=headers).json()
    assert done["status"] == "done"
    assert any(s["action"] == "send_message" and s["status"] == "ok" for s in done["steps"])
    # a mensagem virou notificação real
    notifs = client.get("/notifications", headers=headers).json()
    assert any(n["channel"] == "whatsapp" for n in notifs)


def test_conditional_branches_by_tag(client: TestClient, headers):
    cid = _client_id(client, headers, "VIP")
    r = client.patch(f"/crm/clients/{cid}", json={"tags": ["vip"]}, headers=headers)
    assert r.status_code == 200 and "vip" in r.json()["tags"]
    nodes = [
        _node("n1", "pagina-vendas"),  # passthrough (entrada)
        _node("n2", "se-ou", config={"field": "has_tag", "value": "vip"}),
        _node("n3", "tag", "add_tag", config={"tag": "veio-do-sim"}),
        _node("n4", "tag", "add_tag", config={"tag": "veio-do-nao"}),
    ]
    edges = [_edge("n1", "n2"), _edge("n2", "n3", "sim"), _edge("n2", "n4", "nao")]
    fid = _funnel(client, headers, nodes, edges)

    run = client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers).json()
    assert run["status"] == "done"
    cl = client.get(f"/crm/clients/{cid}", headers=headers).json()
    assert "veio-do-sim" in cl["tags"]
    assert "veio-do-nao" not in cl["tags"]


def test_conditional_takes_nao_branch_without_tag(client: TestClient, headers):
    cid = _client_id(client, headers, "Comum")
    nodes = [
        _node("n1", "se-ou", config={"field": "has_tag", "value": "vip"}),
        _node("n2", "tag", "add_tag", config={"tag": "sim"}),
        _node("n3", "tag", "add_tag", config={"tag": "nao"}),
    ]
    edges = [_edge("n1", "n2", "sim"), _edge("n1", "n3", "nao")]
    fid = _funnel(client, headers, nodes, edges)
    client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers)
    cl = client.get(f"/crm/clients/{cid}", headers=headers).json()
    assert cl["tags"] == ["nao"]


def test_action_failure_marks_run_failed(client: TestClient, headers):
    cid = _client_id(client, headers)
    # cobrança sem valor → run_node lança erro de valor inválido → jornada falha
    nodes = [_node("n1", "emissao-boleto", "create_charge", config={"amount_cents": 0})]
    fid = _funnel(client, headers, nodes, [])
    run = client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers).json()
    assert run["status"] == "failed"
    assert run["error"]
    assert run["steps"][-1]["status"] == "failed"


def test_enroll_empty_funnel_422(client: TestClient, headers):
    fid = _funnel(client, headers, [], [])
    r = client.post(f"/funnels/{fid}/enroll", json={"client_id": None}, headers=headers)
    assert r.status_code == 422


def test_enroll_unknown_client_404(client: TestClient, headers):
    fid = _funnel(client, headers, [_node("n1", "pagina-vendas")], [])
    r = client.post(f"/funnels/{fid}/enroll", json={"client_id": "nope"}, headers=headers)
    assert r.status_code == 404


def test_cancel_stops_resume(client: TestClient, headers):
    cid = _client_id(client, headers)
    nodes = [_node("n1", "esperar", config={"delay_seconds": 0}),
             _node("n2", "tag", "add_tag", config={"tag": "depois"})]
    edges = [_edge("n1", "n2")]
    fid = _funnel(client, headers, nodes, edges)
    run = client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers).json()
    assert run["status"] == "waiting"
    cancelled = client.post(f"/funnels/runs/{run['id']}/cancel", headers=headers).json()
    assert cancelled["status"] == "cancelled"
    # tick não retoma jornada cancelada
    tick = client.post("/funnels/runs/tick", headers=headers).json()
    assert tick["resumed"] == 0
    cl = client.get(f"/crm/clients/{cid}", headers=headers).json()
    assert "depois" not in cl["tags"]


def test_cancel_finished_run_409(client: TestClient, headers):
    cid = _client_id(client, headers)
    fid = _funnel(client, headers, [_node("n1", "pagina-vendas")], [])
    run = client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers).json()
    assert run["status"] == "done"
    r = client.post(f"/funnels/runs/{run['id']}/cancel", headers=headers)
    assert r.status_code == 409


def test_list_runs_by_funnel_and_client(client: TestClient, headers):
    cid = _client_id(client, headers, "Listável")
    fid = _funnel(client, headers, [_node("n1", "pagina-vendas")], [])
    client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers)
    assert len(client.get(f"/funnels/{fid}/runs", headers=headers).json()) == 1
    by_client = client.get(f"/funnels/runs?client_id={cid}", headers=headers).json()
    assert len(by_client) == 1 and by_client[0]["client_name"] == "Listável"


def test_requires_auth(client: TestClient):
    assert client.get("/funnels/runs").status_code == 401
    assert client.post("/funnels/runs/tick").status_code == 401
