"""Orquestração read-only do diagnóstico (Story 5.8, AC1, IV3).

Camada FINA de I/O que separa o mundo com efeito colateral (queries) do motor PURO (`engine.py`):
busca as saídas já calculadas das Stories 5.4 (lucratividade por contrato), 5.6 (rentabilidade de
investimento), 5.7 (projeção + runway) e 8.5 (conferência bancária, por conta), ADAPTA para as
entradas do motor e chama `engine.compute_signals(...)`. Nada aqui decide um sinal — essa é a
responsabilidade do engine puro.

⚠️ **Toda query desta story mora aqui** (Story 8.6, AC7). Se um dia parecer necessário buscar algo
"só o nome da conta", "só contar checkpoints" de dentro do `engine.py`, a resposta é sempre a
mesma: monta-se aqui e passa-se pronto. É essa fronteira que mantém o motor testável sem banco.

SOMENTE LEITURA: não escreve no banco. (O único write do módulo é o rastro de IA, feito pelo
`ai_narrator` quando a narrativa é gerada — ver router.)

[AUTO-DECISION] Comparação de margem período-a-período: usamos o período pedido `[start, end]` como
"depois" e a janela de MESMA duração imediatamente anterior como "antes" (a Story 5.4 já calcula a
DRE de um contrato para qualquer intervalo; aqui só a chamamos duas vezes por contrato). Só
contratos ASSINADOS entram (ativos) — rascunhos/cancelados não representam operação corrente.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.scheduling import janela_de_caixa
from app.modules.bank import reconciliation as bank_reconciliation
from app.modules.contracts import service as contracts_service
from app.modules.contracts.models import STATUS_SIGNED
from app.modules.financial_intelligence import engine
from app.modules.financial_intelligence import profitability as profitability_service
from app.modules.financial_intelligence import projection as projection_service
from app.modules.investments import service as investments_service

# ⚠️ **`_not_investment_yield` e `_as_utc_date` são IMPORTADOS, nunca reescritos** (Story 8.16,
# ratificação §C-1). O primeiro carrega a guarda de lógica ternária SQL
# (`coalesce(external_ref, '')`) que um reescritor distraído perderia — e a perda excluiria
# **todas**
# as cobranças normais, em silêncio; ele já foi esquecido uma vez por um @sm e lembrado por outro,
# *"o que é argumento para o predicado ter um lugar só"*. O segundo é a normalização de `paid_at`
# entre SQLite (texto) e Postgres (tz-aware): uma segunda cópia quebraria em exatamente um dos dois.
#
# Os dois nascem com `_`. A costura frouxa fica **registrada como dívida** (o precedente é
# `app/core/scheduling.py`, que nasceu público justamente por isso); torná-los públicos exigiria
# editar dois módulos fora do escopo desta story, e a instrução normativa é explícita: **importar,
# jamais copiar**.
from app.modules.payables.models import STATUS_PAID as PAYABLE_PAID
from app.modules.payables.models import STATUS_SCHEDULED as PAYABLE_SCHEDULED
from app.modules.payables.models import Payable
from app.modules.payables.service import _as_utc_date
from app.modules.receivables.models import STATUS_PAID as CHARGE_PAID
from app.modules.receivables.models import STATUS_SCHEDULED as CHARGE_SCHEDULED
from app.modules.receivables.models import Charge
from app.modules.receivables.service import _not_investment_yield


def _previous_period(start: date, end: date) -> tuple[date, date]:
    """Janela anterior de MESMA duração, imediatamente antes de `[start, end]`. Determinística."""
    span = end - start
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - span
    return prev_start, prev_end


def _period_label(start: date, end: date) -> str:
    """Rótulo humano da janela de comparação (não é PII). Aproxima em meses de 30 dias; para janelas
    < 1 mês, usa dias — apenas exibição, o número canônico do sinal é a margem em si."""
    days = (end - start).days + 1
    months = round(days / 30)
    if months >= 1:
        return f"{months} {'mês' if months == 1 else 'meses'}"
    return f"{days} {'dia' if days == 1 else 'dias'}"


def _margin_trends(db: Session, *, start: date, end: date) -> list[engine.MarginTrend]:
    """Para cada contrato ASSINADO: margem de contribuição do período atual vs. do período anterior
    (Story 5.4, `margem_contribuicao_pct`). Alimenta a Regra 1 do motor."""
    prev_start, prev_end = _previous_period(start, end)
    label = _period_label(start, end)
    trends: list[engine.MarginTrend] = []
    for contract in contracts_service.list_contracts(db, status=STATUS_SIGNED):
        atual = profitability_service.contract_dre(db, contract=contract, start=start, end=end)
        anterior = profitability_service.contract_dre(
            db, contract=contract, start=prev_start, end=prev_end
        )
        trends.append(
            engine.MarginTrend(
                project_name=contract.title,
                margem_pct_antes=anterior.margem_contribuicao_pct,
                margem_pct_depois=atual.margem_contribuicao_pct,
                period_label=label,
            )
        )
    return trends


def _investment_returns(db: Session, *, start: date, end: date) -> list[engine.InvestmentReturn]:
    """Rentabilidade do período de cada aplicação (Story 5.6). Alimenta a Regra 4 do motor."""
    out: list[engine.InvestmentReturn] = []
    for acc in investments_service.list_accounts(db):
        rent = investments_service.rentability(db, account_id=acc.id, start=start, end=end)
        out.append(
            engine.InvestmentReturn(
                name=acc.name,
                period_rentability_pct=rent["period_rentability_pct"],
            )
        )
    return out


def _today() -> date:
    """Hoje em UTC — a mesma âncora de `bank.reconciliation._today` e de `projection`.

    Existe para que `today` seja **injetável** em `_debitos_suspeitos` (mesmo padrão das 8.5/8.6):
    uma regra cuja população depende do relógio da máquina não é testável. O relógio mora **aqui**,
    nunca no `engine.py` (IV1).
    """
    return datetime.now(UTC).date()


def _completeness(
    db: Session,
    *,
    start: date,
    end: date,
    today: date | None = None,
    report: bank_reconciliation.ConferenciaReport | None = None,
) -> engine.CompletenessInput:
    """A completude dos lançamentos (Story 8.6, AC7) — **a única I/O nova desta story**.

    Chama a conferência da Story 8.5 (`bank.reconciliation.reconciliation_report`, read-only) e
    **adapta** o relatório para a entrada do motor: uma `CompletenessAccountInput` por
    `ConferenciaConta`, mapeada **1:1**, sem agregação nenhuma. Não existe `max()` de
    `dias_desde_ultima_conferencia` aqui: colapsar as contas perderia *qual* delas está
    desatualizada, que é exatamente o que a decisão do fundador F3 proíbe (ratificação D-2
    Ajuste 1). A 8.5 já entrega o valor por conta; esta camada só para de descartá-lo.

    Tenant sem conta bancária (o estado de **todos** os tenants no dia do deploy) → `contas=[]`, e
    é o motor que transforma isso no 🟡 "não sei se os seus lançamentos estão completos". Nenhum
    caminho aqui levanta exceção por ausência de conta — `reconciliation_report` sem
    `bank_account_id` lista as contas ativas e devolve relatório vazio quando não há nenhuma.

    **Direção da dependência:** `financial_intelligence` → `bank` é a permitida (a proibida, pela
    Regra dos Planos §1.3b, é `wallet` → `bank`, coberta por `test_money_planes.py`). `bank` não
    importa `financial_intelligence`, então não há ciclo.

    `report` injetável (Story 8.16): `collect_engine_input` busca o relatório **uma vez** e o passa
    para esta função e para `_debitos_suspeitos`. Duas leituras do mesmo relatório na mesma
    requisição poderiam divergir — e as duas regras precisam concordar sobre **qual** divergência
    estão falando,
    senão o motor nomearia um débito para uma conta com um número e explicaria outro.
    """
    if report is None:
        report = bank_reconciliation.reconciliation_report(db, start=start, end=end, today=today)
    return engine.CompletenessInput(
        contas=[
            engine.CompletenessAccountInput(
                account_name=c.bank_account_name,
                divergencia_cents=c.divergencia_cents,
                tolerancia_cents=c.tolerancia_cents,
                dias_desde_ultima_conferencia=c.dias_desde_ultima_conferencia,
            )
            for c in report.contas
        ],
        # 0 LITERAL — a Onda 1 não tem conciliação (`bank_reconciliations` é da Onda 4), então
        # "movimento sem contrapartida" não é aferível. PROIBIDO aproximar por "movimentos
        # unmatched": na Onda 1 todos são, e esse número alimenta o gate do epic §3.1. A regra já
        # está escrita no motor e acorda na Onda 3 trocando este zero pela contagem real.
        movimentos_sem_contrapartida=0,
    )


def _off_rail(db: Session, *, start: date, end: date) -> engine.OffRailInput:
    """*"N dos M recebimentos deste mês entraram direto na sua conta"* (Story 8.16 AC3/AC9).

    **Numerador (N)** — `Charge` com `paid_at::date` na janela, `bank_account_id IS NOT NULL` e
    `_not_investment_yield()`. É o recebimento que o dono registrou dizendo em qual conta o dinheiro
    caiu: ele **conta** na DRE e no saldo, mas não gerou boleto, não dispara régua e não fecha
    sozinho.
    **Denominador (M)** — a mesma janela, **qualquer** rota (`transaction_id IS NOT NULL` **ou**
    `bank_account_id IS NOT NULL`), também com `_not_investment_yield()`.

    ⚠️ **O predicado de rendimento entra nos DOIS conjuntos, não só no numerador.** No numerador
    porque a `Charge` sintética não tem `bank_account_id` (não cairia lá de qualquer forma); no
    **denominador** porque, sem ele, um tenant que registra rendimento veria o *"N dos M"* mentir —
    o rendimento **não é recebimento de cliente** e inflaria o M. É a mesma família do achado A-1,
    um conjunto ao lado.

    O filtro de `status` restringe a `{paid, scheduled}`: cobrança `open` não tem `paid_at`, e
    cobrança `canceled` não foi recebida. Nenhum filtro manual de `tenant_id` — RLS e só RLS.
    """
    de, ate = janela_de_caixa(start, end)
    janela = (
        Charge.status.in_((CHARGE_PAID, CHARGE_SCHEDULED)),
        _not_investment_yield(),
        Charge.paid_at.is_not(None),
        Charge.paid_at >= de,
        Charge.paid_at < ate,
    )
    fora_qtd, fora_valor = db.execute(
        select(func.count(), func.coalesce(func.sum(Charge.amount_cents), 0)).where(
            *janela, Charge.bank_account_id.is_not(None)
        )
    ).one()
    total_qtd = db.scalar(
        select(func.count()).where(
            *janela,
            or_(Charge.transaction_id.is_not(None), Charge.bank_account_id.is_not(None)),
        )
    )
    return engine.OffRailInput(
        recebimentos_fora_do_trilho=int(fora_qtd or 0),
        recebimentos_total=int(total_qtd or 0),
        valor_fora_do_trilho_cents=int(fora_valor or 0),
    )


def _debitos_suspeitos(
    db: Session,
    *,
    start: date,
    end: date,
    report: bank_reconciliation.ConferenciaReport,
    today: date | None = None,
) -> list[engine.DebitoSuspeitoInput]:
    """Os débitos que **podem** explicar uma divergência POSITIVA (Story 8.16 AC6/AC9).

    Só são buscados débitos de contas que **têm** divergência positiva avaliada: sem divergência
    compatível nenhum sinal sai (AC5), então buscar o resto seria trabalho jogado fora — e, pior,
    daria ao motor uma lista de candidatos que ele teria de descartar sozinho.

    **A população (normativa, ratificação §C-2.3), montada com dado que JÁ EXISTE — sem coluna nova
    e sem reabrir a decisão do worker:**

    - `Payable` em `scheduled` cuja data de débito já passou (`paid_at::date <= hoje`) — a janela
      entre a data e a varredura do worker. **Rara, e a mais precisa quando existe.** União com
    - `Payable` em `paid` com `bank_account_id` informado e `paid_at::date` dentro da janela — os
      débitos que **já contam** no `saldo_sistema` e que, portanto, **podem** explicar o saldo
      declarado estar acima.

    ⚠️ **Nada aqui se chama "agendamento", e o motivo é o defeito D-3.** Depois que o worker promove
    `scheduled → paid`, **nada no dado** distingue *"agendei e o banco não executou"* de *"paguei no
    caixa e o banco não compensou"*. O efeito existe; o adjetivo não. Por isso a população é a mesma
    e só o vocabulário mudou (`DebitoSuspeitoInput`, `source="debito_nao_confirmado"`, "Saídas").

    ⚠️ **O corte `paid_at::date <= reference_date` vale para os DOIS ramos — endurecimento
    deliberado.** O AC escreve o corte só no ramo `paid` (o "não-membro 2"), mas a razão dele é
    aritmética e não conhece status: um débito com data POSTERIOR ao `reference_date` do checkpoint
    **não entrou** no `saldo_sistema` daquela data e, por construção, **não pode** explicar a
    divergência daquela data. Nomeá-lo seria nomear um inocente — e a ratificação é explícita de que
    *"nomear um débito inocente é pior do que ficar calado"*.

    `today` é **injetável** (mesmo padrão das 8.5/8.6). Todo o relógio da story mora aqui; o motor
    recebe `data_debito` pronta e não compara nada com hoje (IV1). Nenhum filtro manual de
    `tenant_id` — RLS e só RLS (Regra de Ouro nº 1).
    """
    hoje = today or _today()
    # Só as contas com divergência POSITIVA avaliada, indexadas pelo id. `saldo_banco_data` é o
    # `reference_date` do checkpoint — a data em que os dois saldos foram apurados.
    alvos = {
        c.bank_account_id: (c.bank_account_name, c.saldo_banco_data)
        for c in report.contas
        if c.divergencia_cents is not None
        and c.divergencia_cents > 0
        and c.saldo_banco_data is not None
    }
    if not alvos:
        return []

    de, ate = janela_de_caixa(start, end)
    _, ate_hoje = janela_de_caixa(hoje, hoje)
    candidatos = db.scalars(
        select(Payable)
        .where(
            Payable.bank_account_id.in_(list(alvos)),
            Payable.paid_at.is_not(None),
            or_(
                # Ramo 1: agendado e a data já passou (a janela entre o dia e a varredura).
                and_(Payable.status == PAYABLE_SCHEDULED, Payable.paid_at < ate_hoje),
                # Ramo 2: já liquidado, com data de caixa dentro da janela conferida.
                and_(Payable.status == PAYABLE_PAID, Payable.paid_at >= de, Payable.paid_at < ate),
            ),
        )
        .order_by(Payable.paid_at, Payable.id)
    ).all()

    out: list[engine.DebitoSuspeitoInput] = []
    for p in candidatos:
        nome_da_conta, referencia = alvos[p.bank_account_id]
        data_debito = _as_utc_date(p.paid_at)
        if data_debito is None or referencia is None or data_debito > referencia:
            continue  # não estava no saldo daquela data ⇒ não explica a divergência daquela data
        out.append(
            engine.DebitoSuspeitoInput(
                # PII: nome de fornecedor. Anonimizado pelo NARRADOR na saída, nunca aqui — o mesmo
                # caminho de `MarginTrend.project_name`.
                descricao=p.supplier or p.description,
                valor_cents=p.amount_cents,
                data_debito=data_debito,
                bank_account_name=nome_da_conta,
            )
        )
    return out


def collect_engine_input(
    db: Session, *, start: date, end: date, today: date | None = None
) -> engine.EngineInput:
    """Monta o snapshot de entrada do motor a partir das fontes já calculadas (5.4/5.6/5.7) e da
    conferência bancária (8.5). Toda a leitura de banco acontece AQUI — o motor recebe só dados
    puros. `today` é injetável (default = hoje em UTC dentro da conferência) apenas para tornar o
    contador de "dias desde a última conferência" testável, como em `bank.reconciliation`.

    ⚠️ **A conferência é buscada UMA VEZ** e alimenta duas regras (completude e débito suspeito):
    duas leituras do mesmo relatório na mesma requisição poderiam divergir, e o motor passaria a
    explicar uma divergência que não é a que ele reportou."""
    proj = projection_service.cash_projection(db)
    report = bank_reconciliation.reconciliation_report(db, start=start, end=end, today=today)
    return engine.EngineInput(
        margins=_margin_trends(db, start=start, end=end),
        runway_days=proj.runway.days,
        projection_windows=[
            engine.ProjectionWindowInput(days=w.days, alert=w.alert) for w in proj.windows
        ],
        investments=_investment_returns(db, start=start, end=end),
        completeness=_completeness(db, start=start, end=end, today=today, report=report),
        off_rail=_off_rail(db, start=start, end=end),
        debitos_suspeitos=_debitos_suspeitos(
            db, start=start, end=end, report=report, today=today
        ),
    )


def compute_signals(
    db: Session, *, start: date, end: date, today: date | None = None
) -> list[engine.Signal]:
    """Busca os dados (I/O) e delega ao motor puro. Ponto único de orquestração dos sinais."""
    return engine.compute_signals(collect_engine_input(db, start=start, end=end, today=today))
