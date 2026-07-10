"""Testes do Assistente Jurídico — catálogo de skills, extração, geração por IA e histórico.

A chamada real ao Claude é monkeypatchada (não gasta tokens nem precisa de chave). Validamos:
o catálogo carrega as 21 skills, a anonimização acontece ANTES da IA, a seção METADADOS é
separada do corpo, e o documento fica isolado/persistido.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.ai import AIResult

REGISTER = {
    "legal_name": "Banca Silva",
    "document": "12321321000177",
    "slug": "bancasilva",
    "email": "adv@example.com",
    "name": "Dra. Silva",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def fake_ai(monkeypatch):
    """Captura o que vai para a IA e devolve um documento com a seção de METADADOS."""
    seen = {}

    def _fake(*, system, user_message, max_tokens=8192, model=None):
        seen["system"] = system
        seen["user"] = user_message
        body = (
            "# SENTENÇA\n\nVistos. Julgo procedente o pedido.\n\n"
            "### METADADOS PARA RELATÓRIO\n- Skills utilizadas: sentenca-judicial-br\n"
            "- Jurisprudências citadas: Súmula 7/STJ (NÍVEL 1)\n"
        )
        return AIResult(text=body, input_tokens=120, output_tokens=80)

    monkeypatch.setattr("app.modules.juridico.service.complete", _fake)
    monkeypatch.setattr("app.modules.juridico.service.settings.anthropic_api_key", "test-key")
    return seen


def test_list_skills_loads_catalog(client: TestClient, headers):
    skills = client.get("/juridico/skills", headers=headers).json()
    assert len(skills) == 21
    names = {s["skill"] for s in skills}
    assert "sentenca-judicial-br" in names and "peticao-analyzer" in names
    assert all(s["label"] and s["category"] for s in skills)


def test_get_skill_config_has_steps(client: TestClient, headers):
    cfg = client.get("/juridico/skills/peticao-analyzer", headers=headers).json()
    assert cfg["skill"] == "peticao-analyzer"
    assert isinstance(cfg["steps"], list) and cfg["steps"]


def test_unknown_skill_config_404(client: TestClient, headers):
    assert client.get("/juridico/skills/nao-existe", headers=headers).status_code == 404


def test_extract_txt(client: TestClient, headers):
    files = {"file": ("peca.txt", b"Conteudo da peticao inicial", "text/plain")}
    r = client.post("/juridico/extract", files=files, headers=headers)
    assert r.status_code == 200
    assert "peticao inicial" in r.json()["text"]


def test_generate_splits_metadata_and_persists(client: TestClient, headers, fake_ai):
    r = client.post(
        "/juridico/documents",
        json={"skill": "sentenca-judicial-br", "answers": {"tipo_acao": "Cobrança"}},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "ready"
    assert "Julgo procedente" in doc["content"]
    assert "METADADOS" not in doc["content"]  # corpo não inclui a seção de metadados
    assert "Súmula 7/STJ" in doc["metadata_raw"]
    assert doc["output_tokens"] == 80
    # o prompt-sistema veio do SKILL.md + protocolo anti-alucinação
    assert "PROTOCOLO ANTI-ALUCINAÇÃO" in fake_ai["system"]
    assert "Dra. Silva" in fake_ai["user"]


def test_generate_anonymizes_pii_before_ai(client: TestClient, headers, fake_ai):
    client.post(
        "/juridico/documents",
        json={
            "skill": "sentenca-judicial-br",
            "answers": {"parte": "Fulano CPF 123.456.789-09 email fulano@x.com"},
        },
        headers=headers,
    )
    # o CPF e o e-mail NÃO podem ter sido enviados ao Claude em texto claro
    assert "123.456.789-09" not in fake_ai["user"]
    assert "fulano@x.com" not in fake_ai["user"]
    assert "[CPF_1]" in fake_ai["user"] and "[EMAIL_1]" in fake_ai["user"]


def test_generate_links_client_and_lists(client: TestClient, headers, fake_ai):
    cl = client.post("/crm/clients", json={"name": "Cliente Réu"}, headers=headers).json()
    client.post(
        "/juridico/documents",
        json={"skill": "despacho-generator", "answers": {}, "client_id": cl["id"]},
        headers=headers,
    )
    docs = client.get(f"/juridico/documents?client_id={cl['id']}", headers=headers).json()
    assert len(docs) == 1 and docs[0]["client_name"] == "Cliente Réu"


def test_generate_unknown_client_404(client: TestClient, headers, fake_ai):
    r = client.post(
        "/juridico/documents",
        json={"skill": "despacho-generator", "answers": {}, "client_id": "nope"},
        headers=headers,
    )
    assert r.status_code == 404


def test_download_docx(client: TestClient, headers, fake_ai):
    doc = client.post(
        "/juridico/documents",
        json={"skill": "sentenca-judicial-br", "answers": {}},
        headers=headers,
    ).json()
    r = client.get(f"/juridico/documents/{doc['id']}/docx", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml"
    )
    assert r.content[:2] == b"PK"  # docx é um zip


def test_generate_without_api_key_marks_failed(client: TestClient, headers, monkeypatch):
    monkeypatch.setattr("app.modules.juridico.service.settings.anthropic_api_key", "")
    r = client.post(
        "/juridico/documents",
        json={"skill": "sentenca-judicial-br", "answers": {}},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["status"] == "failed"


def test_delete_document(client: TestClient, headers, fake_ai):
    doc = client.post(
        "/juridico/documents",
        json={"skill": "sentenca-judicial-br", "answers": {}},
        headers=headers,
    ).json()
    assert client.delete(f"/juridico/documents/{doc['id']}", headers=headers).status_code == 204
    assert client.get(f"/juridico/documents/{doc['id']}", headers=headers).status_code == 404


def test_requires_auth(client: TestClient):
    assert client.get("/juridico/skills").status_code == 401
    assert client.get("/juridico/documents").status_code == 401
