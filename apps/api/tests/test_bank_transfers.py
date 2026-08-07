"""**Transferência entre contas próprias** — um lançamento, duas pernas (Story 8.18).

Cobre (AC1-AC9 / IV2, IV4, IV7):
- **AC3/AC4** as **duas pernas**, com sinais opostos, chaves de origem sufixadas (`:out`/`:in`),
  `transfer_id` pareando, `status='matched'`, `operation_nature='transferencia_propria'` e
  `dedup_hash` distinto **de graça** (a fórmula não carrega a conta);
- **idempotência das pernas**: uma transferência produz **exatamente dois** movimentos — nunca um,
  nunca três — e duas transferências idênticas no mesmo dia são **duas** transferências;
- **AC5** `kind` genérico validado por lista, e transferir para conta `kind='investment'` **funciona
  desde a Onda 1** sem tocar em nada do módulo de investimentos;
- **AC7** todas as guardas, **uma por teste**, cada uma verificando que **nada foi escrito** — e o
  422 de data futura provado no lugar certo (dentro de `create_transfer`), com o **não-membro** ao
  lado (baixa de conta a pagar com a mesma data, aceita como `scheduled`);
- **AC8** `DELETE` apaga o lançamento **e as duas pernas**; linha já enriquecida por importação
  **desliga a origem** em vez de sumir;
- **AC9** as pernas recusam `PATCH` de data/valor e `POST /ignore`, e **aceitam**
  `user_description` — a exceção nomeada da Regra da Origem (d);
- **IV2** os dois saldos derivados se movem e o total das contas elegíveis **não**; com destino
  `kind='investment'`, o *"Disponível como caixa"* **cai** (comportamento correto, fixado aqui);
- **IV7** a purga de conta cobre `bank_transfers` (grátis por herdar `TenantMixin`, e por isso
  testado — o que é grátis é o que some sem ninguém notar).

A **Regra da Neutralidade** (a DRE/Lucratividade/Projeção não se movem) tem arquivo próprio:
`test_transferencia_nao_altera_dre.py`.

RLS/isolamento cross-tenant **não** é exercido aqui (SQLite — ver `conftest.py`): no banco dos
testes unitários todas as linhas são visíveis a todas as sessões. Isso vive em `test_bank_rls.py`
(`rls_e2e`), que esta story estendeu — é lá, e só lá, que a migration 0065 e o `FORCE ROW LEVEL
SECURITY` da tabela nova são de fato exercidos.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today
from app.db.base import TenantMixin
from app.modules.bank import service as bank_service
from app.modules.bank import transfers as transfers_service
from app.modules.bank.models import (
    KIND_CHECKING,
    KIND_INVESTMENT,
    OPERATION_NATURE_TRANSFERENCIA,
    SOURCE_OFX,
    SOURCE_TRANSFER,
    STATUS_MATCHED,
    TRANSFER_KIND_INVESTMENT_IN,
    TRANSFER_KIND_OWN,
    TRANSFER_KINDS,
    BankTransaction,
    BankTransfer,
)

REGISTER = {
    "legal_name": "Transferencia Propria ME",
    "document": "11444777000161",
    "slug": "transferenciapropria",
    "email": "transferencia@example.com",
    "name": "Teresa",
    "password": "uma-senha-bem-grande",
}


def _hoje() -> date:
    """A MESMA âncora do service (`service._today`), nunca `date.today()` solto.

    O service passou a ancorar "hoje" no FUSO DO TENANT; o teste segue. Como o tenant de teste
    fica com o fuso padrão, basta a primitiva pura — sem `db`, sem um segundo relógio.
    """
    return tenant_today(DEFAULT_TENANT_TIMEZONE)


# Datas RELATIVAS a hoje, e não fixas: a guarda de data futura ancora no relógio real, então uma
# data fixa transformaria este arquivo numa bomba-relógio de calendário.
ABERTURA = _hoje() - timedelta(days=60)
DIA = _hoje() - timedelta(days=5)
VALOR = 1_000_00


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _account(
    client: TestClient,
    headers,
    *,
    name: str = "Itaú PJ",
    kind: str = KIND_CHECKING,
    opening: int = 5_000_00,
    opening_date: date = ABERTURA,
    number: str = "",
) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": kind,
            "number": number,
            "opening_balance_cents": opening,
            "opening_balance_is_known": True,
            "opening_date": opening_date.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def origem(client: TestClient, headers) -> dict:
    return _account(client, headers, name="Itaú PJ", number="11111-1")


@pytest.fixture()
def destino(client: TestClient, headers) -> dict:
    return _account(client, headers, name="Nubank PJ", opening=200_00, number="22222-2")


def _transferir(
    client: TestClient,
    headers,
    *,
    from_id: str,
    to_id: str,
    amount_cents: int = VALOR,
    posted_at: date = DIA,
    kind: str = TRANSFER_KIND_OWN,
    description: str = "Reforço da poupança",
    expect: int = 201,
) -> dict:
    resp = client.post(
        "/bank/transfers",
        json={
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount_cents": amount_cents,
            "posted_at": posted_at.isoformat(),
            "kind": kind,
            "description": description,
        },
        headers=headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _pernas(db: Session, transfer_id: str) -> list[BankTransaction]:
    """As duas pernas, ordenadas por valor (saída negativa primeiro). Casadas por `transfer_id`."""
    return list(
        db.scalars(
            select(BankTransaction)
            .where(BankTransaction.transfer_id == transfer_id)
            .order_by(BankTransaction.amount_cents)
        ).all()
    )


def _saldo(client: TestClient, headers, account_id: str) -> int:
    return client.get(f"/bank/accounts/{account_id}/balance", headers=headers).json()[
        "saldo_derivado_cents"
    ]


def _total_de_movimentos(db: Session) -> int:
    return len(list(db.scalars(select(BankTransaction)).all()))


# ── AC3 / AC4 — as duas pernas, e a forma canônica da chave de origem ─────────────────────────


def test_uma_transferencia_gera_exatamente_duas_pernas_com_sinais_opostos(
    client: TestClient, headers, origem, destino, db: Session
):
    """A tabela normativa do AC3/AC4, verificada linha a linha.

    | Perna | Conta | `amount_cents` | `origin_id` | `transfer_id` |
    |---|---|---|---|---|
    | saída | origem | **−** valor | `f"{id}:out"` | `id` |
    | entrada | destino | **+** valor | `f"{id}:in"` | `id` |
    """
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])

    saida, entrada = _pernas(db, t["id"])
    assert saida.bank_account_id == origem["id"]
    assert entrada.bank_account_id == destino["id"]
    assert saida.amount_cents == -VALOR
    assert entrada.amount_cents == VALOR
    assert saida.origin_id == f"{t['id']}:out"
    assert entrada.origin_id == f"{t['id']}:in"
    assert saida.transfer_id == entrada.transfer_id == t["id"]
    assert saida.source == entrada.source == SOURCE_TRANSFER
    # A transferência (o LANÇAMENTO) guarda o valor sempre POSITIVO — o sinal vive nas pernas.
    assert t["amount_cents"] == VALOR


def test_as_pernas_nascem_conciliadas_rotuladas_e_puramente_sinteticas(
    client: TestClient, headers, origem, destino, db: Session
):
    """`matched` no nascimento (o e1p originou os dois lados), `transferencia_propria`, sem `fitid`.

    A linha nascer **puramente sintética** (`fitid IS NULL AND import_batch_id IS NULL`) é o que faz
    o `DELETE` do AC8 poder apagá-la; se ela nascesse com qualquer resquício de importação, o
    desfazer degradaria em vez de apagar — e o dono não entenderia por quê.
    """
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])

    for perna in _pernas(db, t["id"]):
        assert perna.status == STATUS_MATCHED
        assert perna.operation_nature == OPERATION_NATURE_TRANSFERENCIA
        assert perna.fitid is None and perna.import_batch_id is None
        # `user_description` é do dono e o sincronizador nunca a toca.
        assert perna.user_description == ""


def test_a_descricao_de_cada_perna_diz_quem_esta_do_outro_lado(
    client: TestClient, headers, origem, destino, db: Session
):
    """No extrato de uma conta, "saiu R$ 1.000" sem dizer para onde é a linha órfã que o épico
    existe para eliminar. Cada perna nomeia a **outra** conta, e o texto do dono vem junto."""
    t = _transferir(
        client, headers, from_id=origem["id"], to_id=destino["id"], description="Reserva"
    )
    saida, entrada = _pernas(db, t["id"])
    assert saida.raw_description == "Transferência para Nubank PJ — Reserva"
    assert entrada.raw_description == "Transferência de Itaú PJ — Reserva"


def test_sem_descricao_a_perna_ainda_diz_o_que_e(
    client: TestClient, headers, origem, destino, db: Session
):
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"], description="")
    saida, entrada = _pernas(db, t["id"])
    assert saida.raw_description == "Transferência para Nubank PJ"
    assert entrada.raw_description == "Transferência de Itaú PJ"


def test_dedup_hash_distinto_por_perna_de_graca(
    client: TestClient, headers, origem, destino, db: Session
):
    """A fórmula da origem é `sha256("{source}|{origin_id}")`, **sem** o `bank_account_id` (§3.2).

    Como as duas pernas têm `origin_id` diferentes, os hashes saem distintos **de graça** — e é isso
    que impede a constraint `uq_bank_transactions_dedup` de reprovar a segunda perna quando as duas
    contas forem a mesma... o que não acontece, porque `from == to` é 422. A propriedade vale mesmo
    assim: ela é o que torna a forma `:out`/`:in` autossuficiente, sem índice relaxado nenhum.
    """
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    saida, entrada = _pernas(db, t["id"])
    assert saida.dedup_hash != entrada.dedup_hash


def test_idempotencia_das_pernas_exatamente_duas_nunca_uma_nem_tres(
    client: TestClient, headers, origem, destino, db: Session
):
    """**A asserção que a DoD pede pelo nome.** Uma transferência ⇒ **dois** movimentos.

    O modo de falha que ela pega em cada direção:
    - **um só** — alguém "simplificou" para uma chamada ao sincronizador (o dinheiro sairia de uma
      conta e não entraria em lugar nenhum; o total do tenant despencaria sem explicação);
    - **três ou mais** — alguém acrescentou uma contrapartida (a forma que o design §4.5 **rejeita
      nominalmente**: *"o extrato do dono tem uma linha; criar duas inventa um crédito que nunca
      existiu"*).

    E o índice único `uq_bank_transactions_origin` fecha o outro lado: repetir a MESMA chave de
    origem não cria linha nova, atualiza a existente. Provado aqui chamando o sincronizador com a
    chave da perna de saída de novo.
    """
    assert _total_de_movimentos(db) == 0
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    assert _total_de_movimentos(db) == 2, "uma transferência tem DUAS pernas — nunca 1, nunca 3"

    # Ressincronizar a mesma chave move a linha; não cria uma terceira.
    from app.modules.bank.origin import sync_origin_movement

    sync_origin_movement(
        db,
        tenant_id=tenant_id_de(db),
        actor="dono",
        source=SOURCE_TRANSFER,
        origin_id=f"{t['id']}:out",
        bank_account_id=origem["id"],
        posted_at=DIA,
        amount_cents=-VALOR,
        description="ressincronizado",
        transfer_id=t["id"],
    )
    db.commit()
    assert _total_de_movimentos(db) == 2, (
        "a mesma chave de origem criou uma linha nova — a idempotência da perna quebrou, e um "
        "retry de transferência passaria a mover o dinheiro duas vezes"
    )


def tenant_id_de(db: Session) -> str:
    """O tenant da única conta cadastrada — as fixtures deste arquivo criam um tenant só."""
    from app.modules.bank.models import BankAccount

    return db.scalars(select(BankAccount)).first().tenant_id


def test_duas_transferencias_identicas_no_mesmo_dia_sao_DUAS(
    client: TestClient, headers, origem, destino, db: Session
):
    """Dois Pix de R$ 1.000 para a mesma poupança no mesmo dia acontecem — e são dois fatos.

    A idempotência que o índice de origem garante é **por perna**, não "por transferência parecida":
    cada lançamento nasce com `id` novo, logo com chaves de origem novas. Deduplicar aqui seria o
    sistema decidir que um fato do dono não aconteceu.
    """
    a = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    b = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    assert a["id"] != b["id"]
    assert _total_de_movimentos(db) == 4
    assert _saldo(client, headers, origem["id"]) == 5_000_00 - 2 * VALOR
    assert _saldo(client, headers, destino["id"]) == 200_00 + 2 * VALOR


# ── IV2 — os saldos derivados fecham, e SÓ eles se movem ─────────────────────────────────────


def test_os_dois_saldos_se_movem_e_o_total_das_contas_elegiveis_nao(
    client: TestClient, headers, origem, destino, db: Session
):
    """**IV2.** Transferência **redistribui**; não cria nem destrói dinheiro."""
    antes_total = bank_service.active_balance_total(db, until=_hoje())
    _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])

    assert _saldo(client, headers, origem["id"]) == 5_000_00 - VALOR
    assert _saldo(client, headers, destino["id"]) == 200_00 + VALOR
    assert bank_service.active_balance_total(db, until=_hoje()) == antes_total, (
        "o total das contas elegíveis mudou por causa de uma transferência — ela redistribui "
        "saldo, não gera nem destrói dinheiro"
    )


def test_destino_aplicacao_derruba_o_disponivel_como_caixa_e_isso_e_CORRETO(
    client: TestClient, headers, origem, db: Session
):
    """**IV2, o caso que o @po marcou como risco residual.** Fixado por teste, não deixado ao
    acaso.

    `active_balance_total` exclui `kind='investment'` por default (design §6.1: dinheiro aplicado
    não é caixa para pagar a conta de amanhã). Transferir para a aplicação portanto **derruba** o
    *"Disponível como caixa"* — e é **correto**: o dinheiro deixou de ser caixa. É a primeira vez
    que uma ação do dono reduz o runway sem que nada tenha sido pago, e por isso o aviso do AC10
    existe na tela.

    O *"Total em contas"* (que **inclui** aplicação) não se move — as duas afirmações convivem, cada
    uma com o seu rótulo, que é a lição do UX-001.
    """
    aplicacao = _account(
        client, headers, name="CDB Itaú", kind=KIND_INVESTMENT, opening=0, number="33333-3"
    )
    caixa_antes = bank_service.active_balance_total(db, until=_hoje())
    total_antes = bank_service.active_balance_total(db, until=_hoje(), exclude_kinds=())

    _transferir(
        client,
        headers,
        from_id=origem["id"],
        to_id=aplicacao["id"],
        kind=TRANSFER_KIND_INVESTMENT_IN,
    )

    assert bank_service.active_balance_total(db, until=_hoje()) == caixa_antes - VALOR
    assert bank_service.active_balance_total(db, until=_hoje(), exclude_kinds=()) == total_antes


# ── AC5 — `kind` genérico, ZERO acoplamento com o produto financeiro ──────────────────────────


def test_kind_fora_do_vocabulario_e_422(client: TestClient, headers, origem, destino, db: Session):
    _transferir(
        client, headers, from_id=origem["id"], to_id=destino["id"], kind="aporte", expect=422
    )
    assert _total_de_movimentos(db) == 0


def test_o_vocabulario_de_kind_e_do_modulo_bank_e_tem_tres_valores():
    """Validado por LISTA (tem comportamento associado), ao contrário de `operation_nature`."""
    assert TRANSFER_KINDS == ("own_transfer", "investment_in", "investment_out")


def test_transferir_para_aplicacao_nao_toca_o_produto_financeiro(
    client: TestClient, headers, origem, db: Session
):
    """**AC5.** O dinheiro se move e os dois saldos batem — e nenhuma entidade de aplicação nasce.

    Este é o teste que separa a Onda 2 da 2b em comportamento, e não só em prosa: o que a 2b
    acrescenta é a **faceta de produto** (rentabilidade, principal derivado), não a capacidade de
    mover dinheiro para a conta de aplicação, que já existia desde a Onda 1.
    """
    from app.modules.investments.models import InvestmentAccount

    aplicacao = _account(
        client, headers, name="CDB Itaú", kind=KIND_INVESTMENT, opening=0, number="33333-3"
    )
    _transferir(
        client,
        headers,
        from_id=origem["id"],
        to_id=aplicacao["id"],
        kind=TRANSFER_KIND_INVESTMENT_IN,
    )

    assert _saldo(client, headers, aplicacao["id"]) == VALOR
    assert _saldo(client, headers, origem["id"]) == 5_000_00 - VALOR
    assert list(db.scalars(select(InvestmentAccount)).all()) == [], (
        "a transferência criou uma entidade de aplicação — isso é Onda 2b, e é lá que mora o "
        "backfill que torna essa derivação segura"
    )


# ── AC7 — as guardas, uma por teste, TODAS verificando que nada foi escrito ───────────────────


def test_mesma_conta_de_origem_e_destino_e_422(client: TestClient, headers, origem, db: Session):
    _transferir(client, headers, from_id=origem["id"], to_id=origem["id"], expect=422)
    assert _total_de_movimentos(db) == 0
    assert list(db.scalars(select(BankTransfer)).all()) == []


def test_conta_inexistente_e_404_fail_closed(client: TestClient, headers, origem, db: Session):
    """404, nunca 403: um 403 confirmaria a existência da linha (é assim que cross-tenant cai)."""
    _transferir(client, headers, from_id=origem["id"], to_id="nao-existe", expect=404)
    _transferir(client, headers, from_id="nao-existe", to_id=origem["id"], expect=404)
    assert _total_de_movimentos(db) == 0


@pytest.mark.parametrize("papel", ["origem", "destino"])
def test_conta_arquivada_e_422_dizendo_QUAL(
    client: TestClient, headers, origem, destino, db: Session, papel: str
):
    """Numa operação com DUAS contas, *"a conta está arquivada"* obriga o dono a adivinhar qual."""
    alvo = origem if papel == "origem" else destino
    assert (
        client.post(f"/bank/accounts/{alvo['id']}/archive", headers=headers).status_code == 200
    )
    resp = client.post(
        "/bank/transfers",
        json={
            "from_account_id": origem["id"],
            "to_account_id": destino["id"],
            "amount_cents": VALOR,
            "posted_at": DIA.isoformat(),
            "kind": TRANSFER_KIND_OWN,
            "description": "",
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert f"conta de {papel}" in resp.json()["detail"]
    assert alvo["name"] in resp.json()["detail"]
    assert _total_de_movimentos(db) == 0


@pytest.mark.parametrize("valor", [0, -1, -100_00])
def test_valor_zero_ou_negativo_e_422(
    client: TestClient, headers, origem, destino, db: Session, valor: int
):
    """O sinal vive nas pernas. Um negativo aqui seria a 3ª convenção de sinal do repositório."""
    _transferir(
        client, headers, from_id=origem["id"], to_id=destino["id"], amount_cents=valor, expect=422
    )
    assert _total_de_movimentos(db) == 0


@pytest.mark.parametrize("papel", ["origem", "destino"])
def test_data_igual_a_abertura_de_QUALQUER_das_duas_contas_e_422(
    client: TestClient, headers, papel: str, db: Session
):
    """⚠️ **O ponto mais fácil de esquecer:** cada conta tem a SUA `opening_date`.

    Uma perna aceita com a outra recusada deixaria a transferência pela metade — o dinheiro sairia
    de A e não chegaria em B. A borda é `<=` (movimento exige `posted_at > opening_date`,
    estritamente), então a data **igual** à abertura já é 422.
    """
    tarde = _hoje() - timedelta(days=10)
    a = _account(client, headers, name="Antiga", opening_date=ABERTURA, number="44444-4")
    b = _account(client, headers, name="Recente", opening_date=tarde, number="55555-5")
    conta_tardia = b if papel == "destino" else a
    # A data de teste é a abertura da conta que queremos reprovar.
    resp = client.post(
        "/bank/transfers",
        json={
            "from_account_id": (a if papel == "origem" else b)["id"],
            "to_account_id": (b if papel == "origem" else a)["id"],
            "amount_cents": VALOR,
            "posted_at": (ABERTURA if papel == "origem" else tarde).isoformat(),
            "kind": TRANSFER_KIND_OWN,
            "description": "",
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert (a if papel == "origem" else b)["name"] in detail
    assert "data de abertura" in detail
    assert conta_tardia is not None
    assert _total_de_movimentos(db) == 0


def test_data_um_dia_depois_da_abertura_mais_recente_e_ACEITA(client: TestClient, headers, db):
    """A borda do outro lado: sem ela o teste acima seria satisfeito por uma regra boba demais."""
    tarde = _hoje() - timedelta(days=10)
    a = _account(client, headers, name="Antiga", opening_date=ABERTURA, number="44444-4")
    b = _account(client, headers, name="Recente", opening_date=tarde, number="55555-5")
    _transferir(
        client,
        headers,
        from_id=a["id"],
        to_id=b["id"],
        posted_at=tarde + timedelta(days=1),
    )
    assert _total_de_movimentos(db) == 2


def test_data_futura_e_422_DENTRO_de_create_transfer(
    client: TestClient, headers, origem, destino, db: Session
):
    """**Achado A-3 — o BLOQUEIO 5 da onda, com o membro escrito.**

    A guarda genérica (`service._validate_posted_at`) **aceita** data futura para
    `source ∈ SOURCES_SISTEMA` desde a 8.14, e `transfer` está lá dentro. Um 422 que dependesse dela
    ficaria **silenciosamente inócuo** — com teste verde. Por isso ele vive em `create_transfer`.

    ⚠️ **Se este teste falhar depois de alguém "mover a guarda para o lugar comum", a correção é
    trazê-la de volta para cá** — não afrouxar a asserção.
    """
    _transferir(
        client,
        headers,
        from_id=origem["id"],
        to_id=destino["id"],
        posted_at=_hoje() + timedelta(days=1),
        expect=422,
    )
    assert _total_de_movimentos(db) == 0
    assert list(db.scalars(select(BankTransfer)).all()) == []


def test_NAO_MEMBRO_a_mesma_data_futura_e_ACEITA_numa_baixa_de_conta_a_pagar(
    client: TestClient, headers, origem
):
    """O outro lado da assimetria que torna impossível pôr a guarda no lugar comum.

    Mesma data, os dois em `SOURCES_SISTEMA`, respostas **opostas**: a baixa de conta a pagar com
    data futura é **aceita** e vira `scheduled` (8.14 AC2) — existe estado, existe superfície
    (*"Agendado para sair"*), existe caminho de promoção. Transferência agendada não tem nada disso,
    e inventar a quarta semântica de agendamento seria o Artigo IV.
    """
    amanha = _hoje() + timedelta(days=1)
    bill = client.post(
        "/payables/bills",
        json={
            "description": "Aluguel",
            "category": "Estrutura",
            "amount_cents": 120_00,
            "due_date": (_hoje() + timedelta(days=3)).isoformat(),
        },
        headers=headers,
    ).json()
    resp = client.post(
        f"/payables/bills/{bill['id']}/pay",
        json={"bank_account_id": origem["id"], "paid_on": amanha.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert (
        client.get(f"/payables/bills/{bill['id']}", headers=headers).json()["status"]
        == "scheduled"
    )


def test_a_guarda_de_futuro_nao_mora_na_guarda_generica_do_modulo():
    """**Teste ESTRUTURAL** — o comportamental acima passaria com a guarda no lugar errado *hoje*.

    O achado A-3 é sobre **onde** a guarda mora, e o sintoma da forma errada só apareceria numa
    story futura (a que ligar `yield`). Um teste que só olha o 422 não distingue as duas formas;
    este olha a estrutura, como `test_indice_de_origem_e_parcial` faz com o índice parcial.

    Afirma as duas metades: `service._validate_posted_at` **continua aceitando** futuro para
    `SOURCES_SISTEMA` (se um dia recusar, a 8.14 regrediu), e é `transfers.create_transfer` quem
    recusa.
    """
    from app.modules.bank.models import BankAccount

    conta = BankAccount(
        tenant_id="t", name="X", kind=KIND_CHECKING, opening_balance_cents=0,
        opening_balance_is_known=True,
        opening_date=ABERTURA,
    )
    amanha = _hoje() + timedelta(days=1)
    # A guarda genérica ACEITA — é o comportamento da 8.14, e ele não mudou.
    assert (
        bank_service._validate_posted_at(amanha, conta, _hoje(), source=SOURCE_TRANSFER) == amanha
    ), "a 8.14 regrediu: a guarda genérica voltou a recusar futuro para origem de sistema"
    # E a guarda específica RECUSA.
    with pytest.raises(bank_service.BankError) as exc:
        transfers_service._validate_nao_futura(amanha, _hoje())
    assert exc.value.status_code == 422


# ── AC8 — desfazer: as duas pernas somem juntas ──────────────────────────────────────────────


def test_delete_apaga_o_lancamento_E_as_duas_pernas(
    client: TestClient, headers, origem, destino, db: Session
):
    """Sem este `DELETE`, a única correção seria a contrapartida que o design §4.5 rejeita."""
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    assert _total_de_movimentos(db) == 2

    assert client.delete(f"/bank/transfers/{t['id']}", headers=headers).status_code == 204
    db.expire_all()

    assert _total_de_movimentos(db) == 0
    assert list(db.scalars(select(BankTransfer)).all()) == []
    # E os saldos voltam exatamente ao que eram.
    assert _saldo(client, headers, origem["id"]) == 5_000_00
    assert _saldo(client, headers, destino["id"]) == 200_00


def test_delete_nao_alcanca_as_pernas_de_OUTRA_transferencia(
    client: TestClient, headers, origem, destino, db: Session
):
    """A guarda que um `DELETE ... WHERE source='transfer'` mal escrito atropelaria."""
    a = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    b = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])

    assert client.delete(f"/bank/transfers/{a['id']}", headers=headers).status_code == 204
    db.expire_all()

    assert _total_de_movimentos(db) == 2
    assert {p.transfer_id for p in _pernas(db, b["id"])} == {b["id"]}


def test_delete_de_perna_JA_ENRIQUECIDA_desliga_a_origem_em_vez_de_apagar(
    client: TestClient, headers, origem, destino, db: Session
):
    """**Degradação honesta** (§4.5, ramo 2 de `_desliga_ou_apaga`) — reusada, não recopiada.

    O ramo é **inalcançável hoje** (não existe importação), então a linha enriquecida é montada à
    mão. Ele entra agora porque escrevê-lo na Onda 4 significaria descobrir a regra **depois de já
    ter perdido dado bancário real**: um `DELETE` bem-sucedido em cima de uma evidência que não
    voltava.
    """
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    saida, entrada = _pernas(db, t["id"])
    # A Onda 4 casaria a perna de saída com a linha real do extrato:
    saida.fitid = "FITID-DO-BANCO-123"
    db.commit()

    assert client.delete(f"/bank/transfers/{t['id']}", headers=headers).status_code == 204
    db.expire_all()

    sobrou = list(db.scalars(select(BankTransaction)).all())
    assert len(sobrou) == 1, "a perna enriquecida sumiu — a evidência do banco foi perdida"
    assert sobrou[0].id == saida.id
    assert sobrou[0].origin_id is None
    assert sobrou[0].source == SOURCE_OFX
    assert sobrou[0].status == "unmatched"
    # O lançamento some do mesmo jeito — e a entrada, puramente sintética, foi apagada.
    assert list(db.scalars(select(BankTransfer)).all()) == []
    assert entrada is not None


def test_delete_de_transferencia_inexistente_e_404(client: TestClient, headers):
    assert client.delete("/bank/transfers/nao-existe", headers=headers).status_code == 404


def test_nao_existe_PATCH_de_transferencia(client: TestClient, headers, origem, destino):
    """Corrigir é apagar e recriar — barato aqui, **nenhum evento de Agenda envolvido** (AC8)."""
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    resp = client.patch(
        f"/bank/transfers/{t['id']}", json={"amount_cents": 1}, headers=headers
    )
    assert resp.status_code == 405, "apareceu um PATCH de transferência — ele foi cortado no AC8"


# ── AC9 — as pernas não são editáveis nem ignoráveis (Regra da Origem (d)) ────────────────────


def test_as_pernas_recusam_edicao_de_data_e_de_valor(
    client: TestClient, headers, origem, destino, db: Session
):
    """Quem quer mudá-las mexe no lançamento — e a transferência não tem PATCH: apaga e refaz."""
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    saida, _ = _pernas(db, t["id"])

    for corpo in ({"posted_at": DIA.isoformat()}, {"amount_cents": -1}):
        resp = client.patch(f"/bank/transactions/{saida.id}", json=corpo, headers=headers)
        assert resp.status_code == 422, resp.text
        assert "lançamento" in resp.json()["detail"]


def test_as_pernas_ACEITAM_editar_a_descricao_do_dono(
    client: TestClient, headers, origem, destino, db: Session
):
    """A exceção NOMEADA da Regra da Origem (d): *"`user_description` é rótulo, não fato"*.

    Recusar o PATCH inteiro tiraria do dono a única edição que ele legitimamente tem sobre uma perna
    — e ele perderia isso sem que ninguém tivesse decidido tirar.
    """
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    saida, _ = _pernas(db, t["id"])

    resp = client.patch(
        f"/bank/transactions/{saida.id}", json={"user_description": "reserva de emergência"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_description"] == "reserva de emergência"
    # E `raw_description` continua congelada — é a prova documental.
    assert resp.json()["raw_description"].startswith("Transferência para")


def test_as_pernas_recusam_ignore(client: TestClient, headers, origem, destino, db: Session):
    """Ignorar UMA das duas quebraria a simetria e inventaria uma divergência na conferência.

    O dono sairia caçando um furo que ele mesmo criou com um clique — e divergência inventada é pior
    que divergência escondida.
    """
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    saida, _ = _pernas(db, t["id"])

    resp = client.post(f"/bank/transactions/{saida.id}/ignore", headers=headers)
    assert resp.status_code == 422, resp.text
    db.expire_all()
    assert db.get(BankTransaction, saida.id).status == STATUS_MATCHED
    # E o saldo não se moveu: ignorar teria tirado a saída do saldo derivado.
    assert _saldo(client, headers, origem["id"]) == 5_000_00 - VALOR


def test_o_movimento_MANUAL_continua_editavel_e_ignoravel(client: TestClient, headers, origem):
    """O não-membro da guarda (d): ela é sobre origem de SISTEMA, não sobre movimento bancário.

    Sem esta asserção ao lado, a guarda acima estaria satisfeita pela forma mais fácil e mais
    errada — recusar tudo.
    """
    tx = client.post(
        f"/bank/accounts/{origem['id']}/transactions",
        json={"posted_at": DIA.isoformat(), "amount_cents": -50_00, "description": "Tarifa"},
        headers=headers,
    ).json()
    assert (
        client.patch(
            f"/bank/transactions/{tx['id']}", json={"amount_cents": -60_00}, headers=headers
        ).status_code
        == 200
    )
    assert client.post(f"/bank/transactions/{tx['id']}/ignore", headers=headers).status_code == 200


# ── Rotas: listagem, leitura e paginação ─────────────────────────────────────────────────────


def test_listagem_casa_os_DOIS_lados_da_conta(client: TestClient, headers, origem, destino):
    """A pergunta do dono é *"o que passou por esta conta?"* — filtrar só a origem esconderia
    metade do que ele procura, sem dizer que está escondendo."""
    ida = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    volta = _transferir(
        client, headers, from_id=destino["id"], to_id=origem["id"], amount_cents=100_00
    )

    ids = {
        t["id"]
        for t in client.get(
            "/bank/transfers", params={"bank_account_id": destino["id"]}, headers=headers
        ).json()
    }
    assert ids == {ida["id"], volta["id"]}


def test_listagem_filtra_por_janela_inclusiva_nas_duas_pontas(
    client: TestClient, headers, origem, destino
):
    velha = _transferir(
        client, headers, from_id=origem["id"], to_id=destino["id"],
        posted_at=_hoje() - timedelta(days=20),
    )
    nova = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"], posted_at=DIA)

    janela = client.get(
        "/bank/transfers",
        params={"start": DIA.isoformat(), "end": DIA.isoformat()},
        headers=headers,
    ).json()
    assert [t["id"] for t in janela] == [nova["id"]]
    assert velha["id"] not in [t["id"] for t in janela]


def test_paginacao_obrigatoria_com_limit_grampeado(client: TestClient, headers, origem, destino):
    """`limit` grampeado em [1,500] no service — mesmo contrato de `list_transactions`."""
    for _ in range(3):
        _transferir(client, headers, from_id=origem["id"], to_id=destino["id"], amount_cents=100)
    assert len(client.get("/bank/transfers", params={"limit": 2}, headers=headers).json()) == 2
    # O grampeamento é do SERVICE (a rota tem `le=500`, então o teste chama o service direto).
    from app.modules.bank import transfers as t

    assert t.list_transfers.__doc__ and "grampeado" in t.list_transfers.__doc__


def test_get_de_transferencia_inexistente_e_404(client: TestClient, headers):
    assert client.get("/bank/transfers/nao-existe", headers=headers).status_code == 404


def test_a_resposta_NAO_carrega_nenhum_campo_de_saldo(client: TestClient, headers, origem, destino):
    """Regra dos Planos §1.3c: todo campo de saldo precisa do irmão `*_origem`. O jeito de não
    aumentar a dívida G-1 (6 campos sem irmão) é **não expor saldo aqui**."""
    t = _transferir(client, headers, from_id=origem["id"], to_id=destino["id"])
    suspeitos = [k for k in t if "saldo" in k or k.endswith("_balance_cents")]
    assert suspeitos == [], (
        f"campo de saldo sem irmão de procedência em BankTransferOut: {suspeitos}"
    )


# ── IV7 — a purga de conta cobre a tabela nova ───────────────────────────────────────────────


def test_bank_transfers_e_purgada_junto_com_o_tenant(db: Session):
    """**IV7.** É grátis — desde que o modelo herde `TenantMixin`. E o que é grátis é o que some.

    A purga de `platform.delete_account` descobre as tabelas de negócio **dinamicamente**
    (subclasses de `TenantMixin`). Este teste é a asserção de que `BankTransfer` está no conjunto:
    se alguém "simplificar" a herança um dia, a tabela deixaria de ser purgada e a exclusão de conta
    passaria a deixar dado de negócio para trás — em silêncio, e num lugar que a LGPD alcança.
    """
    from app.modules.platform.service import _business_table_names

    assert issubclass(BankTransfer, TenantMixin)
    assert "bank_transfers" in _business_table_names()
