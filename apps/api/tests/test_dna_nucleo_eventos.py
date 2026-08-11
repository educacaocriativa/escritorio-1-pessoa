"""§3.3 — o caminho de erro grava NADA, e é isso que o torna distinguível.

`dna.nucleo.open` é emitido DEPOIS de `GET /dna/faltantes` responder com sucesso, isto é, depois
de a pessoa ter de fato visto perguntas. Gravar `abandon` no caminho de erro seria mentira; criar
um terceiro evento (`dna.nucleo.unavailable`) seria categoria que ninguém pediu, com um consumidor
que não existe. Com `open` condicionado ao sucesso, **ausência de `open` ⇒ a pessoa nunca entrou**
— verdade, derivada, sem evento novo.

**Membro** de "abandonou o núcleo": um tenant com `dna.nucleo.open`, dois `dna.answer.save` e
`dna.nucleo.abandon`.
**Não-membro:** um sub-usuário sem o módulo `settings` que tomou 403 — nenhum evento, e o
relatório não o conta como abandono.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.core.security import create_access_token

REGISTER = {
    "legal_name": "Nucleo ME",
    "document": "11444777000161",
    "slug": "nucleome",
    "email": "nucleo@example.com",
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
    """Sub-usuário só de CRM: o DNA é da EMPRESA e não é dele."""
    token = create_access_token(
        {
            "sub": "sub-crm",
            "tenant_id": tenant_id,
            "role": "member",
            "allowed_modules": ["comercial"],
        }
    )
    return {"Authorization": f"Bearer {token}"}


def _do_dna(db: Session) -> list[tuple[str, str]]:
    return [
        (e.action, e.target)
        for e in db.scalars(select(AuditEntry).where(AuditEntry.action.like("dna.%"))).all()
    ]


def test_open_grava_o_denominador_que_a_pessoa_VIU(
    client: TestClient, headers: dict[str, str], db: Session
):
    """§3.4 — o progresso é derivado, mas o denominador é GRAVADO.

    `GET /dna/faltantes` devolve só as não respondidas: na segunda visita a pessoa vê 4, não 6, e
    "2 de 6" seria falso sobre o que ela viu. E `catalog.NUCLEO` pode crescer — o eixo de
    Calibração já cresceu de 6 para 7 em 2026-08-09 —, o que viraria todo "k de 6" histórico em
    "k de 7" RETROATIVAMENTE. O número exibido é evidência do que a pessoa viu, no princípio do
    `raw_description` de `bank_transactions`: imutável porque é prova.
    """
    r = client.post("/dna/nucleo/open", json={"exibidas": 4}, headers=headers)
    assert r.status_code == 204
    assert r.content == b""

    assert _do_dna(db) == [("dna.nucleo.open", "4")]


def test_abandon_grava_sem_alvo(client: TestClient, headers: dict[str, str], db: Session):
    r = client.post("/dna/nucleo/abandon", json={}, headers=headers)
    assert r.status_code == 204

    assert _do_dna(db) == [("dna.nucleo.abandon", "")]


def test_evento_fora_da_tupla_nao_existe(client: TestClient, headers: dict[str, str], db: Session):
    """Porta estreita validada contra um conjunto, como `_validar` faz contra o catálogo."""
    r = client.post("/dna/nucleo/desistiu", json={}, headers=headers)
    assert r.status_code == 404
    assert _do_dna(db) == []


def test_open_sem_denominador_e_recusado(
    client: TestClient, headers: dict[str, str], db: Session
):
    """Um `open` sem o número exibido não responde à pergunta que ele existe para responder."""
    assert client.post("/dna/nucleo/open", json={}, headers=headers).status_code == 422
    assert client.post("/dna/nucleo/open", json={"exibidas": 0}, headers=headers).status_code == 422
    assert _do_dna(db) == []


def test_403_do_sub_usuario_nao_produz_evento_nenhum(
    client: TestClient, headers: dict[str, str], headers_sub_crm: dict[str, str], db: Session
):
    """§3.3 — o não-membro, com o membro ao lado.

    Sem o controle positivo abaixo este teste passaria verde se a ROTA INTEIRA sumisse: zero
    eventos é o resultado esperado, e zero eventos também é o resultado de não haver rota.
    """
    r = client.post("/dna/nucleo/open", json={"exibidas": 6}, headers=headers_sub_crm)
    assert r.status_code == 403
    assert _do_dna(db) == []

    # Controle positivo: o MEMBRO, na mesma sessão, produz evento.
    assert client.post("/dna/nucleo/open", json={"exibidas": 6}, headers=headers).status_code == 204
    assert _do_dna(db) == [("dna.nucleo.open", "6")]
