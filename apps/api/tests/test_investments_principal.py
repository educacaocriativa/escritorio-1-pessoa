"""O principal da aplicação é CALCULADO, não digitado (Onda 2b-ii).

    principal = opening_balance_cents da conta de aplicação
              + Σ movimentos daquela conta com `source <> 'yield'`

Os três termos e o porquê de cada um estão na spec §3. O que estes testes seguram é que a derivação
não vire uma segunda fórmula e não conte o rendimento duas vezes.

RLS não é exercida aqui (SQLite — ver `conftest.py`); o isolamento cross-tenant da aplicação já é
coberto por `test_investments_rls.py` (`rls_e2e`, Postgres real).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.investments import service as inv_service
from app.modules.investments.models import InvestmentAccount

REGISTER = {
    "legal_name": "Deriva Consultoria",
    "document": "11444777000161",
    "slug": "deriva",
    "email": "deriva@example.com",
    "name": "Dora",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _conta_bancaria(
    client: TestClient,
    headers,
    *,
    name="CDB Itaú",
    kind="investment",
    opening_date="2026-01-01",
    opening_balance_cents=0,
    opening_balance_is_known=True,
) -> dict:
    r = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": kind,
            "opening_date": opening_date,
            "opening_balance_cents": opening_balance_cents,
            "opening_balance_is_known": opening_balance_is_known,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _aplicacao(client: TestClient, headers, *, bank_account_id: str | None, name="Reserva") -> dict:
    r = client.post(
        "/investments",
        json={
            "name": name,
            "kind": "CDB",
            "index_rate_label": "CDI 110%",
            "opened_at": "2026-01-01",
            "bank_account_id": bank_account_id,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _transferencia(client, headers, *, de: str, para: str, valor: int, quando: str, kind: str):
    r = client.post(
        "/bank/transfers",
        json={
            "from_account_id": de,
            "to_account_id": para,
            "amount_cents": valor,
            "posted_at": quando,
            "kind": kind,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _rendimento(client, headers, account_id: str, *, valor: int, quando: str):
    r = client.post(
        f"/investments/{account_id}/yield",
        json={"amount_cents": valor, "date": quando, "chart_account_id": None},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _acc(db: Session, account_id: str) -> InvestmentAccount:
    return db.get(InvestmentAccount, account_id)


# ── Teste 6 da spec §5 ────────────────────────────────────────────────────────────────────────


def test_o_saldo_de_abertura_entra_no_principal(client, db, headers):
    """O dinheiro que já estava aplicado no dia do cadastro é principal, e nunca teve movimento.

    Sem este termo, uma conta cadastrada com R$ 10.000 aplicados mostraria principal ZERO — um
    número errado com aparência de fato, que é a família de defeito que a Onda 0 existe para não
    repetir. É também o caso do fundador: ele cadastra a conta com o saldo que já tem.
    """
    conta = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    assert inv_service.principal_derivado(db, _acc(db, app_["id"])) == 10_000_00


# ── Teste 5 da spec §5 ────────────────────────────────────────────────────────────────────────


def test_aporte_MOVE_o_principal(client, db, headers):
    """Transferir da corrente para a aplicação aumenta o principal. É a metade viva do recorte."""
    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    aplicacao = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=aplicacao["id"])

    _transferencia(
        client,
        headers,
        de=corrente["id"],
        para=aplicacao["id"],
        valor=3_000_00,
        quando="2026-02-10",
        kind="investment_in",
    )

    assert inv_service.principal_derivado(db, _acc(db, app_["id"])) == 13_000_00


# ── Teste 4 da spec §5 ────────────────────────────────────────────────────────────────────────


def test_rendimento_NAO_move_o_principal(client, db, headers):
    """Registrar rendimento não mexe no principal — ele já é contado por `accrued_yield_cents`.

    ⚠️ Este teste sozinho NÃO prova o recorte: se `exclude_sources` fosse ignorado e a soma
    excluísse tudo, ele passaria igual. Quem o completa é `test_aporte_MOVE_o_principal`, acima.
    Os dois juntos particionam o conjunto: um membro de cada lado.
    """
    aplicacao = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=aplicacao["id"])

    _rendimento(client, headers, app_["id"], valor=150_00, quando="2026-02-28")

    acc = _acc(db, app_["id"])
    assert acc.accrued_yield_cents == 150_00, "o rendimento foi registrado (controle positivo)"
    assert inv_service.principal_derivado(db, acc) == 10_000_00, "e NÃO entrou no principal"


# ── Teste 2 da spec §5 — a invariante ─────────────────────────────────────────────────────────


def test_a_invariante_saldo_igual_principal_mais_rendimento(client, db, headers):
    """`derived_balance(conta) == principal + accrued_yield`, com aporte, rendimento E resgate.

    Vale POR CONSTRUÇÃO enquanto todo rendimento tiver perna bancária — que é o que a Onda 2b-i
    garantiu com o 409 de `register_yield`. Quebrá-la é sintoma de movimento escrito por fora da
    Regra da Origem.
    """
    from app.modules.bank import service as bank_service

    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    aplicacao = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=aplicacao["id"])

    _transferencia(
        client,
        headers,
        de=corrente["id"],
        para=aplicacao["id"],
        valor=3_000_00,
        quando="2026-02-10",
        kind="investment_in",
    )
    _rendimento(client, headers, app_["id"], valor=150_00, quando="2026-02-28")
    _transferencia(
        client,
        headers,
        de=aplicacao["id"],
        para=corrente["id"],
        valor=2_000_00,
        quando="2026-03-05",
        kind="investment_out",
    )

    acc = _acc(db, app_["id"])
    saldo = bank_service.derived_balance(db, bank_account_id=aplicacao["id"])
    assert saldo == inv_service.principal_derivado(db, acc) + acc.accrued_yield_cents
    assert saldo == 11_150_00, "10.000 + 3.000 + 150 − 2.000"


# ── Teste 3 da spec §5 ────────────────────────────────────────────────────────────────────────


def test_saldo_de_abertura_desconhecido_da_None_e_NAO_zero(client, db, headers):
    """Conta cadastrada como "tenho a conta e não sei o saldo" (Story 8.21) ⇒ principal `None`.

    **Zero seria uma afirmação** — *"você não tem nada aplicado"* —, falsa e indistinguível de um
    saldo genuinamente zerado. `None` é a ausência da afirmação, e é o princípio que a 8.21 fixou:
    suprimir a afirmação, nunca o número.
    """
    conta = _conta_bancaria(
        client, headers, opening_balance_cents=0, opening_balance_is_known=False
    )
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    principal = inv_service.principal_derivado(db, _acc(db, app_["id"]))
    assert principal is None
    assert principal != 0, "o 0 aqui seria uma afirmação; queremos a ausência dela"


def test_aplicacao_sem_vinculo_da_None(client, db, headers):
    """Sem `bank_account_id` não há de onde derivar. `None`, não zero, pelo mesmo motivo acima."""
    app_ = _aplicacao(client, headers, bank_account_id=None)
    assert inv_service.principal_derivado(db, _acc(db, app_["id"])) is None


def test_principal_negativo_quando_o_resgate_excede(client, db, headers):
    """Resgate BRUTO (principal + rendimento não lançado) deixa o principal negativo — e aparece.

    Clampar em zero seria esconder; recusar o resgate seria recusar um fato que já aconteceu no
    banco. O número aparece como é, e quem o nomeia é a tela (spec §4.4).
    """
    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    aplicacao = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=aplicacao["id"])

    _transferencia(
        client,
        headers,
        de=aplicacao["id"],
        para=corrente["id"],
        valor=10_500_00,
        quando="2026-03-05",
        kind="investment_out",
    )

    assert inv_service.principal_derivado(db, _acc(db, app_["id"])) == -500_00


def test_principais_derivados_resolve_em_lote(client, db, headers):
    """A versão de lote existe para o `GET /investments` não virar N+1 — uma query, N contas."""
    c1 = _conta_bancaria(client, headers, name="CDB A", opening_balance_cents=1_000_00)
    c2 = _conta_bancaria(client, headers, name="CDB B", opening_balance_cents=2_000_00)
    a1 = _aplicacao(client, headers, bank_account_id=c1["id"], name="A")
    a2 = _aplicacao(client, headers, bank_account_id=c2["id"], name="B")
    a3 = _aplicacao(client, headers, bank_account_id=None, name="C")

    accs = [_acc(db, a["id"]) for a in (a1, a2, a3)]
    assert inv_service.principais_derivados(db, accs) == {
        a1["id"]: 1_000_00,
        a2["id"]: 2_000_00,
        a3["id"]: None,
    }


# ── Os nove leitores da coluna (spec §4.2.1) ──────────────────────────────────────────────────


def test_a_api_devolve_o_principal_derivado_e_ignora_a_coluna(client, db, headers):
    """`GET /investments` responde o CALCULADO, não o que está gravado na coluna.

    A coluna é semeada com um valor absurdo de propósito: se a API o devolvesse, o teste falharia
    com um número reconhecível em vez de um zero ambíguo.
    """
    conta = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    acc = _acc(db, app_["id"])
    acc.principal_cents = 777_77  # o valor congelado, que ninguém pode mais ler
    db.commit()

    r = client.get("/investments", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()[0]["principal_cents"] == 10_000_00


def test_rentabilidade_e_None_com_principal_None_e_com_principal_negativo(client, db, headers):
    """`_pct` protege os TRÊS casos sem número: `None`, zero e negativo.

    `None` levantaria `TypeError` (divisão por `None`). **Negativo é o mais perigoso dos três**:
    devolveria um percentual de sinal invertido — plausível na tela, e errado. Rentabilidade sobre
    principal negativo não é um número menor: é uma pergunta sem sentido.
    """
    # (a) principal None — saldo de abertura desconhecido
    c_desconhecida = _conta_bancaria(
        client,
        headers,
        name="CDB sem lastro",
        opening_balance_cents=0,
        opening_balance_is_known=False,
    )
    a_none = _aplicacao(client, headers, bank_account_id=c_desconhecida["id"], name="Sem lastro")
    r = client.get(f"/investments/{a_none['id']}/rentability", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["principal_cents"] is None
    assert r.json()["total_rentability_pct"] is None

    # (b) principal negativo — resgate bruto
    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    aplic = _conta_bancaria(client, headers, name="CDB neg", opening_balance_cents=10_000_00)
    a_neg = _aplicacao(client, headers, bank_account_id=aplic["id"], name="Resgatada")
    _rendimento(client, headers, a_neg["id"], valor=500_00, quando="2026-02-28")
    _transferencia(
        client,
        headers,
        de=aplic["id"],
        para=corrente["id"],
        valor=10_500_00,
        quando="2026-03-05",
        kind="investment_out",
    )
    r = client.get(f"/investments/{a_neg['id']}/rentability", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["principal_cents"] == -500_00, "o número aparece como é"
    assert r.json()["total_rentability_pct"] is None, "a rentabilidade sobre ele, não"


# ── Teste 7 da spec §5 — a recusa ─────────────────────────────────────────────────────────────


def test_editar_o_principal_e_recusado_com_409(client, headers):
    """`PATCH` com `principal_cents` → 409 apontando para a ação REAL (Onda 2b-ii).

    ⚠️ **Este 409 é o OPOSTO do 409 da 2b-i.** Aquele era caminho normal — o dono batia nele ao
    registrar rendimento, e por isso a tela oferecia a saída ali mesmo. Este é **inalcançável pela
    tela** (o campo saiu do formulário): se disparar, é integração antiga ou defeito. É guarda de
    contrato, não fluxo — e por isso **não** tem `detail["acao"]`: um `acao` sem modal do outro
    lado seria um contrato com ninguém.

    A asserção é sobre trechos ESPECÍFICOS da frase, não sobre uma palavra genérica: "aporte"
    sozinho casaria com quase qualquer texto sobre aplicação. A manobra que a Onda 2 pegou foi
    `"trilho" in detail` casando também *"fora do trilho"*.
    """
    conta = _conta_bancaria(client, headers)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    r = client.patch(
        f"/investments/{app_['id']}", json={"principal_cents": 5_000_00}, headers=headers
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, str), "guarda de contrato não é 409 acionável — sem detail['acao']"
    assert "calculado pelos movimentos" in detail
    assert "registre a transferência" in detail


def test_criar_com_principal_diferente_de_zero_e_recusado(client, headers):
    """No CADASTRO o caminho do valor já aplicado é o **saldo de abertura** da conta bancária.

    Recusar sem dizer onde informar seria o beco sem saída que a Onda 2b-i pagou para evitar.
    """
    conta = _conta_bancaria(client, headers)
    r = client.post(
        "/investments",
        json={
            "name": "Reserva",
            "opened_at": "2026-01-01",
            "bank_account_id": conta["id"],
            "principal_cents": 10_000_00,
        },
        headers=headers,
    )
    assert r.status_code == 409, r.text
    assert "saldo de abertura" in r.json()["detail"]


def test_criar_com_principal_zero_continua_passando(client, headers):
    """O default do schema é `0`. Recusá-lo quebraria todo cliente que não manda o campo.

    Sem este teste, a guarda mais óbvia (`if data.principal_cents is not None`) passaria verde e
    quebraria o cadastro inteiro em produção — o campo tem default, então ele NUNCA é `None`.
    """
    conta = _conta_bancaria(client, headers)
    r = client.post(
        "/investments",
        json={"name": "Reserva", "opened_at": "2026-01-01", "bank_account_id": conta["id"]},
        headers=headers,
    )
    assert r.status_code == 201, r.text


# ── Teste 9 da spec §5 — a auditoria ──────────────────────────────────────────────────────────


def test_a_auditoria_reporta_a_divergencia_sem_corrigir(client, db, headers):
    """O script REPORTA. Se ele corrigisse, o `UPDATE` que esta onda existe para não fazer voltaria
    pela porta dos fundos — e alguém o rodaria no deploy sem ler a saída.
    """
    from app.scripts import investment_audit

    conta = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    acc = _acc(db, app_["id"])
    acc.principal_cents = 777_77
    db.commit()

    linhas = investment_audit.auditar(db)

    assert linhas == [
        {
            "id": app_["id"],
            "name": "Reserva",
            "coluna_cents": 777_77,
            "derivado_cents": 10_000_00,
            "diverge": True,
        }
    ]
    db.refresh(acc)
    assert acc.principal_cents == 777_77, "a auditoria NÃO corrige — a coluna segue como estava"


def test_a_auditoria_nao_marca_divergencia_quando_batem(client, db, headers):
    """Controle negativo: sem ele, um `diverge: True` fixo passaria no teste acima."""
    from app.scripts import investment_audit

    conta = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])
    acc = _acc(db, app_["id"])
    acc.principal_cents = 10_000_00
    db.commit()

    assert investment_audit.auditar(db)[0]["diverge"] is False


def test_a_auditoria_nao_chama_de_divergencia_o_que_ela_nao_consegue_comparar(client, db, headers):
    """Principal `None` (saldo de abertura desconhecido) não é divergência — é ausência de medida.

    Marcá-lo mandaria o dono caçar um erro que não existe. É o modo de falha que o épico chama de
    "pior do que ficar calado".
    """
    from app.scripts import investment_audit

    conta = _conta_bancaria(
        client, headers, opening_balance_cents=0, opening_balance_is_known=False
    )
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])
    acc = _acc(db, app_["id"])
    acc.principal_cents = 999_99
    db.commit()

    linha = investment_audit.auditar(db)[0]
    assert linha["derivado_cents"] is None
    assert linha["diverge"] is False


def test_a_auditoria_formata_valor_negativo_e_desconhecido(client, headers):
    """`_reais` é o que o dono lê na saída — negativo com sinal, `None` como "não sei"."""
    from app.scripts.investment_audit import _reais

    assert _reais(10_000_00) == "R$ 10.000,00"
    assert _reais(-500_00) == "-R$ 500,00"
    assert _reais(0) == "R$ 0,00"
    assert _reais(None) == "não sei"
