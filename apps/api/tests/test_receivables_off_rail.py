"""**Story 8.15 — recebimento fora do trilho (`settle_off_rail`) e as outras QUATRO defesas.**

O buraco que esta story fecha: hoje **não existe caminho nenhum** para o dono dizer *"esta cobrança
caiu direto no meu banco"*. O botão "Marcar paga" foi removido de propósito (só o webhook do
gateway marca pago), então a cobrança paga por fora fica **em aberto para sempre** — o dinheiro não
aparece em lugar nenhum e a régua segue mandando lembrete a quem já pagou.

Cobre:

- **AC1/AC2** a porta, o contrato item a item (`paid_at` = caixa, `competence_date` intocada,
  crédito positivo, `transaction_id` NULL para sempre, `FOR UPDATE`, um commit só);
- **AC5** `received_on` futuro ⇒ `scheduled`, pelo helper **público** `status_por_data` —
  importado, nunca copiado — e `is_overdue` continuando `False`;
- **AC7** `scheduled_cents` no resumo, sem contaminar nenhum dos cinco campos antigos;
- **AC9** conta obrigatória, com o **409 acionável** no mesmo formato da 8.12, mais 404 (conta de
  outro tenant / inexistente), 409 (arquivada) e 422 (`received_on <= opening_date`);
- **AC10** a rota de correção (`PATCH .../payment`): move o movimento, nunca duplica; move o estado
  nas duas direções; recusa cobrança do trilho e cobrança em aberto;
- **AC8 — as defesas 2, 3, 4 e 5**:
    2. **espião que LEVANTA EXCEÇÃO** em `wallet_service.build_transaction`;
    3. contagem de `PlatformEarning` **idêntica** antes/depois;
    4. **webhook atrasado é no-op EXPLÍCITO**, nos dois estados (`paid` e `scheduled`);
    5. `settle_off_rail` recusa com **409** a cobrança que já tem `transaction_id`.

A defesa 1 (a varredura estrutural) mora em `test_invariante_do_trilho.py`. O lado de entrada da
Projeção (AC6) vive em `test_financial_intelligence_projection.py`, junto do resto da Projeção; a
etapa 4 do worker, em `test_worker.py`; o isolamento cross-tenant, em `rls_e2e`.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today
from app.modules.bank.models import BankTransaction
from app.modules.payables import service as payables_service
from app.modules.receivables import service as receivables_service
from app.modules.receivables.models import (
    ALL_STATUSES,
    STATUS_PAID,
    STATUS_SCHEDULED,
    Charge,
)
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import PlatformEarning, Transaction

REGISTER = {
    "legal_name": "Fora do Trilho ME",
    "document": "11444777000161",
    "slug": "foradotrilho",
    "email": "fora@example.com",
    "name": "Fabiana",
    "password": "uma-senha-bem-grande",
}

OUTRO_TENANT = {
    "legal_name": "Vizinha SA",
    "document": "45723174000110",
    "slug": "vizinha",
    "email": "vizinha@example.com",
    "name": "Vera",
    "password": "outra-senha-bem-grande",
}


def _hoje() -> date:
    """A MESMA âncora do service, que desde o PR #78 é o FUSO DO TENANT — nunca UTC cru
    nem `date.today()` local. O tenant de teste fica com o fuso padrão."""
    return tenant_today(DEFAULT_TENANT_TIMEZONE)


# Ancorada em "hoje", nunca num dia fixo: data fixa envelheceria junto com o repositório sem nunca
# quebrar, até quebrar por outro motivo (lição de `test_bank_corte_de_data`).
ABERTURA = _hoje() - timedelta(days=60)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _conta(client: TestClient, headers, **over) -> dict:
    payload = {
        "name": "Itaú PJ",
        "kind": "checking",
        "opening_balance_cents": 10_000_00,
        "opening_date": ABERTURA.isoformat(),
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def conta(client: TestClient, headers) -> dict:
    return _conta(client, headers)


def _cliente(client: TestClient, headers, **over) -> dict:
    payload = {"name": "Joana Ré", "email": "joana@example.com", "document": "52998224725"}
    payload.update(over)
    resp = client.post("/crm/clients", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _charge(client: TestClient, headers, **over) -> dict:
    payload = {
        "kind": "service",
        "method": "pix",
        "amount_cents": 1_000_00,
        "due_date": _hoje().isoformat(),
        "description": "Consultoria",
    }
    payload.update(over)
    resp = client.post("/receivables/charges", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _settle(client, headers, charge_id, *, conta_id, quando: date | None = None):
    body: dict = {"bank_account_id": conta_id}
    if quando is not None:
        body["received_on"] = quando.isoformat()
    return client.post(
        f"/receivables/charges/{charge_id}/settle-externally", json=body, headers=headers
    )


def _corrigir(client, headers, charge_id, **body):
    return client.patch(
        f"/receivables/charges/{charge_id}/payment", json=body, headers=headers
    )


def _webhook(client, tenant_id: str, charge_id: str):
    return client.post(
        "/receivables/webhook",
        json={"tenant_id": tenant_id, "charge_id": charge_id, "status": "paid"},
    )


def _movimento(db: Session, charge_id: str) -> BankTransaction | None:
    return db.scalars(select(BankTransaction).where(BankTransaction.origin_id == charge_id)).first()


# ── AC1/AC5 — o vocabulário e a ausência de migration ────────────────────────────────────────


def test_scheduled_entrou_no_vocabulario_de_charges():
    assert STATUS_SCHEDULED == "scheduled"
    assert ALL_STATUSES == {"open", "scheduled", "paid", "canceled"}


def test_scheduled_cabe_na_coluna_e_por_isso_nao_ha_migration():
    """**AC5 verificado, não presumido** — e a asserção é contra a coluna REAL, não contra o `12`.

    Se alguém "melhorar" o vocabulário para uma string maior, este teste reprova **antes** de a
    linha ser gravada truncada em produção. Ampliar a coluna custa uma migration com `ALTER` sobre
    dado existente sob `FORCE RLS` — a armadilha da 0046.
    """
    coluna = Charge.__table__.c.status
    assert len(STATUS_SCHEDULED) <= coluna.type.length
    assert all(len(s) <= coluna.type.length for s in ALL_STATUSES)


def test_a_story_nao_cria_migration():
    versions = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"
    assert not list(versions.glob("*8_15*")), "esta story não cria migration (AC4)"
    assert not list(versions.glob("*off_rail*"))


def test_receivables_IMPORTA_o_helper_de_derivacao_em_vez_de_reimplementar():
    """**Estrutural, não comportamental — e o mutante que ele mata é invisível de outra forma.**

    Um `receivables/service.py` que reimplementasse `SCHEDULED if received_on > hoje else PAID`
    inline passaria em **todos** os testes de comportamento deste arquivo, e a regra derivada
    passaria a existir em **três** lugares (`payables`, `receivables` e o helper). O teste de AC
    comportamental não distingue os dois mundos; este distingue.
    """
    fonte = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app" / "modules" / "receivables" / "service.py"
    )
    arvore = ast.parse(fonte.read_text(encoding="utf-8"))
    importado = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "app.core.scheduling"
        and any(a.name == "status_por_data" for a in node.names)
        for node in ast.walk(arvore)
    )
    assert importado, (
        "`receivables/service.py` parou de importar `app.core.scheduling.status_por_data`. Se a "
        "regra foi reescrita inline, existem agora DUAS derivações do mesmo estado. Importar, "
        "nunca copiar."
    )
    chamadas = sum(
        1
        for node in ast.walk(arvore)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "status_por_data"
    )
    assert chamadas >= 2, (
        "a derivação é usada em MENOS de dois lugares. `settle_off_rail` e "
        "`update_off_rail_payment` precisam das duas — a correção da data é justamente onde a "
        "fronteira `paid ⇄ scheduled` é atravessada."
    )


def test_a_acao_do_409_e_a_MESMA_string_de_payables():
    """**O contrato do 409 acionável é UM, com duas constantes — e o teste é a sincronia.**

    A string é duplicada de propósito (fazer `receivables` importar `payables` só por uma palavra
    seria acoplamento gratuito entre dois módulos de negócio — o mesmo motivo pelo qual
    `app/core/scheduling.py` nasceu neutro). O que garante que as duas não divirjam é **este
    teste**, não um comentário: a UI reconhece a situação por `acao`, e um segundo valor faria a
    tela de cobranças deixar de abrir o cadastro embutido **sem erro nenhum**, só sem funcionar.
    """
    assert receivables_service.ACAO_CADASTRAR_CONTA == payables_service.ACAO_CADASTRAR_CONTA


# ── AC1/AC2 — a porta e o contrato ───────────────────────────────────────────────────────────


def test_settle_off_rail_marca_paga_e_gera_UM_credito_bancario(
    client: TestClient, headers, conta, db: Session
):
    """O caminho feliz inteiro: status, caixa, competência, ponteiros e o movimento."""
    cliente = _cliente(client, headers)
    charge = _charge(client, headers, client_id=cliente["id"])
    competencia_antes = charge["competence_date"]

    resp = _settle(client, headers, charge["id"], conta_id=conta["id"], quando=_hoje())
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == STATUS_PAID
    assert body["paid_at"][:10] == _hoje().isoformat(), "paid_at é a data de CAIXA informada"
    assert body["competence_date"] == competencia_antes, (
        "o recebimento moveu a competência — caixa e competência nunca se invertem "
        "(`receivables/models.py:6-9`)"
    )
    assert body["transaction_id"] is None, "fora do trilho NUNCA tem transação de carteira"
    assert body["bank_account_id"] == conta["id"]

    movimentos = list(db.scalars(select(BankTransaction)).all())
    assert len(movimentos) == 1
    mov = movimentos[0]
    assert mov.amount_cents == 1_000_00, "entrada é POSITIVA (invariante (b) do modelo)"
    assert mov.posted_at == _hoje()
    assert mov.source == "charge" and mov.origin_id == charge["id"]
    assert mov.status == "matched", "movimento de origem nasce conciliado"
    assert mov.counterparty_name == "Joana Ré"
    assert mov.counterparty_document == "52998224725"
    assert body["bank_transaction_id"] == mov.id


def test_o_evento_da_agenda_vai_para_done_e_a_cobranca_sai_da_regua(
    client: TestClient, headers, conta
):
    """A régua **para** de alcançar a cobrança porque ela não é mais `open` — não por exclusão."""
    charge = _charge(client, headers)
    _settle(client, headers, charge["id"], conta_id=conta["id"])

    eventos = client.get(
        "/agenda/events",
        params={
            "start": (_hoje() - timedelta(days=1)).isoformat() + "T00:00:00Z",
            "end": (_hoje() + timedelta(days=1)).isoformat() + "T23:59:59Z",
        },
        headers=headers,
    ).json()
    do_charge = [e for e in eventos if e["external_ref"] == charge["id"]]
    assert do_charge and do_charge[0]["status"] == "done"

    # E o caminho de cobrança recusa a cobrança liquidada (ela não é mais `open`).
    r = client.post(f"/receivables/charges/{charge['id']}/collect", headers=headers)
    assert r.status_code == 409


def test_settle_off_rail_e_IDEMPOTENTE_e_nao_re_data(client: TestClient, headers, conta, db):
    """Segunda chamada devolve a cobrança inalterada e **não duplica o movimento**.

    A garantia final contra o movimento duplicado não é o `if`: é o índice único parcial
    `uq_bank_transactions_origin (tenant_id, source, origin_id)`, no banco, fail-closed.
    """
    charge = _charge(client, headers)
    ontem = _hoje() - timedelta(days=1)
    primeira = _settle(client, headers, charge["id"], conta_id=conta["id"], quando=ontem).json()

    segunda = _settle(client, headers, charge["id"], conta_id=conta["id"], quando=_hoje())
    assert segunda.status_code == 200
    assert segunda.json()["paid_at"] == primeira["paid_at"], "re-datou numa segunda chamada"
    assert len(list(db.scalars(select(BankTransaction)).all())) == 1


def test_cancelar_cobranca_AGENDADA_e_409_e_o_movimento_nao_fica_orfao(
    client: TestClient, headers, conta, db: Session
):
    """⚠️ **Buraco aberto POR esta story, fechado dentro dela.**

    Antes da 8.15 nenhuma `Charge` tinha perna bancária, e cancelar era só trocar o status. Com o
    `settle_off_rail`, uma cobrança `scheduled` tem um `bank_transaction` de crédito **futuro**:
    cancelá-la sem tocar no movimento deixaria o razão bancário afirmando *"este dinheiro vai
    entrar"* sobre uma cobrança que não existe mais — violação (c) da Regra da Origem, que
    apareceria como um crédito inexplicável em "Agendado para entrar".

    Recusar (409) é a resposta certa: desfazer recebimento fora do trilho está FORA de escopo
    (F-D4) e a rota de correção cobre o erro provável.
    """
    charge = _charge(client, headers)
    _settle(
        client, headers, charge["id"], conta_id=conta["id"], quando=_hoje() + timedelta(days=5)
    )

    resp = client.post(f"/receivables/charges/{charge['id']}/cancel", headers=headers)
    assert resp.status_code == 409
    assert "recebimento registrado" in resp.json()["detail"]

    # E nada mudou: nem o status, nem o movimento.
    assert client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()["status"] == (
        STATUS_SCHEDULED
    )
    assert _movimento(db, charge["id"]) is not None


def test_cobranca_cancelada_e_inexistente(client: TestClient, headers, conta):
    cancelada = _charge(client, headers)
    client.post(f"/receivables/charges/{cancelada['id']}/cancel", headers=headers)
    assert _settle(client, headers, cancelada["id"], conta_id=conta["id"]).status_code == 409
    assert _settle(client, headers, "nao-existe", conta_id=conta["id"]).status_code == 404


# ── AC5 — o estado é derivado da data ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [
        (-30, STATUS_PAID),
        (-1, STATUS_PAID),
        (0, STATUS_PAID),  # ⚠️ A BORDA: hoje é RECEBIDO, não agendado
        (1, STATUS_SCHEDULED),
        (30, STATUS_SCHEDULED),
    ],
)
def test_o_estado_vem_da_data_e_a_borda_de_hoje_e_ESTRITA(
    client: TestClient, headers, conta, dias: int, esperado: str
):
    """`received_on == hoje` ⇒ `paid`; `hoje+1` ⇒ `scheduled`.

    A borda `>` é estrita e é o ponto todo: o movimento bancário de hoje já tem
    `posted_at <= hoje` e portanto já entra em `active_balance_total(until=hoje)`. Tratar hoje como
    agendado faria o mesmo dinheiro ser contado duas vezes na Projeção.
    """
    charge = _charge(client, headers)
    resp = _settle(
        client, headers, charge["id"], conta_id=conta["id"], quando=_hoje() + timedelta(days=dias)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == esperado


def test_sem_received_on_o_default_e_HOJE(client: TestClient, headers, conta):
    """Assimetria DELIBERADA com `payables.apply_paid` (que cai no `due_date`, fundador F10).

    Lá o gesto é *"paguei — provavelmente no vencimento"*; aqui é *"caiu na minha conta"*, um fato
    que o dono está observando **agora**. O teste fixa a diferença para que ninguém a "harmonize".
    """
    charge = _charge(client, headers, due_date=(_hoje() - timedelta(days=20)).isoformat())
    body = _settle(client, headers, charge["id"], conta_id=conta["id"]).json()
    assert body["paid_at"][:10] == _hoje().isoformat()
    assert body["status"] == STATUS_PAID


def test_cobranca_AGENDADA_nao_e_vencida(client: TestClient, headers, conta):
    """`is_overdue` já exige `STATUS_OPEN` — teste explícito, sem mudar a função (AC5).

    A cobrança nasce vencida (vencimento no passado); registrada como recebimento **agendado**, ela
    deixa de ser vencida: o dinheiro tem dia marcado. Sem esta asserção, um `is_overdue` "melhorado"
    para olhar só a data faria a régua cobrar quem já pagou — o defeito que esta story fecha.
    """
    charge = _charge(client, headers, due_date=(_hoje() - timedelta(days=10)).isoformat())
    assert client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()["is_overdue"]

    body = _settle(
        client, headers, charge["id"], conta_id=conta["id"], quando=_hoje() + timedelta(days=3)
    ).json()
    assert body["status"] == STATUS_SCHEDULED
    assert body["is_overdue"] is False


def test_o_movimento_do_agendado_nasce_com_a_data_FUTURA(client: TestClient, headers, conta, db):
    """O crédito futuro entra em "Agendado para entrar", **não** em "Total em contas" (8.10/8.14).

    É o campo `agendado_entrada_cents` que a 8.14 declarou **estruturalmente zero até esta story** —
    aqui ele passa a ter valor, e o saldo corrente segue intocado.
    """
    charge = _charge(client, headers)
    dia = _hoje() + timedelta(days=5)
    _settle(client, headers, charge["id"], conta_id=conta["id"], quando=dia)

    mov = _movimento(db, charge["id"])
    assert mov is not None and mov.posted_at == dia and mov.amount_cents == 1_000_00

    lista = client.get("/bank/accounts", headers=headers).json()
    assert lista[0]["saldo_derivado_cents"] == 10_000_00, (
        "o saldo corrente somou um crédito que ainda não caiu na conta"
    )
    assert lista[0]["agendado_entrada_cents"] == 1_000_00
    assert lista[0]["agendado_saida_cents"] == 0


# ── AC7 — `scheduled_cents` no resumo ────────────────────────────────────────────────────────


def test_summary_sem_agendamento_e_IDENTICO_ao_de_antes(client: TestClient, headers, conta):
    """Snapshot dos cinco campos antigos: a definição de nenhum deles mudou."""
    a_vencer = (_hoje() + timedelta(days=5)).isoformat()
    _charge(client, headers, amount_cents=300_00, due_date=a_vencer)
    vencida = _charge(
        client, headers, amount_cents=200_00, due_date=(_hoje() - timedelta(days=5)).isoformat()
    )
    recebida = _charge(client, headers, amount_cents=100_00)
    _settle(client, headers, recebida["id"], conta_id=conta["id"])

    resumo = client.get("/receivables/summary", headers=headers).json()
    assert resumo == {
        "open_cents": 300_00,
        "overdue_cents": 200_00,
        "paid_cents": 100_00,
        "open_count": 1,
        "overdue_count": 1,
        "scheduled_cents": 0,
    }
    assert vencida["id"]  # (a cobrança vencida existe — pré-condição do `overdue_*` acima)


def test_scheduled_cents_nao_se_mistura_com_NENHUM_dos_cinco(client: TestClient, headers, conta):
    """A agendada sai dos três buckets e aparece **só** no campo novo (AC7).

    Sem `scheduled_cents`, ela desapareceria dos três — `open_cents`/`overdue_cents` exigem
    `STATUS_OPEN` e `paid_cents` exige `STATUS_PAID`. É o mesmo modo de falha "o dinheiro some da
    tela" que esta onda existe para eliminar, numa superfície que o Cockpit e a Ficha 360° já
    consomem.
    """
    agendada = _charge(client, headers, amount_cents=700_00)
    _settle(
        client, headers, agendada["id"], conta_id=conta["id"], quando=_hoje() + timedelta(days=2)
    )

    resumo = client.get("/receivables/summary", headers=headers).json()
    assert resumo["scheduled_cents"] == 700_00
    assert resumo["open_cents"] == 0 and resumo["overdue_cents"] == 0
    assert resumo["paid_cents"] == 0
    assert resumo["open_count"] == 0 and resumo["overdue_count"] == 0


# ── AC9 — conta obrigatória, com o 409 acionável da 8.12 ─────────────────────────────────────


def test_tenant_SEM_conta_recebe_409_ACIONAVEL_no_formato_da_8_12(client: TestClient, headers):
    """O payload é **contrato**: a UI abre o cadastro embutido reconhecendo `acao`, nunca a frase.

    A ordem também é contrato: o 409 vem **antes** de olhar o id recebido. Como `bank_account_id` é
    obrigatório, um tenant sem contas só consegue mandar um id qualquer — e um 404 ali diria "esse
    id não existe" quando o fato é "você ainda não cadastrou conta nenhuma".
    """
    charge = _charge(client, headers)
    resp = _settle(client, headers, charge["id"], conta_id="qualquer-coisa")

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["acao"] == "cadastrar_conta"
    assert detail["mensagem"]
    # E nada foi escrito: a cobrança continua em aberto.
    assert client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()["status"] == (
        "open"
    )


def test_conta_ARQUIVADA_e_409_acionavel_com_a_mensagem_propria(client: TestClient, headers, conta):
    charge = _charge(client, headers)
    outra = _conta(client, headers, name="Conta velha")
    assert client.post(
        f"/bank/accounts/{outra['id']}/archive", headers=headers
    ).status_code == 200

    resp = _settle(client, headers, charge["id"], conta_id=outra["id"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["acao"] == "cadastrar_conta"
    assert "arquivada" in resp.json()["detail"]["mensagem"]


def test_conta_de_OUTRO_TENANT_e_404_fail_closed_nunca_409(client: TestClient, headers, conta):
    """⚠️ **409 confirmaria a existência da linha.** A conta de outro tenant simplesmente não
    existe para quem pergunta (a RLS a esconde) — 404, como o resto do projeto."""
    token = client.post("/auth/register", json=OUTRO_TENANT).json()["access_token"]
    alheia = _conta(client, {"Authorization": f"Bearer {token}"}, name="Conta da Vera")

    charge = _charge(client, headers)
    resp = _settle(client, headers, charge["id"], conta_id=alheia["id"])
    # (no SQLite dos testes unitários não há RLS; o que este teste fixa é o CONTRATO da rota —
    # o isolamento real é exercido em `rls_e2e`, contra Postgres.)
    assert resp.status_code in (404, 200)
    if resp.status_code == 404:
        assert resp.json()["detail"] == "Conta bancária não encontrada"


def test_received_on_ANTES_da_abertura_da_conta_e_422_nomeando_as_duas_saidas(
    client: TestClient, headers, conta
):
    """O **piso** vale igual para entrada e saída — e a mensagem diz o que fazer, não o porquê."""
    charge = _charge(client, headers)
    resp = _settle(client, headers, charge["id"], conta_id=conta["id"], quando=ABERTURA)

    assert resp.status_code == 422
    mensagem = resp.json()["detail"]
    assert "Mova a abertura desta conta" in mensagem and "escolha outra conta" in mensagem


# ══════════════════════════════════════════════════════════════════════════════════════════════
# AS DEFESAS 2, 3, 4 e 5 (AC8) — e nenhuma delas é "tomar cuidado"
# ══════════════════════════════════════════════════════════════════════════════════════════════


def test_recebimento_fora_do_trilho_nao_aciona_split(
    client: TestClient, headers, conta, monkeypatch
):
    """**DEFESA 2 — o espião que LEVANTA EXCEÇÃO, não um mock que conta chamadas.**

    `wallet_service.build_transaction` é monkey-patchado para explodir. Se o caminho fora do trilho
    tocar a Carteira, o teste **explode** — e explode com a mensagem que diz por quê, em vez de
    falhar num `assert_not_called` no fim, depois de o dano já ter sido descrito como "0 chamadas
    esperadas, 1 recebida". Mesmo padrão da IV1 da Story 5.6 (`register_yield`).

    Um mock que conta chamadas provaria a mesma coisa **desde que alguém lembre de olhar o
    contador**; o espião que explode não depende de ninguém lembrar.
    """
    def _explode(*_args, **_kwargs):
        raise AssertionError(
            "REGRA DOS PLANOS VIOLADA: o recebimento fora do trilho chamou "
            "`wallet.build_transaction`. Esse dinheiro nunca passou pela e1p — criar uma "
            "`Transaction` ali aplicaria split 40/30/20 sobre dinheiro alheio e geraria "
            "`PlatformEarning` no ledger GLOBAL do Master."
        )

    monkeypatch.setattr(wallet_service, "build_transaction", _explode)

    charge = _charge(client, headers)
    resp = _settle(client, headers, charge["id"], conta_id=conta["id"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == STATUS_PAID


def test_recebimento_fora_do_trilho_nao_cria_platform_earning(
    client: TestClient, headers, conta, db: Session
):
    """**DEFESA 3 — contábil: a contagem E a soma de `PlatformEarning`, antes e depois.**

    `platform_earnings` é ledger **GLOBAL, sem RLS**, e alimenta o GMV do painel do Master: um
    vazamento ali aparece nos números de **todos** os tenants. Três recebimentos fora do trilho
    (IV1) não podem mover um centavo.
    """
    def _snapshot() -> tuple[int, int]:
        return (
            int(db.scalar(select(func.count(PlatformEarning.id))) or 0),
            int(db.scalar(select(func.coalesce(func.sum(PlatformEarning.fee_cents), 0))) or 0),
        )

    antes = _snapshot()
    for i in range(3):
        charge = _charge(client, headers, amount_cents=(i + 1) * 500_00)
        assert _settle(client, headers, charge["id"], conta_id=conta["id"]).status_code == 200

    assert _snapshot() == antes, (
        "o recebimento fora do trilho mexeu no ledger GLOBAL de ganhos da plataforma"
    )
    # E a Carteira do tenant também ficou byte a byte igual.
    assert wallet_service.wallet_summary(db) == {
        "available_cents": 0,
        "pending_cents": 0,
        "withdrawn_cents": 0,
        "gross_total_cents": 0,
        "fees_total_cents": 0,
    }
    assert list(db.scalars(select(Transaction)).all()) == []


def test_webhook_apos_recebimento_fora_do_trilho_e_noop(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """**DEFESA 4 — o webhook atrasado é no-op, e agora ESCOLHIDO em vez de acidental.**

    Hoje o silêncio vem da guarda de idempotência de reenvio (`if status in (paid, scheduled):
    return`). É o comportamento certo (o dinheiro já está contabilizado), mas **ninguém o escolheu
    para este caso**. Se alguém trocar a idempotência por algo mais fino (ex.: *"reenvio só é no-op
    se o `gateway_charge_id` for o mesmo"*), o webhook passaria a criar `Transaction` +
    `PlatformEarning` sobre dinheiro que nunca passou pela e1p — GMV inflado, sem estorno possível
    (a dívida `platform_earnings → transaction` está aberta). Daí o teste **explícito**.
    """
    charge = _charge(client, headers)
    _settle(client, headers, charge["id"], conta_id=conta["id"])
    antes = client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()

    resp = _webhook(client, tenant_id, charge["id"])
    assert resp.status_code == 200 and resp.json()["status"] == STATUS_PAID

    depois = client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()
    assert depois == antes, "o webhook atrasado alterou a cobrança liquidada fora do trilho"
    assert depois["transaction_id"] is None
    assert list(db.scalars(select(Transaction)).all()) == []
    assert int(db.scalar(select(func.count(PlatformEarning.id))) or 0) == 0


def test_webhook_apos_recebimento_AGENDADO_fora_do_trilho_tambem_e_noop(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """⚠️ **A defesa 4 no estado `scheduled` — a janela que uma guarda só-`paid` deixaria aberta.**

    Uma cobrança liquidada fora do trilho com data futura fica `scheduled` **por dias**, até o
    worker promovê-la. Se a guarda de idempotência olhasse só `STATUS_PAID`, um webhook nessa
    janela criaria `Transaction` + `PlatformEarning` — e o buraco duraria exatamente o tempo entre
    o registro e o dia do crédito, que é quando ele é mais provável.
    """
    charge = _charge(client, headers)
    _settle(
        client, headers, charge["id"], conta_id=conta["id"], quando=_hoje() + timedelta(days=4)
    )
    antes = client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()
    assert antes["status"] == STATUS_SCHEDULED

    resp = _webhook(client, tenant_id, charge["id"])
    assert resp.status_code == 200 and resp.json()["status"] == STATUS_SCHEDULED

    depois = client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()
    assert depois == antes
    assert list(db.scalars(select(Transaction)).all()) == []
    assert int(db.scalar(select(func.count(PlatformEarning.id))) or 0) == 0
    assert len(list(db.scalars(select(BankTransaction)).all())) == 1


def test_settle_off_rail_recusa_cobranca_do_trilho(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """**DEFESA 5 — a direção inversa, e ela NÃO é coberta pela idempotência de status.**

    Uma cobrança já paga pelo trilho tem `status='paid'`: se a guarda de idempotência viesse
    primeiro, a tentativa de "corrigi-la" para fora do trilho devolveria **200 em silêncio** e o
    dono ficaria achando que registrou algo. Pior: um ajuste futuro na ordem das guardas faria a
    mesma chamada escrever `bank_account_id` numa cobrança que **já tem** `transaction_id` — os
    dois ponteiros preenchidos, o mesmo dinheiro existindo nos dois planos.
    """
    charge = _charge(client, headers)
    _webhook(client, tenant_id, charge["id"])
    do_trilho = client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()
    assert do_trilho["transaction_id"] is not None

    resp = _settle(client, headers, charge["id"], conta_id=conta["id"])
    assert resp.status_code == 409
    assert "trilho" in resp.json()["detail"]

    depois = db.get(Charge, charge["id"])
    assert depois.bank_account_id is None and depois.bank_transaction_id is None
    assert _movimento(db, charge["id"]) is None
    # E a invariante segue de pé nos dois sentidos.
    assert (depois.transaction_id is None) != (depois.bank_account_id is None)


# ── AC10 — a rota de correção ────────────────────────────────────────────────────────────────


def test_corrigir_a_conta_MOVE_o_movimento_e_nunca_duplica(
    client: TestClient, headers, conta, db: Session
):
    charge = _charge(client, headers)
    _settle(client, headers, charge["id"], conta_id=conta["id"])
    original = _movimento(db, charge["id"]).id
    outra = _conta(client, headers, name="Nubank PJ")

    resp = _corrigir(client, headers, charge["id"], bank_account_id=outra["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["bank_account_id"] == outra["id"]

    movimentos = list(db.scalars(select(BankTransaction)).all())
    assert len(movimentos) == 1, "trocar a conta DUPLICOU o movimento em vez de movê-lo"
    assert movimentos[0].id == original, "não é a mesma linha — foi delete + recreate"
    assert movimentos[0].bank_account_id == outra["id"]


def test_corrigir_a_data_move_o_ESTADO_nas_duas_direcoes(client: TestClient, headers, conta, db):
    """`paid → scheduled` e de volta, pela **mesma** derivação — nunca uma segunda cópia."""
    charge = _charge(client, headers)
    _settle(client, headers, charge["id"], conta_id=conta["id"], quando=_hoje())

    futuro = _hoje() + timedelta(days=7)
    body = _corrigir(client, headers, charge["id"], received_on=futuro.isoformat()).json()
    assert body["status"] == STATUS_SCHEDULED
    assert _movimento(db, charge["id"]).posted_at == futuro

    body = _corrigir(client, headers, charge["id"], received_on=_hoje().isoformat()).json()
    assert body["status"] == STATUS_PAID
    assert _movimento(db, charge["id"]).posted_at == _hoje()


def test_corrigir_revalida_o_piso_contra_a_conta_de_DESTINO(client: TestClient, headers, conta):
    """A conta pode mudar no MESMO PATCH — o piso vale contra o destino, não contra a origem."""
    charge = _charge(client, headers)
    antiga = _hoje() - timedelta(days=40)
    _settle(client, headers, charge["id"], conta_id=conta["id"], quando=antiga)
    nova = _conta(
        client, headers, name="Conta nova", opening_date=(_hoje() - timedelta(days=10)).isoformat()
    )

    resp = _corrigir(client, headers, charge["id"], bank_account_id=nova["id"])
    assert resp.status_code == 422
    assert "Mova a abertura desta conta" in resp.json()["detail"]


def test_corrigir_recusa_cobranca_DO_TRILHO_e_cobranca_EM_ABERTO(
    client: TestClient, headers, tenant_id, conta
):
    """409 nos dois casos — e as **mensagens são diferentes**, porque os fatos são diferentes.

    ⚠️ **ACHADO POR MUTAÇÃO (M10), e a primeira versão deste teste não pegava.** Ela asseverava só
    `"trilho" in detail`, e a mensagem do caso "em aberto" contém *"fora do trilho"* — ou seja, a
    substring casava nos dois. Removida a guarda de `transaction_id`, a cobrança do trilho ainda
    caía no 409 do caso "em aberto" (porque `bank_account_id` também é nulo nela) e **o teste
    continuava verde com a defesa desligada**.

    A distinção importa além do teste: quem tenta corrigir uma cobrança do trilho precisa ouvir
    *"o dinheiro está na Carteira"*, não *"use a edição da cobrança"* — a segunda frase manda o
    dono para um lugar que não resolve o problema dele.
    """
    aberta = _charge(client, headers)
    r = _corrigir(client, headers, aberta["id"], received_on=_hoje().isoformat())
    assert r.status_code == 409
    assert "edição da cobrança" in r.json()["detail"]

    do_trilho = _charge(client, headers)
    _webhook(client, tenant_id, do_trilho["id"])
    r = _corrigir(client, headers, do_trilho["id"], bank_account_id=conta["id"])
    assert r.status_code == 409
    assert "Carteira" in r.json()["detail"], (
        "a cobrança do trilho recebeu a mensagem do caso 'em aberto' — a guarda de "
        "`transaction_id` em `update_off_rail_payment` sumiu"
    )


def test_corrigir_NAO_toca_a_competencia(client: TestClient, headers, conta):
    """Caixa × competência não se invertem — nem no registro, nem na correção (epic §4.3)."""
    charge = _charge(client, headers)
    _settle(client, headers, charge["id"], conta_id=conta["id"])
    competencia = client.get(
        f"/receivables/charges/{charge['id']}", headers=headers
    ).json()["competence_date"]

    body = _corrigir(
        client, headers, charge["id"], received_on=(_hoje() + timedelta(days=15)).isoformat()
    ).json()
    assert body["competence_date"] == competencia


def test_ChargeUpdate_NAO_ganhou_campo_de_conta_bancaria():
    """**Guarda dupla** (AC10), a mesma disciplina que `bank.update_transaction` documenta.

    O campo não existe no schema genérico **e** `update_charge` não faz `setattr` genérico. Sem
    esta asserção, acrescentar `bank_account_id` a `ChargeUpdate` — uma linha, de aparência
    inofensiva — tornaria a conta bancária editável pelo PATCH genérico, que aceita qualquer
    cobrança **em aberto**: escreveria o ponteiro "fora do trilho" numa cobrança que ninguém
    liquidou, e a Invariante do Trilho quebraria pelo lado de fora do fluxo de dinheiro.
    """
    from app.modules.receivables.schemas import ChargeUpdate

    proibidos = {"bank_account_id", "bank_transaction_id", "status", "paid_at", "received_on"}
    assert proibidos.isdisjoint(ChargeUpdate.model_fields), (
        f"`ChargeUpdate` ganhou um campo que não pode ser editável pelo PATCH genérico: "
        f"{proibidos & set(ChargeUpdate.model_fields)}"
    )


# ── AC12 — a proibição normativa (nenhuma superfície de plataforma) ──────────────────────────


def test_nenhuma_rota_de_admin_menciona_o_recebimento_fora_do_trilho():
    """**AC12 — o NEGATIVO desta story, e ele é normativo** (decisão G-D7).

    O sinal do recebimento fora do trilho é **neutro ao dono e NUNCA reportado ao Master**. A Story
    8.16 entrega o teste que varre `/admin`; esta story **não pode criar o que aquele teste vai
    proibir**. Se a e1p um dia quiser cobrar sobre isto, é decisão comercial com consentimento
    contratual — nunca consequência técnica de uma coluna.
    """
    admin = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "platform"
    fontes = [p.read_text(encoding="utf-8") for p in admin.rglob("*.py")]
    ofensores = [
        termo
        for termo in ("bank_account_id", "settle_off_rail", "off_rail", "fora do trilho")
        if any(termo in fonte for fonte in fontes)
    ]
    assert not ofensores, (
        f"o módulo de plataforma (Master) passou a mencionar {ofensores} — nenhuma superfície de "
        "plataforma nasce sobre `charges.bank_account_id` (epic §2.1, decisão G-D7)."
    )
