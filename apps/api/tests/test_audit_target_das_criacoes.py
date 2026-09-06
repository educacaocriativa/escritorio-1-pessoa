"""A trilha de uma CRIAÇÃO tem de apontar para a entidade criada (issue #311, MNT-001).

O gate AST (`tests/test_audit_target_flush_gate.py`) impede a forma do defeito voltar. Estes
testes provam a CONSEQUÊNCIA: que a linha gravada em `audit_entries` realmente carrega o id, e
não a string vazia. São coisas diferentes — o gate reconhece um padrão de código, estes medem o
banco depois da requisição.

UM TESTE POR CALL SITE, de propósito (mesma disciplina de
`tests/test_google_calendar_audit_conta.py`): asserções que cobrem vários call sites por acidente
deixam de morrer quando só um regride, e a cobertura vira ilusão.

Os quatro escolhidos, entre os 17: `agenda.event.create` e `google.credential.connect` são os
nomeados na issue como os que mais doem; `chart_account.create` porque o comentário de
`bank/service.py` o apontava por nome como ofensor conhecido; e `crm.stage.create` porque é o call
site cujo conserto teve de mudar de forma — o `flush` entrou DENTRO do `try`, e agora é ele, não o
commit, que levanta o `IntegrityError` do nome duplicado.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry

REGISTER = {
    "legal_name": "Clínica Maria",
    "document": "98765432000198",
    "slug": "clinicamaria",
    "email": "maria@example.com",
    "name": "Maria",
    "password": "uma-senha-bem-forte",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, db: Session, headers) -> str:
    from app.modules.auth.models import Tenant

    return db.scalars(select(Tenant)).first().id


def _alvo(db: Session, action: str) -> str:
    entrada = db.scalar(select(AuditEntry).where(AuditEntry.action == action))
    assert entrada is not None, f"nenhuma entrada de audit para '{action}'"
    return entrada.target


# ── agenda.event.create ──────────────────────────────────────────────────────
def test_criar_evento_grava_o_id_do_evento_na_trilha(client: TestClient, db: Session, headers):
    """O caso da issue: sem o flush, `target` nascia `''` e a entrada não dizia QUAL evento."""
    resp = client.post(
        "/agenda/events",
        json={
            "title": "Atendimento João",
            "kind": "atendimento",
            "starts_at": "2026-07-01T10:00:00+00:00",
            "ends_at": "2026-07-01T11:00:00+00:00",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    criado = resp.json()["event"]["id"]

    assert criado  # controle: o id existe de fato, senão a asserção abaixo seria '' == ''
    assert _alvo(db, "agenda.event.create") == criado


# ── google.credential.connect ────────────────────────────────────────────────
def test_conectar_o_google_grava_o_id_da_credencial(db: Session, tenant_id: str):
    """`upsert_credential` é o caso difícil: o `db.add` mora num ramo, longe do `record`.

    E `email=""` (o `userinfo` falhou no callback) faz `_invalidar_vinculos_de_outra_conta`
    voltar sem tocar no banco — não há autoflush acidental para salvar o id. O flush colado no
    `add` é o que torna as duas pernas iguais.
    """
    from app.modules.google_calendar import service
    from app.modules.google_calendar.models import GoogleCredential

    service.upsert_credential(
        db,
        tenant_id=tenant_id,
        email="",
        token_data={"access_token": "ya29.fake", "refresh_token": "1//fake", "expires_in": 3600},
    )

    cred = db.scalar(select(GoogleCredential))
    assert cred is not None and cred.id
    assert _alvo(db, "google.credential.connect") == cred.id


# ── chart_account.create ─────────────────────────────────────────────────────
def test_criar_categoria_do_plano_de_contas_grava_o_id(client: TestClient, db: Session, headers):
    """O ofensor que o comentário de `bank/service.py` apontava por NOME e não consertava."""
    resp = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "Consultoria"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    criado = resp.json()["id"]

    assert criado
    assert _alvo(db, "chart_account.create") == criado


# ── crm.stage.create ─────────────────────────────────────────────────────────
def test_criar_estagio_do_crm_grava_o_id(client: TestClient, db: Session, headers):
    resp = client.post("/crm/stages", json={"name": "Proposta enviada"}, headers=headers)
    assert resp.status_code == 201, resp.text
    criado = resp.json()["id"]

    assert criado
    assert _alvo(db, "crm.stage.create") == criado


def test_estagio_duplicado_continua_dando_409(client: TestClient, headers):
    """IV: o `flush` entrou DENTRO do `try`, então é ele que passa a levantar o `IntegrityError`.

    Se um dia alguém mover o `flush` para fora do `try` "para simplificar", a constraint estoura
    como 500 em vez de 409 e o usuário vê um erro cru. Este teste é o que impede isso.
    """
    assert client.post("/crm/stages", json={"name": "Proposta"}, headers=headers).status_code == 201
    repetido = client.post("/crm/stages", json={"name": "Proposta"}, headers=headers)
    assert repetido.status_code == 409, repetido.text


def test_categoria_duplicada_continua_dando_409(client: TestClient, headers):
    """Mesmo IV para `chart_of_accounts`, cujo `flush` também entrou dentro do `try`."""
    corpo = {"grupo_dre": "RECEITA", "categoria": "Consultoria"}
    assert client.post("/chart-of-accounts", json=corpo, headers=headers).status_code == 201
    repetido = client.post("/chart-of-accounts", json=corpo, headers=headers)
    assert repetido.status_code == 409, repetido.text


# ── O universo, medido de uma vez ────────────────────────────────────────────
def test_nenhuma_acao_de_criacao_ficou_com_alvo_vazio(client: TestClient, db: Session, headers):
    """Varredura de saída: depois de exercitar criações, NENHUMA entrada pode ter `target=''`.

    Complementa o gate por outro lado — o gate lê código, este lê o banco. Um call site que
    escapasse do AST (target montado por uma função, por exemplo) ainda cairia aqui.
    """
    client.post(
        "/agenda/events",
        json={
            "title": "Reunião",
            "kind": "reuniao",
            "starts_at": "2026-07-02T10:00:00+00:00",
            "ends_at": "2026-07-02T11:00:00+00:00",
        },
        headers=headers,
    )
    client.post("/crm/stages", json={"name": "Negociação"}, headers=headers)
    client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "RECEITA", "categoria": "Mentoria"},
        headers=headers,
    )
    client.post("/cost-centers", json={"name": "Marketing", "kind": "area"}, headers=headers)
    client.post(
        "/products",
        json={"name": "Curso", "kind": "digital", "price_cents": 10_000},
        headers=headers,
    )

    vazias = [
        e.action
        for e in db.scalars(select(AuditEntry)).all()
        if e.action.endswith(".create") and not e.target
    ]
    assert not vazias, f"ações de criação com `target` vazio (MNT-001): {sorted(set(vazias))}"
    # Controle antivacuidade: a varredura acima precisa ter tido o que varrer.
    criadas = [
        e.action for e in db.scalars(select(AuditEntry)).all() if e.action.endswith(".create")
    ]
    assert len(criadas) >= 5, f"só {len(criadas)} criações auditadas — as chamadas acima falharam?"
