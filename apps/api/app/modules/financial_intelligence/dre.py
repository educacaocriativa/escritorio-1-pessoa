"""DRE por categoria (Story 5.3) — agregação SOMENTE-LEITURA, regime de COMPETÊNCIA.

Regra de ouro do Epic 5 (fixada na Story 5.2, docstring de payables/receivables/models.py):
fluxo de caixa usa `paid_at`; DRE/competência usa `competence_date`. **NUNCA inverter.** Esta é a
primeira story a consumir a regra — um erro aqui propagaria para 5.4 (lucratividade). Por isso o
filtro abaixo usa a data de competência, jamais `paid_at`.

Padrão de agregação: `GROUP BY` no banco (mesmo padrão de `cockpit.service.crm_summary`), nunca
carregar todos os lançamentos em memória para somar em Python. Só o resultado agregado (uma linha
por conta do plano de contas) volta para a aplicação.

Sinal — CONVENÇÃO CANÔNICA do módulo `financial_intelligence` (ratificada pelo @architect na
Story 5.3; a Story 5.4 e todo relatório analítico futuro DEVEM herdar esta regra SEM alteração):

  O sinal de um lançamento é determinado EXCLUSIVAMENTE pela sua TABELA DE ORIGEM, nunca pelo
  `grupo_dre`:  `Charge` (a receber / entrada) = +1 ; `Payable` (a pagar / saída) = −1.
  O `grupo_dre` é APENAS um rótulo de classificação para a hierarquia de exibição — NÃO derive
  nem inverta o sinal a partir dele. O total de um grupo é a soma já-com-sinal dos seus
  lançamentos; o resultado operacional é a SOMA (não subtração) dos totais já-sinalizados dos
  RESULT_GROUPS (todos menos INVESTIMENTO). SEM_CATEGORIA e INVESTIMENTO ficam fora do resultado.

  Relação com a fórmula do epic `RECEITA − CUSTO_DIRETO − DESPESA_FIXA − TRIBUTOS ± FINANCEIRO`:
  esta convenção é uma GENERALIZAÇÃO dela, NÃO uma identidade algébrica. As duas coincidem apenas
  no caso comum em que todo lançamento carrega o sinal "canônico" do seu grupo (toda receita é um
  Charge; todo custo/despesa/tributo é um Payable). Como `chart_account_id` é livre em AMBAS as
  tabelas (nada no schema impede um Charge em CUSTO_DIRETO — p.ex. nota de crédito / estorno de
  custo — nem um Payable em RECEITA — p.ex. reembolso ao cliente), os dois cálculos DIVERGEM
  exatamente nesses casos de estorno. E é a soma por sinal natural que está CORRETA (o estorno
  REDUZ o grupo, em vez de inflá-lo como faria a fórmula literal por magnitude). Por isso o sinal
  natural é o padrão — mais robusto e sem regra especial.

Isolamento: nenhuma query filtra `tenant_id` manualmente — a RLS já fixou o tenant na sessão
(Regra de Ouro nº 1, CLAUDE.md#3). Validado por teste cross-tenant no Postgres real.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import String, func, select
from sqlalchemy.orm import Session

from app.modules.chart_of_accounts.models import GROUP_ORDER, GRUPO_RECEITA, ChartAccount
from app.modules.cost_centers.models import CostCenter
from app.modules.payables.models import STATUS_CANCELED as PAYABLE_CANCELED
from app.modules.payables.models import Payable
from app.modules.receivables.models import STATUS_CANCELED as CHARGE_CANCELED
from app.modules.receivables.models import Charge
from app.modules.wallet.models import STATUS_REFUNDED as TX_REFUNDED
from app.modules.wallet.models import Transaction

# Bucket sintético (NÃO é um grupo do enum `grupo_dre`): lançamentos ainda não classificados
# (chart_account_id IS NULL) ou apontando para uma conta inexistente. Somado à parte, FORA do
# resultado — AC3: "não somem, incentivando a classificação sem travar o relatório".
SEM_CATEGORIA = "SEM_CATEGORIA"

# Grupos que compõem o RESULTADO operacional (DRE). INVESTIMENTO (aporte de capital) fica de fora
# por padrão — é movimento de balanço, não de resultado (documentado em `notes` na resposta).
RESULT_GROUPS: frozenset[str] = frozenset(GROUP_ORDER) - {"INVESTIMENTO"}

_NOTE_INVESTIMENTO = (
    "INVESTIMENTO (aporte/imobilizado) fica fora do resultado operacional — é movimento de "
    "balanço, não de DRE."
)
_NOTE_SEM_CATEGORIA = (
    "Lançamentos sem categoria não entram no resultado; classifique-os no plano de contas para "
    "vê-los no grupo correto."
)
_NOTE_COMPETENCIA = "Regime de competência (data de competência), não de caixa."


@dataclass
class DreCategory:
    categoria: str
    amount_cents: int
    count: int


@dataclass
class DreGroup:
    grupo_dre: str
    total_cents: int
    categorias: list[DreCategory] = field(default_factory=list)


@dataclass
class DreReport:
    start: date
    end: date
    groups: list[DreGroup]
    sem_categoria: DreGroup
    resultado_cents: int
    notes: list[str] = field(default_factory=list)


def _sum_by_account(
    db: Session,
    model: type[Payable | Charge],
    *,
    start: date,
    end: date,
    canceled: str,
    sign: int,
    cost_center_id: str | None = None,
) -> list[tuple[str | None, int, int]]:
    """Soma por `chart_account_id` no BANCO (GROUP BY), no período de COMPETÊNCIA.

    `competence_date` é aditiva/nullable (Story 5.2): o service preenche com `due_date` como
    fallback ao criar, mas usamos `COALESCE(competence_date, due_date)` também aqui como rede de
    segurança para qualquer linha legada em que a competência tenha ficado nula. Lançamentos
    cancelados são excluídos (não pertencem ao resultado). `sign` aplica o sinal natural
    (Receber=+1, Pagar=−1). Retorna (chart_account_id | None, soma_com_sinal, contagem).

    Story 5.5: `cost_center_id` (2ª dimensão) filtra a agregação por centro de custo QUANDO
    informado. Quando `None` (default), NENHUM predicado extra é adicionado — a SQL e o resultado
    ficam IDÊNTICOS ao comportamento da Story 5.3 (IV3: a visão padrão não muda para quem não usa a
    dimensão)."""
    competence = func.coalesce(model.competence_date, model.due_date)
    stmt = select(
        model.chart_account_id,
        func.coalesce(func.sum(model.amount_cents), 0),
        func.count(model.id),
    ).where(competence >= start, competence <= end, model.status != canceled)
    if cost_center_id is not None:
        stmt = stmt.where(model.cost_center_id == cost_center_id)
    stmt = stmt.group_by(model.chart_account_id)
    rows = db.execute(stmt).all()
    return [(acc_id, sign * int(total or 0), int(count)) for acc_id, total, count in rows]


def _sum_transactions_by_account(
    db: Session, *, start: date, end: date, cost_center_id: str | None = None,
) -> list[tuple[str | None, int, int]]:
    """Soma `Transaction` (Carteira) por `chart_account_id` — Story 5.10. Mesma base da DRE, mas só
    entram transações SEM `external_ref` e não estornadas.

    `external_ref` preenchido significa que a transação nasceu de uma Charge já paga (`mark_paid`
    grava `external_ref=charge.id`) — essa receita JÁ é contada via `_sum_by_account(Charge, ...)`;
    somar a Transaction também dobraria o valor. Só entram aqui as transações "órfãs" (venda avulsa
    em "Registrar venda" ou produto/checkout), que não existem em nenhuma outra tabela do DRE.
    Sinal sempre +1 (Carteira só registra dinheiro entrando)."""
    competence = func.coalesce(Transaction.competence_date, func.date(Transaction.created_at))
    stmt = select(
        Transaction.chart_account_id,
        func.coalesce(func.sum(Transaction.gross_cents), 0),
        func.count(Transaction.id),
    ).where(
        competence >= start,
        competence <= end,
        Transaction.status != TX_REFUNDED,
        Transaction.external_ref.is_(None),
    )
    if cost_center_id is not None:
        stmt = stmt.where(Transaction.cost_center_id == cost_center_id)
    stmt = stmt.group_by(Transaction.chart_account_id)
    rows = db.execute(stmt).all()
    return [(acc_id, int(total or 0), int(count)) for acc_id, total, count in rows]


def dre_report(
    db: Session, *, start: date, end: date, cost_center_id: str | None = None
) -> DreReport:
    """Monta a DRE hierárquica (grupo DRE → categoria) do período, em regime de competência.

    Story 5.5: `cost_center_id` (2ª dimensão, OPCIONAL) filtra a DRE por centro de custo quando
    informado. Omitir (`None`) produz resultado BYTE-A-BYTE idêntico ao da Story 5.3 — a visão
    padrão não muda (IV3), pois nenhum predicado extra entra na query.

    SOMENTE LEITURA: não escreve nada (nenhum efeito colateral sobre Carteira/Contas — IV1)."""
    # Taxonomia: id da conta → (grupo, categoria). Inclui arquivadas de propósito — uma categoria
    # arquivada depois da classificação ainda deve resolver o grupo do lançamento histórico
    # (5.1 preserva a linha ao arquivar). É a taxonomia (poucas linhas), não os lançamentos.
    account_map: dict[str, tuple[str, str]] = {
        a.id: (a.grupo_dre, a.categoria) for a in db.scalars(select(ChartAccount)).all()
    }

    # grupo -> categoria -> [amount_cents, count]
    by_group: dict[str, dict[str, list[int]]] = {g: {} for g in GROUP_ORDER}
    sem_amount = 0
    sem_count = 0

    aggregated = _sum_by_account(
        db, Charge, start=start, end=end, canceled=CHARGE_CANCELED, sign=1,
        cost_center_id=cost_center_id,
    ) + _sum_by_account(
        db, Payable, start=start, end=end, canceled=PAYABLE_CANCELED, sign=-1,
        cost_center_id=cost_center_id,
    ) + _sum_transactions_by_account(
        db, start=start, end=end, cost_center_id=cost_center_id,
    )

    for acc_id, amount, count in aggregated:
        resolved = account_map.get(acc_id) if acc_id else None
        if resolved is None:
            # Sem categoria: NULL ou conta que não resolve (defensivo). Fora do resultado.
            sem_amount += amount
            sem_count += count
            continue
        grupo, categoria = resolved
        bucket = by_group.setdefault(grupo, {})
        line = bucket.setdefault(categoria, [0, 0])
        line[0] += amount
        line[1] += count

    groups: list[DreGroup] = []
    resultado = 0
    for grupo in GROUP_ORDER:  # sempre os 6 grupos, na ordem canônica (mesmo os vazios)
        categorias = [
            DreCategory(categoria=cat, amount_cents=amt, count=cnt)
            for cat, (amt, cnt) in sorted(by_group[grupo].items())
        ]
        total = sum(c.amount_cents for c in categorias)
        groups.append(DreGroup(grupo_dre=grupo, total_cents=total, categorias=categorias))
        if grupo in RESULT_GROUPS:
            resultado += total

    sem_categoria = DreGroup(
        grupo_dre=SEM_CATEGORIA,
        total_cents=sem_amount,
        categorias=(
            [DreCategory(categoria="Sem categoria", amount_cents=sem_amount, count=sem_count)]
            if sem_count
            else []
        ),
    )

    notes = [_NOTE_COMPETENCIA, _NOTE_INVESTIMENTO]
    if sem_count:
        notes.append(_NOTE_SEM_CATEGORIA)

    return DreReport(
        start=start,
        end=end,
        groups=groups,
        sem_categoria=sem_categoria,
        resultado_cents=resultado,
        notes=notes,
    )


# ── Cruzamento por centro de custo (Story 5.5, Task 4) ──────────────────────────────────────────
# Rótulo do bucket sintético dos lançamentos sem centro de custo (cost_center_id IS NULL) — AC3.
NAO_ATRIBUIDO = "Não atribuído"

_NOTE_NAO_ATRIBUIDO = (
    "Lançamentos sem centro de custo aparecem em 'Não atribuído' — a 2ª dimensão é sempre opcional."
)
_NOTE_CC_RESULTADO = (
    "'resultado' por centro de custo segue a mesma fórmula/exclusões da DRE (INVESTIMENTO e "
    "lançamentos sem categoria ficam fora)."
)


@dataclass
class CostCenterBucket:
    # None = bucket sintético "Não atribuído" (cost_center_id IS NULL).
    cost_center_id: str | None
    name: str
    kind: str | None
    receita_cents: int
    resultado_cents: int
    lancamentos: int


@dataclass
class CostCenterReport:
    start: date
    end: date
    buckets: list[CostCenterBucket]
    notes: list[str] = field(default_factory=list)


def _sum_by_cost_center_and_account(
    db: Session, model: type[Payable | Charge], *, start: date, end: date, canceled: str, sign: int
) -> list[tuple[str | None, str | None, int, int]]:
    """Soma por (`cost_center_id`, `chart_account_id`) no BANCO (GROUP BY), regime de competência.

    Mesma base da DRE (COALESCE de competência, cancelados fora, sinal natural). Agrega em DUAS
    dimensões para, na aplicação, ratear cada lançamento ao seu centro de custo E resolver o grupo
    DRE da conta. Retorna (cost_center_id | None, chart_account_id | None, soma, contagem)."""
    competence = func.coalesce(model.competence_date, model.due_date)
    rows = db.execute(
        select(
            model.cost_center_id,
            model.chart_account_id,
            func.coalesce(func.sum(model.amount_cents), 0),
            func.count(model.id),
        )
        .where(competence >= start, competence <= end, model.status != canceled)
        .group_by(model.cost_center_id, model.chart_account_id)
    ).all()
    return [
        (cc_id, acc_id, sign * int(total or 0), int(count))
        for cc_id, acc_id, total, count in rows
    ]


def _sum_transactions_by_cost_center_and_account(
    db: Session, *, start: date, end: date
) -> list[tuple[str | None, str | None, int, int]]:
    """Mesma regra de `_sum_transactions_by_account` (só transações órfãs, não estornadas), cruzada
    também por centro de custo — usada pelo `by_cost_center_report` (Story 5.10)."""
    competence = func.coalesce(Transaction.competence_date, func.date(Transaction.created_at))
    rows = db.execute(
        select(
            Transaction.cost_center_id,
            Transaction.chart_account_id,
            func.coalesce(func.sum(Transaction.gross_cents), 0),
            func.count(Transaction.id),
        )
        .where(
            competence >= start,
            competence <= end,
            Transaction.status != TX_REFUNDED,
            Transaction.external_ref.is_(None),
        )
        .group_by(Transaction.cost_center_id, Transaction.chart_account_id)
    ).all()
    return [
        (cc_id, acc_id, int(total or 0), int(count))
        for cc_id, acc_id, total, count in rows
    ]


def by_cost_center_report(db: Session, *, start: date, end: date) -> CostCenterReport:
    """Cruza o resultado do período por centro de custo (2ª dimensão) — Story 5.5, AC2/AC3.

    Para cada centro de custo do tenant (mesmo os sem movimento, para permitir comparar sócios/áreas
    lado a lado) e para o bucket 'Não atribuído' (cost_center_id IS NULL), devolve a receita e o
    'resultado' do período pela MESMA fórmula/exclusões da DRE (Story 5.3): só os RESULT_GROUPS
    entram no resultado (INVESTIMENTO e lançamentos sem categoria ficam fora). SOMENTE LEITURA."""
    account_map: dict[str, str] = {
        a.id: a.grupo_dre for a in db.scalars(select(ChartAccount)).all()
    }
    centers = list(db.scalars(select(CostCenter)).all())  # RLS-scoped; inclui arquivados
    cc_map: dict[str, CostCenter] = {c.id: c for c in centers}

    aggregated = _sum_by_cost_center_and_account(
        db, Charge, start=start, end=end, canceled=CHARGE_CANCELED, sign=1
    ) + _sum_by_cost_center_and_account(
        db, Payable, start=start, end=end, canceled=PAYABLE_CANCELED, sign=-1
    ) + _sum_transactions_by_cost_center_and_account(db, start=start, end=end)

    # cost_center_id | None -> [receita, resultado, contagem]
    acc: dict[str | None, list[int]] = {}
    for cc_id, account_id, amount, count in aggregated:
        bucket = acc.setdefault(cc_id, [0, 0, 0])
        bucket[2] += count
        grupo = account_map.get(account_id) if account_id else None
        if grupo in RESULT_GROUPS:
            bucket[1] += amount
        if grupo == GRUPO_RECEITA:
            bucket[0] += amount

    buckets: list[CostCenterBucket] = []
    seen: set[str] = set()
    # 1) Todos os centros NÃO arquivados (mesmo zerados) — comparação lado a lado.
    for c in sorted(
        (c for c in centers if c.archived_at is None), key=lambda c: c.name.lower()
    ):
        b = acc.get(c.id, [0, 0, 0])
        buckets.append(
            CostCenterBucket(
                cost_center_id=c.id, name=c.name, kind=c.kind,
                receita_cents=b[0], resultado_cents=b[1], lancamentos=b[2],
            )
        )
        seen.add(c.id)
    # 2) Centros ARQUIVADOS que ainda têm lançamentos no período (não perder dinheiro do histórico).
    for cc_id, b in acc.items():
        if cc_id is None or cc_id in seen:
            continue
        c = cc_map.get(cc_id)
        buckets.append(
            CostCenterBucket(
                cost_center_id=cc_id,
                name=c.name if c else "(centro removido)",
                kind=c.kind if c else None,
                receita_cents=b[0], resultado_cents=b[1], lancamentos=b[2],
            )
        )
    # 3) Bucket "Não atribuído" (sempre por último) quando há lançamentos sem centro de custo.
    if None in acc:
        b = acc[None]
        buckets.append(
            CostCenterBucket(
                cost_center_id=None, name=NAO_ATRIBUIDO, kind=None,
                receita_cents=b[0], resultado_cents=b[1], lancamentos=b[2],
            )
        )

    return CostCenterReport(
        start=start,
        end=end,
        buckets=buckets,
        notes=[_NOTE_COMPETENCIA, _NOTE_CC_RESULTADO, _NOTE_NAO_ATRIBUIDO],
    )


# ── Matriz mensal (Story 5.11: meses x categorias) ──────────────────────────────────────────────
def _month_keys(start: date, end: date) -> list[str]:
    """Lista contígua de meses "YYYY-MM" entre `start` e `end` (inclusive) — mesas mesmo quando
    não há nenhum lançamento no mês (a matriz não pode "pular" coluna)."""
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return months


def _sum_by_account_monthly(
    db: Session,
    model: type[Payable | Charge],
    *,
    start: date,
    end: date,
    canceled: str,
    sign: int,
    cost_center_id: str | None = None,
) -> list[tuple[str, str | None, int]]:
    """Como `_sum_by_account`, mas agrupando TAMBÉM por mês de competência (Story 5.11). O mês é
    extraído com CAST para texto + SUBSTR (funciona igual em SQLite e Postgres, sem
    `date_trunc`/`to_char` — os dois dialetos guardam/serializam a data em ISO 'YYYY-MM-DD').
    Retorna (mês 'YYYY-MM', chart_account_id | None, soma_com_sinal) — sem contagem (a matriz não
    usa `count`, ao contrário de `_sum_by_account`)."""
    competence = func.coalesce(model.competence_date, model.due_date)
    month_key = func.substr(func.cast(competence, String), 1, 7)
    stmt = select(
        month_key,
        model.chart_account_id,
        func.coalesce(func.sum(model.amount_cents), 0),
    ).where(competence >= start, competence <= end, model.status != canceled)
    if cost_center_id is not None:
        stmt = stmt.where(model.cost_center_id == cost_center_id)
    stmt = stmt.group_by(month_key, model.chart_account_id)
    rows = db.execute(stmt).all()
    return [(month, acc_id, sign * int(total or 0)) for month, acc_id, total in rows]


def _sum_transactions_by_account_monthly(
    db: Session, *, start: date, end: date, cost_center_id: str | None = None,
) -> list[tuple[str, str | None, int]]:
    """Como `_sum_transactions_by_account`, com o mês adicionado ao GROUP BY (Story 5.11)."""
    competence = func.coalesce(Transaction.competence_date, func.date(Transaction.created_at))
    month_key = func.substr(func.cast(competence, String), 1, 7)
    stmt = select(
        month_key,
        Transaction.chart_account_id,
        func.coalesce(func.sum(Transaction.gross_cents), 0),
    ).where(
        competence >= start,
        competence <= end,
        Transaction.status != TX_REFUNDED,
        Transaction.external_ref.is_(None),
    )
    if cost_center_id is not None:
        stmt = stmt.where(Transaction.cost_center_id == cost_center_id)
    stmt = stmt.group_by(month_key, Transaction.chart_account_id)
    rows = db.execute(stmt).all()
    return [(month, acc_id, int(total or 0)) for month, acc_id, total in rows]


@dataclass
class DreMatrixRow:
    label: str
    kind: str  # "result" | "informational" | "uncategorized"
    # Grupo DRE de ORIGEM do lançamento (não confundir com o grupo de EXIBIÇÃO em
    # group_by="cost_center", onde a linha aparece sob um centro de custo). `None` para a linha
    # sintética "Sem categoria". Usado pelo drill-down (`matrix_cell_entries`, Story 5.13) para
    # localizar sem ambiguidade os lançamentos por trás da célula, mesmo quando duas categorias
    # do MESMO nome existem em grupos DRE diferentes sob o mesmo centro de custo.
    grupo_dre: str | None
    monthly_cents: list[int]
    total_cents: int


@dataclass
class DreMatrixGroup:
    key: str
    # Nome do centro de custo (group_by="cost_center", "Não atribuído" incluso) — None quando
    # group_by="dre" (o frontend já resolve o rótulo do grupo DRE a partir de `key`, código estável
    # tipo "RECEITA"; não duplicamos essa tabela de tradução no backend).
    label: str | None
    rows: list[DreMatrixRow]
    subtotal_cents: list[int]  # soma SÓ das linhas kind="result" (mesma exclusão do resultado)
    subtotal_total: int


@dataclass
class DreMatrixReport:
    months: list[str]
    groups: list[DreMatrixGroup]
    grand_total_cents: list[int]
    grand_total: int
    notes: list[str]


def _row_kind(grupo: str | None) -> str:
    if grupo is None:
        return "uncategorized"
    if grupo == "INVESTIMENTO":
        return "informational"
    return "result"


def _build_matrix_group(
    key: str,
    label: str | None,
    cats: dict[tuple[str | None, str], list[int]],
    kind_of: Callable[[tuple[str | None, str]], str],
    n: int,
) -> DreMatrixGroup:
    """`cats` é chaveado por (grupo_dre_de_origem | None, categoria) — NÃO só por categoria —
    porque `categoria` é única apenas DENTRO de um grupo_dre (constraint do plano de contas),
    nunca por tenant inteiro. Em group_by="cost_center" um único centro de custo pode ter duas
    contas com o MESMO nome de categoria em grupos DIFERENTES (ex.: "Equipamentos" em
    INVESTIMENTO e em CUSTO_DIRETO); sem essa chave composta, as duas se fundiriam numa linha só
    e o `kind` (result/informational) de uma sobrescreveria o da outra silenciosamente."""
    rows = []
    for cat_key in sorted(cats, key=lambda k: k[1]):
        cents = cats[cat_key]
        rows.append(
            DreMatrixRow(
                label=cat_key[1], kind=kind_of(cat_key), grupo_dre=cat_key[0],
                monthly_cents=cents, total_cents=sum(cents),
            )
        )
    subtotal = [sum(r.monthly_cents[i] for r in rows if r.kind == "result") for i in range(n)]
    return DreMatrixGroup(
        key=key, label=label, rows=rows, subtotal_cents=subtotal, subtotal_total=sum(subtotal),
    )


def dre_matrix_report(
    db: Session,
    *,
    start: date,
    end: date,
    group_by: str = "dre",
    cost_center_id: str | None = None,
) -> DreMatrixReport:
    """DRE em matriz (mês x categoria), regime de competência (Story 5.11). SOMENTE LEITURA.

    `group_by="dre"`: mesma hierarquia grupo->categoria de `dre_report`, com o eixo de mês
    adicionado. Aceita `cost_center_id` opcional (mesma semântica de `dre_report`).
    `group_by="cost_center"`: agrupa por centro de custo em vez de grupo DRE — implementado na
    Story 5.11 Task 4 (ver `_dre_matrix_by_cost_center`).

    Em AMBOS os modos, cada LINHA (não o grupo) carrega seu próprio `kind` — necessário porque em
    `group_by="cost_center"` um único centro de custo pode conter categorias de mais de um grupo
    DRE (ex.: uma categoria de INVESTIMENTO e uma de RECEITA sob o mesmo centro de custo). O
    subtotal de cada grupo e o `grand_total` somam SÓ linhas `kind="result"` — mesma exclusão de
    INVESTIMENTO/sem-categoria que a DRE por categoria já aplica hoje."""
    if group_by not in ("dre", "cost_center"):
        raise ValueError(f"group_by inválido: {group_by}")
    months = _month_keys(start, end)
    n = len(months)
    month_index = {mo: i for i, mo in enumerate(months)}

    if group_by == "cost_center":
        return _dre_matrix_by_cost_center(
            db, start=start, end=end, months=months, month_index=month_index, n=n,
        )

    account_map: dict[str, tuple[str, str]] = {
        a.id: (a.grupo_dre, a.categoria) for a in db.scalars(select(ChartAccount)).all()
    }

    aggregated = _sum_by_account_monthly(
        db, Charge, start=start, end=end, canceled=CHARGE_CANCELED, sign=1,
        cost_center_id=cost_center_id,
    ) + _sum_by_account_monthly(
        db, Payable, start=start, end=end, canceled=PAYABLE_CANCELED, sign=-1,
        cost_center_id=cost_center_id,
    ) + _sum_transactions_by_account_monthly(
        db, start=start, end=end, cost_center_id=cost_center_id,
    )

    by_group: dict[str, dict[tuple[str | None, str], list[int]]] = {g: {} for g in GROUP_ORDER}
    sem_by_month = [0] * n

    for month, acc_id, amount in aggregated:
        idx = month_index[month]
        resolved = account_map.get(acc_id) if acc_id else None
        if resolved is None:
            sem_by_month[idx] += amount
            continue
        grupo, categoria = resolved
        cents = by_group.setdefault(grupo, {}).setdefault((grupo, categoria), [0] * n)
        cents[idx] += amount

    groups = [
        _build_matrix_group(grupo, None, by_group[grupo], lambda k: _row_kind(k[0]), n)
        for grupo in GROUP_ORDER
    ]
    has_sem_categoria = any(c != 0 for c in sem_by_month)
    if has_sem_categoria:
        groups.append(
            _build_matrix_group(
                "SEM_CATEGORIA", None, {(None, "Sem categoria"): sem_by_month},
                lambda k: _row_kind(k[0]), n,
            )
        )

    grand_total = [sum(g.subtotal_cents[i] for g in groups) for i in range(n)]
    notes = [_NOTE_COMPETENCIA, _NOTE_INVESTIMENTO]
    if has_sem_categoria:
        notes.append(_NOTE_SEM_CATEGORIA)

    return DreMatrixReport(
        months=months, groups=groups, grand_total_cents=grand_total,
        grand_total=sum(grand_total), notes=notes,
    )


def _sum_by_cost_center_and_account_monthly(
    db: Session, model: type[Payable | Charge], *, start: date, end: date, canceled: str, sign: int,
) -> list[tuple[str, str | None, str | None, int]]:
    """Como `_sum_by_cost_center_and_account`, com o mês adicionado ao GROUP BY (Story 5.11)."""
    competence = func.coalesce(model.competence_date, model.due_date)
    month_key = func.substr(func.cast(competence, String), 1, 7)
    rows = db.execute(
        select(
            month_key,
            model.cost_center_id,
            model.chart_account_id,
            func.coalesce(func.sum(model.amount_cents), 0),
        )
        .where(competence >= start, competence <= end, model.status != canceled)
        .group_by(month_key, model.cost_center_id, model.chart_account_id)
    ).all()
    return [(month, cc_id, acc_id, sign * int(total or 0)) for month, cc_id, acc_id, total in rows]


def _sum_transactions_by_cost_center_and_account_monthly(
    db: Session, *, start: date, end: date,
) -> list[tuple[str, str | None, str | None, int]]:
    """Como `_sum_transactions_by_cost_center_and_account`, com o mês no GROUP BY (Story 5.11)."""
    competence = func.coalesce(Transaction.competence_date, func.date(Transaction.created_at))
    month_key = func.substr(func.cast(competence, String), 1, 7)
    rows = db.execute(
        select(
            month_key,
            Transaction.cost_center_id,
            Transaction.chart_account_id,
            func.coalesce(func.sum(Transaction.gross_cents), 0),
        )
        .where(
            competence >= start,
            competence <= end,
            Transaction.status != TX_REFUNDED,
            Transaction.external_ref.is_(None),
        )
        .group_by(month_key, Transaction.cost_center_id, Transaction.chart_account_id)
    ).all()
    return [(month, cc_id, acc_id, int(total or 0)) for month, cc_id, acc_id, total in rows]


def _dre_matrix_by_cost_center(
    db: Session, *, start: date, end: date, months: list[str], month_index: dict[str, int], n: int,
) -> DreMatrixReport:
    account_map: dict[str, tuple[str, str]] = {
        a.id: (a.grupo_dre, a.categoria) for a in db.scalars(select(ChartAccount)).all()
    }
    centers = list(db.scalars(select(CostCenter)).all())
    cc_map: dict[str, CostCenter] = {c.id: c for c in centers}

    aggregated = _sum_by_cost_center_and_account_monthly(
        db, Charge, start=start, end=end, canceled=CHARGE_CANCELED, sign=1,
    ) + _sum_by_cost_center_and_account_monthly(
        db, Payable, start=start, end=end, canceled=PAYABLE_CANCELED, sign=-1,
    ) + _sum_transactions_by_cost_center_and_account_monthly(db, start=start, end=end)

    # cost_center_id | None -> (grupo_dre | None, categoria) -> cents_por_mes
    by_cc: dict[str | None, dict[tuple[str | None, str], list[int]]] = {}
    for month, cc_id, acc_id, amount in aggregated:
        idx = month_index[month]
        resolved = account_map.get(acc_id) if acc_id else None
        grupo = resolved[0] if resolved else None
        categoria = resolved[1] if resolved else "Sem categoria"
        cents = by_cc.setdefault(cc_id, {}).setdefault((grupo, categoria), [0] * n)
        cents[idx] += amount

    groups: list[DreMatrixGroup] = []
    seen: set[str] = set()
    for c in sorted((c for c in centers if c.archived_at is None), key=lambda c: c.name.lower()):
        cats = by_cc.get(c.id, {})
        groups.append(_build_matrix_group(c.id, c.name, cats, lambda k: _row_kind(k[0]), n))
        seen.add(c.id)
    for cc_id, cats in by_cc.items():
        if cc_id is None or cc_id in seen:
            continue
        c = cc_map.get(cc_id)
        label = c.name if c else "(centro removido)"
        groups.append(_build_matrix_group(cc_id, label, cats, lambda k: _row_kind(k[0]), n))
    if None in by_cc:
        groups.append(
            _build_matrix_group(
                "_unassigned", NAO_ATRIBUIDO, by_cc[None], lambda k: _row_kind(k[0]), n,
            )
        )

    grand_total = [sum(g.subtotal_cents[i] for g in groups) for i in range(n)]
    notes = [_NOTE_COMPETENCIA, _NOTE_INVESTIMENTO, _NOTE_NAO_ATRIBUIDO]
    return DreMatrixReport(
        months=months, groups=groups, grand_total_cents=grand_total,
        grand_total=sum(grand_total), notes=notes,
    )


# ── Drill-down analítico de uma célula da matriz (Story 5.13) ───────────────────────────────────
@dataclass
class DreMatrixEntry:
    id: str
    source: str  # "charge" | "payable" | "transaction"
    date: date
    description: str
    status: str
    amount_cents: int  # já assinado (Charge/Transaction=+, Payable=−)


def matrix_cell_entries(
    db: Session,
    *,
    start: date,
    end: date,
    categoria: str,
    grupo_dre: str | None,
    cost_center_id: str | None = None,
) -> list[DreMatrixEntry]:
    """Lançamentos INDIVIDUAIS por trás de UMA célula da matriz (categoria x mês) — o "ver
    analítico" ao clicar num valor (Story 5.13). SOMENTE LEITURA, mesmo período de competência da
    matriz. `grupo_dre=None` busca a linha sintética "Sem categoria" (`chart_account_id IS NULL`);
    caso contrário resolve TODAS as contas do plano com esse (grupo_dre, categoria) — a chave
    composta usada por `DreMatrixRow.grupo_dre` evita pegar uma categoria homônima de outro grupo.
    `cost_center_id`: omitir (`None`) = sem filtro (modo group_by="dre"); `"_unassigned"` = só
    lançamentos SEM centro de custo (mesmo sentinel de `_dre_matrix_by_cost_center`); id real = só
    daquele centro. Inclui `Transaction` (Carteira) — mesma 3ª origem somada pela matriz."""
    if grupo_dre is None:
        account_ids: list[str] | None = None  # sentinel: filtra por chart_account_id IS NULL
    else:
        account_ids = [
            a.id
            for a in db.scalars(
                select(ChartAccount).where(
                    ChartAccount.grupo_dre == grupo_dre, ChartAccount.categoria == categoria,
                )
            ).all()
        ]
        if not account_ids:
            return []

    def _cc_filter(stmt, column):
        if cost_center_id == "_unassigned":
            return stmt.where(column.is_(None))
        if cost_center_id is not None:
            return stmt.where(column == cost_center_id)
        return stmt

    def _account_filter(stmt, column):
        if account_ids is None:
            return stmt.where(column.is_(None))
        return stmt.where(column.in_(account_ids))

    entries: list[DreMatrixEntry] = []

    charge_competence = func.coalesce(Charge.competence_date, Charge.due_date)
    stmt = select(Charge).where(
        charge_competence >= start, charge_competence <= end, Charge.status != CHARGE_CANCELED,
    )
    stmt = _account_filter(stmt, Charge.chart_account_id)
    stmt = _cc_filter(stmt, Charge.cost_center_id)
    for c in db.scalars(stmt).all():
        entries.append(
            DreMatrixEntry(
                id=c.id, source="charge", date=c.competence_date or c.due_date,
                description=c.description or "Cobrança", status=c.status,
                amount_cents=c.amount_cents,
            )
        )

    payable_competence = func.coalesce(Payable.competence_date, Payable.due_date)
    stmt = select(Payable).where(
        payable_competence >= start, payable_competence <= end, Payable.status != PAYABLE_CANCELED,
    )
    stmt = _account_filter(stmt, Payable.chart_account_id)
    stmt = _cc_filter(stmt, Payable.cost_center_id)
    for p in db.scalars(stmt).all():
        entries.append(
            DreMatrixEntry(
                id=p.id, source="payable", date=p.competence_date or p.due_date,
                description=p.description or "Conta a pagar", status=p.status,
                amount_cents=-p.amount_cents,
            )
        )

    tx_competence = func.coalesce(Transaction.competence_date, func.date(Transaction.created_at))
    stmt = select(Transaction).where(
        tx_competence >= start, tx_competence <= end,
        Transaction.status != TX_REFUNDED, Transaction.external_ref.is_(None),
    )
    stmt = _account_filter(stmt, Transaction.chart_account_id)
    stmt = _cc_filter(stmt, Transaction.cost_center_id)
    for t in db.scalars(stmt).all():
        entries.append(
            DreMatrixEntry(
                id=t.id, source="transaction",
                date=t.competence_date or t.created_at.date(),
                description=t.description or "Venda avulsa", status=t.status,
                amount_cents=t.gross_cents,
            )
        )

    entries.sort(key=lambda e: e.date)
    return entries
