"""`GET /payables/bills/paid-before` — o agregado que alimenta o aviso pró-ativo (Story 8.11).

**O que este endpoint responde:** *"quantas contas eu já paguei ANTES deste dia?"* — para que o
cadastro da conta bancária possa dizer, **antes de salvar**, quantas contas pagas ficariam fora do
extrato do e1p com a `opening_date` escolhida (o saldo derivado só soma `posted_at > opening_date`,
e `_validate_posted_at` recusa o resto com 422).

**O que ele NÃO responde, e é a distinção mais fina da story** (AC4 / `CLAUDE.md` Regra 5): ele não
produz um saldo. O saldo de abertura é um fato **sobre o banco**, que o sistema por definição não
conhece; derivá-lo de `payables` seria somar o que o sistema sabe e chamar de "o que o banco diz" —
a circularidade que faria a divergência ir a zero por construção no dia um. **O e1p não inventa o
número: ele diz qual número ir buscar.**

Três regras duras exercitadas aqui:

- **eixo de CAIXA** (`paid_at`), nunca de competência (`competence_date`) nem de vencimento
  (`due_date`) — `payables/models.py:6-9`, *"nunca inverter"*;
- **borda `<` estrita**, casando com `posted_at > opening_date` do saldo derivado: conta paga
  exatamente na data de corte fica de fora, e por isso a data que o aviso sugere é o **dia
  anterior** à conta paga mais antiga;
- **`status='paid'` com `paid_at IS NULL` (legado) fica de fora**: sem a data do caixa não dá para
  afirmar de que lado da abertura ela cai, e chutar seria inventar.

Isolamento cross-tenant NÃO é exercido aqui (SQLite — ver `conftest.py`): está em
`test_bank_rls.py::test_paid_before_isolamento_cross_tenant` (`rls_e2e`, Postgres real).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.payables.models import STATUS_PAID, Payable
from app.modules.payables.schemas import PayablesPaidBeforeOut

REGISTER = {
    "legal_name": "Paid Before ME",
    "document": "11444777000161",
    "slug": "paidbefore",
    "email": "paidbefore@example.com",
    "name": "Bruna",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _bill(client: TestClient, headers, *, amount_cents: int, due_date: str = "2026-06-10") -> dict:
    resp = client.post(
        "/payables/bills",
        json={
            "description": "Conta",
            "category": "Geral",
            "supplier": "Fornecedor",
            "amount_cents": amount_cents,
            "due_date": due_date,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _pagar_em(db: Session, payable_id: str, dia: str) -> None:
    """Baixa com data controlada.

    `mark_paid` carimba `datetime.now(UTC)` e não aceita data — a rota de baixa retroativa é a
    Story 8.12, que ainda não existe. Para exercitar a contagem por `paid_at` a escrita é direta,
    do mesmo jeito que `test_bank_accounts.py` fabrica o estado pré-guarda do BANK-001.
    """
    p = db.get(Payable, payable_id)
    p.status = STATUS_PAID
    p.paid_at = datetime.fromisoformat(f"{dia}T12:00:00+00:00")
    db.commit()


def _paid_before(client: TestClient, headers, dia: str) -> dict:
    resp = client.get("/payables/bills/paid-before", params={"date": dia}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_requires_auth(client: TestClient):
    resp = client.get("/payables/bills/paid-before", params={"date": "2026-07-01"})
    assert resp.status_code == 401


def test_tenant_sem_conta_paga_devolve_zeros_e_datas_nulas(client: TestClient, headers):
    """Zero é zero, e as datas são `None` — não uma data fabricada.

    O `None` é o que permite à UI ficar **em silêncio** (AC3: nenhum aviso com N == 0). Uma data
    default aqui viraria uma frase afirmando algo sobre um conjunto vazio.
    """
    body = _paid_before(client, headers, "2026-07-30")
    assert body == {
        "count": 0,
        "total_cents": 0,
        "oldest_paid_on": None,
        "newest_paid_on": None,
    }


def test_conta_paga_com_todos_os_campos(client: TestClient, headers, db: Session):
    b1 = _bill(client, headers, amount_cents=120_000)
    b2 = _bill(client, headers, amount_cents=80_000)
    b3 = _bill(client, headers, amount_cents=50_000)
    _pagar_em(db, b1["id"], "2026-05-03")
    _pagar_em(db, b2["id"], "2026-06-20")
    _pagar_em(db, b3["id"], "2026-07-11")

    body = _paid_before(client, headers, "2026-07-30")
    assert body["count"] == 3
    assert body["total_cents"] == 250_000
    assert body["oldest_paid_on"] == "2026-05-03"
    assert body["newest_paid_on"] == "2026-07-11"


def test_a_borda_e_estrita_conta_paga_NA_data_de_corte_fica_de_fora(
    client: TestClient, headers, db: Session
):
    """**Mutante:** trocar `<` por `<=` aqui faria o aviso sugerir a data errada.

    `_movements_sums` soma `posted_at > opening_date`, **estritamente**, e `_validate_posted_at`
    recusa `posted_at <= opening_date` com 422. Uma conta paga exatamente na data de abertura fica
    fora do saldo do mesmo jeito — por isso ela **não** conta como "coberta" e por isso a data que
    o aviso sugere é o **dia anterior** à mais antiga, nunca o mesmo dia.
    """
    b = _bill(client, headers, amount_cents=100_000)
    _pagar_em(db, b["id"], "2026-06-15")

    assert _paid_before(client, headers, "2026-06-15")["count"] == 0, (
        "conta paga NA data de corte entrou na contagem — a borda virou `<=` e a data sugerida "
        "pelo aviso passaria a deixar essa conta fora do extrato"
    )
    assert _paid_before(client, headers, "2026-06-16")["count"] == 1


def test_a_borda_e_estrita_tambem_na_meia_noite_exata(client: TestClient, headers, db: Session):
    """**Mutante:** `paid_at < corte` → `paid_at <= corte`.

    A comparação por data de calendário é feita como limite de **timestamp** (`paid_at < meia-noite
    UTC do dia de corte`) porque `::date` não existe no SQLite dos testes. Isso deixa uma borda que
    o teste do dia inteiro (acima) não alcança: uma baixa carimbada **exatamente** em
    `00:00:00 UTC` do dia de corte. Ela é do dia de corte, e portanto está FORA — pelo mesmo motivo
    que qualquer outra hora daquele dia.
    """
    b = _bill(client, headers, amount_cents=100_000)
    linha = db.get(Payable, b["id"])
    linha.status = STATUS_PAID
    linha.paid_at = datetime(2026, 6, 15, 0, 0, 0, tzinfo=UTC)
    db.commit()

    assert _paid_before(client, headers, "2026-06-15")["count"] == 0, (
        "a borda do timestamp virou `<=`: uma baixa na meia-noite exata do dia de corte entrou"
    )


def test_conta_em_aberto_e_cancelada_ficam_de_fora(client: TestClient, headers, db: Session):
    """Só o que já **saiu da conta** conta: em aberto ainda não saiu, cancelada nunca vai sair."""
    aberta = _bill(client, headers, amount_cents=999_999)
    cancelada = _bill(client, headers, amount_cents=999_999)
    paga = _bill(client, headers, amount_cents=70_000)
    assert client.post(
        f"/payables/bills/{cancelada['id']}/cancel", headers=headers
    ).status_code == 200
    _pagar_em(db, paga["id"], "2026-06-01")
    assert aberta["status"] == "open"

    body = _paid_before(client, headers, "2026-07-01")
    assert body["count"] == 1
    assert body["total_cents"] == 70_000


def test_paga_sem_paid_at_legado_fica_de_fora(client: TestClient, headers, db: Session):
    """`status='paid'` com `paid_at IS NULL` **não** entra — e o teste fixa isso.

    Sem a data do caixa não há como afirmar de que lado da abertura a conta cai. Incluí-la faria o
    aviso contar uma conta que ele não sabe datar; e as datas do intervalo (`oldest`/`newest`)
    passariam a descrever um conjunto diferente do que `count` conta.
    """
    orfa = _bill(client, headers, amount_cents=333_000)
    linha = db.get(Payable, orfa["id"])
    linha.status = STATUS_PAID
    linha.paid_at = None
    db.commit()

    body = _paid_before(client, headers, "2026-07-30")
    assert body == {
        "count": 0,
        "total_cents": 0,
        "oldest_paid_on": None,
        "newest_paid_on": None,
    }


def test_contagem_usa_paid_at_e_NUNCA_due_date(client: TestClient, headers, db: Session):
    """**A regra dura** (`payables/models.py:6-9`): caixa usa `paid_at`, nunca `due_date`.

    O caso do fundador é justamente o descasado (*"se estiver fazendo retroativo, pq não deu certo
    no dia"*): conta que **venceu** em maio e só foi **paga** em julho. Pelo vencimento ela estaria
    coberta por uma abertura em junho; pelo caixa, não — e é o caixa que decide se o dinheiro saiu
    antes de a conta abrir no e1p.
    """
    b = _bill(client, headers, amount_cents=45_000, due_date="2026-05-05")
    _pagar_em(db, b["id"], "2026-07-20")

    # Corte em 01/06: pelo VENCIMENTO (05/05) ela contaria; pelo CAIXA (20/07) não.
    assert _paid_before(client, headers, "2026-06-01")["count"] == 0, (
        "a contagem caiu no eixo de competência/vencimento — regra invertida"
    )
    assert _paid_before(client, headers, "2026-07-21")["count"] == 1


def test_date_invalida_e_422(client: TestClient, headers):
    resp = client.get(
        "/payables/bills/paid-before", params={"date": "30/07/2026"}, headers=headers
    )
    assert resp.status_code == 422


def test_a_rota_nao_e_capturada_por_bills_id(client: TestClient, headers):
    """⚠️ **Ordem de registro.** `GET /bills/{payable_id}` está declarada DEPOIS de propósito.

    Invertida, o FastAPI casaria `paid-before` como um `payable_id` e a rota nova responderia 404
    "Conta não encontrada" — um bug silencioso, porque o front trata falha do aviso como "não
    mostra nada" (degradação em silêncio, AC3).
    """
    resp = client.get("/payables/bills/paid-before?date=2026-07-30", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "count" in resp.json()
    # E a rota por id continua funcionando (a ordem não quebrou a irmã).
    b = _bill(client, headers, amount_cents=1_000)
    assert client.get(f"/payables/bills/{b['id']}", headers=headers).status_code == 200


# ── AC4 — teste de AUSÊNCIA: nada aqui é, vira ou sugere um saldo ─────────────────────────────


def test_a_resposta_nao_tem_nenhum_campo_de_saldo(client: TestClient, headers):
    """Varredura de contrato: `PayablesPaidBeforeOut` não expõe saldo nenhum.

    Se um dia alguém acrescentar `saldo_sugerido_cents` (ou `opening_balance_cents`) aqui, terá
    somado o que o sistema sabe e chamado de "o que o banco diz" — a circularidade da Regra 5, com
    a divergência indo a zero por construção no dia um e a métrica primária do épico morrendo
    junto. `total_cents` é o total **pago**, e a UI o rotula como tal.
    """
    campos = set(PayablesPaidBeforeOut.model_fields)
    assert campos == {"count", "total_cents", "oldest_paid_on", "newest_paid_on"}
    proibidos = [c for c in campos if "saldo" in c or "opening" in c or "balance" in c]
    assert proibidos == [], (
        f"campo de saldo em PayablesPaidBeforeOut: {proibidos}. O saldo de abertura é um fato "
        "SOBRE O BANCO — o e1p confirma, nunca deriva (AC4 / CLAUDE.md Regra 5)."
    )


def test_o_endpoint_nao_escreve_nada(client: TestClient, headers, db: Session):
    """Read-only de verdade: chamar não cria conta, não muda status, não deixa auditoria."""
    from app.core.audit import AuditEntry

    b = _bill(client, headers, amount_cents=10_000)
    _pagar_em(db, b["id"], "2026-06-01")
    antes = (
        db.query(Payable).count(),
        db.query(AuditEntry).count(),
        db.get(Payable, b["id"]).status,
    )

    for _ in range(3):
        _paid_before(client, headers, "2026-07-30")

    assert (
        db.query(Payable).count(),
        db.query(AuditEntry).count(),
        db.get(Payable, b["id"]).status,
    ) == antes


def test_bank_service_nao_importa_payables(client: TestClient):
    """⚠️ **Restrição normativa do epic §4.1(d)**, e a razão de o endpoint morar em `payables`.

    *"A dependência é de negócio para banco, nunca a volta"*: `payables`/`receivables` **podem**
    importar `app.modules.bank`; `app.modules.bank` **nunca** importa `payables`/`receivables`. Um
    endpoint em `bank/router.py` que contasse contas a pagar recriaria o ciclo — *"sem isso, o
    primeiro atalho de conveniência recria um ciclo"*.

    Esta é a versão MÍNIMA da checagem, restrita ao arquivo que esta story tocou. O gate estrutural
    completo (AST + texto cru sobre o pacote inteiro, `test_bank_nao_importa_payables`) é da Story
    8.9 e **não** é antecipado aqui: a 8.11 pode mergear antes dela, e aproveitar a janela para
    escrever o gate de outra story seria expandir escopo.
    """
    from pathlib import Path

    servico = Path(__file__).resolve().parents[1] / "app" / "modules" / "bank" / "service.py"
    fonte = servico.read_text(encoding="utf-8")
    assert "modules.payables" not in fonte and "modules import payables" not in fonte, (
        "`bank/service.py` passou a importar `payables` — a dependência é de negócio para banco, "
        "NUNCA a volta (epic §4.1d)"
    )
