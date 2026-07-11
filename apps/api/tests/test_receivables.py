"""Testes de Contas a Receber — incluindo a baixa que alimenta a Carteira com split."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Cobra Co",
    "document": "77888999000181",
    "slug": "cobraco",
    "email": "cobra@example.com",
    "name": "Cobra",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _charge(**over):
    base = {
        "kind": "service",
        "method": "pix",
        "amount_cents": 10000,
        "due_date": "2026-08-10",
        "description": "Mensalidade",
    }
    return {**base, **over}


def test_boleto_charge_generates_pdf_attachment(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(method="boleto"), headers=headers).json()
    atts = client.get(
        f"/attachments?owner_type=charge&owner_id={c['id']}", headers=headers
    ).json()
    boleto = [a for a in atts if a["label"] == "boleto"]
    assert boleto and boleto[0]["content_type"] == "application/pdf"
    assert boleto[0]["size"] > 0


def test_webhook_recognizes_payment_and_credits_wallet(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(method="boleto"), headers=headers).json()
    # gateway confirma o pagamento (sem login, sem ação do dono)
    resp = client.post(
        "/receivables/webhook",
        json={"tenant_id": c["tenant_id"], "charge_id": c["id"], "status": "paid"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    # cobrança paga e Carteira creditada (disponível para saque)
    got = client.get(f"/receivables/charges/{c['id']}", headers=headers).json()
    assert got["status"] == "paid"
    wallet = client.get("/wallet/summary", headers=headers).json()
    assert wallet["available_cents"] > 0


def test_recurring_charge_generates_occurrences(client: TestClient, headers):
    client.post(
        "/receivables/charges",
        json=_charge(due_date="2026-08-10", method="boleto", recurrence="monthly",
                     recurrence_count=4),
        headers=headers,
    )
    charges = client.get("/receivables/charges", headers=headers).json()
    assert len(charges) == 4
    dues = sorted(c["due_date"] for c in charges)
    assert dues == ["2026-08-10", "2026-09-10", "2026-10-10", "2026-11-10"]
    groups = {c["recurrence_group"] for c in charges}
    assert len(groups) == 1 and None not in groups
    # cada uma com seu código de boleto próprio
    assert all(c["payment_code"] for c in charges)


def test_edit_charge_moves_agenda(client: TestClient, headers):
    c = client.post(
        "/receivables/charges", json=_charge(due_date="2026-08-10"), headers=headers
    ).json()
    resp = client.patch(
        f"/receivables/charges/{c['id']}",
        json={"description": "Nova descrição", "amount_cents": 33300, "due_date": "2026-09-05"},
        headers=headers,
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["amount_cents"] == 33300
    assert out["due_date"] == "2026-09-05"
    ev = [e for e in client.get("/agenda/events?limit=500", headers=headers).json()
          if e["kind"] == "cobranca_receber"][0]
    assert ev["starts_at"].startswith("2026-09-05")  # evento moveu junto
    assert ev["amount_cents"] == 33300


def test_cannot_edit_paid_charge(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    client.post(f"/receivables/charges/{c['id']}/pay", headers=headers)
    resp = client.patch(
        f"/receivables/charges/{c['id']}", json={"amount_cents": 5000}, headers=headers
    )
    assert resp.status_code == 409


def test_create_charge_generates_code(client: TestClient, headers):
    resp = client.post("/receivables/charges", json=_charge(), headers=headers)
    assert resp.status_code == 201, resp.text
    c = resp.json()
    assert c["status"] == "open"
    assert c["payment_code"]  # gateway stub
    assert c["is_overdue"] is False


def test_create_charge_injects_agenda_event(client: TestClient, headers):
    client.post("/receivables/charges", json=_charge(due_date="2026-08-10"), headers=headers)
    # o vencimento aparece na agenda como cobranca_receber
    events = client.get(
        "/agenda/events",
        params={"start": "2026-08-01T00:00:00+00:00", "end": "2026-08-31T00:00:00+00:00"},
        headers=headers,
    ).json()
    kinds = [e["kind"] for e in events]
    assert "cobranca_receber" in kinds


def test_pay_charge_feeds_wallet_with_split(client: TestClient, headers):
    charge = client.post(
        "/receivables/charges", json=_charge(amount_cents=10000), headers=headers
    ).json()
    # antes de pagar, carteira zerada
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] == 0

    paid = client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers).json()
    assert paid["status"] == "paid"
    assert paid["transaction_id"]

    # serviço pix 30% -> líquido 7000 disponível
    s = client.get("/wallet/summary", headers=headers).json()
    assert s["available_cents"] == 7000
    assert s["fees_total_cents"] == 3000


def test_pay_twice_is_idempotent(client: TestClient, headers):
    charge = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)
    # não duplica receita na carteira
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] == 7000


def test_cancel_then_pay_rejected(client: TestClient, headers):
    charge = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    client.post(f"/receivables/charges/{charge['id']}/cancel", headers=headers)
    resp = client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)
    assert resp.status_code == 409


def test_overdue_summary(client: TestClient, headers):
    client.post("/receivables/charges", json=_charge(due_date="2020-01-01"), headers=headers)
    client.post("/receivables/charges", json=_charge(due_date="2099-01-01"), headers=headers)
    s = client.get("/receivables/summary", headers=headers).json()
    assert s["overdue_cents"] == 10000
    assert s["open_cents"] == 10000
    assert s["overdue_count"] == 1


def test_collect_with_ai_writes_message_and_notifies(client: TestClient, headers):
    # sem ANTHROPIC_API_KEY nos testes, usa o template (não chama o Claude)
    c = client.post(
        "/receivables/charges",
        json=_charge(due_date="2020-01-01", amount_cents=15000),
        headers=headers,
    ).json()
    r = client.post(f"/receivables/charges/{c['id']}/collect", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["message"]) > 10
    assert body["status"] == "logged"
    # uma notificação de WhatsApp foi registrada
    notifs = client.get("/notifications", headers=headers).json()
    assert any(n["channel"] == "whatsapp" for n in notifs)


def test_collect_only_open(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    client.post(f"/receivables/charges/{c['id']}/pay", headers=headers)  # paga
    resp = client.post(f"/receivables/charges/{c['id']}/collect", headers=headers)
    assert resp.status_code == 409


def test_charge_shows_client_name(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "João Cobrado"}, headers=headers).json()
    client.post("/receivables/charges", json=_charge(client_id=cl["id"]), headers=headers)
    charges = client.get("/receivables/charges", headers=headers).json()
    assert charges[0]["client_name"] == "João Cobrado"


def test_message_history_and_manual_message(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Msg"}, headers=headers).json()
    c = client.post(
        "/receivables/charges",
        json=_charge(client_id=cl["id"], due_date="2020-01-01"),
        headers=headers,
    ).json()
    # cobrança com IA + mensagem manual
    client.post(f"/receivables/charges/{c['id']}/collect", headers=headers)
    r = client.post(
        f"/receivables/charges/{c['id']}/message",
        json={"text": "Oi, passando para lembrar 🙂"},
        headers=headers,
    )
    assert r.status_code == 200
    # histórico mostra as duas mensagens
    msgs = client.get(f"/receivables/charges/{c['id']}/messages", headers=headers).json()
    assert len(msgs) == 2
    assert any("lembrar" in m["message"] for m in msgs)


def test_messages_empty_without_client(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()  # sem cliente
    msgs = client.get(f"/receivables/charges/{c['id']}/messages", headers=headers).json()
    assert msgs == []


def test_get_single_charge(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    got = client.get(f"/receivables/charges/{c['id']}", headers=headers).json()
    assert got["id"] == c["id"]


def test_requires_auth(client: TestClient):
    assert client.get("/receivables/summary").status_code == 401


# ── Story 2.2: gateway de pagamento real (Asaas) ──────────────────────────────────────────────
# Documento válido para o path do gateway (o gateway registrado exige CPF/CNPJ do pagador).
VALID_CPF = "11144477735"


def _configure_gateway(monkeypatch, create_fn):
    """Ativa o gateway real nos testes e injeta um `create_registered_charge` fake (sem HTTP)."""
    from app.config import settings
    from app.core import payment_gateway

    monkeypatch.setattr(settings, "payment_gateway_api_key", "test-key")
    monkeypatch.setattr(settings, "payment_gateway_provider", "asaas")
    monkeypatch.setattr(payment_gateway, "create_registered_charge", create_fn)


def _fake_result(**kwargs):
    from app.core.payment_gateway import GatewayChargeResult

    ref = kwargs["external_reference"]
    return GatewayChargeResult(
        provider="asaas",
        gateway_charge_id=f"pay_{ref.split(':')[1][:6]}",
        payment_code=f"REGISTERED-{kwargs['method']}-{ref.split(':')[1][:6]}",
        status="PENDING",
        boleto_url="https://asaas.example/boleto",
    )


def test_webhook_accepts_real_asaas_payload_and_credits_wallet(client: TestClient, headers):
    """AC2: o payload REAL do provedor (event + payment.externalReference) dá a baixa."""
    c = client.post("/receivables/charges", json=_charge(method="boleto"), headers=headers).json()
    payload = {
        "event": "PAYMENT_RECEIVED",
        "payment": {"id": "pay_x", "externalReference": f"{c['tenant_id']}:{c['id']}",
                    "status": "RECEIVED"},
    }
    resp = client.post("/receivables/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    got = client.get(f"/receivables/charges/{c['id']}", headers=headers).json()
    assert got["status"] == "paid"
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] > 0


def test_webhook_real_payload_is_idempotent(client: TestClient, headers):
    """AC3/IV2: reenvio at-least-once do mesmo evento não duplica a receita na carteira."""
    c = client.post(
        "/receivables/charges", json=_charge(amount_cents=10000), headers=headers
    ).json()
    payload = {
        "event": "PAYMENT_CONFIRMED",
        "payment": {"externalReference": f"{c['tenant_id']}:{c['id']}"},
    }
    client.post("/receivables/webhook", json=payload)
    client.post("/receivables/webhook", json=payload)  # reenvio
    # serviço pix 30% -> 7000 líquido, uma única vez
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] == 7000


def test_webhook_ignores_non_payment_event(client: TestClient, headers):
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    resp = client.post(
        "/receivables/webhook",
        json={"event": "PAYMENT_CREATED",
              "payment": {"externalReference": f"{c['tenant_id']}:{c['id']}"}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    # não deu baixa
    got = client.get(f"/receivables/charges/{c['id']}", headers=headers).json()
    assert got["status"] == "open"


def test_webhook_real_payload_missing_reference_rejected(client: TestClient):
    resp = client.post(
        "/receivables/webhook",
        json={"event": "PAYMENT_RECEIVED", "payment": {"externalReference": "sem-separador"}},
    )
    assert resp.status_code == 400


def test_webhook_secret_enforced_for_real_payload(client: TestClient, headers, monkeypatch):
    """Fail-closed: com GATEWAY_WEBHOOK_SECRET definido, o token do header é obrigatório."""
    from app.config import settings

    monkeypatch.setattr(settings, "gateway_webhook_secret", "s3cr3t")
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    payload = {"event": "PAYMENT_RECEIVED",
               "payment": {"externalReference": f"{c['tenant_id']}:{c['id']}"}}
    # sem token -> 401
    assert client.post("/receivables/webhook", json=payload).status_code == 401
    # token errado -> 401
    bad = client.post("/receivables/webhook", json=payload,
                      headers={"asaas-access-token": "errado"})
    assert bad.status_code == 401
    # token correto -> 200 paid
    ok = client.post("/receivables/webhook", json=payload,
                     headers={"asaas-access-token": "s3cr3t"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "paid"


def test_webhook_internal_secret_still_enforced(client: TestClient, headers, monkeypatch):
    """Retrocompat: o payload interno de dev valida o `secret` no corpo quando o segredo existe."""
    from app.config import settings

    monkeypatch.setattr(settings, "gateway_webhook_secret", "s3cr3t")
    c = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    base = {"tenant_id": c["tenant_id"], "charge_id": c["id"], "status": "paid"}
    assert client.post("/receivables/webhook", json=base).status_code == 401
    ok = client.post("/receivables/webhook", json={**base, "secret": "s3cr3t"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "paid"


def test_graceful_degradation_without_gateway(client: TestClient, headers):
    """IV1: sem chave do gateway, a cobrança usa o stub (código stub + boleto layout-stub)."""
    c = client.post("/receivables/charges", json=_charge(method="boleto"), headers=headers).json()
    assert c["gateway_provider"] is None
    assert c["payment_code"].startswith("34191")  # linha do boleto stub
    atts = client.get(f"/attachments?owner_type=charge&owner_id={c['id']}", headers=headers).json()
    assert any(a["label"] == "boleto" and a["size"] > 0 for a in atts)


def test_gateway_configured_uses_registered_code(client: TestClient, headers, monkeypatch):
    """AC1: com o gateway configurado, a cobrança carrega o código REGISTRADO e o external_ref
    correto (tenant_id:charge_id)."""
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _fake_result(**kwargs)

    _configure_gateway(monkeypatch, fake_create)
    cl = client.post(
        "/crm/clients", json={"name": "Pagador", "document": VALID_CPF}, headers=headers
    ).json()
    c = client.post(
        "/receivables/charges", json=_charge(method="boleto", client_id=cl["id"]), headers=headers
    ).json()
    assert c["payment_code"].startswith("REGISTERED-boleto")
    assert c["gateway_provider"] == "asaas"
    assert len(calls) == 1
    assert calls[0]["external_reference"] == f"{c['tenant_id']}:{c['id']}"


def test_gateway_called_per_recurring_occurrence(client: TestClient, headers, monkeypatch):
    """AC4: cada ocorrência recorrente gera seu próprio registro no gateway (uma chamada cada)."""
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _fake_result(**kwargs)

    _configure_gateway(monkeypatch, fake_create)
    cl = client.post(
        "/crm/clients", json={"name": "Pagador", "document": VALID_CPF}, headers=headers
    ).json()
    client.post(
        "/receivables/charges",
        json=_charge(method="boleto", client_id=cl["id"], recurrence="monthly",
                     recurrence_count=3),
        headers=headers,
    )
    assert len(calls) == 3
    refs = {kw["external_reference"] for kw in calls}
    assert len(refs) == 3  # um external_reference distinto por ocorrência


def test_gateway_failure_degrades_to_stub(client: TestClient, headers, monkeypatch):
    """Fail-safe: se o gateway falhar, a cobrança ainda é criada com o stub (não quebra o fluxo)."""
    from app.core.payment_gateway import GatewayError

    def boom(**kwargs):
        raise GatewayError("indisponível")

    _configure_gateway(monkeypatch, boom)
    cl = client.post(
        "/crm/clients", json={"name": "Pagador", "document": VALID_CPF}, headers=headers
    ).json()
    resp = client.post(
        "/receivables/charges", json=_charge(method="boleto", client_id=cl["id"]), headers=headers
    )
    assert resp.status_code == 201
    c = resp.json()
    assert c["gateway_provider"] is None
    assert c["payment_code"].startswith("34191")  # caiu no stub
