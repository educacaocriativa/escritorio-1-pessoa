"""Regras da conta de investimento (Story 5.6): CRUD + registrar rendimento + rentabilidade.

Isolamento por RLS (nenhuma query filtra tenant manualmente — Regra de Ouro nº 1). Mesmo padrão
CRUD simples de `chart_accounts`/`cost_centers`.

═══════════════════════════════════════════════════════════════════════════════════════════════
DECISÃO TÉCNICA CENTRAL (Task 3 / AC2 / IV1) — LEIA ANTES DE ALTERAR `register_yield`:
═══════════════════════════════════════════════════════════════════════════════════════════════
O rendimento (juro) vira um "lançamento de receita no grupo FINANCEIRO" reusando a tabela `charges`
(Contas a Receber — "o caminho de lançamento existente" da IV1), MAS construído DIRETAMENTE já
baixado (`status=paid`), sem NUNCA chamar `receivables.mark_paid`/`wallet.build_transaction`.

  Por quê assim: no e1p o ÚNICO ponto que cria uma `Transaction` na Carteira (com split 40/30/20 e
  `PlatformEarning`) é `wallet_service.build_transaction`, chamado só por `receivables.mark_paid`.
  Basta NÃO chamar esse caminho para garantir a IV1 ("receita financeira, não venda com split").
  Como a Charge JÁ nasce `status=paid`, um `mark_paid`/webhook sobre ela é no-op idempotente
  (guarda `if status == PAID: return`) — o split não é acionado nem por engano. Coberto por teste
  explícito (test_investments.py): registrar rendimento NÃO cria Transaction/PlatformEarning.

  Diferenças deliberadas da Charge de rendimento vs. uma cobrança normal de cliente:
   - `external_ref = "investment:<account_id>"` — MARCA a origem (rendimento, não cobrança de
     cliente nenhum) e correlaciona à conta de investimento (sem FK dura, padrão do projeto).
   - NÃO cria evento na Agenda (construção direta; não passa por `build_charge`) — não polui a
     agenda com um "vencimento" de algo que já está realizado.
   - `client_id = None` (não é de cliente nenhum).

  ⚠️ VISIBILIDADE / RECONCILIAÇÃO (ponto reservado à decisão do fundador + @architect, quality_gate
  desta story): como é uma `Charge status=paid`, este lançamento HOJE também é somado por
  `receivables.summary().paid_cents` (o "Recebido" da tela Cobranças) e listado por `list_charges`.
  Isso NÃO move dinheiro (sem Transaction/saque), mas mistura rendimento de investimento com
  recebimento de clientes nesse total. A story pedia explicitamente "aparece em Contas a Receber";
  a missão do fundador pediu para NÃO poluir as telas de cobrança normal. Como as duas orientações
  divergem e o assunto é dinheiro/reconciliação, NÃO alterei `receivables` por conta própria — está
  documentado no Dev Agent Record da story para decisão (mitigação pronta: filtrar
  `external_ref LIKE 'investment:%'` em `list_charges`/`summary`; ou a alternativa do @sm de uma
  tabela de lançamentos financeiros dedicada). A DRE (5.3) já inclui este lançamento corretamente,
  pois agrega `charges` por `chart_account_id`+competência direto (não via `list_charges`).

⚠️ ONDA 2b-i: `register_yield` passou a gerar TAMBÉM um `bank_transaction` `source='yield'`, pelo
`sync_origin_movement`. Isso **NÃO relaxa a IV1** acima: `bank_transactions` é o plano do BANCO;
`Transaction`/`PlatformEarning` são o plano da PLATAFORMA, e continuam intocados. Misturar os dois
é a Regra dos Planos do Epic 8, e foi exatamente essa mistura que produziu o bug de origem dele.
A perna existe porque rendimento **move dinheiro numa conta real do dono** — e um evento assim sem
`bank_transaction` correspondente é o termo P3, que invalida a leitura do gate do épico.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.bank import origin as bank_origin
from app.modules.bank import service as bank_service
from app.modules.bank.models import KIND_INVESTMENT, SOURCE_YIELD
from app.modules.chart_of_accounts import service as chart_service
from app.modules.chart_of_accounts.models import GRUPO_FINANCEIRO
from app.modules.investments.models import InvestmentAccount, external_ref_for
from app.modules.investments.schemas import (
    InvestmentAccountCreate,
    InvestmentAccountUpdate,
)
from app.modules.receivables.models import STATUS_PAID, Charge
from app.modules.settings.service import hoje_do_tenant

# Valores INERTES nos campos que só teriam efeito no split (kind/method) — nunca são usados porque
# a Charge de rendimento não passa por mark_paid/build_transaction. Mantidos válidos por serem
# colunas NOT NULL. Ver docstring do módulo.
_YIELD_CHARGE_KIND = "service"
_YIELD_CHARGE_METHOD = "pix"


class InvestmentError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        # `None` = o router serializa `str(e)` como sempre. Só o erro ACIONÁVEL abaixo preenche.
        self.detail: dict | None = None


# ── O 409 ACIONÁVEL, no MESMO formato que a Story 8.12 fixou (AC9) ───────────────────────────
#
# ⚠️ **A string é duplicada de `payables.service.ACAO_CADASTRAR_CONTA` DE PROPÓSITO**, e a
# sincronia é garantida por **teste**, não por comentário:
# `test_investments.py::test_a_acao_do_409_e_a_MESMA_string_de_payables_e_receivables` compara as
# três constantes. Fazer `investments` importar `payables` só por causa de uma palavra seria
# acoplamento gratuito entre dois módulos de negócio — o mesmo motivo pelo qual `receivables` a
# duplica em vez de importar.
ACAO_CADASTRAR_CONTA = "cadastrar_conta"

SEM_CONTA_VINCULADA_MSG = (
    "Para registrar o rendimento o e1p precisa saber em qual conta o dinheiro entrou — é isso "
    "que faz o movimento aparecer no seu extrato e a conferência valer alguma coisa. Vincule "
    "esta aplicação à conta bancária dela uma vez e o rendimento segue normalmente."
)


class ContaNaoVinculadaError(InvestmentError):
    """A aplicação não aponta para conta bancária nenhuma, e o rendimento precisa de uma perna.

    **É esta recusa que mantém o termo P3 vazio POR CONSTRUÇÃO** (pré-condição do gate do Epic 8),
    e não a disciplina de o dono lembrar de vincular. Mesmo mecanismo pelo qual a Story 8.12 zerou
    P1 ao tornar a conta obrigatória na baixa.

    ⚠️ **409, e o formato é o mesmo dos outros dois módulos**: a tela reconhece a situação por
    `detail["acao"]` e oferece o vínculo ali mesmo. Um segundo valor no `acao` quebraria isso
    **sem erro nenhum**, só deixando de funcionar.
    """

    def __init__(self) -> None:
        super().__init__(SEM_CONTA_VINCULADA_MSG, 409)
        self.detail = {"acao": ACAO_CADASTRAR_CONTA, "mensagem": SEM_CONTA_VINCULADA_MSG}


def get_account(db: Session, account_id: str) -> InvestmentAccount:
    acc = db.get(InvestmentAccount, account_id)
    if acc is None:
        # Cross-tenant também cai aqui: a RLS esconde a linha → db.get None → 404 (fail-closed).
        raise InvestmentError("Conta de investimento não encontrada", 404)
    return acc


def create_account(
    db: Session, *, tenant_id: str, actor: str, data: InvestmentAccountCreate
) -> InvestmentAccount:
    if data.bank_account_id:
        _validate_bank_account(db, data.bank_account_id)
    acc = InvestmentAccount(
        tenant_id=tenant_id,
        name=data.name,
        kind=data.kind,
        index_rate_label=data.index_rate_label,
        principal_cents=data.principal_cents,
        accrued_yield_cents=0,
        opened_at=data.opened_at,
        bank_account_id=data.bank_account_id,
    )
    db.add(acc)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="investment.create", target=acc.id)
    db.commit()
    db.refresh(acc)
    return acc


def update_account(
    db: Session, *, account_id: str, tenant_id: str, actor: str, data: InvestmentAccountUpdate
) -> InvestmentAccount:
    """Edita principal/indexador/tipo/nome. NÃO mexe em `accrued_yield_cents` (esse só muda via
    register_yield, que também gera o lançamento de receita — manter as duas coisas juntas)."""
    acc = get_account(db, account_id)
    if data.name is not None:
        acc.name = data.name
    if data.kind is not None:
        acc.kind = data.kind
    if data.index_rate_label is not None:
        acc.index_rate_label = data.index_rate_label
    if data.principal_cents is not None:
        acc.principal_cents = data.principal_cents
    if data.bank_account_id is not None:
        # Onda 2b-i: é por aqui que a aplicação LEGADA é vinculada — ato do dono, não backfill.
        _validate_bank_account(db, data.bank_account_id)
        acc.bank_account_id = data.bank_account_id
    audit.record(db, tenant_id=tenant_id, actor=actor, action="investment.update", target=acc.id)
    db.commit()
    db.refresh(acc)
    return acc


def list_accounts(db: Session) -> list[InvestmentAccount]:
    return list(db.scalars(select(InvestmentAccount).order_by(InvestmentAccount.name)).all())


def _validate_financeiro_account(db: Session, chart_account_id: str) -> None:
    """A conta do plano de contas informada existe (RLS) E pertence ao grupo FINANCEIRO? (AC2)

    404 se inexistente/de outro tenant (a RLS esconde a linha); 422 se existir mas estiver em outro
    grupo DRE — "preservar a coerência do regime de competência" (AC2) implica preservar a coerência
    do grupo: rendimento de aplicação é receita FINANCEIRA, não pode ser classificado noutro grupo.
    """
    try:
        account = chart_service.get_account(db, chart_account_id)  # 404 se não visível
    except chart_service.ChartAccountError as e:
        # Converte o erro do plano de contas no erro deste módulo (mantém o status 404 fail-closed).
        raise InvestmentError("Conta do plano de contas não encontrada", e.status_code) from e
    if account.grupo_dre != GRUPO_FINANCEIRO:
        raise InvestmentError(
            "A conta do plano de contas do rendimento deve pertencer ao grupo FINANCEIRO", 422
        )


_CONTA_NAO_E_APLICACAO_MSG = (
    "A conta bancária de uma aplicação precisa ser do tipo 'aplicação'. Se o dinheiro está numa "
    "conta corrente, ele não está aplicado — e o rendimento cairia na conta errada, fazendo os "
    "dois saldos derivados mentirem juntos."
)

# ⚠️ Duplicada em substância de `payables.service._CONTA_ARQUIVADA_MSG` DE PROPÓSITO. Aquela
# constante é privada do módulo de Contas a Pagar, e importar um símbolo `_` entre dois módulos de
# negócio seria acoplamento gratuito — o mesmo motivo pelo qual `receivables` duplica
# `ACAO_CADASTRAR_CONTA` em vez de importá-la. O que NÃO é duplicado é o `acao` do 409, porque
# aquele é contrato com a UI e tem teste de sincronia.
_CONTA_ARQUIVADA_MSG = (
    "A conta bancária escolhida está arquivada e não recebe lançamentos novos. Escolha outra "
    "conta ou cadastre a conta que você usa hoje — com o saldo de abertura do dia."
)


def _validate_bank_account(db: Session, bank_account_id: str) -> None:
    """A conta bancária do vínculo existe (RLS), é aplicação e está ativa? (Onda 2b-i)

    **404 se inexistente ou de outro tenant** — `bank_service.get_account` é fail-closed e a RLS
    esconde a linha alheia. Nunca 409 nesse caso: 409 confirmaria a existência da linha, que é
    vazamento de existência com cara de validação (critério já fixado no módulo `bank`).

    **422 se a conta não for `kind='investment'`.** A faceta de produto fala de UMA aplicação; se
    ela apontasse para uma conta corrente, o rendimento creditaria onde o dinheiro não está.
    """
    try:
        acc = bank_service.get_account(db, bank_account_id)
    except bank_service.BankError as e:
        raise InvestmentError("Conta bancária não encontrada", e.status_code) from e
    if acc.kind != KIND_INVESTMENT:
        raise InvestmentError(_CONTA_NAO_E_APLICACAO_MSG, 422)
    if acc.archived_at is not None:
        raise InvestmentError(_CONTA_ARQUIVADA_MSG, 409)


def _today(db: Session) -> date:
    """A MESMA âncora de "hoje" do sistema (fuso do tenant) — nunca um segundo relógio.

    `datetime.now(UTC).date()` aqui adiantaria o dia das 21h à meia-noite em UTC−3 e recusaria,
    como "futuro", um rendimento legítimo lançado à noite. Gate: `tests/test_fuso_do_tenant.py`.
    """
    return hoje_do_tenant(db)


_DATA_FUTURA_MSG = (
    "A data do rendimento não pode ser futura — um rendimento que ainda não caiu não é um "
    "rendimento. Lance-o no dia em que o banco creditar."
)


def register_yield(
    db: Session,
    *,
    account_id: str,
    tenant_id: str,
    actor: str,
    amount_cents: int,
    date: date,  # noqa: A002 (nome de domínio; é a data de competência do rendimento)
    chart_account_id: str | None,
) -> InvestmentAccount:
    """Registra o rendimento (juro) do período: soma ao `accrued_yield_cents` da conta E, na MESMA
    transação, cria a `Charge` de receita financeira JÁ baixada (Task 3) — SEM tocar Carteira/split.

    Ver a docstring do módulo para a decisão técnica completa (IV1). O sinal do lançamento vem da
    tabela de origem (`Charge` = +1), nunca do grupo_dre (convenção canônica ratificada na 5.3).
    """
    acc = get_account(db, account_id)
    # Onda 2b-i: a perna bancária exige saber ONDE o dinheiro entrou. Sem vínculo, 409 ACIONÁVEL.
    if not acc.bank_account_id:
        raise ContaNaoVinculadaError()
    # ⚠️ `bank/transfers.py:185` EXIGE que a 2b decida isto em vez de copiar a forma da
    # transferência — e a razão aqui é outra. Não é "o e1p registra o que já aconteceu": é que um
    # rendimento que ainda não caiu não é um rendimento, e ele não teria PARA ONDE ir. Ao contrário
    # de uma `Payable` com data futura, não existe estado `scheduled` para rendimento, nem
    # superfície onde ele apareceria, nem caminho de promoção. Aceitá-lo inventaria a quarta
    # semântica de agendamento que o Art. IV proíbe.
    if date > _today(db):
        raise InvestmentError(_DATA_FUTURA_MSG, 422)
    if chart_account_id:
        _validate_financeiro_account(db, chart_account_id)

    acc.accrued_yield_cents += amount_cents

    # Charge sintética "já baixada": construída DIRETAMENTE (não via build_charge), NUNCA por
    # mark_paid/build_transaction → não gera Transaction/PlatformEarning (IV1). status=paid a torna
    # inclusive imune a um mark_paid/webhook posterior (guarda de idempotência).
    now = datetime.now(UTC)
    charge = Charge(
        tenant_id=tenant_id,
        client_id=None,  # rendimento não é de cliente nenhum
        description=f"Rendimento de aplicação: {acc.name}",
        kind=_YIELD_CHARGE_KIND,  # inerte (só afetaria o split, que não é acionado)
        method=_YIELD_CHARGE_METHOD,  # inerte
        amount_cents=amount_cents,
        due_date=date,
        competence_date=date,  # regime de competência (DRE, 5.3) — período do rendimento
        paid_at=now,  # regime de caixa: já realizado
        status=STATUS_PAID,
        chart_account_id=chart_account_id,  # grupo FINANCEIRO (validado acima quando informado)
        external_ref=external_ref_for(account_id),  # MARCA a origem (rendimento) + correlação
    )
    db.add(charge)
    db.flush()  # o id da Charge tem default PYTHON-side; sem o flush o `origin_id` nasceria vazio

    # ── A perna bancária (Onda 2b-i) ─────────────────────────────────────────────────────────
    # Pelo MESMO `sync_origin_movement` de payables/receivables/transfers — a **única** função do
    # repositório que escreve `source ∈ SOURCES_SISTEMA`. Não commita: movimento e lançamento
    # entram na MESMA transação, e é o commit abaixo que fecha os dois. Nasce `status='matched'`.
    #
    # **`posted_at=date` e não `paid_at::date`:** o `date` é o dia em que o rendimento caiu para o
    # dono. Usar o instante do registro erraria sempre que ele lançasse com qualquer atraso. O
    # resíduo (competência 31/07 × crédito 01/08) é o **termo 3** da decomposição da divergência —
    # resíduo estrutural, que a banda de tolerância existe para absorver. E ele **não alcança o
    # gate**: o predicado de P3 pergunta *"existe perna?"*, não *"a perna caiu nesta janela?"*.
    #
    # ⚠️ O ramo *"origem desliquidada → apaga"* de `sync_origin_movement` é **INALCANÇÁVEL** para
    # `source='yield'`: não existe caminho de estorno nem de exclusão de rendimento hoje (o router
    # só expõe `register_yield`). Escrito aqui para quem reencontrar o ramo morto na 2b-ii não
    # achar que foi esquecimento.
    bank_origin.sync_origin_movement(
        db,
        tenant_id=tenant_id,
        actor=actor,
        source=SOURCE_YIELD,
        origin_id=charge.id,
        bank_account_id=acc.bank_account_id,
        posted_at=date,
        amount_cents=amount_cents,  # crédito: o sinal vem da tabela de origem (Charge = +1)
        description=f"Rendimento de aplicação: {acc.name}",
    )

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="investment.register_yield", target=acc.id
    )
    db.commit()
    db.refresh(acc)
    return acc


def _pct(numerator: int, principal_cents: int) -> float | None:
    """Rentabilidade (fração) protegendo divisão por zero: principal 0 → None (AC3)."""
    if principal_cents == 0:
        return None
    return numerator / principal_cents


def rentability(
    db: Session, *, account_id: str, start: date | None = None, end: date | None = None
) -> dict:
    """Rentabilidade da conta (AC3): total (rendimento acumulado / principal) e do período (soma dos
    rendimentos com competência no intervalo / principal). Divisão por zero (principal 0) → None.

    O rendimento do período é somado no BANCO (SUM) sobre as `Charge` marcadas
    `external_ref='investment:<account_id>'`, filtradas por `competence_date` (regime de
    competência, coerente com a DRE 5.3)."""
    acc = get_account(db, account_id)

    stmt = select(func.coalesce(func.sum(Charge.amount_cents), 0)).where(
        Charge.external_ref == external_ref_for(account_id)
    )
    if start is not None:
        stmt = stmt.where(Charge.competence_date >= start)
    if end is not None:
        stmt = stmt.where(Charge.competence_date <= end)
    period_yield = int(db.scalar(stmt) or 0)

    return {
        "account_id": acc.id,
        "principal_cents": acc.principal_cents,
        "accrued_yield_cents": acc.accrued_yield_cents,
        "total_rentability_pct": _pct(acc.accrued_yield_cents, acc.principal_cents),
        "period_rentability_pct": _pct(period_yield, acc.principal_cents),
        "period_yield_cents": period_yield,
        "start": start,
        "end": end,
    }
