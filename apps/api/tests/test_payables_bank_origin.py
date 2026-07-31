"""**Story 8.12 — a baixa de Contas a Pagar gera o movimento bancário.**

É a story que liga a Regra da Origem (8.9) ao primeiro fluxo de negócio real: até aqui
`sync_origin_movement` existia e não tinha chamador nenhum; a partir daqui, **toda** baixa de conta
a pagar escreve o razão bancário, na mesma transação, e o razão para de nascer vazio.

Cobre:

- **AC1** conta bancária OBRIGATÓRIA (sem default, sem `| None`, sem fallback para a primária no
  service); id desconhecido → 404;
- **AC2** o **409 acionável** `{"acao": "cadastrar_conta", "mensagem": ...}` — cujo **formato é
  contrato** consumido pela 8.13/8.15/8.17;
- **AC3** `paid_on` default = `due_date`; **piso** contra a `opening_date`; **teto em hoje**
  (`[CORTE DO @PM]`, sai na 8.14); `paid_at` derivado de `paid_on`;
- **AC4** `competence_date` NÃO se move junto — `test_alterar_data_de_baixa_nao_altera_dre`;
- **AC5** o movimento: valor **negativo**, `posted_at == paid_on`, nasce `matched`, puramente
  sintético, e na MESMA transação da baixa;
- **AC6** idempotência nas três formas (retry, request duplicado, bandeja + `PagarPage`);
- **AC7** `PATCH /bills/{id}/payment` — trocar conta **move** o movimento; trocar data revalida
  contra a conta de DESTINO; `PayableUpdate` intocado;
- **AC8/AC9** estorno **APAGA** o movimento (linha sintética) e **desliga a origem** quando a linha
  já foi enriquecida pela importação; ciclo baixar → estornar → **baixar de novo**;
- **AC10** a bandeja de comprovantes continua funcionando, com a conta primária como substituto
  declarado até a 8.13;
- **AC11/AC12** corpo obrigatório em `/pay`; `PayableOut` expõe o vínculo;
- **IV** DRE/Lucratividade, Conferência (o checkpoint não é tocado), Carteira e a exclusão LGPD.

Isolamento cross-tenant **não** é exercido aqui (SQLite — ver `conftest.py`): a metade autoritativa
do AC13 vive em `test_bank_rls.py` (`rls_e2e`, Postgres real com o papel `e1p_app`).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.bank.models import (
    SOURCE_OFX,
    SOURCE_PAYABLE,
    STATUS_MATCHED,
    STATUS_UNMATCHED,
    BankBalanceCheckpoint,
    BankTransaction,
)
from app.modules.financial_intelligence import dre as dre_service
from app.modules.payables import service as payables_service
from app.modules.payables.models import Payable
from app.modules.payables.schemas import PayableUpdate

REGISTER = {
    "legal_name": "Origem da Baixa ME",
    "document": "11444777000161",
    "slug": "origemdabaixa",
    "email": "baixa@example.com",
    "name": "Bruna",
    "password": "uma-senha-bem-grande",
}

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

ABERTURA = date(2026, 1, 1)
# Vencimento no PASSADO de propósito: é o caso do mutirão das 45 contas do fundador, e é o único em
# que o default do AC3 (`paid_on = due_date`) convive com o teto em hoje sem 422.
VENCIMENTO = date(2026, 6, 10)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _hoje() -> date:
    return datetime.now(UTC).date()


def _conta(client: TestClient, headers, *, name: str = "Itaú PJ", **over) -> dict:
    payload = {
        "name": name,
        "kind": "checking",
        "opening_balance_cents": 1_500_00,
        "opening_date": ABERTURA.isoformat(),
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def conta(client: TestClient, headers) -> dict:
    return _conta(client, headers)


def _bill(client: TestClient, headers, **over) -> dict:
    payload = {
        "description": "Aluguel",
        "category": "Estrutura",
        "supplier": "Imobiliária Central",
        "amount_cents": 120_00,
        "due_date": VENCIMENTO.isoformat(),
    }
    payload.update(over)
    resp = client.post("/payables/bills", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _pay(client: TestClient, headers, bill_id: str, *, conta_id: str, paid_on: date | None = None):
    body: dict = {"bank_account_id": conta_id}
    if paid_on is not None:
        body["paid_on"] = paid_on.isoformat()
    return client.post(f"/payables/bills/{bill_id}/pay", json=body, headers=headers)


def _movimento(db: Session, origin_id: str) -> BankTransaction | None:
    return db.scalars(
        select(BankTransaction).where(
            BankTransaction.source == SOURCE_PAYABLE, BankTransaction.origin_id == origin_id
        )
    ).first()


# ── AC5 / AC1 — a baixa escreve o razão bancário ─────────────────────────────────────────────


def test_baixa_gera_movimento_negativo_ja_conciliado(client: TestClient, headers, conta, db):
    """**O coração da story.** Uma baixa, um movimento — negativo, na data do caixa, conciliado.

    `matched` no nascimento é a única escrita legítima desse status fora do `_refresh_status` da
    conciliação (Onda 5, inexistente): o e1p originou os **dois** lados do fato, então não há
    julgamento de conciliação a fazer.
    """
    bill = _bill(client, headers)
    resp = _pay(client, headers, bill["id"], conta_id=conta["id"])
    assert resp.status_code == 200, resp.text
    out = resp.json()

    tx = _movimento(db, bill["id"])
    assert tx is not None, "a baixa não escreveu o razão bancário — é a story inteira"
    assert tx.amount_cents == -120_00, "conta a pagar é SAÍDA: o valor tem de ser negativo"
    assert tx.posted_at == VENCIMENTO
    assert tx.status == STATUS_MATCHED
    assert tx.source == SOURCE_PAYABLE and tx.origin_id == bill["id"]
    assert tx.bank_account_id == conta["id"]
    assert "Aluguel" in tx.raw_description and "Imobiliária Central" in tx.raw_description
    assert tx.counterparty_name == "Imobiliária Central"
    # Puramente SINTÉTICA — é o que a guarda do estorno (AC9) inspeciona para decidir entre apagar
    # e degradar, e é o que a importação da Onda 4 vai enriquecer.
    assert tx.fitid is None and tx.import_batch_id is None

    # AC12 — o vínculo aparece no schema de saída (a UI da 8.13 depende dele).
    assert out["bank_account_id"] == conta["id"]
    assert out["bank_transaction_id"] == tx.id


def test_baixa_move_o_saldo_derivado(client: TestClient, headers, conta):
    """O objetivo do épico, medido pela superfície que o usuário vê: o saldo se mexe sozinho."""
    antes = client.get(f"/bank/accounts/{conta['id']}/balance", headers=headers).json()
    bill = _bill(client, headers, amount_cents=250_00)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    depois = client.get(f"/bank/accounts/{conta['id']}/balance", headers=headers).json()
    assert depois["saldo_derivado_cents"] == antes["saldo_derivado_cents"] - 250_00


def test_paid_at_deriva_de_paid_on_e_competencia_nao_se_move(
    client: TestClient, headers, conta, db
):
    """**AC3 + AC4** — caixa (`paid_at`) anda com `paid_on`; competência (`competence_date`) não.

    Regra dura de `payables/models.py:6-9`, e a razão de ela estar testada aqui: `paid_at` deixou
    de ser `datetime.now(UTC)` cravado nesta story, e a "melhoria" seguinte mais provável seria
    mover a competência junto — o que reescreveria a DRE de um mês fechado.
    """
    bill = _bill(client, headers, competence_date="2026-05-31")
    dia = VENCIMENTO - timedelta(days=3)
    out = _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=dia).json()

    assert out["paid_at"].startswith(dia.isoformat())
    assert out["competence_date"] == "2026-05-31", "a baixa mexeu na competência"
    assert db.get(Payable, bill["id"]).competence_date == date(2026, 5, 31)


def test_paid_on_ausente_usa_o_vencimento(client: TestClient, headers, conta, db):
    """**AC3, fundador F10** — o default é o VENCIMENTO, não `now()` nem `min(due_date, hoje)`.

    *"deixar habilitado no vencimento, pois se estiver fazendo retroativo, pq não deu certo no
    dia"*. É o caso do mutirão das 45 contas, e é por isso que o default importa.
    """
    bill = _bill(client, headers)
    out = _pay(client, headers, bill["id"], conta_id=conta["id"]).json()
    assert out["paid_at"].startswith(VENCIMENTO.isoformat())
    assert _movimento(db, bill["id"]).posted_at == VENCIMENTO


# ── AC2 — o 409 ACIONÁVEL, cujo FORMATO é contrato ───────────────────────────────────────────


def test_tenant_sem_conta_bancaria_recebe_409_acionavel(client: TestClient, headers):
    """**AC2 — o payload é contrato**, consumido pela 8.13 (cadastro embutido) e pela 8.15/8.17.

    ⚠️ A verificação vem **antes** da resolução do id, e é isso que torna este 409 alcançável a
    partir da rota: `bank_account_id` é obrigatório no corpo, então um tenant sem conta nenhuma só
    consegue mandar um id qualquer — e um 404 ali diria "esse id não existe" quando o fato é "você
    ainda não cadastrou conta nenhuma". Também não vaza existência: com zero contas próprias,
    **todo** id recebe a mesma resposta.
    """
    bill = _bill(client, headers)
    resp = _pay(client, headers, bill["id"], conta_id="uma-conta-qualquer")
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["acao"] == "cadastrar_conta"
    assert isinstance(detail["mensagem"], str) and detail["mensagem"]
    # e a conta continua em aberto: nada foi gravado pela metade
    assert client.get(f"/payables/bills/{bill['id']}", headers=headers).json()["status"] == "open"


def test_conta_desconhecida_e_404_e_nao_409(client: TestClient, headers, conta):
    """**AC1/Task 4** — quem TEM conta e manda um id que não é dele recebe **404**, nunca 409.

    409 confirmaria que a linha existe em algum lugar; a RLS a esconde e o produto responde "não
    existe" (fail-closed), como em todo o resto do projeto. O contraste com o teste acima é o ponto:
    a mesma chamada muda de código de status conforme o tenant tenha ou não conta cadastrada, e é a
    ausência de contas — não o id — que é acionável.
    """
    bill = _bill(client, headers)
    resp = _pay(client, headers, bill["id"], conta_id="id-de-outro-tenant")
    assert resp.status_code == 404, resp.text


def test_conta_arquivada_recebe_409_acionavel(client: TestClient, headers, conta):
    """Conta encerrada não recebe lançamento novo — mesma regra de `bank.create_transaction`.

    É 409 acionável (e não 422) porque a saída para o usuário é a mesma do AC2: escolher/cadastrar
    a conta que ele usa hoje. A 8.13 abre a mesma tela nos dois casos.
    """
    outra = _conta(client, headers, name="Conta antiga", number="99-9")
    assert client.post(
        f"/bank/accounts/{outra['id']}/archive", headers=headers
    ).status_code == 200
    bill = _bill(client, headers)
    resp = _pay(client, headers, bill["id"], conta_id=outra["id"])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["acao"] == "cadastrar_conta"


# ── AC3 — o piso e o teto da data ────────────────────────────────────────────────────────────


def test_data_anterior_a_abertura_da_conta_e_422_com_as_duas_saidas(
    client: TestClient, headers, conta
):
    """**Piso.** O saldo de abertura já contempla tudo até ali — somar antes dobraria o valor.

    A mensagem nomeia as **duas** saídas (AC3), e não só o problema: mover a abertura da conta (com
    o saldo daquele dia) **ou** escolher outra conta. Uma mensagem que só diz "não pode" deixa o
    dono do mutirão sem saber o que fazer com a conta paga em janeiro.
    """
    antiga = ABERTURA - timedelta(days=1)
    bill = _bill(client, headers, due_date=antiga.isoformat())
    resp = _pay(client, headers, bill["id"], conta_id=conta["id"])
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert ABERTURA.isoformat() in detail
    assert "escolha outra conta" in detail
    assert "saldo daquele dia" in detail


def test_data_futura_e_422_e_nao_truncada(client: TestClient, headers, conta):
    """**Teto — `[CORTE DO @PM]`, e ele SAI na Story 8.14.**

    Garante que **nunca exista um `payable` `paid` com data futura** enquanto `scheduled` não
    existir: se `paid`+futuro entrasse primeiro, o backfill das 45 e os agendamentos ficariam no
    mesmo status, separáveis só por um predicado sobre a data — e desmanchar isso depois seria uma
    migration com backfill sob `FORCE RLS`.

    **422, jamais truncado em silêncio para hoje:** gravar uma data que o usuário não informou é
    inventar o fato de caixa (Artigo IV).
    """
    bill = _bill(client, headers)
    amanha = _hoje() + timedelta(days=1)
    resp = _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=amanha)
    assert resp.status_code == 422, resp.text
    assert "futura" in resp.json()["detail"]
    assert client.get(f"/payables/bills/{bill['id']}", headers=headers).json()["status"] == "open"


def test_vencimento_futuro_sem_data_informada_tambem_bate_no_teto(
    client: TestClient, headers, conta
):
    """A consequência **declarada** de combinar o default do AC3 com o teto: conta a vencer exige a
    data em que o dinheiro saiu.

    O default é o vencimento; se o vencimento é futuro, o default é futuro, e o teto recusa. Não é
    um furo do teste — é o comportamento que a 8.14 vem resolver com `scheduled`. Escrito como
    asserção para que a 8.14 saiba exatamente qual linha muda.
    """
    bill = _bill(client, headers, due_date=(_hoje() + timedelta(days=10)).isoformat())
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 422
    # ... e informar o dia em que o dinheiro saiu resolve, sem tela nova.
    assert _pay(
        client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje()
    ).status_code == 200


# ── AC11 — o corpo obrigatório ───────────────────────────────────────────────────────────────


def test_pay_sem_corpo_e_422(client: TestClient, headers, conta):
    """**AC11** — a rota antiga (sem corpo) deixa de existir. É quebra DECLARADA de contrato.

    Os dois consumidores de frontend (`PagarPage.tsx` e `FilaPagamentosPage.tsx`) são consertados
    na Story 8.13: **8.12 e 8.13 formam um par de release.**
    """
    bill = _bill(client, headers)
    assert client.post(f"/payables/bills/{bill['id']}/pay", headers=headers).status_code == 422


# ── AC6 — idempotência, nas três formas ──────────────────────────────────────────────────────


def test_baixa_repetida_nao_cria_segundo_movimento(client: TestClient, headers, conta, db):
    """Retry de request e request duplicado: **um** movimento, `paid_at` não re-datado.

    A garantia final não é o `if p.status == STATUS_PAID`: é o índice único parcial
    `uq_bank_transactions_origin (tenant_id, source, origin_id)`, no banco, fail-closed. A metade
    autoritativa dele (Postgres real) vive em `test_bank_rls.py`.
    """
    bill = _bill(client, headers)
    primeira = _pay(client, headers, bill["id"], conta_id=conta["id"]).json()
    segunda = _pay(client, headers, bill["id"], conta_id=conta["id"]).json()

    assert segunda["paid_at"] == primeira["paid_at"]
    assert segunda["bank_transaction_id"] == primeira["bank_transaction_id"]
    assert db.query(BankTransaction).count() == 1


def test_baixa_pela_bandeja_seguida_da_baixa_pela_tela_nao_duplica(
    client: TestClient, headers, conta, db
):
    """A terceira forma do AC6: **duas portas diferentes**, o mesmo lançamento.

    É o caso real — o dono compartilha o comprovante pelo celular e, depois, esquece e clica em
    "marcar paga" na tela. Um segundo movimento aqui seria dinheiro saindo duas vezes do extrato.
    """
    bill = _bill(client, headers)
    rid = client.post(
        "/payables/receipts",
        files={"file": ("comprovante.png", PNG, "image/png")},
        headers=headers,
    ).json()["id"]
    assert client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": bill["id"], "mark_paid": True},
        headers=headers,
    ).status_code == 200

    depois = _pay(client, headers, bill["id"], conta_id=conta["id"]).json()
    assert db.query(BankTransaction).count() == 1
    assert depois["bank_transaction_id"] == _movimento(db, bill["id"]).id


# ── AC7 — a rota de correção do pagamento ────────────────────────────────────────────────────


def _corrigir(client: TestClient, headers, bill_id: str, **body):
    return client.patch(f"/payables/bills/{bill_id}/payment", json=body, headers=headers)


def test_trocar_a_conta_move_o_movimento_e_nao_duplica(client: TestClient, headers, conta, db):
    """**Regra da Origem (c): move, nunca duplica.** Os dois saldos se corrigem sozinhos.

    O `origin_dedup_hash` é `sha256("{source}|{origin_id}")` **sem a conta**, deliberadamente, para
    que esta troca seja um UPDATE e não uma recriação.
    """
    outra = _conta(client, headers, name="Nubank PJ", number="99-9")
    bill = _bill(client, headers)
    antes = _pay(client, headers, bill["id"], conta_id=conta["id"]).json()

    resp = _corrigir(client, headers, bill["id"], bank_account_id=outra["id"])
    assert resp.status_code == 200, resp.text
    out = resp.json()

    assert db.query(BankTransaction).count() == 1, "trocar a conta DUPLICOU o movimento"
    assert out["bank_transaction_id"] == antes["bank_transaction_id"], "não moveu: recriou"
    assert out["bank_account_id"] == outra["id"]
    assert _movimento(db, bill["id"]).bank_account_id == outra["id"]

    saldo_origem = client.get(f"/bank/accounts/{conta['id']}/balance", headers=headers).json()
    saldo_destino = client.get(f"/bank/accounts/{outra['id']}/balance", headers=headers).json()
    assert saldo_origem["saldo_derivado_cents"] == 1_500_00
    assert saldo_destino["saldo_derivado_cents"] == 1_500_00 - 120_00


def test_trocar_a_data_revalida_contra_a_conta_de_destino(client: TestClient, headers, conta, db):
    """A conta pode mudar **no mesmo PATCH** — então o piso é o da conta de DESTINO, não da atual.

    Sem esta revalidação, um movimento entraria numa conta que só existe no e1p a partir de uma data
    posterior: a linha existiria, o saldo não se moveria, e ninguém entenderia por quê.
    """
    nova = _conta(
        client, headers, name="Conta nova", number="88-8",
        opening_date=(VENCIMENTO + timedelta(days=1)).isoformat(),
    )
    bill = _bill(client, headers)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200

    # A data cabe na conta ATUAL (abertura em janeiro) e NÃO cabe na de destino.
    recusado = _corrigir(client, headers, bill["id"], bank_account_id=nova["id"])
    assert recusado.status_code == 422, recusado.text
    assert _movimento(db, bill["id"]).bank_account_id == conta["id"], "gravou apesar do 422"
    # ⚠️ **O status sozinho NÃO prova a guarda** — achado por MUTAÇÃO (M4 do gate desta story):
    # removendo a revalidação de `update_payment`, o `sync_origin_movement` ainda recusa com 422
    # (ele também aplica o piso), e um teste que olhasse só o código de status ficaria verde. O que
    # muda é a MENSAGEM: só a guarda de `payables` nomeia as **duas saídas** do AC3, e é ela que o
    # usuário precisa ler. Sem esta asserção, o mutante sobrevive.
    assert "escolha outra conta" in recusado.json()["detail"], (
        "a mensagem veio da guarda genérica do módulo `bank`, não da revalidação do AC3 — "
        "`update_payment` deixou de validar a data contra a conta de DESTINO"
    )

    # Com uma data que cabe na conta de destino, passa — e o movimento MOVE inteiro.
    dia = VENCIMENTO + timedelta(days=3)
    aceito = _corrigir(
        client, headers, bill["id"], bank_account_id=nova["id"], paid_on=dia.isoformat()
    )
    assert aceito.status_code == 200, aceito.text
    tx = _movimento(db, bill["id"])
    assert tx.bank_account_id == nova["id"] and tx.posted_at == dia
    assert aceito.json()["paid_at"].startswith(dia.isoformat())


def test_corrigir_pagamento_de_conta_aberta_e_409(client: TestClient, headers, conta):
    """Nesta story a rota aceita **só** `paid` — não há pagamento a corrigir numa conta aberta.

    A 8.14 acrescenta `scheduled` a este conjunto; até lá, o 409 é o que impede a rota de virar um
    segundo caminho de baixa (que nasceria sem o 409 acionável, sem o teto e sem o piso).
    """
    bill = _bill(client, headers)
    resp = _corrigir(client, headers, bill["id"], paid_on=VENCIMENTO.isoformat())
    assert resp.status_code == 409, resp.text


def test_payable_update_nao_ganhou_campo_de_conta_bancaria():
    """**AC7 — a guarda é DUPLA, de propósito** (a mesma disciplina de `bank.update_transaction`).

    O campo não existe no schema genérico **e** nenhuma função faz `setattr` genérico. Mantendo o
    PATCH genérico intacto, ninguém torna um campo editável em conta paga por acidente — que é
    exatamente como uma coluna imutável deixa de ser.
    """
    proibidos = {"bank_account_id", "bank_transaction_id", "paid_on", "paid_at"}
    assert not (proibidos & set(PayableUpdate.model_fields)), (
        "`PayableUpdate` ganhou um campo de pagamento. A correção do pagamento tem rota e schema "
        "próprios (`PATCH /bills/{id}/payment` + `PayablePaymentUpdate`) — ver AC7."
    )


def test_patch_generico_nao_altera_o_vinculo_bancario(client: TestClient, headers, conta, db):
    """A metade de comportamento da guarda acima: mandar o campo no PATCH genérico não o grava."""
    bill = _bill(client, headers)
    pago = _pay(client, headers, bill["id"], conta_id=conta["id"]).json()
    client.patch(
        f"/payables/bills/{bill['id']}",
        json={"bank_account_id": "conta-plantada", "competence_date": "2026-06-30"},
        headers=headers,
    )
    assert db.get(Payable, bill["id"]).bank_account_id == pago["bank_account_id"]


# ── AC8 / AC9 — o estorno APAGA ──────────────────────────────────────────────────────────────


def test_estorno_apaga_o_movimento(client: TestClient, headers, conta, db):
    """**AC8** — some de verdade; não vira `ignored`, não ganha contrapartida.

    Um movimento bancário é a afirmação *"este dinheiro saiu desta conta"*. Estornado o pagamento,
    o sistema **não afirma mais isso** — e manter a linha com uma etiqueta seria manter uma
    afirmação falsa. A trilha não se perde: ela mora em `audit_entries`.
    """
    bill = _bill(client, headers)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    assert db.query(BankTransaction).count() == 1

    resp = client.post(f"/payables/bills/{bill['id']}/reverse", headers=headers)
    assert resp.status_code == 200, resp.text
    out = resp.json()

    assert db.query(BankTransaction).count() == 0, (
        "o movimento sobreviveu ao estorno — se virou `ignored`, o repagamento vai colidir com o "
        "índice único e o extrato continua afirmando uma saída que não aconteceu"
    )
    assert out["bank_account_id"] is None and out["bank_transaction_id"] is None
    assert out["status"] == "open" and out["paid_at"] is None
    # O saldo derivado volta ao ponto de partida — sem contrapartida inventada.
    saldo = client.get(f"/bank/accounts/{conta['id']}/balance", headers=headers).json()
    assert saldo["saldo_derivado_cents"] == 1_500_00


def test_estorno_de_linha_ja_enriquecida_desliga_a_origem_em_vez_de_apagar(
    client: TestClient, headers, conta, db
):
    """**AC9 — o ramo INALCANÇÁVEL hoje, montado à mão, a partir de `reverse_payable`.**

    Se a linha já tiver sido casada com o extrato (Onda 4, `fitid`/`import_batch_id` preenchidos),
    apagar destruiria evidência bancária que não volta. O estorno então **desliga a origem** e a
    linha vira órfã do extrato — o que é verdade: o dinheiro saiu mesmo; o sistema é que não sabe
    mais por quê. **Degradação honesta.**

    Este é o tipo de código cuja ausência não dá erro: dá um DELETE bem-sucedido em cima de uma
    evidência que não voltava.
    """
    bill = _bill(client, headers)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    tx = _movimento(db, bill["id"])
    tx.fitid = "FITID-DO-BANCO-123"  # ← o enriquecimento que a Onda 4 fará
    db.commit()

    assert client.post(f"/payables/bills/{bill['id']}/reverse", headers=headers).status_code == 200
    db.expire_all()

    sobrevivente = db.get(BankTransaction, tx.id)
    assert sobrevivente is not None, "apagou uma linha que carregava evidência do extrato"
    assert sobrevivente.origin_id is None
    assert sobrevivente.source == SOURCE_OFX
    assert sobrevivente.status == STATUS_UNMATCHED
    # O cache do lançamento zera junto: o `payable` não aponta mais para um movimento alheio.
    assert db.get(Payable, bill["id"]).bank_transaction_id is None


def test_ciclo_baixar_estornar_baixar(client: TestClient, headers, conta, db):
    """**A prova mecânica de por que o estorno APAGA** (AC8, terceira razão).

    Com `ignored`, a segunda baixa produziria uma segunda linha com a mesma
    `(tenant_id, source, origin_id)` e o banco recusaria — o repagamento seria **impossível**. Com
    o DELETE, ele é trivial. É este o teste que cai se alguém "melhorar" o estorno para `ignored`.
    """
    bill = _bill(client, headers)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    assert client.post(f"/payables/bills/{bill['id']}/reverse", headers=headers).status_code == 200

    de_novo = _pay(client, headers, bill["id"], conta_id=conta["id"])
    assert de_novo.status_code == 200, de_novo.text
    assert db.query(BankTransaction).count() == 1
    assert de_novo.json()["bank_transaction_id"] == _movimento(db, bill["id"]).id


def test_estorno_nao_acrescenta_trilha_de_auditoria_nova(client: TestClient, headers, conta, db):
    """`payable.reverse` continua sendo o rastro do estorno — o movimento tem o seu, no módulo bank.

    A story é explícita: **não acrescentar trilha nova**. O que importa é que a auditoria do DELETE
    exista (`bank.origin.delete`, gravada pelo sincronizador) sem duplicar a do lançamento.
    """
    from app.core.audit import AuditEntry

    bill = _bill(client, headers)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    assert client.post(f"/payables/bills/{bill['id']}/reverse", headers=headers).status_code == 200

    acoes = [a.action for a in db.scalars(select(AuditEntry)).all()]
    assert acoes.count("payable.reverse") == 1
    assert "bank.origin.delete" in acoes


# ── AC10 — a bandeja de comprovantes (IV1) ───────────────────────────────────────────────────


def _upload(client: TestClient, headers) -> str:
    resp = client.post(
        "/payables/receipts",
        files={"file": ("comprovante.png", PNG, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_bandeja_usa_a_conta_primaria_e_gera_o_movimento(client: TestClient, headers, conta, db):
    """**AC10** — o share sheet do Android e o Atalho do iOS passam a alimentar o razão bancário
    **sem uma linha de tela nova**.

    A conta primária é substituto declarado (`[SUPOSIÇÃO DO @SM]` + `TODO(8.13)`), e a data é
    **hoje** — que é exatamente o que o `datetime.now(UTC)` fazia antes desta story, então a
    bandeja não muda de comportamento (IV1).
    """
    bill = _bill(client, headers)
    rid = _upload(client, headers)
    resp = client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": bill["id"], "mark_paid": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"

    tx = _movimento(db, bill["id"])
    assert tx is not None and tx.bank_account_id == conta["id"]
    assert tx.posted_at == _hoje()
    assert tx.amount_cents == -120_00


def test_bandeja_sem_conta_primaria_devolve_409_acionavel(client: TestClient, headers):
    """**O MESMO 409** da rota de pagamento — não um formato próprio da bandeja.

    Dois formatos de erro para a mesma situação obrigariam a UI da 8.13 a tratar cada porta de um
    jeito. E não escolhemos uma conta qualquer no lugar da primária: escolher o destino do dinheiro
    do usuário sem ele pedir é o tipo de "ajuda" que só se descobre quando o dinheiro já foi para o
    lugar errado.
    """
    bill = _bill(client, headers)
    rid = _upload(client, headers)
    resp = client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": bill["id"], "mark_paid": True},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["acao"] == "cadastrar_conta"
    # E o comprovante continua na bandeja: nada foi gravado pela metade.
    assert [i["id"] for i in client.get("/payables/receipts", headers=headers).json()] == [rid]


def test_bandeja_sem_baixa_nao_exige_conta_bancaria(client: TestClient, headers):
    """`mark_paid=False` só arquiva o comprovante — e não pode passar a exigir conta bancária.

    O contra-exemplo da regra do AC1: a conta é obrigatória **na baixa**, não em tudo que a bandeja
    faz. Sem este teste, o 409 poderia migrar para o caminho de anexar e ninguém notaria.
    """
    bill = _bill(client, headers)
    rid = _upload(client, headers)
    resp = client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": bill["id"], "mark_paid": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "open"


# ── Integration Verification ─────────────────────────────────────────────────────────────────


def _dre(db: Session) -> dict:
    return asdict(dre_service.dre_report(db, start=date(2026, 6, 1), end=date(2026, 6, 30)))


def test_movimento_bancario_nao_altera_dre(client: TestClient, headers, conta, db):
    """**IV2** — snapshot campo a campo: dar a baixa (e gerar o movimento) não move a DRE.

    A DRE agrega por **competência** e filtra `status != canceled`. O movimento de extrato não é
    receita nem despesa de competência — se entrasse na DRE, entraria como número inventado.
    `profitability.py` deriva da DRE, logo está coberto pelo mesmo snapshot.
    """
    bill = _bill(client, headers, competence_date="2026-06-15")
    antes = _dre(db)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    assert _dre(db) == antes


def test_alterar_data_de_baixa_nao_altera_dre(client: TestClient, headers, conta, db):
    """**IV2/AC4 — o teste nomeado pelo design.** Mudar a data do CAIXA não mexe na COMPETÊNCIA.

    `paid_on` move fluxo de caixa, projeção e o `bank_transaction`; **não** move a DRE nem a
    Lucratividade. Snapshot antes/depois, idêntico campo a campo.
    """
    bill = _bill(client, headers, competence_date="2026-06-15")
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    antes = _dre(db)

    assert _corrigir(
        client, headers, bill["id"], paid_on=(VENCIMENTO + timedelta(days=20)).isoformat()
    ).status_code == 200
    assert _dre(db) == antes, (
        "a DRE mudou ao corrigir a DATA DA BAIXA. Caixa é `paid_at`, competência é "
        "`competence_date` — nunca inverter (payables/models.py:6-9)."
    )


def test_nenhum_caminho_desta_story_escreve_checkpoint(client: TestClient, headers, conta, db):
    """**IV6 / Regra 5** — a divergência só pode diminuir porque o SISTEMA passou a saber mais.

    O checkpoint é a verdade EXTERNA e não é corrigido por nada. Se a baixa (ou o estorno)
    escrevesse um checkpoint "de ajuste", a divergência iria a zero por construção e o épico
    perderia a métrica que o justifica.
    """
    bill = _bill(client, headers)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    assert _corrigir(client, headers, bill["id"], paid_on=VENCIMENTO.isoformat()).status_code == 200
    assert client.post(f"/payables/bills/{bill['id']}/reverse", headers=headers).status_code == 200
    assert db.query(BankBalanceCheckpoint).count() == 0


def test_baixa_nao_toca_a_carteira(client: TestClient, headers, conta, db):
    """**IV5** — `payables` nunca tocou a Carteira e continua não tocando (plano 2 × plano 3)."""
    from app.modules.wallet.models import Transaction

    bill = _bill(client, headers)
    assert _pay(client, headers, bill["id"], conta_id=conta["id"]).status_code == 200
    assert db.query(Transaction).count() == 0


def test_payables_e_movimentos_estao_na_purga_de_exclusao_de_conta():
    """**IV10 (LGPD), como asserção ESTRUTURAL.**

    `platform.delete_account` purga **dinamicamente** as subclasses de `TenantMixin` — mas
    "dinamicamente" é uma afirmação sobre código que muda. Esta story faz `payables` e
    `bank_transactions` carregarem, juntas, o retrato de quem o dono pagou e de que conta saiu o
    dinheiro; nenhuma das duas pode sobreviver à exclusão da conta.

    A metade de COMPORTAMENTO da purga (o `DELETE` de fato) já é exercida em
    `test_platform.py::test_delete_account_purges_and_writes_platform_log`, que inclui
    `bank_transactions`; aqui garantimos que as duas tabelas continuam **dentro** do conjunto que
    aquela purga varre.
    """
    from app.modules.platform.service import _business_table_names

    tabelas = _business_table_names()
    assert {"payables", "bank_transactions"} <= tabelas


def test_apply_paid_continua_sem_commitar(client: TestClient, headers, conta, db, tenant_id):
    """**Contrato herdado** — e é ele que faz a bandeja funcionar num commit só.

    `apply_paid` não commita e `sync_origin_movement` não commita: a baixa, o anexo e o movimento
    entram na MESMA transação. Um dos dois sem o outro é exatamente o estado que esta onda existe
    para tornar impossível — por isso o rollback tem de levar os **dois** embora.
    """
    bill = _bill(client, headers)
    payables_service.apply_paid(
        db,
        payable_id=bill["id"],
        tenant_id=tenant_id,
        actor="dono",
        bank_account_id=conta["id"],
    )
    assert _movimento(db, bill["id"]) is not None  # existe na transação aberta
    db.rollback()
    db.expire_all()

    assert db.get(Payable, bill["id"]).status == "open"
    assert _movimento(db, bill["id"]) is None, (
        "o movimento sobreviveu ao rollback da baixa — algum caminho commitou por conta própria"
    )
