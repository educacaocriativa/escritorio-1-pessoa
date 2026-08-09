"""O DNA chegando ao briefing — a ponta que justifica a onda inteira."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.tenancy import CurrentUser
from app.modules.dna import resolver
from app.modules.vima import absences
from app.modules.vima import service as vima_service

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


@pytest.fixture(autouse=True)
def sem_ia(monkeypatch):
    """O V2 não chama IA, mas o briefing chama. Fixar a narração isola o que está sendo testado."""
    from app.core import ai

    monkeypatch.setattr(
        ai, "complete",
        lambda **kw: type("R", (), {"text": "prosa", "input_tokens": 1, "output_tokens": 1})(),
    )


def test_o_tenant_novo_tem_topo_seco_e_o_dna_o_desliga(client: TestClient, headers, db):
    """A ponta a ponta: responder muda o que o dono lê amanhã.

    Topo seco é a única Ausência que dispara sobre o VAZIO — um tenant recém-criado sempre a
    tem. É exatamente por isso que ela é a única com opção de desligamento.
    """
    antes = client.get("/vima/briefing", headers=headers).json()
    pendentes = [linha for linha in antes["linhas"] if linha["secao"] == "PENDENTE"]
    assert pendentes, "o tenant novo deveria ter ao menos uma pendência"

    client.put(
        "/dna/cliente.topo_seco_dias", json={"valor": None, "source": "gancho"}, headers=headers
    )

    # O resolver passou a devolver o desligamento...
    assert resolver.limiares(db) == {"topo_sem_lead_dias": None}

    # ...e `coletar` deixa de rodar a regra.
    tenant_id = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]
    dono = CurrentUser(
        user_id="u1", tenant_id=tenant_id, role="owner",
        allowed_modules=[], is_platform_admin=False,
    )
    ausencias = absences.coletar(
        db, user=dono, hoje=date(2026, 8, 8), limiares=resolver.limiares(db)
    )
    assert not [a for a in ausencias if a.kind == "comercial.topo.sem_lead"]


def test_o_briefing_de_hoje_nao_e_regerado(client: TestClient, headers):
    """Idempotente por (tenant, usuário, dia): a resposta vale do PRÓXIMO em diante.

    Quebrar isso para aplicar a calibração na hora custaria o que a idempotência compra — o F5
    que relê em vez de pagar narração nova, e o dono reencontrando de tarde as palavras da manhã.
    """
    antes = client.get("/vima/briefing", headers=headers).json()
    client.put(
        "/dna/ritmo.card_parado_dias", json={"valor": 5, "source": "gancho"}, headers=headers
    )
    depois = client.get("/vima/briefing", headers=headers).json()
    assert depois["id"] == antes["id"]
    assert depois["texto"] == antes["texto"]


def test_recalibrar_limpa_o_silencio_do_briefing_anterior(client: TestClient, headers, db):
    """Sem isso, apertar um limiar não muda nada visível e a configuração parece quebrada."""
    client.get("/vima/briefing", headers=headers)
    tenant_id = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]
    user_id = client.get("/auth/me", headers=headers).json()["user"]["id"]
    dono = CurrentUser(
        user_id=user_id, tenant_id=tenant_id, role="owner",
        allowed_modules=[], is_platform_admin=False,
    )

    # O briefing de hoje já disse as pendências dele: o silêncio está carregado.
    assert vima_service._ja_reportadas(db, user=dono) != {}

    # Recalibrar zera.
    client.put(
        "/dna/ritmo.card_parado_dias", json={"valor": 5, "source": "gancho"}, headers=headers
    )
    assert vima_service._ja_reportadas(db, user=dono) == {}


def test_responder_RETRATO_nao_limpa_o_silencio(client: TestClient, headers, db):
    """Retrato não muda comportamento — limpar o silêncio por causa dele seria repetição à toa."""
    client.get("/vima/briefing", headers=headers)
    me = client.get("/auth/me", headers=headers).json()["user"]
    dono = CurrentUser(
        user_id=me["id"], tenant_id=me["tenant_id"], role="owner",
        allowed_modules=[], is_platform_admin=False,
    )
    antes = vima_service._ja_reportadas(db, user=dono)
    assert antes != {}

    client.put(
        "/dna/oferta.o_que_vende", json={"valor": "misto", "source": "config"}, headers=headers
    )
    assert vima_service._ja_reportadas(db, user=dono) == antes
