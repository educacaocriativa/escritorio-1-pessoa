"""`POST /vima/pergunta` — o contrato HTTP em cima de `pergunta.responder`."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Pergunta ME", "document": "11444777000161", "slug": "perguntame",
    "email": "pergunta@example.com", "name": "Flávio", "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_pergunta_sem_chave_de_api_responde_sem_ia(client: TestClient, headers, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "")
    resp = client.post("/vima/pergunta", json={"texto": "oi", "historico": []}, headers=headers)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["por_ia"] is False
    assert corpo["resposta"]


def test_pergunta_chama_o_servico_e_devolve_a_resposta(client: TestClient, headers, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")

    def _fake(db, *, user, pergunta, historico):
        from app.modules.vima.pergunta import Resposta
        assert pergunta == "quanto tenho a receber?"
        assert historico == []
        return Resposta(texto="R$ 500,00", por_ia=True)

    monkeypatch.setattr("app.modules.vima.pergunta.responder", _fake)
    resp = client.post(
        "/vima/pergunta", json={"texto": "quanto tenho a receber?", "historico": []},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"resposta": "R$ 500,00", "por_ia": True}


def test_pergunta_repassa_o_historico_para_o_servico(client: TestClient, headers, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    capturado = {}

    def _fake(db, *, user, pergunta, historico):
        from app.modules.vima.pergunta import Resposta
        capturado["historico"] = historico
        return Resposta(texto="ok", por_ia=True)

    monkeypatch.setattr("app.modules.vima.pergunta.responder", _fake)
    client.post(
        "/vima/pergunta",
        json={
            "texto": "e essa semana?",
            "historico": [{"papel": "usuario", "texto": "quanto tenho a receber?"},
                          {"papel": "vima", "texto": "R$ 500,00"}],
        },
        headers=headers,
    )
    historico = capturado["historico"]
    assert [(t.papel, t.texto) for t in historico] == [
        ("usuario", "quanto tenho a receber?"), ("vima", "R$ 500,00"),
    ]


def test_pergunta_sem_autenticacao_e_rejeitada(client: TestClient):
    resp = client.post("/vima/pergunta", json={"texto": "oi", "historico": []})
    assert resp.status_code in (401, 403)


def test_pergunta_vazia_e_rejeitada_pela_validacao(client: TestClient, headers):
    resp = client.post("/vima/pergunta", json={"texto": "", "historico": []}, headers=headers)
    assert resp.status_code == 422
