"""O briefing como API: idempotente por (usuário, dia) e filtrado por permissão."""
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import facts
from app.core.facts import FIN_PAGAMENTO_RECEBIDO
from app.core.security import create_access_token
from app.modules.receivables.models import METHOD_PIX, STATUS_PAID, Charge
from app.modules.vima.models import Briefing
from app.modules.wallet.models import KIND_SERVICE

REGISTER = {
    "legal_name": "Vima ME",
    "document": "11444777000161",
    "slug": "vimame",
    "email": "vima@example.com",
    "name": "Flávio",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


@pytest.fixture()
def headers_sub_crm(tenant_id: str) -> dict[str, str]:
    """Funcionário que só enxerga o CRM — o mesmo vocabulário de `User.allowed_modules`."""
    token = create_access_token(
        {
            "sub": "sub-user-1",
            "tenant_id": tenant_id,
            "role": "sub_user",
            "allowed_modules": ["crm"],
            "is_platform_admin": False,
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def cobranca_paga_hoje(db: Session, tenant_id: str) -> Charge:
    """Espelha o que `receivables.service` emite ao reconhecer um pagamento (Onda 2)."""
    cobranca = Charge(
        tenant_id=tenant_id, description="Consultoria", kind=KIND_SERVICE,
        method=METHOD_PIX, amount_cents=320_000, due_date=date(2026, 8, 3),
        status=STATUS_PAID, paid_at=datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
    )
    db.add(cobranca)
    db.flush()
    facts.record(
        db, tenant_id=tenant_id, module="financeiro", kind=FIN_PAGAMENTO_RECEBIDO,
        title="Pagamento de João recebido", actor="system",
        subject_type="charge", subject_id=cobranca.id,
    )
    db.commit()
    return cobranca


def test_gera_uma_vez_por_usuario_por_dia(client: TestClient, headers, db, monkeypatch):
    """Reabrir a tela relê o gravado; não narra de novo. Sem isso, F5 dez vezes = dez
    narrações pagas."""
    chamadas = {"n": 0}
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")

    def _conta(**kw):
        chamadas["n"] += 1
        return type("R", (), {"text": "prosa", "input_tokens": 1, "output_tokens": 1})()

    monkeypatch.setattr("app.core.ai.complete", _conta)

    a = client.get("/vima/briefing", headers=headers).json()
    b = client.get("/vima/briefing", headers=headers).json()
    assert a["id"] == b["id"]
    assert chamadas["n"] == 1
    assert db.query(Briefing).count() == 1


def test_sub_usuario_de_crm_nao_recebe_linha_financeira(
    client: TestClient, headers_sub_crm, cobranca_paga_hoje
):
    corpo = client.get("/vima/briefing", headers=headers_sub_crm).json()
    assert all(linha["module"] != "financeiro" for linha in corpo["linhas"])


def test_o_dono_recebe_a_linha_financeira_com_o_valor_da_origem(
    client: TestClient, headers, cobranca_paga_hoje
):
    """A contraprova do filtro — e a prova de que a Invariante 2 fecha o ciclo: o fato nunca
    guardou o valor, e ele aparece no briefing porque foi lido de `charges` na composição."""
    corpo = client.get("/vima/briefing", headers=headers).json()
    financeiras = [linha for linha in corpo["linhas"] if linha["module"] == "financeiro"]
    assert any("Pagamento de João recebido" in linha["texto"] for linha in financeiras)
    assert any("R$ 3.200,00" in linha["texto"] for linha in financeiras)


def test_marcar_lido(client: TestClient, headers):
    b = client.get("/vima/briefing", headers=headers).json()
    assert b["read_at"] is None
    lido = client.post(f"/vima/briefing/{b['id']}/read", headers=headers).json()
    assert lido["read_at"] is not None


def test_dia_sem_nada_devolve_briefing_vazio_e_nao_falha(client: TestClient, headers):
    """`vazio` = nada ACONTECEU. Pendência e número são estado permanente, não notícia — um
    tenant recém-criado sempre tem os dois, e chamar isso de "briefing cheio" mentiria."""
    corpo = client.get("/vima/briefing", headers=headers).json()
    assert corpo["vazio"] is True
    assert corpo["texto"]
