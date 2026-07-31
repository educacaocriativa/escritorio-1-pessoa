"""Testes do saldo declarado — a **verdade externa** do plano 3 (Story 8.4).

Cobre (Tasks 4-6 / AC2-8 / IV1,IV2,IV4):
- **AC4** declarar (201) e **redeclarar o mesmo dia** (200, corrige, UMA linha) — não 409;
- **AC3** `origin='ofx'` recusado com 422 (a Onda 3 é que escreve nele) e `import_batch_id` NULL;
- **AC5** as guardas que protegem a comparação: data futura 422, data < abertura 422, borda
  `reference_date == opening_date` **aceita**, saldo negativo **aceito**, conta arquivada 422,
  conta inexistente 404;
- **AC6** `latest_checkpoint`: o mais recente na janela, o filtro de `origins`, o desempate
  `ofx` > `manual` no mesmo dia e — o caso de maior valor — o **`None`** que faz a Story 8.5
  declarar `indisponivel` em vez de comparar contra zero;
- **AC7** `days_since_last_declared_balance` por conta e consolidado, com `None` != `0`;
- **AC2** a data de calendário: o par (`latest_checkpoint(on_or_before=D)`,
  `derived_balance(until=D)`) considera o movimento de `D` e ignora o de `D+1`;
- **AC8** as 4 rotas, sob autenticação, com `DELETE` → 204 e `GET` seguinte → 404;
- **IV1** DRE intacta, **IV2** saldo derivado IMUNE ao checkpoint, **IV4** Projeção intacta.

O IV5 (purga LGPD de `bank_balance_checkpoints` no `delete_account`) vive em `test_platform.py`,
junto das outras tabelas do módulo.

RLS/isolamento cross-tenant NÃO é exercido aqui (SQLite — ver `conftest.py`): "o checkpoint é de
outro tenant" é uma afirmação que só o Postgres real prova, e ela vive em `test_bank_rls.py`
(`rls_e2e`), que esta story estendeu.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_BANCO, ORIGEM_MISTO
from app.modules.bank import service
from app.modules.bank.models import (
    KIND_CHECKING,
    ORIGIN_MANUAL,
    ORIGIN_OFX,
    BankBalanceCheckpoint,
    BankTransaction,
)
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import projection as projection_service

REGISTER = {
    "legal_name": "Saldo Declarado ME",
    "document": "11444777000161",
    "slug": "saldodeclarado",
    "email": "saldo@example.com",
    "name": "Selma",
    "password": "uma-senha-bem-grande",
}

# Toda data usada é do passado real: as guardas de "data futura" ancoram em
# `datetime.now(UTC).date()`, como o resto do projeto.
OPENING = date(2026, 7, 1)
OPENING_CENTS = 1_500_00


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account(client: TestClient, headers, *, opening: int = OPENING_CENTS, **over) -> dict:
    payload = {
        "name": "Itaú PJ",
        "kind": KIND_CHECKING,
        "opening_balance_cents": opening,
        "opening_date": OPENING.isoformat(),
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _declarar(
    client: TestClient,
    headers,
    account_id: str,
    *,
    balance_cents: int,
    reference_date: date | str = date(2026, 7, 15),
    expect: int = 201,
    **over,
) -> dict:
    body = {
        "reference_date": (
            reference_date if isinstance(reference_date, str) else reference_date.isoformat()
        ),
        "balance_cents": balance_cents,
    }
    body.update(over)
    resp = client.post(
        f"/bank/accounts/{account_id}/checkpoints", json=body, headers=headers
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _lancar(
    client: TestClient, headers, account_id: str, *, amount_cents: int, posted_at: date
) -> dict:
    resp = client.post(
        f"/bank/accounts/{account_id}/transactions",
        json={
            "posted_at": posted_at.isoformat(),
            "amount_cents": amount_cents,
            "description": "movimento",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _saldo(client: TestClient, headers, account_id: str, *, until: date | None = None) -> int:
    params = {"until": until.isoformat()} if until else None
    resp = client.get(
        f"/bank/accounts/{account_id}/balance", params=params, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["saldo_derivado_cents"]


# ── AC4/AC8 — declarar e redeclarar ──────────────────────────────────────────────────────────


def test_declarar_saldo_cria_com_201_e_campos_corretos(client: TestClient, headers, db: Session):
    account = _account(client, headers)
    cp = _declarar(client, headers, account["id"], balance_cents=1_234_56)

    assert cp["bank_account_id"] == account["id"]
    assert cp["reference_date"] == "2026-07-15"
    assert cp["balance_cents"] == 1_234_56
    assert cp["origin"] == ORIGIN_MANUAL
    # Eixo A: o saldo declarado é do plano 3, e é por isso que ele é comparável ao derivado.
    assert cp["balance_origem"] == ORIGEM_BANCO
    # `created_by` é o usuário logado (rastro de quem declarou o número que está valendo).
    me = client.get("/auth/me", headers=headers).json()["user"]
    assert cp["created_by"] == me["id"]

    linha = db.get(BankBalanceCheckpoint, cp["id"])
    # A Onda 3 é que preenche o lote de importação; nesta onda é NULL por construção.
    assert linha.import_batch_id is None


def test_redeclarar_mesmo_dia_corrige_com_200_e_nao_duplica(
    client: TestClient, headers, db: Session
):
    """AC4: quem digitou 1.234,00 no lugar de 12.340,00 corrige com um gesto, não com 409."""
    account = _account(client, headers)
    primeiro = _declarar(client, headers, account["id"], balance_cents=1_234_00)

    corrigido = _declarar(
        client, headers, account["id"], balance_cents=12_340_00, expect=200
    )
    assert corrigido["id"] == primeiro["id"], "a correção criou uma linha nova em vez de corrigir"
    assert corrigido["balance_cents"] == 12_340_00

    assert db.query(BankBalanceCheckpoint).count() == 1, (
        "redeclarar o mesmo dia deixou duas linhas — a constraint única do dia (por conta e "
        "origem) existe justamente para que isso seja impossível"
    )


def test_dias_diferentes_convivem(client: TestClient, headers, db: Session):
    account = _account(client, headers)
    _declarar(client, headers, account["id"], balance_cents=100, reference_date=date(2026, 7, 10))
    _declarar(client, headers, account["id"], balance_cents=200, reference_date=date(2026, 7, 11))
    assert db.query(BankBalanceCheckpoint).count() == 2


def test_contas_diferentes_no_mesmo_dia_convivem(client: TestClient, headers, db: Session):
    """O checkpoint é POR CONTA (epic §9 F3) — não existe "saldo declarado do tenant"."""
    a = _account(client, headers, number="1111-1")
    b = _account(client, headers, name="Poupança", number="2222-2")
    _declarar(client, headers, a["id"], balance_cents=100)
    _declarar(client, headers, b["id"], balance_cents=200)
    assert db.query(BankBalanceCheckpoint).count() == 2


# ── AC3 — só `manual` é escrito nesta onda ───────────────────────────────────────────────────


def test_origin_ofx_recusado_com_422(client: TestClient, headers):
    """`ofx` vem do `<LEDGERBAL>` de um arquivo que ainda não existe: aceitá-lo pela API criaria
    uma linha dizendo "o banco atestou isto" sem nenhum arquivo por trás."""
    account = _account(client, headers)
    erro = _declarar(
        client, headers, account["id"], balance_cents=1_000, origin=ORIGIN_OFX, expect=422
    )
    assert "importação de extrato ainda não existe" in erro["detail"]


def test_origin_desconhecida_recusada_com_422(client: TestClient, headers):
    account = _account(client, headers)
    _declarar(
        client, headers, account["id"], balance_cents=1_000, origin="telepatia", expect=422
    )


# ── AC5 — as guardas que protegem a comparação da Story 8.5 ──────────────────────────────────


def test_data_futura_recusada(client: TestClient, headers):
    account = _account(client, headers)
    amanha = datetime.now(UTC).date() + timedelta(days=1)
    erro = _declarar(
        client, headers, account["id"], balance_cents=1_000, reference_date=amanha, expect=422
    )
    assert "não pode ser futura" in erro["detail"]


def test_data_anterior_a_abertura_recusada(client: TestClient, headers):
    account = _account(client, headers)
    erro = _declarar(
        client,
        headers,
        account["id"],
        balance_cents=1_000,
        reference_date=OPENING - timedelta(days=1),
        expect=422,
    )
    assert OPENING.isoformat() in erro["detail"], (
        "a mensagem precisa citar a data de abertura — sem ela o usuário não sabe o que corrigir"
    )


def test_data_igual_a_abertura_e_aceita(client: TestClient, headers):
    """A borda. Assimetria deliberada com o movimento, que exige `posted_at > opening_date`.

    `opening_balance_cents` é, por definição, o saldo ao FIM do dia de abertura — então
    `derived_balance(until=opening_date)` devolve exatamente ele e a comparação da 8.5 é válida.
    Recusar esta data cortaria o caso mais sadio que existe: conferir no dia em que se cadastrou.
    """
    account = _account(client, headers)
    cp = _declarar(
        client, headers, account["id"], balance_cents=OPENING_CENTS, reference_date=OPENING
    )
    assert cp["reference_date"] == OPENING.isoformat()
    assert _saldo(client, headers, account["id"], until=OPENING) == OPENING_CENTS


def test_saldo_negativo_e_aceito(client: TestClient, headers):
    """Conta no limite / cheque especial. Recusar forçaria o usuário a mentir o número que ele
    está olhando na tela do banco — e a divergência resultante seria criada pelo próprio e1p."""
    account = _account(client, headers)
    cp = _declarar(client, headers, account["id"], balance_cents=-987_65)
    assert cp["balance_cents"] == -987_65


def test_conta_inexistente_404(client: TestClient, headers):
    _declarar(client, headers, "conta-que-nao-existe", balance_cents=1_000, expect=404)


def test_conta_arquivada_recusa_saldo_novo(client: TestClient, headers):
    account = _account(client, headers)
    assert (
        client.post(f"/bank/accounts/{account['id']}/archive", headers=headers).status_code == 200
    )
    erro = _declarar(client, headers, account["id"], balance_cents=1_000, expect=422)
    assert "arquivada" in erro["detail"]


# ── AC8 — as rotas de leitura e o DELETE ─────────────────────────────────────────────────────


def test_listar_ordena_do_mais_recente_para_o_mais_antigo(client: TestClient, headers):
    account = _account(client, headers)
    for dia, valor in ((10, 100), (20, 200), (15, 150)):
        _declarar(
            client,
            headers,
            account["id"],
            balance_cents=valor,
            reference_date=date(2026, 7, dia),
        )

    resp = client.get(f"/bank/accounts/{account['id']}/checkpoints", headers=headers)
    assert resp.status_code == 200, resp.text
    assert [c["reference_date"] for c in resp.json()] == [
        "2026-07-20",
        "2026-07-15",
        "2026-07-10",
    ]


def test_listar_filtra_janela_e_pagina(client: TestClient, headers):
    account = _account(client, headers)
    for dia in (10, 15, 20):
        _declarar(
            client,
            headers,
            account["id"],
            balance_cents=dia,
            reference_date=date(2026, 7, dia),
        )

    janela = client.get(
        f"/bank/accounts/{account['id']}/checkpoints",
        params={"start": "2026-07-12", "end": "2026-07-20"},
        headers=headers,
    ).json()
    assert [c["reference_date"] for c in janela] == ["2026-07-20", "2026-07-15"]

    pagina = client.get(
        f"/bank/accounts/{account['id']}/checkpoints",
        params={"limit": 1, "offset": 1},
        headers=headers,
    ).json()
    assert [c["reference_date"] for c in pagina] == ["2026-07-15"]


def test_listar_de_conta_inexistente_e_404_e_nao_lista_vazia(client: TestClient, headers):
    """Vazio significaria "esta conta nunca teve saldo informado" — afirmação diferente."""
    resp = client.get("/bank/accounts/nao-existe/checkpoints", headers=headers)
    assert resp.status_code == 404, resp.text


def test_listar_so_traz_os_da_conta_pedida(client: TestClient, headers):
    a = _account(client, headers, number="1111-1")
    b = _account(client, headers, name="Poupança", number="2222-2")
    cp_a = _declarar(client, headers, a["id"], balance_cents=100)
    _declarar(client, headers, b["id"], balance_cents=200)

    lista = client.get(f"/bank/accounts/{a['id']}/checkpoints", headers=headers).json()
    assert [c["id"] for c in lista] == [cp_a["id"]]


def test_get_e_delete(client: TestClient, headers):
    account = _account(client, headers)
    cp = _declarar(client, headers, account["id"], balance_cents=4_200)

    assert client.get(f"/bank/checkpoints/{cp['id']}", headers=headers).json()["id"] == cp["id"]
    assert client.delete(f"/bank/checkpoints/{cp['id']}", headers=headers).status_code == 204
    assert client.get(f"/bank/checkpoints/{cp['id']}", headers=headers).status_code == 404


def test_get_e_delete_de_inexistente_404(client: TestClient, headers):
    assert client.get("/bank/checkpoints/fantasma", headers=headers).status_code == 404
    assert client.delete("/bank/checkpoints/fantasma", headers=headers).status_code == 404


def test_rotas_exigem_autenticacao(client: TestClient, headers):
    account = _account(client, headers)
    cp = _declarar(client, headers, account["id"], balance_cents=1)
    for method, url in (
        ("post", f"/bank/accounts/{account['id']}/checkpoints"),
        ("get", f"/bank/accounts/{account['id']}/checkpoints"),
        ("get", f"/bank/checkpoints/{cp['id']}"),
        ("delete", f"/bank/checkpoints/{cp['id']}"),
    ):
        resp = getattr(client, method)(url, **({"json": {}} if method == "post" else {}))
        assert resp.status_code in (401, 403), f"{method.upper()} {url} → {resp.status_code}"


# ── AC6 — `latest_checkpoint`, a função que a conferência consome ────────────────────────────


def _seed_cp(
    db: Session,
    tenant_id: str,
    account_id: str,
    *,
    reference_date: date,
    balance_cents: int,
    origin: str = ORIGIN_MANUAL,
) -> BankBalanceCheckpoint:
    """Escreve direto pelo modelo: a API só aceita `manual`, e o AC6 precisa de linhas `ofx`."""
    cp = BankBalanceCheckpoint(
        tenant_id=tenant_id,
        bank_account_id=account_id,
        reference_date=reference_date,
        balance_cents=balance_cents,
        origin=origin,
    )
    db.add(cp)
    db.commit()
    return cp


def _tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def test_latest_checkpoint_devolve_o_mais_recente_da_janela(
    client: TestClient, headers, db: Session
):
    account = _account(client, headers)
    for dia, valor in ((5, 500), (12, 1_200), (25, 2_500)):
        _declarar(
            client,
            headers,
            account["id"],
            balance_cents=valor,
            reference_date=date(2026, 7, dia),
        )

    achado = service.latest_checkpoint(
        db, bank_account_id=account["id"], on_or_before=date(2026, 7, 20)
    )
    assert achado is not None
    assert achado.reference_date == date(2026, 7, 12), (
        "pegou um checkpoint POSTERIOR ao teto da janela — comparar com ele acusaria como "
        "divergência tudo o que aconteceu no meio"
    )
    assert achado.balance_cents == 1_200

    # O teto é inclusivo, como `derived_balance(until=...)`: as duas janelas coincidem.
    no_dia = service.latest_checkpoint(
        db, bank_account_id=account["id"], on_or_before=date(2026, 7, 12)
    )
    assert no_dia.reference_date == date(2026, 7, 12)


def test_latest_checkpoint_none_e_o_caminho_normal(client: TestClient, headers, db: Session):
    """AC6, o caso de maior valor depois do IV2.

    `None` é o que faz a Story 8.5 declarar `saldo_banco_origem='indisponivel'` e o relatório
    **dizer que não sabe**. Se um dia isto virar `0` (ou o saldo de abertura, ou uma exceção), a
    conferência passa a inventar uma divergência inteira com aparência de fato.
    """
    account = _account(client, headers)

    # Conta sem checkpoint nenhum.
    assert (
        service.latest_checkpoint(
            db, bank_account_id=account["id"], on_or_before=date(2026, 7, 31)
        )
        is None
    )

    # Conta COM checkpoint, mas nenhum dentro da janela pedida.
    _declarar(client, headers, account["id"], balance_cents=999, reference_date=date(2026, 7, 20))
    assert (
        service.latest_checkpoint(
            db, bank_account_id=account["id"], on_or_before=date(2026, 7, 19)
        )
        is None
    )

    # Conta inexistente: também `None` (e não exceção) — "não há verdade externa aqui" é o mesmo
    # estado honesto, e a RLS já cobre o cross-tenant.
    assert (
        service.latest_checkpoint(
            db, bank_account_id="conta-que-nao-existe", on_or_before=date(2026, 7, 31)
        )
        is None
    )


def test_latest_checkpoint_respeita_filtro_de_origins(client: TestClient, headers, db: Session):
    account = _account(client, headers)
    tid = _tenant_id(client, headers)
    _seed_cp(db, tid, account["id"], reference_date=date(2026, 7, 10), balance_cents=1_000)
    _seed_cp(
        db,
        tid,
        account["id"],
        reference_date=date(2026, 7, 20),
        balance_cents=2_000,
        origin=ORIGIN_OFX,
    )

    so_manual = service.latest_checkpoint(
        db,
        bank_account_id=account["id"],
        on_or_before=date(2026, 7, 31),
        origins=(ORIGIN_MANUAL,),
    )
    assert so_manual.reference_date == date(2026, 7, 10)

    so_ofx = service.latest_checkpoint(
        db, bank_account_id=account["id"], on_or_before=date(2026, 7, 31), origins=(ORIGIN_OFX,)
    )
    assert so_ofx.reference_date == date(2026, 7, 20)

    with pytest.raises(service.BankError) as exc:
        service.latest_checkpoint(
            db, bank_account_id=account["id"], on_or_before=date(2026, 7, 31), origins=("xpto",)
        )
    assert exc.value.status_code == 422


def test_latest_checkpoint_desempata_ofx_na_frente_de_manual(
    client: TestClient, headers, db: Session
):
    """Mesmo dia, duas portas de entrada: vence o `ofx` (um intermediário humano a menos).

    Só passa a ter efeito na Onda 3 — está aqui para a regra não ser inventada duas vezes, e para
    que ninguém a "simplifique" para `ORDER BY origin DESC`, que dá o mesmo resultado hoje por
    acidente alfabético e o resultado errado no dia em que um terceiro valor entrar.
    """
    account = _account(client, headers)
    tid = _tenant_id(client, headers)
    mesmo_dia = date(2026, 7, 18)
    # `manual` inserido PRIMEIRO de propósito: se o desempate não existisse, o `created_at desc`
    # faria o `ofx` vencer por acidente. Insere-se `ofx` primeiro no segundo caso, abaixo.
    _seed_cp(db, tid, account["id"], reference_date=mesmo_dia, balance_cents=1_000)
    _seed_cp(
        db, tid, account["id"], reference_date=mesmo_dia, balance_cents=2_000, origin=ORIGIN_OFX
    )

    vencedor = service.latest_checkpoint(
        db, bank_account_id=account["id"], on_or_before=mesmo_dia
    )
    assert vencedor.origin == ORIGIN_OFX and vencedor.balance_cents == 2_000

    # E o mesmo resultado com a ordem de inserção invertida — o desempate é pela regra, não pelo
    # relógio.
    outra = _account(client, headers, name="Segunda", number="9999-9")
    _seed_cp(
        db, tid, outra["id"], reference_date=mesmo_dia, balance_cents=2_000, origin=ORIGIN_OFX
    )
    _seed_cp(db, tid, outra["id"], reference_date=mesmo_dia, balance_cents=1_000)
    assert (
        service.latest_checkpoint(db, bank_account_id=outra["id"], on_or_before=mesmo_dia).origin
        == ORIGIN_OFX
    )


def test_latest_checkpoint_nao_mistura_contas(client: TestClient, headers, db: Session):
    a = _account(client, headers, number="1111-1")
    b = _account(client, headers, name="Poupança", number="2222-2")
    _declarar(client, headers, b["id"], balance_cents=9_999, reference_date=date(2026, 7, 20))

    assert (
        service.latest_checkpoint(db, bank_account_id=a["id"], on_or_before=date(2026, 7, 31))
        is None
    ), "o saldo declarado de uma conta vazou para outra — a conferência é POR CONTA"


# ── AC7 — `days_since_last_declared_balance` ─────────────────────────────────────────────────


def test_days_since_none_quando_nunca_houve(client: TestClient, headers, db: Session):
    account = _account(client, headers)
    hoje = date(2026, 7, 31)
    assert (
        service.days_since_last_declared_balance(
            db, bank_account_id=account["id"], today=hoje
        )
        is None
    ), "`None` (nunca declarado) e `0` (declarado hoje) são estados diferentes"
    assert service.days_since_last_declared_balance(db, today=hoje) is None


def test_days_since_conta_conta_e_consolidado(client: TestClient, headers, db: Session):
    a = _account(client, headers, number="1111-1")
    b = _account(client, headers, name="Poupança", number="2222-2")
    hoje = date(2026, 7, 31)
    _declarar(client, headers, a["id"], balance_cents=100, reference_date=date(2026, 7, 1))
    _declarar(client, headers, b["id"], balance_cents=200, reference_date=date(2026, 7, 25))

    # Por conta: aponta QUAL conta está desatualizada (o que a 8.5 quer mostrar).
    assert service.days_since_last_declared_balance(db, bank_account_id=a["id"], today=hoje) == 30
    assert service.days_since_last_declared_balance(db, bank_account_id=b["id"], today=hoje) == 6
    # Consolidado do tenant: o mais RECENTE de todas as contas.
    assert service.days_since_last_declared_balance(db, today=hoje) == 6


def test_days_since_zero_no_dia_da_declaracao(client: TestClient, headers, db: Session):
    account = _account(client, headers)
    _declarar(client, headers, account["id"], balance_cents=100, reference_date=date(2026, 7, 15))
    assert (
        service.days_since_last_declared_balance(
            db, bank_account_id=account["id"], today=date(2026, 7, 15)
        )
        == 0
    )


# ── AC2 — a data de calendário faz a comparação da 8.5 ter base sã ───────────────────────────


def test_checkpoint_e_saldo_derivado_casam_na_mesma_data(client: TestClient, headers, db: Session):
    """Checkpoint em `D`, movimentos em `D` e `D+1`: o par considera o de `D` e ignora o de `D+1`.

    É o teste que prova que a comparação da Story 8.5 tem base sã. `reference_date` significa o FIM
    do dia `D`, e `derived_balance(until=D)` é inclusivo em `D` — as duas janelas coincidem por
    construção, sem nenhuma aritmética de fuso no caminho.
    """
    account = _account(client, headers)
    D = date(2026, 7, 15)
    _lancar(client, headers, account["id"], amount_cents=300_00, posted_at=D)
    _lancar(client, headers, account["id"], amount_cents=-50_00, posted_at=D + timedelta(days=1))

    _declarar(client, headers, account["id"], balance_cents=1_800_00, reference_date=D)

    cp = service.latest_checkpoint(db, bank_account_id=account["id"], on_or_before=D)
    assert cp.reference_date == D
    derivado = service.derived_balance(db, bank_account_id=account["id"], until=cp.reference_date)

    # 1.500,00 de abertura + 300,00 do dia D. O −50,00 de D+1 está FORA.
    assert derivado == 1_800_00
    assert cp.balance_cents == derivado, (
        "o par (checkpoint, saldo derivado) na MESMA data não fecha — se as janelas não "
        "coincidirem, a 8.5 reporta divergência onde não há"
    )
    # E o saldo sem teto inclui o dia seguinte: a diferença é a janela, não o dado.
    assert service.derived_balance(db, bank_account_id=account["id"]) == 1_750_00


# ── IV2 — o teste de maior valor da story ────────────────────────────────────────────────────


def test_checkpoint_nao_altera_saldo_derivado(client: TestClient, headers, db: Session):
    """**O invariante que sustenta o épico inteiro.** O checkpoint NUNCA corrige o saldo derivado.

    Um implementador bem-intencionado pode "melhorar" a experiência gerando um movimento de ajuste
    para fechar a diferença. Isso zeraria a divergência **por construção** e destruiria a métrica
    primária do epic (`|divergencia_cents|` por conta, §3.1): o produto passaria a concordar consigo
    mesmo em vez de medir o furo — que é a única coisa que ele está vendendo. Este teste é a defesa
    permanente contra essa boa intenção.
    """
    account = _account(client, headers)
    _lancar(client, headers, account["id"], amount_cents=250_00, posted_at=date(2026, 7, 10))

    antes_sem_teto = _saldo(client, headers, account["id"])
    antes_na_data = _saldo(client, headers, account["id"], until=date(2026, 7, 15))
    movimentos_antes = db.query(BankTransaction).count()
    assert antes_sem_teto == 1_750_00

    # Um saldo GROSSEIRAMENTE diferente do derivado — R$ 1.000.000,00 contra R$ 1.750,00.
    _declarar(client, headers, account["id"], balance_cents=100_000_000)

    assert _saldo(client, headers, account["id"]) == antes_sem_teto, (
        "o saldo derivado mudou depois de declarar um saldo. O checkpoint é a verdade EXTERNA "
        "contra a qual o derivado é medido, nunca uma fonte que o corrija — se ele corrigisse, a "
        "divergência iria a zero por construção e o produto perderia a capacidade de dizer QUANTO "
        "está faltando."
    )
    assert _saldo(client, headers, account["id"], until=date(2026, 7, 15)) == antes_na_data
    assert db.query(BankTransaction).count() == movimentos_antes, (
        "declarar um saldo criou um MOVIMENTO — é exatamente o 'movimento de ajuste' automático "
        "que este teste existe para impedir"
    )

    # A conta em si também não foi tocada: nem `opening_balance_cents`, nem coluna de saldo nova.
    conta = client.get(f"/bank/accounts/{account['id']}", headers=headers).json()
    assert conta["opening_balance_cents"] == OPENING_CENTS
    assert conta["saldo_derivado_cents"] == antes_sem_teto

    # E a divergência continua MENSURÁVEL — que é o ponto de tudo isto (a 8.5 é quem a calcula).
    cp = service.latest_checkpoint(
        db, bank_account_id=account["id"], on_or_before=date(2026, 7, 15)
    )
    derivado = service.derived_balance(
        db, bank_account_id=account["id"], until=cp.reference_date
    )
    assert cp.balance_cents - derivado == 100_000_000 - 1_750_00


def test_deletar_checkpoint_tambem_nao_mexe_no_saldo(client: TestClient, headers):
    account = _account(client, headers)
    _lancar(client, headers, account["id"], amount_cents=250_00, posted_at=date(2026, 7, 10))
    antes = _saldo(client, headers, account["id"])

    cp = _declarar(client, headers, account["id"], balance_cents=1)
    client.delete(f"/bank/checkpoints/{cp['id']}", headers=headers)

    assert _saldo(client, headers, account["id"]) == antes


# ── IV1 / IV4 — o resto do produto não sente nada ────────────────────────────────────────────


def test_checkpoint_nao_altera_dre(client: TestClient, headers, db: Session):
    """IV1: um checkpoint é uma DECLARAÇÃO, não um lançamento. Snapshot campo a campo."""
    account = _account(client, headers)
    antes = asdict(dre_service.dre_report(db, start=date(2026, 7, 1), end=date(2026, 7, 31)))

    _declarar(client, headers, account["id"], balance_cents=42_000_00)

    depois = asdict(dre_service.dre_report(db, start=date(2026, 7, 1), end=date(2026, 7, 31)))
    assert depois == antes
    for campo in antes:
        assert depois[campo] == antes[campo], f"campo da DRE contaminado pelo checkpoint: {campo}"


def test_checkpoint_nao_altera_projecao_de_caixa(client: TestClient, headers, db: Session):
    """IV4: declarar um saldo NÃO move a projeção — nem um centavo, em nenhuma origem.

    ⚠️ **[Story 8.8 — @dev] A asserção final mudou (`plataforma` → `misto`), o teste ficou MAIS
    forte.** Antes, com a conta cadastrada, a projeção nem olhava para o banco, então "o checkpoint
    não a alterou" era quase tautologia. Agora a projeção **soma o saldo derivado** desta conta — e
    o teste passa a provar, no ponto onde importa, o aviso (c) de `BankBalanceCheckpoint`: o
    checkpoint é a verdade EXTERNA e **nunca corrige o saldo derivado**. Se algum dia alguém fizer o
    checkpoint ajustar o derivado (por um "movimento de ajuste" automático, a boa intenção mais
    provável aqui), este `assert` cai — e o produto teria perdido a divergência, que é o que ele
    vende.
    """
    account = _account(client, headers)
    hoje = date(2026, 7, 15)
    antes = asdict(projection_service.cash_projection(db, today=hoje))
    assert antes["saldo_inicial_origem"] == ORIGEM_MISTO, "pré-condição: a conta já existe"

    _declarar(client, headers, account["id"], balance_cents=99_999_999)

    depois = asdict(projection_service.cash_projection(db, today=hoje))
    assert depois == antes, (
        "A projeção mudou depois de um saldo DECLARADO. O checkpoint é a verdade externa e nunca "
        "corrige o saldo derivado — se corrigisse, a divergência iria a zero por construção."
    )
    assert depois["saldo_inicial_origem"] == ORIGEM_MISTO
    assert depois["saldo_inicial_banco_cents"] != 99_999_999, (
        "o saldo DECLARADO virou a parcela bancária da projeção — ela deve vir do DERIVADO"
    )
