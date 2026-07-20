"""Testes do Construtor de Funil de Vendas."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import whatsapp as core_whatsapp
from app.modules.whatsapp_templates.models import (
    STATUS_APPROVED,
    STATUS_PENDING,
    WhatsappTemplate,
)

REGISTER = {
    "legal_name": "Funil SA",
    "document": "31313131000152",
    "slug": "funilsa",
    "email": "funil@example.com",
    "name": "Fu",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _template(
    db: Session, tenant_id: str, *, status: str = STATUS_APPROVED, **overrides
) -> WhatsappTemplate:
    tpl = WhatsappTemplate(
        tenant_id=tenant_id, name="confirmacao_pedido", language="pt_BR",
        category_requested="UTILITY", category_approved="UTILITY", status=status,
        body_text="Olá {{1}}, seu pedido {{2}} foi confirmado!",
        variable_count=2, variable_examples=["Maria", "#123"],
    )
    for k, v in overrides.items():
        setattr(tpl, k, v)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


def test_components_catalog(client: TestClient, headers):
    resp = client.get("/funnels/components", headers=headers)
    assert resp.status_code == 200
    cats = {c["category"] for c in resp.json()}
    assert {"gatilhos", "logica", "acoes", "comunicacao", "trafego"} <= cats
    # cada categoria tem itens e cor
    for c in resp.json():
        assert c["items"] and c["color"].startswith("#")


def test_create_and_get(client: TestClient, headers):
    nodes = [
        {"id": "n1", "type": "funnelNode", "position": {"x": 0, "y": 0},
         "data": {"label": "Página de Captura", "category": "gatilhos"}},
        {"id": "n2", "type": "funnelNode", "position": {"x": 200, "y": 100},
         "data": {"label": "Enviar E-mail", "category": "comunicacao"}},
    ]
    edges = [{"id": "e1", "source": "n1", "target": "n2"}]
    f = client.post("/funnels", json={"name": "Meu funil", "nodes": nodes, "edges": edges},
                    headers=headers).json()
    assert f["name"] == "Meu funil"
    assert len(f["nodes"]) == 2
    assert len(f["edges"]) == 1
    got = client.get(f"/funnels/{f['id']}", headers=headers).json()
    assert got["nodes"][1]["data"]["label"] == "Enviar E-mail"


def test_list_summary(client: TestClient, headers):
    client.post("/funnels", json={"name": "F1", "nodes": [{"id": "a"}]}, headers=headers)
    resp = client.get("/funnels", headers=headers).json()
    assert resp[0]["name"] == "F1"
    assert resp[0]["node_count"] == 1


def test_update_graph(client: TestClient, headers):
    f = client.post("/funnels", json={"name": "F"}, headers=headers).json()
    resp = client.patch(
        f"/funnels/{f['id']}",
        json={"nodes": [{"id": "x"}, {"id": "y"}],
              "edges": [{"id": "e", "source": "x", "target": "y"}]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["nodes"]) == 2


def test_delete(client: TestClient, headers):
    f = client.post("/funnels", json={"name": "Apagar"}, headers=headers).json()
    assert client.delete(f"/funnels/{f['id']}", headers=headers).status_code == 204
    assert client.get(f"/funnels/{f['id']}", headers=headers).status_code == 404


def test_requires_name(client: TestClient, headers):
    assert client.post("/funnels", json={"nodes": []}, headers=headers).status_code == 422


def test_ai_compose_email(client: TestClient, headers):
    resp = client.post(
        "/funnels/ai-compose",
        json={"kind": "email", "prompt": "boas-vindas para novo aluno"},
        headers=headers,
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["subject"]  # e-mail tem assunto
    assert out["body"]


def test_ai_compose_whatsapp(client: TestClient, headers):
    resp = client.post(
        "/funnels/ai-compose",
        json={"kind": "whatsapp", "prompt": "lembrete de pagamento"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["body"]


def test_catalog_marks_actions(client: TestClient, headers):
    d = client.get("/funnels/components", headers=headers).json()
    by_key = {i["key"]: i for c in d for i in c["items"]}
    assert by_key["emissao-proposta"]["action"] == "create_quote"
    assert by_key["emissao-boleto"]["action"] == "create_charge"
    assert by_key["whatsapp"]["action"] == "send_message"
    assert by_key["pagina-vendas"]["action"] == ""  # página não executa ação


def test_run_create_client(client: TestClient, headers):
    resp = client.post(
        "/funnels/run-node",
        json={"action": "create_client", "params": {"name": "Lead do Funil"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ref_id"]
    clients = client.get("/crm/clients", headers=headers).json()
    assert any(c["name"] == "Lead do Funil" for c in clients)


def test_run_create_quote(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Funil"}, headers=headers).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "create_quote", "client_id": cl["id"],
              "params": {"title": "Serviço X", "amount_cents": 150000}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    quotes = client.get("/quotes", headers=headers).json()
    assert any(q["total_cents"] == 150000 for q in quotes)


def test_run_create_charge(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Pagador"}, headers=headers).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "create_charge", "client_id": cl["id"],
              "params": {"method": "boleto", "amount_cents": 9900, "description": "Boleto funil"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    charges = client.get(f"/receivables/charges?client_id={cl['id']}", headers=headers).json()
    assert any(c["amount_cents"] == 9900 and c["method"] == "boleto" for c in charges)


def test_run_send_message(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        core_whatsapp, "send_template",
        lambda **kwargs: (captured.update(kwargs), "sent")[1],
    )
    tpl = _template(db, tenant_id)
    cl = client.post(
        "/crm/clients", json={"name": "Contato", "phone": "5511988887777"}, headers=headers
    ).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "send_message", "client_id": cl["id"],
              "params": {"template_id": tpl.id, "variables": ["Maria", "#123"]}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["template_name"] == tpl.name
    assert captured["variables"] == ["Maria", "#123"]
    notifs = client.get("/notifications", headers=headers).json()
    # o texto registrado é o template RENDERIZADO (sem {{n}}), não o texto cru.
    assert any(
        n["message"] == "Olá Maria, seu pedido #123 foi confirmado!" and n["channel"] == "whatsapp"
        for n in notifs
    )


def test_run_send_message_missing_template_is_422(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Contato"}, headers=headers).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "send_message", "client_id": cl["id"], "params": {}},
        headers=headers,
    )
    assert resp.status_code == 422


def test_run_send_message_template_not_approved_is_422(
    client: TestClient, headers, db: Session, tenant_id: str
):
    tpl = _template(db, tenant_id, status=STATUS_PENDING)
    cl = client.post("/crm/clients", json={"name": "Contato"}, headers=headers).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "send_message", "client_id": cl["id"],
              "params": {"template_id": tpl.id, "variables": ["Maria", "#123"]}},
        headers=headers,
    )
    assert resp.status_code == 422


def test_run_send_message_resolves_client_keyword_variables(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        core_whatsapp, "send_template",
        lambda **kwargs: (captured.update(kwargs), "sent")[1],
    )
    tpl = _template(db, tenant_id)
    cl = client.post(
        "/crm/clients", json={"name": "Maria Cliente", "phone": "5511988887777"}, headers=headers
    ).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "send_message", "client_id": cl["id"],
              "params": {"template_id": tpl.id, "variables": ["{{cliente.nome}}", "#999"]}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # mistura de literal ("#999") + keyword ("{{cliente.nome}}") resolvida contra o cliente.
    assert captured["variables"] == ["Maria Cliente", "#999"]
    notifs = client.get("/notifications", headers=headers).json()
    assert any(
        n["message"] == "Olá Maria Cliente, seu pedido #999 foi confirmado!" for n in notifs
    )


def test_run_send_email(client: TestClient, headers):
    # Regressão: action="send_email" deve entregar por e-mail (core/email), não por WhatsApp.
    cl = client.post(
        "/crm/clients", json={"name": "Contato", "email": "contato@example.com"}, headers=headers
    ).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "send_email", "client_id": cl["id"],
              "params": {"subject": "Bem-vindo", "message": "Olá! Tudo bem?"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    notifs = client.get("/notifications", headers=headers).json()
    assert any(
        n["message"] == "Olá! Tudo bem?" and n["channel"] == "email"
        and n["recipient"] == "contato@example.com"
        for n in notifs
    )


def test_run_send_email_to_team(client: TestClient, headers):
    # Nó configurado com destinatário="team" (ex.: alertar a equipe de um lead novo) envia pro
    # e-mail do escritório (perfil), não pro cliente — sem perfil.email configurado, cai no
    # e-mail do owner (fallback, garante que o nó funcione fora da caixa).
    cl = client.post(
        "/crm/clients", json={"name": "Lead Site", "email": "lead@example.com"}, headers=headers
    ).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "send_email", "client_id": cl["id"],
              "params": {"subject": "Novo lead", "message": "Chegou um lead novo!",
                         "recipient": "team"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    notifs = client.get("/notifications", headers=headers).json()
    assert any(
        n["message"] == "Chegou um lead novo!" and n["channel"] == "email"
        and n["recipient"] == "funil@example.com"  # owner (REGISTER["email"]), não o lead
        for n in notifs
    )


def test_run_send_email_resolves_client_placeholders(client: TestClient, headers):
    # {{cliente.*}} no assunto/corpo do e-mail é substituído pelos dados reais do lead — inclui
    # {{cliente.notas}}, que traz as respostas de campos customizados sem precisar de uma
    # keyword por campo (formulário varia de página pra página).
    cl = client.post(
        "/crm/clients",
        json={"name": "Raissa", "phone": "43996823962",
              "notes": "Ocasião: Casamento\nConvidados: 160"},
        headers=headers,
    ).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "send_email", "client_id": cl["id"],
              "params": {
                  "subject": "Novo lead: {{cliente.nome}}",
                  "message": "Nome: {{cliente.nome}}\nWhatsApp: {{cliente.telefone}}\n\n"
                             "{{cliente.notas}}",
                  "recipient": "team",
              }},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    notifs = client.get("/notifications", headers=headers).json()
    notif = next(n for n in notifs if n["client_id"] == cl["id"])
    assert "Nome: Raissa" in notif["message"]
    assert "WhatsApp: 43996823962" in notif["message"]
    assert "Ocasião: Casamento" in notif["message"]
    assert "Convidados: 160" in notif["message"]
    assert "{{" not in notif["message"]


def test_run_send_email_placeholder_shows_fallback_when_empty(client: TestClient, headers):
    # {{cliente.email}}/{{cliente.telefone}} sem valor viram "(não informado)" em vez de
    # deixar a linha em branco no e-mail (ex.: "E-mail: " sem nada depois, confuso pra quem lê).
    cl = client.post("/crm/clients", json={"name": "Sem Contato"}, headers=headers).json()
    resp = client.post(
        "/funnels/run-node",
        json={"action": "send_email", "client_id": cl["id"],
              "params": {
                  "subject": "x",
                  "message": "E-mail: {{cliente.email}}\nWhatsApp: {{cliente.telefone}}",
                  "recipient": "team",
              }},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    notifs = client.get("/notifications", headers=headers).json()
    notif = next(n for n in notifs if n["client_id"] == cl["id"])
    assert notif["message"] == "E-mail: (não informado)\nWhatsApp: (não informado)"


def test_run_requires_client(client: TestClient, headers):
    resp = client.post(
        "/funnels/run-node",
        json={"action": "create_quote", "params": {"amount_cents": 1000, "title": "x"}},
        headers=headers,
    )
    assert resp.status_code == 422


def test_requires_auth(client: TestClient):
    assert client.get("/funnels").status_code == 401
