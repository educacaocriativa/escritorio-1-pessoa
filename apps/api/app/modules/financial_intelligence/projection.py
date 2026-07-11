"""Projeção de fluxo de caixa 30/60/90 dias + runway (Story 5.7) — agregação SOMENTE-LEITURA.

**Regime de CAIXA — o OPOSTO da DRE (5.3/5.4/5.6).** A regra determinística fixada na Story 5.2
(docstring de payables/receivables/models.py) diz: fluxo de caixa usa a data de PAGAMENTO; DRE usa
`competence_date`. **Nunca inverter.** Esta projeção olha para o FUTURO — itens ainda em aberto
(`status="open"`), que por definição têm `paid_at` NULL (a baixa ainda não aconteceu). Logo "data
de pagamento prevista" (FR7/epic) NÃO é `paid_at` — é o **vencimento** (`due_date`) dos itens em
aberto, a única data de pagamento que um lançamento aberto realmente tem hoje (Task 1 da story). Por
isso as queries abaixo filtram por `due_date`, JAMAIS por `competence_date` (que é da DRE) nem por
`paid_at` (que é NULL aqui).

Saldo inicial: reaproveita `wallet_service.wallet_summary(db)["available_cents"]` — o MESMO número
que o Cockpit usa (`cockpit.service.finance_summary`), sem recalcular. É o dinheiro que já está
disponível na Carteira (histórico consolidado); somar `paid_at` passados à mão contaria o mesmo
dinheiro duas vezes.

Recorrências futuras (AC3): cada ocorrência recorrente JÁ é materializada como uma linha própria
`Payable`/`Charge` com seu `due_date` no momento da criação (`core/recurrence.advance`).
A projeção NÃO reimplementa recorrência — cada ocorrência futura é capturada pela mesma query de
"status=open + due_date na janela". `recurrence_group` só liga as ocorrências; não é lido aqui.

Sinal — CONVENÇÃO CANÔNICA do módulo (herdada da 5.3, ratificada pelo @architect): o sinal vem da
TABELA DE ORIGEM, nunca do `grupo_dre`: `Charge` (a receber / entrada) = +1 ; `Payable` (a pagar /
saída) = −1. Aqui isso é literal: entradas somam, saídas subtraem do saldo projetado.

Itens VENCIDOS e ainda em aberto (`due_date < hoje`, `status="open"`) — decisão do @architect (Aria,
gate da 5.7, sobrepõe a [AUTO-DECISION] #2 do @dev que os excluía): ENTRAM na projeção como caixa
esperado IMEDIATO, contando em TODAS as janelas (um item já vencido é esperado "agora", não na sua
data de vencimento passada). Excluí-los subestimava sistematicamente o caixa em qualquer tenant com
inadimplência (situação REAL e comum, não edge case) e — pior — ocultava contas a pagar já vencidas,
que são obrigações quase-certas, deixando a projeção otimista demais justamente quando o dono já
está apertado (o oposto do propósito da story: "saiba se e quando o caixa aperta"). O montante
vencido é exposto à parte (`overdue_inflow_cents`/`overdue_outflow_cents`) para o consumidor
risk-ajustar: recebíveis vencidos podem nunca se concretizar — a incerteza é comunicada por
TRANSPARÊNCIA, não escondida por exclusão silenciosa.

Isolamento: nenhuma query filtra `tenant_id` manualmente — a RLS já fixou o tenant na sessão
(Regra de Ouro nº 1, CLAUDE.md#3). Validado por teste cross-tenant no Postgres real.

SOMENTE LEITURA (IV1): nenhuma escrita, nenhuma conta criada — só agrega e projeta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.payables.models import STATUS_OPEN as PAYABLE_OPEN
from app.modules.payables.models import Payable
from app.modules.receivables.models import STATUS_OPEN as CHARGE_OPEN
from app.modules.receivables.models import Charge
from app.modules.wallet import service as wallet_service

DEFAULT_WINDOWS: tuple[int, ...] = (30, 60, 90)

_NOTE_CAIXA = (
    "Regime de CAIXA: usa a data de pagamento prevista (vencimento dos itens em aberto), NUNCA a "
    "data de competência (que é da DRE). Saldo inicial vem do disponível da Carteira."
)
_NOTE_RECORRENCIA = (
    "Recorrências futuras já entram: cada ocorrência é uma conta/cobrança própria com seu "
    "vencimento."
)
_NOTE_RUNWAY_SEM_RISCO = (
    "Sem queima líquida de caixa na janela (as entradas cobrem as saídas) — sem risco de runway."
)
_NOTE_OVERDUE = (
    "Inclui lançamentos VENCIDOS e ainda em aberto (atraso/inadimplência) como caixa esperado "
    "imediato — eles entram em TODAS as janelas (ver overdue_inflow_cents/overdue_outflow_cents). "
    "Recebíveis vencidos podem não se concretizar; trate a projeção com cautela quando há "
    "inadimplência relevante."
)


@dataclass
class ProjectionWindow:
    days: int
    saldo_projetado_cents: int
    # True quando o saldo projetado fica NEGATIVO nesta janela — a Story 5.8 consome este sinal
    # como indicador 🔴 sem reimplementar o cálculo.
    alert: bool


@dataclass
class Runway:
    # None = caixa não está sendo queimado (crescendo/estável) → "sem risco" (não faz sentido
    # projetar "dias até acabar" um caixa que não diminui). Caso contrário, dias até o saldo inicial
    # zerar no ritmo de queima líquida atual.
    days: int | None
    burn_rate_cents_per_day: int


@dataclass
class CashProjection:
    today: date
    saldo_inicial_cents: int
    # Montante de itens em aberto JÁ VENCIDOS (due_date < hoje) que a projeção conta como caixa
    # esperado imediato — exposto à parte para o consumidor risk-ajustar (recebíveis vencidos podem
    # não chegar). Já EMBUTIDO em todas as `windows`; estes campos só tornam a parcela visível.
    overdue_inflow_cents: int
    overdue_outflow_cents: int
    windows: list[ProjectionWindow]
    runway: Runway
    notes: list[str] = field(default_factory=list)


def _window_sums(
    db: Session,
    model: type[Charge | Payable],
    *,
    open_status: str,
    today: date,
    horizons: list[date],
) -> tuple[list[int], int]:
    """Soma CUMULATIVA de `amount_cents` de itens em aberto por horizonte, feita no BANCO.

    Para cada horizonte (today+30/60/90), soma os lançamentos `status=open` cujo `due_date` cai em
    `(-∞, horizonte]` — cumulativo, não faixas isoladas (o saldo de 60 dias já embute o de 30).
    NÃO há limite inferior: itens JÁ VENCIDOS (`due_date < today`) contam em TODAS as janelas, como
    caixa esperado imediato (decisão do @architect — ver docstring do módulo). Uma única query por
    modelo (SUM(CASE ...)) — não carrega linha nenhuma para a aplicação, mesmo padrão de
    agregação-no-banco da DRE.

    Retorna `(somas_por_horizonte, soma_vencida)`: a soma por horizonte (na mesma ordem) e a parcela
    já vencida (`due_date < today`), que já está EMBUTIDA em cada horizonte e é devolvida só para
    exposição transparente."""
    max_horizon = horizons[-1]
    horizon_cols = [
        func.coalesce(
            func.sum(case((model.due_date <= h, model.amount_cents), else_=0)),
            0,
        )
        for h in horizons
    ]
    overdue_col = func.coalesce(
        func.sum(case((model.due_date < today, model.amount_cents), else_=0)),
        0,
    )
    stmt = select(*horizon_cols, overdue_col).where(
        model.status == open_status,
        model.due_date <= max_horizon,
    )
    row = db.execute(stmt).one()
    values = [int(v or 0) for v in row]
    return values[:-1], values[-1]


def cash_projection(
    db: Session,
    *,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    today: date | None = None,
) -> CashProjection:
    """Projeta o saldo de caixa para cada janela (dias a partir de hoje) e calcula o runway.

    `windows` são os horizontes em DIAS (default 30/60/90), a partir de `today` (default = hoje UTC,
    mesma âncora do Cockpit). Para cada janela:
        saldo_projetado = saldo_inicial(Carteira) + entradas_abertas_até − saídas_abertas_até
    (regime de CAIXA por `due_date`). `alert=True` quando o saldo projetado fica negativo.

    Runway: queima líquida diária = (saídas − entradas) da MAIOR janela / dias dessa janela. Se há
    queima positiva, `runway.days = saldo_inicial / queima_diária` (clampado em ≥ 0). Sem queima
    (caixa crescendo/estável) OU sem saldo a queimar → `runway.days = None` ("sem risco"), evitando
    divisão por zero de forma explícita.

    SOMENTE LEITURA: não escreve nada (IV1)."""
    today = today or datetime.now(UTC).date()
    # Janelas ascendentes e sem duplicatas — o cálculo cumulativo assume ordem crescente; o
    # horizonte de burn é a maior. Ignora valores não-positivos (janela de 0 dia não faz sentido).
    ordered = sorted({w for w in windows if w > 0})
    if not ordered:
        ordered = list(DEFAULT_WINDOWS)
    horizons = [today + timedelta(days=w) for w in ordered]

    saldo_inicial = int(wallet_service.wallet_summary(db)["available_cents"])
    inflows, overdue_inflow = _window_sums(
        db, Charge, open_status=CHARGE_OPEN, today=today, horizons=horizons
    )
    outflows, overdue_outflow = _window_sums(
        db, Payable, open_status=PAYABLE_OPEN, today=today, horizons=horizons
    )

    projected_windows: list[ProjectionWindow] = []
    for i, w in enumerate(ordered):
        saldo = saldo_inicial + inflows[i] - outflows[i]
        projected_windows.append(
            ProjectionWindow(days=w, saldo_projetado_cents=saldo, alert=saldo < 0)
        )

    # Runway pela MAIOR janela (proxy do ritmo atual). Queima líquida = saídas − entradas.
    burn_window_days = ordered[-1]
    net_burn = outflows[-1] - inflows[-1]  # > 0 = queima; ≤ 0 = caixa crescendo/estável
    if net_burn > 0 and burn_window_days > 0:
        burn_rate = round(net_burn / burn_window_days)  # centavos/dia
    else:
        burn_rate = 0

    if burn_rate > 0:
        # Divisão por zero coberta: burn_rate > 0 garantido aqui. Saldo já negativo ⇒ 0 dias.
        runway_days: int | None = max(0, round(saldo_inicial / burn_rate))
    else:
        # Sem queima (ou sem burn rate) → "sem risco", não projeta "dias até acabar".
        runway_days = None

    notes = [_NOTE_CAIXA, _NOTE_RECORRENCIA]
    if runway_days is None:
        notes.append(_NOTE_RUNWAY_SEM_RISCO)
    if overdue_inflow or overdue_outflow:
        notes.append(_NOTE_OVERDUE)

    return CashProjection(
        today=today,
        saldo_inicial_cents=saldo_inicial,
        overdue_inflow_cents=overdue_inflow,
        overdue_outflow_cents=overdue_outflow,
        windows=projected_windows,
        runway=Runway(days=runway_days, burn_rate_cents_per_day=burn_rate),
        notes=notes,
    )
