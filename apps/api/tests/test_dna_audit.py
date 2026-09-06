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


def _alvos(db: Session, action: str) -> list[tuple[str, str]]:
    """Os `(target, detail)` da trilha daquela action — o contrato da #312, nos dois campos."""
    return [
        (e.target, e.detail)
        for e in db.scalars(select(AuditEntry).where(AuditEntry.action == action)).all()
    ]


def _id_da_linha(db: Session, key: str) -> str:
    return db.scalars(select(DnaAnswer).where(DnaAnswer.question_key == key)).one().id


def test_responder_grava_trilha_com_o_source_no_detail(
    client: TestClient, headers: dict[str, str], db: Session
):
    """§6.1, na forma da #312: o `target` é o ID da linha e o `source` vai no `detail`.

    A asserção é o VALOR dos dois campos, não `!= ""` — `!= ""` passaria com qualquer string,
    inclusive com a errada. Afirmar o id EXATO é o que prova o contrato de `audit_entries.
    target` ("um id, e só"), e afirmar o `detail` exato é o que faz este teste morrer se alguém
    devolver o `source` para o `target` (composto, a forma proibida) ou para o `action`.

    E o id não é decoração: é o que devolve `question_key` por JOIN, sem guardá-la no rastro.
    """
    r = client.put(f"/dna/{TICKET}", json={"valor": "2k_10k", "source": "nucleo"}, headers=headers)
    assert r.status_code == 200

    linha_id = _id_da_linha(db, TICKET)
    assert _alvos(db, "dna.answer.save") == [(linha_id, "nucleo")]
    # O id é um id de verdade (36 chars de UUID), não um composto disfarçado.
    assert ":" not in linha_id and len(linha_id) == 36


def test_pular_uma_pergunta_grava_trilha(
    client: TestClient, headers: dict[str, str], db: Session
):
    r = client.post(f"/dna/{TICKET}/pular", json={"source": "gancho"}, headers=headers)
    assert r.status_code == 200

    assert _alvos(db, "dna.answer.skip") == [(_id_da_linha(db, TICKET), "gancho")]
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

    # E a história das DUAS passagens sobrevive, no `detail` — que é justamente a coluna que o
    # upsert destruiu acima (`linhas[0].source` já diz só "config").
    alvos = _alvos(db, "dna.answer.save")
    assert sorted(d for _, d in alvos) == ["config", "nucleo"]

    # E o `target` das DUAS aponta para a MESMA linha, a que sobreviveu ao upsert. É esta
    # asserção que prova que o id no `target` não perdeu a pergunta: `question_key` é a chave do
    # upsert e volta por JOIN, sem precisar viajar composta no rastro.
    assert {t for t, _ in alvos} == {linhas[0].id}
    assert db.get(DnaAnswer, linhas[0].id).question_key == TICKET
