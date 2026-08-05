"""O fuso do tenant vale para "hoje", para "agora" e para todo texto que um humano lê.

Estes testes cobrem a dívida registrada no `CLAUDE.md` §6.1 ("hoje" ancorado em UTC) e o vazamento
de `isoformat()` cru em mensagem de usuário. A janela crítica é sempre a mesma: entre 21:00 e
23:59 em São Paulo (UTC−3) já é o **dia seguinte** em UTC. Um sistema que chama isso de "hoje"
erra a data de vencimento, o atraso, a projeção de caixa e a data impressa num contrato.

Todo teste aqui fixa um instante nessa janela — `2026-08-06T01:30Z` é `2026-08-05 22:30` em São
Paulo. Nada de relógio real: o `now` é parâmetro, mesma disciplina de `core/scheduling.py`.
"""
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# 2026-08-06 01:30 UTC == 2026-08-05 22:30 em America/Sao_Paulo.
# Em UTC já é dia 6; para quem usa o sistema, ainda é a noite do dia 5.
NOITE_DO_DIA_5 = datetime(2026, 8, 6, 1, 30, tzinfo=UTC)

REGISTER = {
    "legal_name": "Fuso ME",
    "document": "11444777000161",
    "slug": "fusome",
    "email": "fuso@example.com",
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


# ── core/tz: as primitivas ──────────────────────────────────────────────────


def test_data_local_nao_e_a_data_utc_na_janela_da_noite():
    """A primitiva que todo o resto usa: a data de calendário NO FUSO do tenant."""
    from app.core.tz import local_date

    assert local_date(NOITE_DO_DIA_5, "America/Sao_Paulo") == date(2026, 8, 5)
    # A prova de que o teste tem sentido: em UTC o mesmo instante é outro dia.
    assert NOITE_DO_DIA_5.date() == date(2026, 8, 6)


def test_tenant_today_usa_o_fuso_do_tenant():
    from app.core.tz import tenant_today

    assert tenant_today("America/Sao_Paulo", now=NOITE_DO_DIA_5) == date(2026, 8, 5)
    # Fuso diferente, dia diferente — o parâmetro não é decorativo.
    assert tenant_today("Europe/London", now=NOITE_DO_DIA_5) == date(2026, 8, 6)


def test_tenant_today_e_fail_safe_com_fuso_invalido():
    """Mesma garantia de `tenant_zone`: fuso corrompido no banco não derruba a request."""
    from app.core.tz import tenant_today

    assert tenant_today("Marte/Olympus", now=NOITE_DO_DIA_5) == date(2026, 8, 5)
    assert tenant_today(None, now=NOITE_DO_DIA_5) == date(2026, 8, 5)


def test_formata_datetime_para_humano_em_pt_br():
    """O que aparece na tela é `05/08/2026 22:30`, nunca `2026-08-06T01:30:00+00:00`."""
    from app.core.tz import format_datetime_br

    assert format_datetime_br(NOITE_DO_DIA_5, "America/Sao_Paulo") == "05/08/2026 22:30"


def test_formata_datetime_naive_assume_utc():
    """SQLite devolve naive mesmo em coluna `timezone=True` (ver notifications/service.py)."""
    from app.core.tz import format_datetime_br

    naive = datetime(2026, 8, 6, 1, 30)
    assert format_datetime_br(naive, "America/Sao_Paulo") == "05/08/2026 22:30"


# ── settings: resolver o fuso a partir da sessão RLS ────────────────────────


def test_tenant_timezone_le_o_perfil_e_tem_default(db: Session, client: TestClient, tenant_id: str):
    from app.modules.settings.service import tenant_timezone

    assert tenant_timezone(db) == "America/Sao_Paulo"


def test_tenant_timezone_respeita_o_fuso_configurado(
    db: Session, client: TestClient, headers: dict[str, str], tenant_id: str
):
    from app.modules.settings import service as settings_service
    from app.modules.settings.service import tenant_timezone

    profile = settings_service.get_profile(db, tenant_id)
    profile.timezone = "America/Manaus"
    db.commit()

    assert tenant_timezone(db) == "America/Manaus"


# ── Os módulos de dinheiro: "hoje" deixa de ser UTC ─────────────────────────


def test_payables_hoje_e_no_fuso_do_tenant(db: Session, client: TestClient, tenant_id: str):
    from app.modules.payables.service import _today

    assert _today(db, now=NOITE_DO_DIA_5) == date(2026, 8, 5)


def test_receivables_hoje_e_no_fuso_do_tenant(db: Session, client: TestClient, tenant_id: str):
    from app.modules.receivables.service import _today

    assert _today(db, now=NOITE_DO_DIA_5) == date(2026, 8, 5)


def test_bank_hoje_e_no_fuso_do_tenant(db: Session, client: TestClient, tenant_id: str):
    from app.modules.bank.service import _today

    assert _today(db, now=NOITE_DO_DIA_5) == date(2026, 8, 5)


def test_projecao_hoje_e_no_fuso_do_tenant(db: Session, client: TestClient, tenant_id: str):
    from app.modules.financial_intelligence.diagnostics import _today

    assert _today(db, now=NOITE_DO_DIA_5) == date(2026, 8, 5)


# ── Texto que o humano lê ───────────────────────────────────────────────────


def test_espera_do_funil_nao_mostra_iso_cru(db: Session, client: TestClient, tenant_id: str):
    """O bug do screenshot: `Aguardando até 2026-08-05T11:11:32.812731+00:00`."""
    from app.modules.funnels.engine import _mensagem_de_espera

    msg = _mensagem_de_espera(db, NOITE_DO_DIA_5)

    assert "05/08/2026 22:30" in msg
    assert "T01:30" not in msg
    assert "+00:00" not in msg


def test_variavel_data_do_contrato_usa_o_dia_local(
    db: Session, client: TestClient, tenant_id: str
):
    """Um contrato assinado na noite do dia 5 não pode sair datado do dia 6."""
    from app.modules.contracts.service import _auto_vars

    auto = _auto_vars(db, tenant_id, None, "Fuso ME", now=NOITE_DO_DIA_5)

    assert auto["DATA"] == "05/08/2026"
