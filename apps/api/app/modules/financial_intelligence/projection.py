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

⚠️ **BUG CONHECIDO, agora ROTULADO em vez de silencioso (Story 8.1, Onda 0 do Epic 8).** Esse
`available_cents` é um número do **plano 1 (plataforma)** usado onde deveria estar o do **plano 3
(bancário)** — o saldo da conta bancária do usuário (design `controle-bancario-design.md` §1.1,
epic §1.1). Não existe configuração de uso em que esteja certo: quem nunca saca acumula todo o
faturamento líquido histórico e o número **nunca diminui quando uma conta é paga** (`payables` não
toca a Carteira, por design); quem saca tudo vê o número ir a zero com o dinheiro já no banco.
**Esta story NÃO corrige o número — isso é a Story 8.8.** Ela faz duas coisas:
  (a) **declara a procedência** em `saldo_inicial_origem` (Regra dos Planos §1.3c — nenhum saldo
      trafega sem origem; vocabulário em `app.core.money_planes`);
  (b) **cala toda inferência** construída sobre esse saldo enquanto a origem for `plataforma`:
      `runway.days` (§6.1.1) e `ProjectionWindow.alert` (§6.1.2).
O princípio, literal: **suprima a AFIRMAÇÃO, nunca o NÚMERO** — `saldo_inicial_cents`,
`saldo_projetado_cents` e `burn_rate_cents_per_day` continuam expostos e inalterados (AC7).

A supressão acontece **AQUI, na origem do dado**, e não em cada consumidor, porque é *fail-closed*:
qualquer superfície criada depois herda a supressão sem precisar saber que ela existe. Efeito
colateral deliberado e desejado: `engine.py` e `diagnostics.py` ficam **INTOCADOS** —
`engine._runway_signal(None)` já devolve `[]` e `engine._projection_window_signals` só emite para
`alert=True`, então o `/financeiro/diagnostico` para de afirmar os dois sinais **por construção**,
sem uma segunda regra para manter em sincronia (design §6.1.1/§6.1.2; ratificação D-1/D-5).

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

from app.core.money_planes import ORIGEM_PLATAFORMA
from app.modules.payables.models import STATUS_OPEN as PAYABLE_OPEN
from app.modules.payables.models import Payable
from app.modules.receivables.models import STATUS_OPEN as CHARGE_OPEN
from app.modules.receivables.models import Charge
from app.modules.wallet import service as wallet_service

DEFAULT_WINDOWS: tuple[int, ...] = (30, 60, 90)

# A frase "Saldo inicial vem do disponível da Carteira" saiu daqui na Story 8.1: ela é sobre
# PROCEDÊNCIA, não sobre o regime caixa×competência, e agora tem nota própria
# (`_NOTE_ORIGEM_PLATAFORMA`) que a diz de forma explícita, não en passant. Esta nota volta a ter
# uma responsabilidade só.
_NOTE_CAIXA = (
    "Regime de CAIXA: usa a data de pagamento prevista (vencimento dos itens em aberto), NUNCA a "
    "data de competência (que é da DRE)."
)
_NOTE_RECORRENCIA = (
    "Recorrências futuras já entram: cada ocorrência é uma conta/cobrança própria com seu "
    "vencimento."
)
_NOTE_RUNWAY_SEM_RISCO = (
    "Sem queima líquida de caixa na janela (as entradas cobrem as saídas) — sem risco de runway."
)
# ⚠️ As três notas da Story 8.1 abaixo NÃO podem conter a palavra "risco". Motivo concreto:
# `test_runway_none_when_cash_is_growing` (5.7) afirma `any("risco" in n.lower() ...)` para provar
# que a nota de "sem risco" está lá — se uma nota de SUPRESSÃO também dissesse "risco", aquele teste
# poderia ficar verde pelo motivo errado e a distinção do AC4 deixaria de ser aferida. "Sem risco"
# (eu sei, e está tudo bem) e "não sei" (não tenho lastro para dizer) nunca compartilham palavra,
# nota ou rótulo de tela.
_NOTE_ORIGEM_PLATAFORMA = (
    "O saldo inicial vem do disponível na Carteira e1p, não da sua conta bancária. Enquanto você "
    "não cadastrar sua conta, a projeção e o runway são aproximações."
)
_NOTE_RUNWAY_SUPRIMIDO = (
    "O fôlego de caixa em dias não é exibido: ele parte do saldo inicial, que hoje é o disponível "
    "na Carteira e1p e não o saldo da sua conta bancária. A queima diária "
    "(burn_rate_cents_per_day) continua válida — vem das contas em aberto, não do saldo inicial."
)
_NOTE_ALERT_SUPRIMIDO = (
    "Os saldos projetados de cada janela continuam sendo exibidos, mas o e1p não afirma se o seu "
    "caixa fica negativo: o saldo de partida é o disponível na Carteira e1p, não o da sua conta "
    "bancária. Cadastre sua conta para que essa leitura volte a ter lastro."
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
    # O NÚMERO — continua exposto e exibido mesmo quando o veredito é calado (Story 8.1, §6.1.2).
    saldo_projetado_cents: int
    # True quando o saldo projetado fica NEGATIVO nesta janela — a Story 5.8 consome este sinal
    # como indicador 🔴 sem reimplementar o cálculo.
    alert: bool
    # Story 8.1 (AC4b): True quando o `alert` foi CALADO porque o saldo inicial é de origem
    # `plataforma`. `alert` é `saldo_projetado < 0`, um CRUZAMENTO DE LIMIAR sobre uma soma que
    # contém o termo contaminado — erro no saldo inicial vira erro de VEREDITO, não de magnitude.
    # E como `request_payout` (`wallet/service.py`) só marca `withdrawn` (ninguém saca de fato),
    # `available_cents` cresce monotonicamente para todo tenant real → o alerta seria uma máquina
    # de FALSO NEGATIVO: calado justamente quando deveria falar.
    # INVARIANTE DE CONTRATO: `alert_suprimido is True ⇒ alert is False`. Nenhum consumidor deve
    # precisar tratar "suprimido, mas com veredito".
    alert_suprimido: bool


@dataclass
class Runway:
    # None = caixa não está sendo queimado (crescendo/estável) → "sem risco" (não faz sentido
    # projetar "dias até acabar" um caixa que não diminui) OU o cálculo foi SUPRIMIDO (ver
    # `days_suprimido` — são estados DIFERENTES e nunca compartilham mensagem). Caso contrário,
    # dias até o saldo inicial zerar no ritmo de queima líquida atual.
    days: int | None
    # Story 8.1 (AC3): True quando havia queima e o número de dias FOI CALADO porque o saldo
    # inicial é de origem `plataforma`. Distingue "não sei" de "sem risco" (AC4).
    # INVARIANTE DE CONTRATO: `days_suprimido is True ⇒ days is None`.
    days_suprimido: bool
    # NÃO é suprimido: deriva de contas em aberto (`due_date`), não do saldo inicial — não está
    # contaminado. É para cá que se desloca a cobertura do cálculo que os testes da 5.7 tinham.
    burn_rate_cents_per_day: int


@dataclass
class CashProjection:
    today: date
    saldo_inicial_cents: int
    # Story 8.1 (AC1) — Regra dos Planos §1.3c: nenhum saldo trafega sem procedência. Valor em
    # `app.core.money_planes.ORIGENS`. Na Onda 0 é SEMPRE `plataforma` (não existe `bank_accounts`);
    # a precedência `misto`/`banco` é da Story 8.8, que ao trocar este valor restaura os dois sinais
    # suprimidos sem alterar uma linha da lógica de supressão.
    saldo_inicial_origem: str
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

    **Story 8.1 — as duas supressões, aplicadas DEPOIS do cálculo (a aritmética é intocada, AC7):**
      - `saldo_inicial_origem == plataforma` **e** `burn_rate > 0` → `runway.days = None` +
        `days_suprimido = True` (AC3);
      - `saldo_inicial_origem == plataforma` → `alert = False` + `alert_suprimido = True` em TODAS
        as janelas (AC4b). ⚠️ Aqui **não** há a condição `burn_rate > 0`: o `alert` é por janela e
        não depende de queima média — a contaminação do saldo inicial vale para qualquer janela.
    Nenhum número muda: `saldo_inicial_cents`, `saldo_projetado_cents` e `burn_rate_cents_per_day`
    saem idênticos ao que saíam antes.

    SOMENTE LEITURA: não escreve nada (IV1)."""
    today = today or datetime.now(UTC).date()
    # Janelas ascendentes e sem duplicatas — o cálculo cumulativo assume ordem crescente; o
    # horizonte de burn é a maior. Ignora valores não-positivos (janela de 0 dia não faz sentido).
    ordered = sorted({w for w in windows if w > 0})
    if not ordered:
        ordered = list(DEFAULT_WINDOWS)
    horizons = [today + timedelta(days=w) for w in ordered]

    saldo_inicial = int(wallet_service.wallet_summary(db)["available_cents"])
    # Onda 0: não existe `bank_accounts` — o saldo inicial só pode vir do plano 1. A Story 8.8
    # troca este valor por `misto`/`banco`, e é essa troca (só ela) que restaura os dois sinais.
    saldo_inicial_origem = ORIGEM_PLATAFORMA
    inflows, overdue_inflow = _window_sums(
        db, Charge, open_status=CHARGE_OPEN, today=today, horizons=horizons
    )
    outflows, overdue_outflow = _window_sums(
        db, Payable, open_status=PAYABLE_OPEN, today=today, horizons=horizons
    )

    # AC4b — o veredito de janela negativa é calado quando o saldo de partida não tem lastro. Sem
    # a condição `burn_rate > 0` (diferente do runway): o `alert` é por janela, não depende de
    # queima média. `saldo_projetado_cents` NÃO muda — só o veredito.
    alert_suprimido = saldo_inicial_origem == ORIGEM_PLATAFORMA
    projected_windows: list[ProjectionWindow] = []
    for i, w in enumerate(ordered):
        saldo = saldo_inicial + inflows[i] - outflows[i]
        alert = saldo < 0  # calculado exatamente como antes...
        if alert_suprimido:
            alert = False  # ...e só DEPOIS calado (invariante: suprimido ⇒ alert False)
        projected_windows.append(
            ProjectionWindow(
                days=w,
                saldo_projetado_cents=saldo,
                alert=alert,
                alert_suprimido=alert_suprimido,
            )
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

    # AC3 — o número de dias é calado quando havia queima E o saldo de partida não tem lastro.
    # Calculado acima como antes; suprimido só DEPOIS (invariante: suprimido ⇒ days is None).
    days_suprimido = saldo_inicial_origem == ORIGEM_PLATAFORMA and burn_rate > 0
    if days_suprimido:
        runway_days = None

    notes = [_NOTE_CAIXA, _NOTE_RECORRENCIA]
    if saldo_inicial_origem == ORIGEM_PLATAFORMA:
        notes.append(_NOTE_ORIGEM_PLATAFORMA)
    if days_suprimido:
        notes.append(_NOTE_RUNWAY_SUPRIMIDO)
    # ⚠️ AC4 — a guarda que evita trocar um número falso por uma tranquilidade falsa. A condição
    # era só `if runway_days is None`; sem o `and not days_suprimido` o produto passaria a dizer
    # "sem risco" no caso suprimido, que é PIOR que o bug original (o primeiro erra um número, o
    # segundo dá permissão para gastar).
    if runway_days is None and not days_suprimido:
        notes.append(_NOTE_RUNWAY_SEM_RISCO)
    if any(w.alert_suprimido for w in projected_windows):
        notes.append(_NOTE_ALERT_SUPRIMIDO)
    if overdue_inflow or overdue_outflow:
        notes.append(_NOTE_OVERDUE)

    return CashProjection(
        today=today,
        saldo_inicial_cents=saldo_inicial,
        saldo_inicial_origem=saldo_inicial_origem,
        overdue_inflow_cents=overdue_inflow,
        overdue_outflow_cents=overdue_outflow,
        windows=projected_windows,
        runway=Runway(
            days=runway_days,
            days_suprimido=days_suprimido,
            burn_rate_cents_per_day=burn_rate,
        ),
        notes=notes,
    )
