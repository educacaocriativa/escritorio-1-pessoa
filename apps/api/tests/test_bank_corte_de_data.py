"""O corte de data das superfícies de saldo corrente (Story 8.10).

**A story inteira em uma frase:** `until=None` deixou de significar *"sem limite superior"* e passou
a significar **hoje**. A assinatura de `derived_balance`/`derived_balances_as_of` é byte a byte a
mesma; só o **significado do default** mudou — e é por isso que este arquivo existe. O compilador
não ajuda em nada aqui: nenhum chamador precisou mudar, nenhum tipo se moveu, e a única evidência
de que a mudança aconteceu é comportamento sob um cenário que **hoje não existe em produção**.

**Por que o cenário não existe (ainda), e por que isso é o ponto.** `_validate_posted_at` recusa
`posted_at` futuro com 422, então não há como criar movimento futuro pela API — e esta story **não
o afrouxa** (quem o faz é a 8.12/8.14, para o caminho de ORIGEM; a guarda continua valendo para a
porta manual). O cenário é montado aqui **direto pelo model**, que é legítimo: a partir da 8.14 o
sincronizador criará exatamente essas linhas por um caminho que não passa pela guarda.

Consequência prática: no dia em que esta story subir, **os números não mudam para ninguém**. Ela é
uma guarda posicionada **antes** do problema, não a correção de um sintoma. O teste é o único lugar
onde a mudança é visível — e é por isso que ele precisa ser exigente.

**Cobertura (AC1-AC8):**
- default = hoje nas duas funções, e o movimento futuro **não** conta;
- `SEM_CORTE` (`date.max`) inclui o futuro — a saída de emergência existe e funciona;
- a borda: movimento **exatamente hoje** conta (o corte é inclusivo);
- os caminhos de `bank/router.py` que herdaram o novo default, um a um;
- **nenhum** deles "consertado" com `SEM_CORTE` (varredura AST — AC4);
- `BankBalanceOut.until` nunca mais `null`, e é a data **efetivamente usada** (AC5);
- a **assimetria** de `active_balance_total`, declarada e travada por teste de contrato (AC6);
- IV1/IV2/IV3: Conferência, Projeção e DRE idênticas campo a campo com o movimento futuro plantado.

RLS não é exercida aqui (SQLite — ver `conftest.py`); o caso cross-tenant do corte de data está em
`test_bank_rls.py` (`rls_e2e`, Postgres real).
"""
from __future__ import annotations

import ast
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today
from app.modules.bank import reconciliation, service
from app.modules.bank.models import (
    KIND_CHECKING,
    KIND_INVESTMENT,
    SOURCE_MANUAL,
    STATUS_IGNORED,
    STATUS_UNMATCHED,
    BankTransaction,
)
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import projection as projection_service

REGISTER = {
    "legal_name": "Corte de Data ME",
    "document": "11444777000161",
    "slug": "cortededata",
    "email": "corte@example.com",
    "name": "Dora",
    "password": "uma-senha-bem-grande",
}

OPENING_CENTS = 1_000_00


def _hoje() -> date:
    """A MESMA âncora do service (`service._today`), nunca `date.today()` solto.

    O service passou a ancorar "hoje" no FUSO DO TENANT; o teste segue. Como o tenant de teste
    fica com o fuso padrão, basta a primitiva pura — sem `db`, sem um segundo relógio.
    """
    return tenant_today(DEFAULT_TENANT_TIMEZONE)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _conta(client: TestClient, headers, **over) -> dict:
    """Conta aberta ONTEM, para que "hoje" e "amanhã" sejam ambos posteriores à abertura.

    Abrir num dia fixo (`2026-07-01`) daria uma bomba-relógio invertida: o teste do corte compara
    contra o relógio real, e uma abertura fixa envelheceria junto com o repositório sem nunca
    quebrar — até o dia em que quebrasse por outro motivo. Ancorar em `hoje - 1` mantém as duas
    pontas móveis juntas.
    """
    payload = {
        "name": "Itaú PJ",
        "kind": KIND_CHECKING,
        "opening_balance_cents": OPENING_CENTS,
        "opening_date": (_hoje() - timedelta(days=1)).isoformat(),
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _plantar(
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    amount_cents: int,
    posted_at: date,
    status: str = STATUS_UNMATCHED,
) -> BankTransaction:
    """Monta o movimento **direto pelo model**, contornando `_validate_posted_at` de propósito.

    ⚠️ Isto **não** é um atalho para escapar de uma validação inconveniente — é a única forma de
    montar hoje o estado que a 8.12/8.14 vai produzir amanhã. A guarda da porta manual continua de
    pé e tem os seus próprios testes (`test_bank_transactions.py`); esta story não a toca. Se um dia
    alguém "consertar" este helper fazendo-o passar pela API, o cenário do futuro deixa de ser
    montável e **todo este arquivo vira vácuo** — sem nenhum teste ficar vermelho.
    """
    tx = BankTransaction(
        tenant_id=tenant_id,
        bank_account_id=account_id,
        posted_at=posted_at,
        amount_cents=amount_cents,
        raw_description="Agendado (plantado pelo teste, como a 8.14 fará)",
        user_description="",
        dedup_hash=f"plantado-{account_id}-{posted_at.isoformat()}-{amount_cents}",
        source=SOURCE_MANUAL,
        status=status,
    )
    db.add(tx)
    db.commit()
    return tx


# ── AC1/AC2/AC3 — o default mudou de significado ─────────────────────────────────────────────


def test_default_de_derived_balance_e_hoje_e_o_futuro_fica_de_fora(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """**O teste que só faz sentido depois desta story.** R$ 5.000 agendados para daqui a 5 dias.

    Antes da 8.10, `derived_balance()` somava esse dinheiro: o dono veria no *"Total em contas"* um
    valor que já tem destino marcado. Agora não vê — e continua não vendo sem precisar lembrar de
    passar data nenhuma. É a definição de **fail-closed**.
    """
    acc = _conta(client, headers)
    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-5_000_00,
        posted_at=_hoje() + timedelta(days=5),
    )

    assert service.derived_balance(db, bank_account_id=acc["id"]) == OPENING_CENTS, (
        "o saldo corrente somou um movimento com `posted_at` no FUTURO. É o defeito que a Story "
        "8.10 existe para impedir: o dono conta com R$ 5.000 que já têm destino marcado."
    )


def test_sem_corte_continua_incluindo_o_futuro(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """A saída de emergência existe, é explícita e é feia — `until=SEM_CORTE`.

    O par com o teste acima é o que prova que a mudança é de **corte**, não de dado: a linha está
    lá, some do saldo corrente e reaparece quando alguém pede o histórico inteiro **por escrito**.
    """
    acc = _conta(client, headers)
    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-5_000_00,
        posted_at=_hoje() + timedelta(days=5),
    )

    assert service.SEM_CORTE == date.max, "SEM_CORTE deixou de ser `date.max` (contrato do design)"
    assert (
        service.derived_balance(db, bank_account_id=acc["id"], until=service.SEM_CORTE)
        == OPENING_CENTS - 5_000_00
    )
    # E a diferença entre os dois números é EXATAMENTE o agendado — o insumo que a 8.14 vai querer.
    corrente = service.derived_balance(db, bank_account_id=acc["id"])
    historico = service.derived_balance(db, bank_account_id=acc["id"], until=service.SEM_CORTE)
    assert corrente - historico == 5_000_00


def test_a_borda_e_hoje_inclusive(client: TestClient, headers, tenant_id: str, db: Session):
    """`until` é **inclusivo**: o movimento de HOJE conta; o de amanhã não.

    A borda é o lugar onde um `<` no lugar de um `<=` esconderia o pagamento que o dono acabou de
    fazer — um saldo que "esquece" o dia corrente é indistinguível de um lançamento perdido.
    """
    acc = _conta(client, headers)
    _plantar(
        db, tenant_id=tenant_id, account_id=acc["id"], amount_cents=-100_00, posted_at=_hoje()
    )
    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-7_00,
        posted_at=_hoje() + timedelta(days=1),
    )

    assert service.derived_balance(db, bank_account_id=acc["id"]) == OPENING_CENTS - 100_00, (
        "ou o movimento de hoje ficou de fora (corte exclusivo), ou o de amanhã entrou"
    )


def test_derived_balances_as_of_segue_a_mesma_regra(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """A versão em lote — a que a tela "Contas & Saldos" consome — muda pela mesma regra.

    Inclui a conta ARQUIVADA de propósito: `include_archived=True` continua sendo sobre *quais
    contas*, nunca sobre *qual janela de datas*. Misturar os dois recortes num parâmetro só seria o
    D-3 de novo.
    """
    a = _conta(client, headers, name="A", number="1")
    b = _conta(client, headers, name="B", number="2", opening_balance_cents=50_00)
    arq = _conta(client, headers, name="Z", number="3", opening_balance_cents=7_00)
    client.post(f"/bank/accounts/{arq['id']}/archive", headers=headers)

    futuro = _hoje() + timedelta(days=3)
    _plantar(db, tenant_id=tenant_id, account_id=a["id"], amount_cents=-900_00, posted_at=futuro)
    _plantar(db, tenant_id=tenant_id, account_id=arq["id"], amount_cents=-1_00, posted_at=futuro)

    assert service.derived_balances_as_of(db) == {a["id"]: OPENING_CENTS, b["id"]: 50_00}

    com_arquivadas = service.derived_balances_as_of(db, include_archived=True)
    assert com_arquivadas[arq["id"]] == 7_00, "arquivada também não soma o futuro"

    historico = service.derived_balances_as_of(db, as_of=service.SEM_CORTE, include_archived=True)
    assert historico[a["id"]] == OPENING_CENTS - 900_00
    assert historico[arq["id"]] == 7_00 - 1_00


def test_movimento_futuro_IGNORADO_continua_fora_pelos_dois_motivos(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """Os dois filtros são independentes e se compõem — nenhum "corrige" o outro.

    Um movimento futuro **e** ignorado fica fora do saldo corrente (pela data) e também fora do
    histórico com `SEM_CORTE` (pelo status). Se o segundo caso somasse, a 8.10 teria acidentalmente
    furado o `status <> 'ignored'` que mora dentro de `_movements_sums` (AC5 da 8.3).
    """
    acc = _conta(client, headers)
    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-333_00,
        posted_at=_hoje() + timedelta(days=2),
        status=STATUS_IGNORED,
    )

    assert service.derived_balance(db, bank_account_id=acc["id"]) == OPENING_CENTS
    assert (
        service.derived_balance(db, bank_account_id=acc["id"], until=service.SEM_CORTE)
        == OPENING_CENTS
    ), "ignorar deixou de tirar do saldo quando o movimento é futuro"


def test_resolve_until_e_a_unica_normalizacao():
    """`None` → hoje; qualquer data → ela mesma, intacta (inclusive `SEM_CORTE`)."""
    assert service.resolve_until(None, _hoje()) == _hoje()
    assert service.resolve_until(date(2026, 1, 15), _hoje()) == date(2026, 1, 15)
    assert service.resolve_until(service.SEM_CORTE, _hoje()) == date.max


# ── AC4 — os caminhos de `bank/router.py` ────────────────────────────────────────────────────


def test_as_rotas_de_conta_herdaram_o_corte_sem_edicao_de_chamador(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """As respostas de conta do router **não foram editadas** — e mesmo assim mudaram de resposta.

    É a forma da correção: `_out(acc, service.derived_balance(db, bank_account_id=acc.id))` continua
    idêntico nas 4 rotas de CRUD e na lista, e o corte chegou nelas pelo **significado do default**.
    Este teste é o que impede alguém de "otimizar" isso de volta passando `SEM_CORTE` sem perceber.

    ⚠️ `POST /bank/accounts` não aparece aqui por impossibilidade lógica, não por esquecimento: a
    conta nasce na própria chamada, então não existe movimento futuro para ela naquele instante. Ela
    compartilha a linha exata das outras três (mesma expressão, mesmo helper) e está coberta pela
    varredura estrutural `test_nenhuma_rota_de_saldo_corrente_usa_sem_corte`.
    """
    acc = _conta(client, headers)
    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-5_000_00,
        posted_at=_hoje() + timedelta(days=5),
    )

    # GET /bank/accounts/{id}
    assert client.get(
        f"/bank/accounts/{acc['id']}", headers=headers
    ).json()["saldo_derivado_cents"] == OPENING_CENTS

    # GET /bank/accounts (lista da 8.7 — a origem do "Total em contas")
    lista = client.get("/bank/accounts", headers=headers).json()
    assert [a["saldo_derivado_cents"] for a in lista] == [OPENING_CENTS]

    # PATCH /bank/accounts/{id}
    patch = client.patch(
        f"/bank/accounts/{acc['id']}", json={"name": "Itaú PJ (renomeada)"}, headers=headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["saldo_derivado_cents"] == OPENING_CENTS

    # POST /bank/accounts/{id}/archive
    arquivada = client.post(f"/bank/accounts/{acc['id']}/archive", headers=headers)
    assert arquivada.status_code == 200, arquivada.text
    assert arquivada.json()["saldo_derivado_cents"] == OPENING_CENTS


def test_nenhuma_rota_de_saldo_corrente_usa_sem_corte():
    """**AC4, em forma de varredura:** é PROIBIDO "consertar" as 6 chamadas passando `SEM_CORTE`.

    A tentação é real e chega com boa intenção: alguém vê o número mudar numa tela, procura o motivo
    e "restaura" o comportamento antigo no chamador — o que reintroduziria o defeito exatamente onde
    ele dói mais, com um diff que parece uma correção. `SEM_CORTE` é feio para ser notado; e este
    teste é quem nota quando ninguém está olhando.

    A asserção positiva no fim impede o vácuo: se `derived_balance` sumir de `router.py`, o teste
    passaria por não haver mais nada a proibir.

    **AST, não `grep`** — mesmo motivo do `test_conferencia_nao_usa_derived_balances_as_of`: as
    docstrings do router **precisam** poder citar a constante proibida para explicar por que ela é
    proibida. Uma varredura de texto tornaria a explicação impossível de escrever.
    """
    arvore = ast.parse(
        (Path(__file__).resolve().parents[1] / "app" / "modules" / "bank" / "router.py").read_text(
            encoding="utf-8"
        )
    )
    usos = [
        node
        for node in ast.walk(arvore)
        if (isinstance(node, ast.Name) and node.id == "SEM_CORTE")
        or (isinstance(node, ast.Attribute) and node.attr == "SEM_CORTE")
    ]
    assert not usos, (
        "AC4 VIOLADO: `bank/router.py` passou a USAR `SEM_CORTE` (linha(s) "
        f"{', '.join(str(n.lineno) for n in usos)}). Nenhuma superfície de saldo CORRENTE quer o "
        "futuro — se alguma passar a querer, a decisão precisa de story própria, não de um "
        "argumento acrescentado numa linha."
    )
    chamadas = [
        node.func.attr
        for node in ast.walk(arvore)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "derived_balance" in chamadas and "derived_balances_as_of" in chamadas, (
        "o router parou de usar as funções de saldo derivado — se a soma foi reimplementada aqui, "
        "a Regra dos Planos §1.3a ficou inauditável"
    )


# ── AC5 — `BankBalanceOut.until` nunca mais `null` ───────────────────────────────────────────


def test_balance_sem_query_devolve_a_data_de_hoje_no_payload(client: TestClient, headers):
    """O campo `until` para de se calar justamente na chamada mais comum.

    *"Um saldo sem a data em que foi apurado é um número que não dá para conferir"* — o contrato já
    estava escrito no router desde a 8.2, e vinha `null` sempre que ninguém passava a query.
    """
    acc = _conta(client, headers)
    body = client.get(f"/bank/accounts/{acc['id']}/balance", headers=headers).json()

    assert body["until"] is not None, (
        "`BankBalanceOut.until` voltou a vir `null` — a tela perde a data de apuração do saldo"
    )
    assert body["until"] == _hoje().isoformat()
    assert body["saldo_derivado_cents"] == OPENING_CENTS


def test_balance_com_query_ecoa_a_data_pedida(client: TestClient, headers, tenant_id, db: Session):
    """Passando `?until=`, o payload devolve **aquela** data — e o saldo é o daquela data.

    A normalização não pode "melhorar" um corte que o chamador informou: quem pergunta pelo saldo de
    uma data específica está conferindo contra o extrato daquele dia (Story 8.5).
    """
    acc = _conta(client, headers)
    ontem = _hoje() - timedelta(days=1)
    body = client.get(
        f"/bank/accounts/{acc['id']}/balance", params={"until": ontem.isoformat()}, headers=headers
    ).json()
    assert body["until"] == ontem.isoformat()


def test_o_until_devolvido_e_o_EFETIVAMENTE_usado_nao_o_cru_da_query(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """**O mutante mais perigoso desta story**, e a razão de o AC5 existir separado do AC1.

    Devolver `until=None` (o valor cru da query) junto com um saldo apurado até hoje faria o payload
    **mentir a data de apuração** — e mentir a data é pior do que não informá-la, porque o
    consumidor tem como não perceber. O par (saldo, data) tem de vir do mesmo corte, sempre.
    """
    acc = _conta(client, headers)
    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-800_00,
        posted_at=_hoje() + timedelta(days=4),
    )
    body = client.get(f"/bank/accounts/{acc['id']}/balance", headers=headers).json()

    # O saldo é o de HOJE...
    assert body["saldo_derivado_cents"] == OPENING_CENTS
    # ...e a data declarada é a MESMA que produziu esse número.
    assert body["until"] == _hoje().isoformat()
    assert (
        service.derived_balance(db, bank_account_id=acc["id"], until=date.fromisoformat(
            body["until"]
        ))
        == body["saldo_derivado_cents"]
    ), "o payload declarou uma data de apuração que não produz o saldo que ele devolveu"


# ── AC6 — a assimetria de `active_balance_total`, declarada e travada ────────────────────────


def test_active_balance_total_MANTEM_o_default_antigo(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """⚠️ **Assimetria DELIBERADA, não esquecimento** (AC6 / docstring da função).

    `active_balance_total(until=None)` continua significando *"sem limite superior"*: ela não delega
    para as duas funções normalizadas e o item 2.5 do epic não a nomeia. Este teste existe para que
    a próxima onda **não presuma** que ela mudou junto — e para que, se alguém decidir uniformizar,
    a decisão apareça aqui como uma expectativa que precisa ser reescrita à mão, com a ratificação
    §C-7.3 (dupla contagem do dia D na Projeção) na frente.
    """
    acc = _conta(client, headers)
    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-5_000_00,
        posted_at=_hoje() + timedelta(days=5),
    )

    assert service.active_balance_total(db) == OPENING_CENTS - 5_000_00, (
        "`active_balance_total` passou a cortar em hoje. Se foi de propósito, a mudança precisa de "
        "story própria: o único chamador de produção semeia a PROJEÇÃO, e o `until=today` que ele "
        "passa é o que impede a dupla contagem do dia D (ratificação §C-7.3)."
    )
    # E o corte explícito continua funcionando — é o que a Projeção usa, e é o que a salva.
    assert service.active_balance_total(db, until=_hoje()) == OPENING_CENTS


def test_active_balance_total_so_e_chamada_com_until_explicito():
    """**Teste de contrato (AC6):** todo chamador de PRODUÇÃO passa `until` explícito.

    A assimetria acima só é segura enquanto ninguém chamar esta função sem data. Um chamador novo
    que a omitisse somaria o futuro **em silêncio** — e o sintoma seria um saldo inicial de projeção
    inflado, plausível, sem exceção nenhuma no caminho. É o mesmo padrão de gate estrutural da Regra
    dos Planos: a varredura falha antes de o número mentir.

    Se você chegou aqui porque este teste ficou vermelho: **não adicione o seu arquivo à lista.**
    Passe `until=` na sua chamada. Se você realmente quer o histórico inteiro, passe
    `service.SEM_CORTE` e escreva na story por quê — é a primeira vez no repositório.
    """
    app_dir = Path(__file__).resolve().parents[1] / "app"
    faltando: list[str] = []
    encontrados = 0

    for py in sorted(app_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            nome = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if nome != "active_balance_total":
                continue
            encontrados += 1
            if not any(kw.arg == "until" for kw in node.keywords):
                faltando.append(f"{py.relative_to(app_dir)}:{node.lineno}")

    assert encontrados >= 1, (
        "nenhuma chamada de `active_balance_total` foi encontrada em `app/` — ou a função perdeu o "
        "último chamador (e a assimetria do AC6 deixou de ter razão de existir), ou esta varredura "
        "parou de varrer. Nos dois casos, este teste virou vácuo."
    )
    assert not faltando, (
        "chamada(s) de `active_balance_total` SEM `until` explícito: "
        f"{', '.join(faltando)}. Diferente de `derived_balance`, o default AQUI continua sendo "
        "'sem limite superior' (AC6 da Story 8.10) — sem `until`, esta soma inclui movimento "
        "agendado e o saldo inicial da Projeção nasce inflado, sem nenhum erro no caminho."
    )


# ── IV1/IV2/IV3 — o que NÃO pode ter mudado ──────────────────────────────────────────────────


def _seed_movimento_financeiro(client: TestClient, headers) -> None:
    """Uma cobrança e uma conta a pagar, para que a DRE do período não seja trivialmente vazia."""
    assert client.post(
        "/receivables/charges",
        json={"description": "Consultoria", "kind": "service", "method": "pix",
              "amount_cents": 300_000, "due_date": _hoje().isoformat()},
        headers=headers,
    ).status_code == 201
    assert client.post(
        "/payables/bills",
        json={"description": "Aluguel", "category": "Aluguel", "amount_cents": 120_000,
              "due_date": _hoje().isoformat()},
        headers=headers,
    ).status_code == 201


def test_IV1_conferencia_identica_campo_a_campo(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """**A verificação mais importante da story.** `reconciliation.py` não é editado (AC7).

    A conferência sempre passou `until = reference_date do checkpoint daquela conta` — explícito,
    nunca `None` —, então a mudança de default não a alcança. E a regra 6 do `CLAUDE.md` (mesma data
    dos dois lados) já mantinha o movimento posterior ao checkpoint fora da comparação. Snapshot
    campo a campo **com um movimento futuro plantado**: se este relatório se mexer, a story está
    errada.
    """
    acc = _conta(client, headers)
    hoje = _hoje()
    assert client.post(
        f"/bank/accounts/{acc['id']}/checkpoints",
        json={"reference_date": hoje.isoformat(), "balance_cents": 900_00, "origin": "manual"},
        headers=headers,
    ).status_code == 201

    janela = {"start": hoje - timedelta(days=7), "end": hoje}
    antes = asdict(reconciliation.reconciliation_report(db, **janela, today=hoje))
    assert antes["contas"][0]["divergencia_cents"] == 900_00 - OPENING_CENTS, (
        "pré-condição: a divergência conhecida tem de existir, senão o snapshot é de um relatório "
        "vazio e não prova nada"
    )

    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-5_000_00,
        posted_at=hoje + timedelta(days=5),
    )

    depois = asdict(reconciliation.reconciliation_report(db, **janela, today=hoje))
    assert depois == antes, (
        "a Conferência mudou por causa de um movimento FUTURO. Ela compara na data do checkpoint "
        "dos dois lados — se mudou, alguém trocou o `until` explícito por um default."
    )


def test_IV2_projecao_identica_campo_a_campo(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """`projection.py` **não é editado**, e `_saldo_inicial` já passava `until=today` (AC6).

    É a outra metade do teste de contrato acima: lá a varredura prova que o argumento está escrito;
    aqui o comportamento prova que ele funciona. Um movimento agendado não pode mover a semente da
    Projeção — se movesse, o runway do dono passaria a contar dinheiro que ainda não saiu.
    """
    _seed_movimento_financeiro(client, headers)
    acc = _conta(client, headers)
    hoje = _hoje()
    antes = asdict(projection_service.cash_projection(db, today=hoje))

    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-5_000_00,
        posted_at=hoje + timedelta(days=5),
    )

    depois = asdict(projection_service.cash_projection(db, today=hoje))
    assert depois == antes, (
        "a Projeção de Caixa mudou por causa de um movimento FUTURO — `_saldo_inicial` deixou de "
        "passar `until=today`, ou `active_balance_total` mudou de default (ver AC6)"
    )


def test_IV3_dre_identica_campo_a_campo(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """A DRE agrega por **competência** e não lê `bank_transactions`. Snapshot mesmo assim.

    Saldo bancário não entra em DRE em hipótese nenhuma (Regra dos Planos §1.3a) — este teste é o
    que garante que a 8.10 não abriu um caminho novo entre os planos por acidente.
    """
    _seed_movimento_financeiro(client, headers)
    acc = _conta(client, headers)
    hoje = _hoje()
    janela = {"start": hoje.replace(day=1), "end": hoje}
    antes = asdict(dre_service.dre_report(db, **janela))

    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=acc["id"],
        amount_cents=-5_000_00,
        posted_at=hoje + timedelta(days=5),
    )

    assert asdict(dre_service.dre_report(db, **janela)) == antes


def test_IV8_os_dois_totais_da_tela_nao_incluem_o_agendado(
    client: TestClient, headers, tenant_id: str, db: Session
):
    """IV8 — "Total em contas" e "Disponível como caixa" saem da lista, e a lista corta em hoje.

    Os dois totais são calculados no front a partir do `saldo_derivado_cents` de
    `GET /bank/accounts` (`contas.ts`), então basta a lista estar certa para os dois estarem. A
    conta de **aplicação** entra aqui para exercer também o recorte que exclui `investment`.
    """
    corrente = _conta(client, headers, name="Corrente", number="1")
    cdb = _conta(
        client, headers, name="CDB", number="2", kind=KIND_INVESTMENT,
        opening_balance_cents=900_00,
    )
    futuro = _hoje() + timedelta(days=6)
    _plantar(
        db, tenant_id=tenant_id, account_id=corrente["id"], amount_cents=-700_00, posted_at=futuro
    )
    _plantar(db, tenant_id=tenant_id, account_id=cdb["id"], amount_cents=-1_00, posted_at=futuro)

    saldos = {
        a["name"]: a["saldo_derivado_cents"]
        for a in client.get("/bank/accounts", headers=headers).json()
    }
    assert saldos == {"Corrente": OPENING_CENTS, "CDB": 900_00}
    # "Total em contas" (soma de tudo) e "Disponível como caixa" (exclui aplicação), ambos limpos.
    assert sum(saldos.values()) == OPENING_CENTS + 900_00
    assert saldos["Corrente"] == OPENING_CENTS
