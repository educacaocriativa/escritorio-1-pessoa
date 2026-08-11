"""§6.1 e §6.4 — o upsert deixa de apagar a história.

O teste de maior valor da onda é `test_editar_no_config_nao_apaga_a_historia_do_nucleo`: ele é a
diferença entre o upsert apagar história e o upsert ser só estado atual.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.modules.dna.models import DnaAnswer

REGISTER = {
    "legal_name": "Medicao ME",
    "document": "11444777000161",
    "slug": "medicaome",
    "email": "medicao@example.com",
    "name": "Flávio",
    "password": "uma-senha-bem-grande",
}

TICKET = "oferta.ticket_tipico"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _alvos(db: Session, action: str) -> list[str]:
    return [
        e.target for e in db.scalars(select(AuditEntry).where(AuditEntry.action == action)).all()
    ]


def test_responder_grava_trilha_com_o_source_no_target(
    client: TestClient, headers: dict[str, str], db: Session
):
    """§6.1. A asserção é o VALOR do target, não `!= ""`.

    `target != ""` passaria com qualquer string — inclusive com a errada. Afirmar o valor exato é
    o que faz este teste morrer se alguém trocar o `source` de lugar (para o `action`, que é a
    forma proibida) ou esquecer a chave da pergunta.
    """
    r = client.put(f"/dna/{TICKET}", json={"valor": "2k_10k", "source": "nucleo"}, headers=headers)
    assert r.status_code == 200

    assert _alvos(db, "dna.answer.save") == [f"nucleo:{TICKET}"]


def test_pular_uma_pergunta_grava_trilha(
    client: TestClient, headers: dict[str, str], db: Session
):
    r = client.post(f"/dna/{TICKET}/pular", json={"source": "gancho"}, headers=headers)
    assert r.status_code == 200

    assert _alvos(db, "dna.answer.skip") == [f"gancho:{TICKET}"]
    # Não-membro: pular não é salvar.
    assert _alvos(db, "dna.answer.save") == []


def test_editar_no_config_nao_apaga_a_historia_do_nucleo(
    client: TestClient, headers: dict[str, str], db: Session
):
    """§6.4 — o teste de maior valor da onda.

    Responder no núcleo e, semanas depois, editar a mesma pergunta na aba de `/config` fazia a
    linha passar a dizer que aquela resposta NASCEU no `/config`. O upsert continua sendo upsert:
    o que muda é que a história agora mora noutro lugar, que é append.
    """
    client.put(f"/dna/{TICKET}", json={"valor": "2k_10k", "source": "nucleo"}, headers=headers)
    client.put(f"/dna/{TICKET}", json={"valor": "10k_50k", "source": "config"}, headers=headers)

    # O upsert continua sendo upsert: UMA linha, com o estado ATUAL.
    linhas = db.scalars(select(DnaAnswer).where(DnaAnswer.question_key == TICKET)).all()
    assert len(linhas) == 1
    assert linhas[0].value == "10k_50k"
    assert linhas[0].source == "config"

    # E a história das DUAS passagens sobrevive.
    assert sorted(_alvos(db, "dna.answer.save")) == [f"config:{TICKET}", f"nucleo:{TICKET}"]
