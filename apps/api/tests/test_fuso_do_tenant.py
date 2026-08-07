"""O fuso do tenant vale para "hoje", para "agora" e para todo texto que um humano lê.

Estes testes cobrem a dívida registrada no `CLAUDE.md` §6.1 ("hoje" ancorado em UTC) e o vazamento
de `isoformat()` cru em mensagem de usuário. A janela crítica é sempre a mesma: entre 21:00 e
23:59 em São Paulo (UTC−3) já é o **dia seguinte** em UTC. Um sistema que chama isso de "hoje"
erra a data de vencimento, o atraso, a projeção de caixa e a data impressa num contrato.

Todo teste aqui fixa um instante nessa janela — `2026-08-06T01:30Z` é `2026-08-05 22:30` em São
Paulo. Nada de relógio real: o `now` é parâmetro, mesma disciplina de `core/scheduling.py`.
"""
import ast
import pathlib
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
    """Configura pelo CAMINHO DE PRODUÇÃO (`PATCH /settings/profile`), não escrevendo no model.

    A versão anterior fazia `profile.timezone = ...` — o que fixava o LOCAL DE ARMAZENAMENTO junto
    com o comportamento. Quando o fuso saiu de `tenant_profiles` para `tenants` (migration 0072,
    porque a RLS escondia a coluna das rotas de auth), este teste passou a falhar por gravar numa
    coluna congelada, e não porque `tenant_timezone` tivesse quebrado. Passar pela rota testa a
    mesma coisa sem amarrar o teste à tabela.
    """
    from app.modules.settings.service import tenant_timezone

    r = client.patch("/settings/profile", json={"timezone": "America/Manaus"}, headers=headers)
    assert r.status_code == 200

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


# ── Gate estático: a Vima inteira ancora "hoje" em `hoje_do_tenant` ──────────
#
# O briefing é diário — é o produto onde "que dia é hoje" DECIDE o conteúdo, e onde errar o dia
# não estoura nada: gera o briefing de amanhã hoje, ocupa a unique key `(tenant, usuário, dia)`
# e apaga o de amanhã de verdade. Nenhum teste de comportamento pega isso sem rodar às 21h.
#
# A varredura separa as duas espécies de leitura de relógio, porque só uma é bug:
#   - `datetime.now(UTC)` para carimbar um INSTANTE (`read_at`, `referencia`) é correto e é o
#     que o resto do sistema faz;
#   - `datetime.now(UTC).date()` / `date.today()` para decidir QUE DIA É HOJE é a regressão.
#
# `absences.py` e `composer.py` são puros por contrato (recebem `hoje` e `agora` por parâmetro)
# e por isso não podem ler o relógio de forma NENHUMA — nem instante.

VIMA_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "vima"

# Módulos que não podem tocar no relógio de jeito nenhum: recebem o tempo por parâmetro.
VIMA_PUROS = {"absences.py", "composer.py", "permissions.py"}


def _chamadas_de_relogio(arvore: ast.AST) -> list[tuple[str, ast.expr]]:
    """Devolve `(forma, nó)` para cada leitura de relógio encontrada."""
    achados: list[tuple[str, ast.expr]] = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        alvo = no.func
        if not isinstance(alvo, ast.Attribute):
            continue
        # `date.today()` / `datetime.today()`
        if alvo.attr in {"today", "utcnow"}:
            achados.append((alvo.attr, no))
            continue
        if alvo.attr != "now":
            continue
        # `datetime.now(...)` — é "hoje" se alguém pedir `.date()` do resultado.
        achados.append(("now", no))
    return achados


def _vira_data(arvore: ast.AST, chamada: ast.Call) -> bool:
    """`datetime.now(UTC).date()` — a chamada de relógio virou uma DATA DE CALENDÁRIO."""
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "date"
            and no.func.value is chamada
        ):
            return True
    return False


@pytest.mark.parametrize("caminho", sorted(VIMA_DIR.glob("*.py")), ids=lambda p: p.name)
def test_vima_nunca_deriva_hoje_do_relogio_do_servidor(caminho: pathlib.Path):
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    puro = caminho.name in VIMA_PUROS

    for forma, no in _chamadas_de_relogio(arvore):
        if forma in {"today", "utcnow"} or _vira_data(arvore, no):
            pytest.fail(
                f"{caminho.name}:{no.lineno} deriva 'hoje' do relógio do servidor. "
                "Use `hoje_do_tenant(db)` — em UTC−3, das 21h à meia-noite já é amanhã."
            )
        if puro:
            pytest.fail(
                f"{caminho.name}:{no.lineno} lê o relógio, e este módulo é PURO: "
                "o tempo entra por parâmetro (`hoje`/`agora`), como em core/scheduling.py."
            )


def test_o_gate_da_vima_tem_o_que_varrer():
    """A instanciação obrigatória do gate: um conjunto vazio passaria calado para sempre."""
    arquivos = {p.name for p in VIMA_DIR.glob("*.py")}
    assert VIMA_PUROS <= arquivos
    assert "service.py" in arquivos  # o membro que PODE ler instante, e não pode derivar "hoje"
