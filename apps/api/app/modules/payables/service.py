"""Regras de Contas a Pagar: cadastro, baixa, vencimento na agenda, previsão de custos."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.recurrence import advance, occurrences

# O estado é DERIVADO da data, nunca escolhido (Story 8.14 AC2). O helper é **público e neutro**
# (`app/core/`) porque a Story 8.15 o consome para `Charge` — **importar, nunca copiar**.
from app.core.scheduling import status_por_data
from app.db.base import _uuid

# ⚠️ **Duas palavras `scheduled` neste arquivo, e elas NÃO são a mesma coisa.** O `scheduled` da
# Agenda quer dizer *"este evento ainda está pendente na sua agenda"* (é o estado NÃO-terminal de um
# `AgendaEvent`); o `scheduled` de `payables` (Story 8.14) quer dizer *"o débito já tem dia marcado
# no banco"* — que, do ponto de vista da Agenda, deixa o evento **`done`**. Os dois vocabulários
# apontam para lados opostos no mesmo instante, então o da Agenda entra com prefixo: um `import`
# nu faria a colisão passar como sombreamento silencioso, e o sintoma seria o evento voltando a
# "pendente" numa baixa bem-sucedida.
from app.modules.agenda.models import (
    KIND_COBRANCA_PAGAR,
    PRIORITY_NORMAL,
    AgendaEvent,
)
from app.modules.agenda.models import (
    STATUS_DONE as AGENDA_STATUS_DONE,
)
from app.modules.agenda.models import (
    STATUS_SCHEDULED as AGENDA_STATUS_PENDENTE,
)

# ⚠️ **A direção de import de NEGÓCIO → BANCO (Regra dos Planos §1.3d, Story 8.9 AC10).**
# `payables` **pode** importar `app.modules.bank`; `app.modules.bank` **nunca** importa `payables`.
# A volta é proibida e o gate `test_bank_nao_importa_payables` (AST **e** texto cru) a reprova.
from app.modules.bank import origin as bank_origin
from app.modules.bank import service as bank_service
from app.modules.bank.models import SOURCE_PAYABLE, BankAccount
from app.modules.chart_of_accounts import service as chart_service
from app.modules.contracts import service as contracts_service
from app.modules.cost_centers import service as cost_centers_service
from app.modules.payables.models import (
    STATUS_CANCELED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_SCHEDULED,
    Payable,
)
from app.modules.payables.schemas import (
    PayableCreate,
    PayableOut,
    PaymentQueueOut,
    PaymentQueueSummary,
)


class PayableError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        # `None` = o router serializa `str(e)` como sempre. Só o erro ACIONÁVEL abaixo preenche.
        self.detail: dict | None = None


# Os estados em que uma conta a pagar ainda é uma OBRIGAÇÃO que pode ter virado dinheiro saindo —
# e portanto candidata a ser o mesmo dinheiro de um lançamento manual (Story 8.17 AC5). `canceled`
# fica fora: não é obrigação nenhuma, e casá-la daria um 409 sem saída pelo caminho oferecido.
# ⚠️ **[Story 8.14] `scheduled` ENTROU AQUI** — a Story 8.17 já o listava no AC5 e o registrou como
# desvio declarado ("`scheduled` não existe ainda"); a dívida se paga com **uma entrada nesta
# tupla**, exatamente como aquela story previu, e nada mais mudou. Uma conta agendada é o caso mais
# perigoso da guarda: o dono agendou no app do banco, deu a baixa no e1p **e** lançou o mesmo Pix à
# mão — o saldo cairia duas vezes.
_ESTADOS_CANDIDATOS: tuple[str, ...] = (STATUS_OPEN, STATUS_SCHEDULED, STATUS_PAID)

ACAO_CADASTRAR_CONTA = "cadastrar_conta"

SEM_CONTA_MSG = (
    "Para dar baixa nesta conta o e1p precisa saber de qual conta bancária o dinheiro saiu — é "
    "isso que faz o movimento aparecer no seu extrato e a conferência valer alguma coisa. "
    "Cadastre a sua conta bancária uma vez e o pagamento segue normalmente."
)

_CONTA_ARQUIVADA_MSG = (
    "A conta bancária escolhida está arquivada e não recebe lançamentos novos. Escolha outra "
    "conta ou cadastre a conta que você usa hoje — com o saldo de abertura do dia."
)


class ContaBancariaNecessaria(PayableError):
    """**409 ACIONÁVEL** — o formato do payload é CONTRATO, não detalhe de implementação (AC2).

        {"detail": {"acao": "cadastrar_conta", "mensagem": "..."}}

    A Story 8.13 consome exatamente este shape para abrir o cadastro de conta **embutido** no
    fluxo de pagamento e voltar para a baixa; a 8.15 (recebimento fora do trilho) e a 8.17
    (lançamento manual) devem reusá-lo. Um 409 mudo com uma frase solta obrigaria cada tela a
    reconhecer a situação por substring da mensagem — que é como um contrato de erro deixa de ser
    contrato.

    ⚠️ **É consequência DECLARADA, não descoberta depois:** a partir da Story 8.12, um tenant sem
    `bank_accounts` **não consegue dar baixa em conta a pagar**. As duas alternativas foram
    consideradas e rejeitadas no design da Onda 2 §4.1 — criar sozinho uma conta `kind='cash'`
    chamada "Caixa" inventa dado (Artigo IV), e permitir nulo quando o tenant tem zero contas cria
    um terceiro estado de "não sei" que a conferência teria de aprender a reportar (*"opcional
    significa que alguém pula, e a conferência volta a medir o que você esqueceu de preencher"* —
    fundador F7).

    ⚠️ **Nunca use este erro para uma conta que EXISTE em outro tenant.** Ali a resposta é **404**
    (`bank_service.get_account`, fail-closed pela RLS): 409 confirmaria a existência da linha.
    """

    def __init__(self, mensagem: str = ""):
        mensagem = mensagem or SEM_CONTA_MSG
        super().__init__(mensagem, 409)
        self.detail = {"acao": ACAO_CADASTRAR_CONTA, "mensagem": mensagem}


def is_overdue(p: Payable, today: date | None = None) -> bool:
    today = today or datetime.now(UTC).date()
    return p.status == STATUS_OPEN and p.due_date < today


def payable_out(p: Payable, today: date | None = None) -> PayableOut:
    """Serialização canônica de um Payable → PayableOut (usada pelo router e pela fila da Story 5.9,
    para não duplicar a montagem do schema). `today` opcional só afeta o cálculo de is_overdue."""
    return PayableOut(
        id=p.id,
        tenant_id=p.tenant_id,
        description=p.description,
        category=p.category,
        supplier=p.supplier,
        amount_cents=p.amount_cents,
        due_date=p.due_date,
        competence_date=p.competence_date,
        chart_account_id=p.chart_account_id,
        contract_id=p.contract_id,
        cost_center_id=p.cost_center_id,
        status=p.status,
        is_overdue=is_overdue(p, today),
        paid_at=p.paid_at,
        recurrence=p.recurrence,
        recurrence_count=p.recurrence_count,
        recurrence_group=p.recurrence_group,
        payment_code=p.payment_code,
        attachment_url=p.attachment_url,
        # Story 8.12 AC12 — o vínculo com o razão bancário fica VISÍVEL. Sem ele a UI da 8.13 não
        # tem como mostrar "saiu do Itaú PJ" nem como pré-selecionar a conta na correção.
        # ⚠️ Nenhuma superfície de `/admin/*` recebe estes campos (epic §2.1): não existe agregado
        # de plataforma sobre a conta bancária do dono.
        bank_account_id=p.bank_account_id,
        bank_transaction_id=p.bank_transaction_id,
        created_at=p.created_at,
    )


def build_payable(db: Session, *, tenant_id: str, actor: str, data: PayableCreate) -> Payable:
    """Cria a conta SEM commitar — reutilizável dentro de outra transação (mesmo padrão de
    `receivables.build_charge`). Se recorrente, gera N ocorrências — cada uma com seu
    vencimento e seu evento na Agenda (assim cada repetição pode receber seu próprio boleto).
    """
    # Story 5.2: valida o vínculo opcional ao plano de contas (404 se apontar p/ conta
    # inexistente/de outro tenant — a RLS já esconde a linha cross-tenant).
    if data.chart_account_id and not chart_service.exists(db, data.chart_account_id):
        raise PayableError("Conta do plano de contas não encontrada", 404)
    # Story 5.4: valida o vínculo opcional ao contrato (404 se apontar p/ contrato inexistente/de
    # outro tenant — a RLS já esconde a linha cross-tenant).
    if data.contract_id and not contracts_service.exists(db, data.contract_id):
        raise PayableError("Contrato não encontrado", 404)
    # Story 5.5: valida o vínculo opcional ao centro de custo (2ª dimensão). 404 se apontar p/ um
    # centro inexistente/de outro tenant — a RLS já esconde a linha cross-tenant.
    if data.cost_center_id and not cost_centers_service.exists(db, data.cost_center_id):
        raise PayableError("Centro de custo não encontrado", 404)
    n = occurrences(data.recurrence, data.recurrence_count)
    group = _uuid() if n > 1 else None
    title = f"A pagar: {data.supplier or data.description or 'conta'}"
    first: Payable | None = None
    for i in range(n):
        due = advance(data.due_date, data.recurrence, i)
        # competência (regime de competência/DRE): fallback = vencimento da ocorrência quando
        # omitida; se informada, avança em paralelo ao vencimento (cada ocorrência no seu período).
        competence = (
            advance(data.competence_date, data.recurrence, i)
            if data.competence_date is not None
            else due
        )
        payable = Payable(
            tenant_id=tenant_id,
            description=data.description,
            category=data.category,
            supplier=data.supplier,
            amount_cents=data.amount_cents,
            due_date=due,
            competence_date=competence,
            chart_account_id=data.chart_account_id,
            contract_id=data.contract_id,
            cost_center_id=data.cost_center_id,
            recurrence=data.recurrence,
            recurrence_count=n,
            recurrence_group=group,
            # boleto/anexo informados na criação só na 1ª ocorrência (as demais anexa-se depois)
            payment_code=data.payment_code if i == 0 else "",
            attachment_url=data.attachment_url if i == 0 else "",
            status=STATUS_OPEN,
        )
        db.add(payable)
        db.flush()
        day_start = datetime.combine(due, time.min, tzinfo=UTC)
        event = AgendaEvent(
            tenant_id=tenant_id, title=title, kind=KIND_COBRANCA_PAGAR,
            status=AGENDA_STATUS_PENDENTE,
            priority=PRIORITY_NORMAL, source="payables", starts_at=day_start,
            ends_at=day_start.replace(hour=23, minute=59), all_day=True,
            amount_cents=data.amount_cents, external_ref=payable.id,
        )
        db.add(event)
        db.flush()
        payable.agenda_event_id = event.id
        if i == 0:
            first = payable

    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.create", target=first.id)
    return first


def create_payable(db: Session, *, tenant_id: str, actor: str, data: PayableCreate) -> Payable:
    p = build_payable(db, tenant_id=tenant_id, actor=actor, data=data)
    db.commit()
    db.refresh(p)
    return p


def get_payable(db: Session, payable_id: str) -> Payable:
    p = db.get(Payable, payable_id)
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    return p


def update_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str, data) -> Payable:
    """Edita a conta (dados + boleto/Pix). Mexer em valor/vencimento exige conta em aberto e
    sincroniza o evento da Agenda (move o vencimento, atualiza valor/título)."""
    p = get_payable(db, payable_id)
    core = (data.description, data.category, data.supplier, data.amount_cents,
            data.due_date, data.recurrence)
    if any(v is not None for v in core) and p.status != STATUS_OPEN:
        raise PayableError("Só contas em aberto podem ter os dados editados", 409)

    # boleto/Pix podem ser ajustados a qualquer momento
    if data.payment_code is not None:
        p.payment_code = data.payment_code
    if data.attachment_url is not None:
        p.attachment_url = data.attachment_url
    # Story 5.2: reclassificação (competência/conta do plano de contas) — metadado contábil, não
    # toca no caminho de dinheiro; ajustável a qualquer momento.
    if data.competence_date is not None:
        p.competence_date = data.competence_date
    if data.chart_account_id is not None:
        if data.chart_account_id == "":
            p.chart_account_id = None
        elif not chart_service.exists(db, data.chart_account_id):
            raise PayableError("Conta do plano de contas não encontrada", 404)
        else:
            p.chart_account_id = data.chart_account_id
    # Story 5.4: (re)vincular/desvincular do contrato. "" desvincula (bucket "Empresa"); um id
    # inexistente/de outro tenant → 404. Metadado analítico, não toca no caminho de dinheiro.
    if data.contract_id is not None:
        if data.contract_id == "":
            p.contract_id = None
        elif not contracts_service.exists(db, data.contract_id):
            raise PayableError("Contrato não encontrado", 404)
        else:
            p.contract_id = data.contract_id
    # Story 5.5: (re)vincular/desvincular do centro de custo (2ª dimensão). "" desvincula ("Não
    # atribuído"); id inexistente/de outro tenant → 404. Metadado analítico, não toca no dinheiro.
    if data.cost_center_id is not None:
        if data.cost_center_id == "":
            p.cost_center_id = None
        elif not cost_centers_service.exists(db, data.cost_center_id):
            raise PayableError("Centro de custo não encontrado", 404)
        else:
            p.cost_center_id = data.cost_center_id
    # dados principais
    if data.description is not None:
        p.description = data.description
    if data.category is not None:
        p.category = data.category
    if data.supplier is not None:
        p.supplier = data.supplier
    if data.amount_cents is not None:
        p.amount_cents = data.amount_cents
    if data.recurrence is not None:
        p.recurrence = data.recurrence
    if data.due_date is not None:
        p.due_date = data.due_date

    # reverbera na Agenda (evento de vencimento vinculado)
    ev = db.get(AgendaEvent, p.agenda_event_id) if p.agenda_event_id else None
    if ev is not None:
        if data.due_date is not None:
            day_start = datetime.combine(p.due_date, time.min, tzinfo=UTC)
            ev.starts_at = day_start
            ev.ends_at = day_start.replace(hour=23, minute=59)
        if data.amount_cents is not None:
            ev.amount_cents = p.amount_cents
        if data.description is not None or data.supplier is not None:
            ev.title = f"A pagar: {p.supplier or p.description or 'conta'}"

    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.update", target=p.id)
    db.commit()
    db.refresh(p)
    return p


def list_payables(
    db: Session, *, status: str | None = None, limit: int = 200, offset: int = 0
) -> list[Payable]:
    limit = max(1, min(limit, 500))
    stmt = select(Payable).order_by(Payable.due_date)
    if status:
        stmt = stmt.where(Payable.status == status)
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


def _today() -> date:
    """Hoje em UTC — a MESMA âncora de `is_overdue`, `summary` e `bank.service._today`.

    A dívida geral de fuso por tenant está registrada no `CLAUDE.md` §6.1 e não é resolvida aqui.
    """
    return datetime.now(UTC).date()


def _conta_de_baixa(db: Session, bank_account_id: str) -> BankAccount:
    """Resolve a conta da baixa: **409 acionável, 404, 409 — nesta ordem, e por este motivo.**

    1. **Tenant sem NENHUMA conta ativa → 409 acionável** (`ContaBancariaNecessaria`), *antes* de
       olhar o id recebido. Esta ordem é o que torna o AC2 **alcançável a partir da rota**: como
       `PayablePayIn.bank_account_id` é obrigatório, um tenant sem contas só consegue mandar um id
       qualquer — e um 404 ali diria "esse id não existe" quando o fato é "você ainda não cadastrou
       conta nenhuma". Também **não vaza existência**: com zero contas próprias, *todo* id recebe a
       mesma resposta, inclusive o id real de outro tenant.
    2. **Id desconhecido (ou de outro tenant, escondido pela RLS) → 404 fail-closed**, delegado a
       `bank_service.get_account`. 409 aqui confirmaria que a linha existe em algum lugar.
    3. **Conta arquivada → 409 acionável**, com a mensagem própria: a conta existe, mas encerrada
       não recebe lançamento novo (mesma regra de `bank.service.create_transaction`), e a saída é a
       mesma do caso (1) — cadastrar/escolher a conta que ele usa hoje.
    """
    if not bank_service.list_accounts(db):
        raise ContaBancariaNecessaria()
    acc = _traduz_bank_error(lambda: bank_service.get_account(db, bank_account_id))
    if acc.archived_at is not None:
        raise ContaBancariaNecessaria(_CONTA_ARQUIVADA_MSG)
    return acc


def _traduz_bank_error(call):
    """Executa uma chamada ao módulo `bank` traduzindo `BankError` → `PayableError`.

    A fronteira de módulo existe também para os ERROS: sem esta tradução, um `BankError` subindo de
    `sync_origin_movement` atravessaria o `except PayableError` do router e viraria **500** — um
    422 legítimo (data, valor) apareceria para o usuário como falha do servidor. O `status_code` é
    preservado; a mensagem do módulo `bank` já explica o que fazer.
    """
    try:
        return call()
    except bank_service.BankError as e:
        raise PayableError(str(e), e.status_code) from e


def _valida_data_de_baixa(paid_on: date, acc: BankAccount) -> date:
    """A guarda da data da baixa: **só o PISO**. 422 — nunca trunca em silêncio.

    **Piso — `paid_on > acc.opening_date`.** A comparação NÃO é reescrita aqui: quem a aplica é
    `bank.service.validate_posted_at_floor`, extraída como pública pela Story 8.9 exatamente para
    isto (duas cópias do mesmo predicado divergem no dia em que só uma for corrigida). O que esta
    função acrescenta é a **mensagem do AC3**, que nomeia as **duas** saídas — a genérica do módulo
    `bank` explica a fórmula do saldo, e quem está dando baixa numa conta antiga precisa saber o
    que fazer, não por que a soma dobraria.

    ── ⚠️ **[Story 8.14] O TETO SAIU DAQUI, e a remoção é o fecho de um ciclo aberto de propósito.**

    Até a Story 8.13 esta função também recusava `paid_on > hoje`, com a marca `[CORTE DO @PM]` e a
    instrução literal *"não remova este teto antes da 8.14"*. O teto nunca foi uma regra de negócio:
    era **faseamento**. Ele garantia que **nunca existisse um `payable` `paid` com data futura**
    enquanto o estado `scheduled` não existisse — porque, se `paid`+futuro entrasse primeiro, o
    backfill das 45 contas do mutirão e os pagamentos agendados ficariam no MESMO status,
    separáveis só por um predicado sobre a data, e desmanchar isso depois seria uma migration com
    backfill sob `FORCE RLS` (a armadilha da 0046).

    Agora `scheduled` existe, e o estado passou a ser **derivado da data** (`apply_paid`):
    `paid_on` futuro ⇒ `scheduled`; hoje ou passado ⇒ `paid`. **Não reintroduza o teto** — e não o
    troque por um truncamento silencioso em `hoje`, que continua sendo a "correção" tentadora:
    gravar uma data que o usuário não informou é inventar o fato de caixa (Artigo IV).

    A guarda de data futura que **continua de pé** é outra e protege outra coisa: a do lançamento
    **externo** (`bank.service._validate_posted_at`, `SOURCES_EXTERNA`), onde data futura é erro de
    digitação. O corte é por `source` — *"o e1p pode afirmar o futuro do que ele mesmo agendou; não
    pode afirmar o futuro do que outro atestou"*.
    """
    try:
        bank_service.validate_posted_at_floor(paid_on, acc)
    except bank_service.BankError as e:
        raise PayableError(
            f"Esta conta bancária só existe no e1p a partir de "
            f"{acc.opening_date.isoformat()}, então um pagamento em {paid_on.isoformat()} não "
            "entraria no extrato dela. Mova a abertura desta conta para antes de "
            f"{paid_on.strftime('%d/%m')} e informe o saldo daquele dia, ou escolha outra conta.",
            422,
        ) from e
    return paid_on


def _descricao_do_movimento(p: Payable) -> str:
    """A descrição que vai para `bank_transactions.raw_description`.

    Mesma ordem de preferência do título do evento da Agenda (`build_payable`), invertida de
    propósito: na Agenda o fornecedor identifica melhor a linha; no extrato, quem lê está
    procurando *o que* foi pago. Os dois juntos quando houver os dois.
    """
    partes = [texto for texto in (p.description, p.supplier) if texto]
    return " — ".join(partes) or "Conta a pagar"


def _sincroniza_movimento(
    db: Session,
    p: Payable,
    *,
    tenant_id: str,
    actor: str,
    bank_account_id: str | None,
    posted_at: date | None,
) -> None:
    """O **único** ponto deste módulo que escreve o razão bancário. Não commita.

    ⚠️ **Nenhum segundo caminho de escrita.** Se aparecer um `BankTransaction(...)` com
    `source='payable'` fora de `bank.origin.sync_origin_movement`, a Regra da Origem fica
    inauditável — o gate `test_chamadores_do_sincronizador_estao_na_allowlist` existe para que a
    segunda porta não passe despercebida.

    `bank_account_id=None` significa *"este lançamento não está mais liquidado"* ⇒ o movimento é
    **apagado** (ou, se já tiver sido enriquecido pela importação da Onda 4, desligado da origem —
    a guarda mora em `origin._desliga_ou_apaga`).

    O cache (`p.bank_transaction_id`) é gravado com **o que o sincronizador devolveu**, sempre — é
    assim que ele nunca diverge do `origin_id`
    (`test_cache_de_movimento_nunca_diverge_do_origin_id_pelos_caminhos_reais`).
    """
    movimento = _traduz_bank_error(
        lambda: bank_origin.sync_origin_movement(
            db,
            tenant_id=tenant_id,
            actor=actor,
            source=SOURCE_PAYABLE,
            origin_id=p.id,
            bank_account_id=bank_account_id,
            posted_at=posted_at,
            # **NEGATIVO — é saída.** O sinal é interno à tabela de movimentos (invariante (b) de
            # `BankTransaction`) e `-abs()` é deliberado: `p.amount_cents` já é `> 0` por schema,
            # mas um `-p.amount_cents` sobre um dado legado negativo viraria uma ENTRADA no extrato.
            amount_cents=-abs(p.amount_cents) if bank_account_id else None,
            description=_descricao_do_movimento(p),
            counterparty_name=p.supplier,
            operation_nature=None,
        )
    )
    p.bank_account_id = bank_account_id
    p.bank_transaction_id = movimento.id if movimento is not None else None


def apply_paid(
    db: Session,
    *,
    payable_id: str,
    tenant_id: str,
    actor: str,
    bank_account_id: str,
    paid_on: date | None = None,
) -> Payable:
    """Dá baixa na conta **e escreve o movimento bancário** — na MESMA transação. SEM commitar.

    Mesmo padrão de `receivables.build_charge`: a versão sem commit é a real, e a versão
    pública (`mark_paid`) é um wrapper que commita. Assim anexar o comprovante, dar a baixa e
    gerar o movimento acontecem numa transação só (ver payables/receipts.py::link_receipt).
    **Um dos dois sem o outro é exatamente o estado que a Onda 2 existe para tornar impossível.**

    Idempotente: conta já paga volta inalterada (não re-data o `paid_at`, não move o movimento —
    para corrigir conta ou data existe `update_payment`). A garantia final contra o movimento
    duplicado não é este `if`: é o índice único parcial `uq_bank_transactions_origin`
    `(tenant_id, source, origin_id)`, no banco, fail-closed.

    ── ⚠️ **[Story 8.14] O ESTADO É DERIVADO DA DATA, NUNCA ESCOLHIDO** (AC2)

    | `paid_on` | `status` resultante | `paid_at` |
    |---|---|---|
    | `> hoje` | `scheduled` | o `paid_on` informado |
    | `== hoje` ou `< hoje` | `paid` | o `paid_on` informado |

    A derivação mora em `app.core.scheduling.status_por_data` — **público e neutro**, porque a Story
    8.15 o consome para `Charge`. Nenhum schema de entrada (`PayableCreate`, `PayableUpdate`,
    `PayablePayIn`, `PayablePaymentUpdate`) aceita `status`: quem decide é a data, e a API não
    oferece o campo. Invariante testável nas duas direções:
    **`status == 'scheduled' ⟺ paid_at.date() > hoje`, no momento da escrita** — depois disso quem
    move é `promote_scheduled`, no worker.

    **`scheduled` NÃO é idempotente aqui, e isso é o ponto:** uma conta agendada que recebe uma
    baixa nova (com a data em que o dinheiro saiu de verdade) **atravessa** o `if` acima e
    re-deriva o estado. O movimento não duplica porque `sync_origin_movement` é upsert sobre
    `(source, origin_id)`: ele **move**, nunca cria um segundo.

    Args:
        bank_account_id: **OBRIGATÓRIO, sem default e sem `| None`** (AC1, fundador F7). Não há
            sobrecarga e **não há fallback para a conta primária aqui**: o pré-preenchimento pela
            primária é da UI (Story 8.13), e a diferença importa — *"o que o pré-preenchimento
            evita é **construir**, não **confirmar**"*. Tenant sem conta nenhuma → 409 acionável;
            conta de outro tenant → 404; conta arquivada → 409 acionável (ver `_conta_de_baixa`).
        paid_on: `None` ⇒ **`p.due_date`** (fundador F10: *"deixar habilitado no vencimento, pois
            se estiver fazendo retroativo, pq não deu certo no dia"*) — não `now()`, e **não**
            `min(due_date, hoje)`, recomendação que a própria @architect revogou por estar
            *"desenhando o produto em volta de uma limitação do meu próprio modelo"*. **Só o piso**
            em `_valida_data_de_baixa` (o teto saiu na 8.14). ⚠️ Consequência da remoção do teto:
            dar baixa numa conta com vencimento **futuro** sem informar `paid_on` deixou de ser
            422 e passou a gravar `scheduled` no vencimento — que é exatamente o que o dono quis
            dizer ao clicar em "marcar paga" numa conta que ele acabou de agendar no app do banco.

    `p.paid_at` (regime de CAIXA) passa a **derivar de `paid_on`** em vez de ser `now()` cravado.
    `p.competence_date` (regime de COMPETÊNCIA) **não é tocado** — `payables/models.py:6-9`, regra
    dura: mudar a data da baixa move fluxo de caixa, projeção e o movimento bancário; **não** move
    a DRE nem a Lucratividade (`test_alterar_data_de_baixa_nao_altera_dre`).
    """
    p = db.scalar(select(Payable).where(Payable.id == payable_id).with_for_update())
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    # Idempotência ANTES de qualquer validação de conta: um retry de request precisa devolver o
    # mesmo 200 de antes, não um 404 porque o cliente reenviou um id de conta que mudou.
    if p.status == STATUS_PAID:
        return p
    if p.status == STATUS_CANCELED:
        raise PayableError("Conta cancelada não pode ser paga", 409)

    # Ordem deliberada: TODA validação antes de qualquer escrita (mesma disciplina de
    # `bank.origin.sync_origin_movement`).
    acc = _conta_de_baixa(db, bank_account_id)
    paid_on = _valida_data_de_baixa(paid_on if paid_on is not None else p.due_date, acc)

    # [8.14] Derivado da data, nunca escolhido — e pelo helper PÚBLICO, que a 8.15 importa.
    p.status = status_por_data(
        paid_on, _today(), status_agendado=STATUS_SCHEDULED, status_pago=STATUS_PAID
    )
    # Meia-noite UTC da data de caixa — mesma convenção de `paid_before` e de `summary`, e o mesmo
    # cuidado de data-de-calendário que o bug de fuso da Agenda (`CLAUDE.md` §6.0) ensinou.
    p.paid_at = datetime.combine(paid_on, time.min, tzinfo=UTC)
    if p.agenda_event_id:
        ev = db.get(AgendaEvent, p.agenda_event_id)
        if ev is not None:
            # `done` também no caminho `scheduled` (8.14): do ponto de vista da Agenda a decisão já
            # foi tomada e a conta não é mais uma pendência de hoje. É o que permite o worker do
            # AC10 promover `scheduled → paid` **sem tocar na Agenda** — o evento já está no estado
            # final desde a baixa, e a promoção não tem nada a reverberar ali.
            ev.status = AGENDA_STATUS_DONE  # não fica "atrasado" na agenda
    _sincroniza_movimento(
        db, p, tenant_id=tenant_id, actor=actor, bank_account_id=acc.id, posted_at=paid_on
    )
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.paid", target=p.id)
    return p


def mark_paid(
    db: Session,
    *,
    payable_id: str,
    tenant_id: str,
    actor: str,
    bank_account_id: str,
    paid_on: date | None = None,
) -> Payable:
    """Wrapper de `apply_paid` que **commita**. Mesmos parâmetros, mesma regra (AC1)."""
    p = apply_paid(
        db,
        payable_id=payable_id,
        tenant_id=tenant_id,
        actor=actor,
        bank_account_id=bank_account_id,
        paid_on=paid_on,
    )
    db.commit()
    db.refresh(p)
    return p


def update_payment(
    db: Session,
    *,
    payable_id: str,
    tenant_id: str,
    actor: str,
    bank_account_id: str | None = None,
    paid_on: date | None = None,
) -> Payable:
    """Corrige o **pagamento** de uma conta já paga: a conta bancária e/ou a data. Commita.

    **Por que esta rota existe** (F-D10): reagendar/corrigir é **evento normal, não excepcional**.
    Sem ela, corrigir seria estornar + repagar — **delete + recreate** do movimento e o evento da
    Agenda indo e voltando; operação pesada para um evento leve, todo mês.

    - aceita `status='paid'` **e `status='scheduled'`** (a 8.14 acrescentou o segundo); conta em
      aberto → **409**, porque não há pagamento a corrigir. **A rota pode MOVER o estado nas duas
      direções** — corrigir a data para o futuro transforma `paid` em `scheduled`, e antecipar uma
      agendada para hoje/ontem a transforma em `paid`. O estado continua derivado da data, e é a
      mesma derivação de `apply_paid` (`status_por_data`), não uma segunda cópia;
    - trocar a conta → **UPDATE de `bank_account_id` na MESMA linha** do movimento. **Move, nunca
      duplica** (Regra da Origem (c)); os dois saldos derivados se corrigem sozinhos porque são
      derivados, e o `origin_dedup_hash` é estável sob troca de conta exatamente por isto;
    - trocar a data → UPDATE de `posted_at`, **revalidado contra a `opening_date` da conta de
      DESTINO** — o piso do AC3 vale de novo, e a conta pode ter mudado no mesmo PATCH;
    - `competence_date` **não** é tocado (regra dura de caixa × competência).

    ⚠️ **`PayableUpdate` NÃO é tocado, e isso é a mesma disciplina que `bank.update_transaction`
    documenta como dupla "de propósito":** o campo não existe no schema genérico **e** nenhuma
    função faz `setattr` genérico. Mantendo o PATCH genérico intacto, ninguém torna um campo
    editável em conta paga por acidente — que é como uma coluna imutável deixa de ser.
    """
    p = db.scalar(select(Payable).where(Payable.id == payable_id).with_for_update())
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    if p.status not in (STATUS_PAID, STATUS_SCHEDULED):
        raise PayableError(
            "Só uma conta paga ou agendada tem pagamento a corrigir. Para mexer em valor, "
            "vencimento ou fornecedor de uma conta em aberto, use a edição da conta.",
            409,
        )

    destino_id = bank_account_id if bank_account_id is not None else p.bank_account_id
    if not destino_id:
        # Conta paga ANTES desta story (legado): não há de qual conta ela saiu, e o e1p não
        # inventa uma (Artigo IV). É o mesmo 409 acionável do AC2 — a 8.13 abre o cadastro/seleção.
        raise ContaBancariaNecessaria()
    acc = _conta_de_baixa(db, destino_id)

    if paid_on is None:
        # Data ausente = "não altera". `paid_at` é a data de caixa autoritativa; legado sem ela
        # cai no vencimento, que é o mesmo default do AC3.
        paid_on = _as_utc_date(p.paid_at) or p.due_date
    paid_on = _valida_data_de_baixa(paid_on, acc)

    p.paid_at = datetime.combine(paid_on, time.min, tzinfo=UTC)
    # [8.14] A MESMA derivação de `apply_paid`, pelo MESMO helper. Duas cópias da regra derivada
    # divergiriam no primeiro ajuste — e a correção da data é justamente onde a fronteira
    # `paid ⇄ scheduled` é atravessada.
    p.status = status_por_data(
        paid_on, _today(), status_agendado=STATUS_SCHEDULED, status_pago=STATUS_PAID
    )
    _sincroniza_movimento(
        db, p, tenant_id=tenant_id, actor=actor, bank_account_id=acc.id, posted_at=paid_on
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="payable.payment_update", target=p.id
    )
    db.commit()
    db.refresh(p)
    return p


def cancel_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    p = get_payable(db, payable_id)
    if p.status == STATUS_PAID:
        raise PayableError("Conta paga não pode ser cancelada", 409)
    p.status = STATUS_CANCELED
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.cancel", target=p.id)
    db.commit()
    db.refresh(p)
    return p


def reverse_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    """Estorna uma conta paga **ou agendada**: volta para 'open', limpa paid_at, reabre a edição,
    devolve o evento vinculado na Agenda para pendente (desfaz o `done` de mark_paid) — e
    **APAGA o movimento bancário** (AC8), na mesma transação.

    **Por que apagar, e não marcar `ignored` nem lançar uma contrapartida.** Um movimento bancário
    é a afirmação *"este dinheiro saiu desta conta"*; estornado o pagamento, o sistema **não afirma
    mais isso**. As duas alternativas foram consideradas e rejeitadas no design §4.5:

    - **contrapartida** (`+valor` compensando o `−valor`): o extrato do dono tem **uma** linha;
      criar duas **inventa um crédito que nunca existiu no banco**, e a importação da Onda 4
      encontraria dois órfãos irreconciliáveis. Fabricar fato bancário pela porta de trás;
    - **`ignored`**: (i) `ignored` significa *"o usuário disse que isto não deve contar"* — é
      julgamento do dono, não estado de sistema; (ii) a linha ficaria visível com um "motivo" que é
      ruído, não evidência; (iii) **colide com `uq_bank_transactions_origin` quando o pagamento é
      refeito** — baixar → estornar → baixar de novo produziria uma segunda linha com a mesma
      `(tenant_id, source, origin_id)` e o banco recusaria. O DELETE não tem esse problema.

    A trilha de auditoria **não se perde**: mora em `audit_entries` (`payable.reverse`, gravado
    logo abaixo, **sem trilha nova**), que é a finalidade dela.

    ⚠️ **A guarda da linha puramente sintética vale aqui** (AC9): o DELETE só acontece enquanto a
    linha for `fitid IS NULL AND import_batch_id IS NULL`. Já enriquecida pela importação (Onda 4),
    o estorno **não apaga** — desliga a origem e a linha vira órfã do extrato, degradação honesta.
    A guarda mora em `origin._desliga_ou_apaga` e **não é reimplementada aqui**. Hoje o ramo
    enriquecido é inalcançável (não há importação), **e é exatamente por isso que os 45 estornos do
    mutirão são seguros**.

    ── ⚠️ **[Story 8.14] `scheduled` também é estornável — e não há verbo novo para isso** (AC9)

    **Cancelar um agendamento É estornar.** O significado de `reverse` sempre foi *"esta saída não
    vai acontecer"*, e ele serve igualmente bem para uma saída que **ainda não aconteceu**. Uma rota
    `POST .../cancel-schedule` seria um segundo caminho para a mesma mecânica (apagar o movimento,
    devolver o evento da Agenda, reabrir a edição) — e dois caminhos para a mesma mecânica é como
    um deles deixa de receber a próxima correção.

    A conta **reaparece na Fila**, que é o comportamento certo: agendamento cancelado significa que
    a conta voltou a ser problema. E o movimento bancário futuro é **apagado** pela mesma mecânica
    da 8.12 — nada sobra afirmando que aquele dinheiro vai sair.
    """
    p = db.scalar(select(Payable).where(Payable.id == payable_id).with_for_update())
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    if p.status not in (STATUS_PAID, STATUS_SCHEDULED):
        raise PayableError("Só contas pagas ou agendadas podem ser estornadas", 409)
    p.status = STATUS_OPEN
    p.paid_at = None
    # `bank_account_id=None` é como se pede a remoção do movimento; o helper zera as DUAS colunas
    # (a autoritativa e o cache) com o que o sincronizador devolveu — `None`.
    _sincroniza_movimento(
        db, p, tenant_id=tenant_id, actor=actor, bank_account_id=None, posted_at=None
    )
    if p.agenda_event_id:
        ev = db.get(AgendaEvent, p.agenda_event_id)
        if ev is not None:
            ev.status = AGENDA_STATUS_PENDENTE
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.reverse", target=p.id)
    db.commit()
    db.refresh(p)
    return p


def _as_utc_date(value: object) -> date | None:
    """Normaliza o resultado de `MIN/MAX(paid_at)` para uma data de calendário em UTC.

    O SQLite devolve `TIMESTAMP` como **texto** em agregações; o Postgres devolve `datetime`
    (tz-aware). Sem esta normalização a função quebraria só em um dos dois bancos — mesmo cuidado
    que `bank.service._validate_opening_date_move` já toma com `MIN(posted_at)`.
    """
    if value is None:
        return None
    if isinstance(value, str):
        # "2026-07-10 12:00:00.000000" → 2026-07-10 (o texto do SQLite já está em UTC).
        return date.fromisoformat(value[:10])
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    return None


def paid_before(db: Session, *, date_: date) -> dict:
    """Agregado read-only: contas **pagas** cujo dinheiro saiu ANTES de `date_` (Story 8.11).

    Alimenta o aviso pró-ativo do cadastro de conta bancária: "você tem N contas pagas entre X e Y
    — se esta conta abrir em `date_`, elas não vão entrar no extrato do e1p". O e1p **diz qual
    número ir buscar**; ele não inventa nenhum (AC4).

    **Eixo de CAIXA, nunca de competência** (`payables/models.py:6-9`, verbatim: *"fluxo de caixa
    usa `paid_at`; DRE/lucratividade usam `competence_date`. Nunca inverter"*). A pergunta aqui é
    *"o dinheiro saiu da conta antes de ela abrir no e1p?"* — pergunta de caixa. `due_date` daria a
    contagem errada para toda conta paga em atraso ou adiantada, que é justamente o caso do mutirão
    (epic §7.2).

    **A borda é `<`, estrita, e ela combina com a guarda que já existe.** `_movements_sums` soma
    `posted_at > opening_date` e `_validate_posted_at` recusa `posted_at <= opening_date`: uma
    conta paga **exatamente na** `opening_date` fica de fora do saldo do mesmo jeito. Por isso a
    data que o aviso sugere é o **dia anterior** à conta paga mais antiga, e não o mesmo dia.

    Conta com `status='paid'` e `paid_at IS NULL` (legado) fica **fora**: sem a data do caixa não
    dá para afirmar de que lado da abertura ela cai, e chutar seria inventar.

    Comparação por **data de calendário em UTC** feita como limite de timestamp
    (`paid_at < meia-noite UTC de date_`) — mesmo padrão de `summary()` acima, dialeto-agnóstico e
    sem `::date` (que o SQLite dos testes não tem).

    Isolamento por RLS, sem filtro manual de `tenant_id` (Regra de Ouro nº 1).
    """
    corte = datetime.combine(date_, time.min, tzinfo=UTC)
    count, total, oldest, newest = db.execute(
        select(
            func.count(Payable.id),
            func.coalesce(func.sum(Payable.amount_cents), 0),
            func.min(Payable.paid_at),
            func.max(Payable.paid_at),
        ).where(
            Payable.status == STATUS_PAID,
            Payable.paid_at.is_not(None),
            Payable.paid_at < corte,
        )
    ).one()
    return {
        "count": int(count or 0),
        # Total PAGO — rotulado como tal na UI e jamais oferecido como saldo de abertura (AC4).
        "total_cents": int(total or 0),
        "oldest_paid_on": _as_utc_date(oldest),
        "newest_paid_on": _as_utc_date(newest),
    }


# ── A guarda de contagem dupla, do lado de quem SABE o que é uma conta a pagar (Story 8.17) ───


def probe_pagamento_duplicado(
    db: Session, *, amount_cents: int, posted_at: date
) -> bank_service.DuplicataCandidato | None:
    """*"Esta saída manual pode ser o mesmo dinheiro de uma conta a pagar que eu já conheço?"*

    Implementação concreta do `bank_service.DuplicataProbe`, registrada em `app/main.py`. **Ela vive
    aqui, e não em `bank`, por decisão de arquitetura ratificada** (§C-5): o gate estrutural da
    Story 8.9 proíbe `bank` de importar `payables`, e a dependência é de **negócio para banco,
    jamais a volta**. `bank` declara o contrato e não sabe quem o implementa; este módulo, que já
    importa `bank` desde a 8.12, é quem sabe consultar a obrigação — e é quem monta o DTO opaco.

    Por que o problema existe (design Onda 2 §7(b)): *"hoje o formulário manual é a porta primária e
    parece o jeito de registrar qualquer coisa — inclusive um pagamento. Um pagamento registrado nos
    dois lugares derruba o saldo **duas vezes**, e a divergência resultante parece um achado real. É
    o pior modo de falha desta onda."*

    **O critério — o mesmo do enriquecimento da Onda 4, um número e não dois:**
    - **valor absoluto EXATO** (`abs(amount_cents) == p.amount_cents`), sem tolerância percentual;
    - **±`DUPLICATA_JANELA_DIAS` dias** de `posted_at`, em aritmética de **data de calendário**
      (`posted_at` é `DATE`; nada aqui converte fuso — a lição do `CLAUDE.md` §6.0);
    - estados **`open`** e **`paid`**, com `due_date` **ou** a data de caixa (`paid_at`) na janela.
      Uma conta já paga é candidata legítima: o caso ruim é justamente o dono dar a baixa **e**
      lançar à mão o mesmo pagamento.

    ⚠️ **Desvio declarado da Story 8.17 AC5:** ela lista os estados `open|scheduled|paid`, mas
    **`scheduled` não existe ainda** — `payables.models.ALL_STATUSES` é `{open, paid, canceled}` e
    quem cria `scheduled` é a Story 8.14. Filtrar por um valor inexistente seria ruído; quando a
    8.14 chegar, `scheduled` entra em `_ESTADOS_CANDIDATOS` (uma entrada numa tupla) e o teste
    `test_estados_candidatos_existem_no_vocabulario` reprova se alguém esquecer. `canceled` fica
    **fora** de propósito: conta cancelada não é obrigação nenhuma, e casá-la produziria um 409 que
    o usuário não teria como resolver pelo caminho que a mensagem oferece.

    **Desempate** (AC5), quando há mais de um: **menor distância em dias** e, no empate, `due_date`
    **mais recente**. A mensagem é **uma** escolha e nunca uma lista — mesmo anti-ruído da banda de
    tolerância da conferência.

    **Isolamento:** roda na sessão do REQUEST, sob RLS, sem nenhum filtro manual de `tenant_id`
    (Regra de Ouro nº 1). Nunca abre sessão própria — isso seria escapar da GUC do tenant e a guarda
    passaria a enxergar conta a pagar de outro tenant (o cenário do IV5).

    **Uma query só** (não N+1): traz os candidatos da janela e classifica em Python — o conjunto é
    pequeno por construção (mesmo valor exato, 7 dias).
    """
    alvo = abs(amount_cents)
    inicio = posted_at - timedelta(days=bank_service.DUPLICATA_JANELA_DIAS)
    fim = posted_at + timedelta(days=bank_service.DUPLICATA_JANELA_DIAS)
    # Limites de TIMESTAMP para a data de caixa, em vez de `::date` — dialeto-agnóstico (o SQLite
    # dos testes não tem `::date`), mesmo padrão de `paid_before`/`summary` acima. `fim` é
    # inclusivo, por isso o teto é a meia-noite do dia SEGUINTE, com `<`.
    caixa_de = datetime.combine(inicio, time.min, tzinfo=UTC)
    caixa_ate = datetime.combine(fim + timedelta(days=1), time.min, tzinfo=UTC)

    candidatos = list(
        db.scalars(
            select(Payable).where(
                Payable.status.in_(_ESTADOS_CANDIDATOS),
                Payable.amount_cents == alvo,
                or_(
                    Payable.due_date.between(inicio, fim),
                    and_(
                        Payable.paid_at.is_not(None),
                        Payable.paid_at >= caixa_de,
                        Payable.paid_at < caixa_ate,
                    ),
                ),
            )
        ).all()
    )
    if not candidatos:
        return None

    def _distancia(p: Payable) -> int:
        """Dias até o movimento, pela data que estiver mais perto (vencimento ou caixa)."""
        dias = [abs((p.due_date - posted_at).days)]
        caixa = _as_utc_date(p.paid_at)
        if caixa is not None:
            dias.append(abs((caixa - posted_at).days))
        return min(dias)

    escolhido = min(candidatos, key=lambda p: (_distancia(p), -p.due_date.toordinal()))
    return bank_service.DuplicataCandidato(
        # Opaco do lado de lá: `bank` não sabe que isto é o id de uma conta a pagar. Quem traduz
        # para `{"payable_id": ...}` é a rota de `bank` (achado A-2 / ratificação §C-5.3).
        referencia_id=escolhido.id,
        # O que o usuário reconhece: o fornecedor, ou a descrição quando não houver fornecedor.
        descricao=escolhido.supplier or escolhido.description,
        valor_cents=escolhido.amount_cents,
        data=escolhido.due_date,
    )


def list_categories(db: Session) -> list[str]:
    rows = db.scalars(select(Payable.category).distinct().order_by(Payable.category)).all()
    return list(rows)


def promote_scheduled(
    db: Session, *, tenant_id: str, actor: str, today: date | None = None
) -> int:
    """`scheduled → paid` para toda conta cuja data de débito já chegou. Devolve quantas promoveu.

    **É a etapa 4 de `app.worker.run_sweep`** (Story 8.14 AC10) — e a varredura mora AQUI, não no
    worker: o worker **orquestra** (sessão por tenant, isolamento de falha, contador), o módulo
    **conhece a regra**. A Story 8.15 cria o irmão em `receivables` com esta mesma assinatura, e a
    etapa 4 passa a chamar os dois; uma quinta etapa seria a mesma regra em dois lugares.

    ⚠️ **O SALDO DERIVADO NÃO DEPENDE DESTE WORKER — e a story prova isso com teste** (F-D11). O
    movimento bancário nasceu com `posted_at` = a data agendada, e o saldo é **função da data**
    (`_movements_sums` filtra `posted_at <= until`): ele entra sozinho quando o dia chega, com o
    worker desligado, parado ou nem instalado. O que esta função move é **só o `status`** — para a
    Fila de Pagamentos e o resumo pararem de mostrar como "agendada" uma conta que já saiu.

    A mesma disciplina vale para a Projeção: o recorte do AC6 (`scheduled AND paid_at::date > hoje`)
    faz a aritmética depender da **data**, não do status materializado. Se este worker ficar uma
    semana parado, nenhum número fica errado — só um rótulo fica velho.

    **Não toca em mais nada**, e cada omissão é deliberada:
    - `paid_at` **não** é re-datado (ele é a data de caixa que o usuário informou; sobrescrevê-la
      por "hoje" inventaria um fato de caixa — Artigo IV);
    - `bank_account_id` / `bank_transaction_id` intactos (o movimento já está certo);
    - o evento da Agenda já está `done` desde a baixa (ver `apply_paid`);
    - `competence_date` **jamais** (caixa × competência não se invertem).

    **Idempotente:** rodar duas vezes seguidas promove zero na segunda — depois do primeiro passe
    nenhuma linha satisfaz `status == 'scheduled'`.

    `today` é **injetável** pelo mesmo motivo das Stories 8.5/8.6: um contador preso ao relógio da
    máquina não é testável. Isolamento por RLS, sem filtro manual de `tenant_id` (Regra de Ouro
    nº 1) — `tenant_id` fica na assinatura para a auditoria e para o teste `rls_e2e`.
    """
    today = today or _today()
    # Limite de TIMESTAMP em vez de `::date` (dialeto-agnóstico — o SQLite dos testes não tem
    # `::date`), mesmo padrão de `paid_before`/`probe_pagamento_duplicado`. "A data já chegou" é
    # `paid_at::date <= today`, ou seja, `paid_at < meia-noite UTC de today+1`.
    limite = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC)
    vencidas = list(
        db.scalars(
            select(Payable).where(
                Payable.status == STATUS_SCHEDULED,
                # Agendada sem data de caixa é estado inalcançável (a derivação exige `paid_on`);
                # a guarda existe porque `paid_at IS NULL` compararia como desconhecido em SQL e
                # a linha ficaria presa em `scheduled` para sempre, sem ninguém notar.
                Payable.paid_at.is_not(None),
                Payable.paid_at < limite,
            )
        ).all()
    )
    for p in vencidas:
        p.status = STATUS_PAID
        audit.record(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="payable.scheduled_promoted",
            target=p.id,
        )
    if vencidas:
        db.commit()
    return len(vencidas)


def summary(db: Session) -> dict:
    today = datetime.now(UTC).date()
    week_end = today + timedelta(days=7)
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    open_rows = list(db.scalars(select(Payable).where(Payable.status == STATUS_OPEN)).all())
    overdue = [p for p in open_rows if p.due_date < today]
    open_future = [p for p in open_rows if p.due_date >= today]

    paid_month = db.scalar(
        select(func.coalesce(func.sum(Payable.amount_cents), 0)).where(
            Payable.status == STATUS_PAID,
            Payable.paid_at >= datetime.combine(month_start, time.min, tzinfo=UTC),
        )
    ) or 0
    month_total = db.scalar(
        select(func.coalesce(func.sum(Payable.amount_cents), 0)).where(
            Payable.status != STATUS_CANCELED,
            Payable.due_date >= month_start,
            Payable.due_date < next_month,
        )
    ) or 0

    # [8.14] `scheduled_cents` — e ele **não se mistura com nada** (AC8).
    #
    # Fica FORA de `open_cents` (uma agendada não é "a pagar": já foi resolvida) e FORA de
    # `paid_month_cents` (o dinheiro não saiu). `overdue_cents` e `week_cents` derivam de
    # `open_rows`, então também não a veem — agendada não é atrasada nem vence nesta semana.
    #
    # ⚠️ **`month_cents` CONTINUA incluindo a agendada, e isso é preservado de propósito:** ele já
    # filtrava `status != canceled` e é o total do mês **por vencimento**, não por caixa. Excluí-la
    # mudaria a definição de um número que está em produção — e mudaria para pior, porque a conta
    # continua vencendo naquele mês independentemente de quando o débito foi agendado.
    scheduled_cents = db.scalar(
        select(func.coalesce(func.sum(Payable.amount_cents), 0)).where(
            Payable.status == STATUS_SCHEDULED
        )
    ) or 0

    return {
        "open_cents": sum(p.amount_cents for p in open_future),
        "overdue_cents": sum(p.amount_cents for p in overdue),
        "week_cents": sum(p.amount_cents for p in open_future if p.due_date < week_end),
        "month_cents": month_total,
        "paid_month_cents": paid_month,
        "scheduled_cents": int(scheduled_cents),
    }


def monthly_costs(db: Session) -> int:
    """Custo do mês para o Cockpit: total de contas (não canceladas) com vencimento no mês."""
    today = datetime.now(UTC).date()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return db.scalar(
        select(func.coalesce(func.sum(Payable.amount_cents), 0)).where(
            Payable.status != STATUS_CANCELED,
            Payable.due_date >= month_start,
            Payable.due_date < next_month,
        )
    ) or 0


def payment_queue(
    db: Session, *, tenant_id: str, today: date | None = None
) -> PaymentQueueOut:
    """Fila de Pagamentos (Story 5.9): Payables EM ABERTO ordenados por vencimento e agrupados em
    quatro baldes calculados NA LEITURA (nunca gravados — assim o balde de um item nunca fica
    desatualizado com a passagem do tempo, sem precisar de job/cron):

      - atrasados:        due_date <  hoje
      - hoje:             due_date == hoje
      - proximos_7_dias:  hoje    <  due_date <= hoje+7
      - proximos_30_dias: hoje+7  <  due_date <= hoje+30

    Vencimentos além de 30 dias ficam FORA da fila (não são "próximos"). Reaproveita `is_overdue()`
    como base do balde "atrasados". É uma VISÃO nova sobre o mesmo `Payable` de Contas a Pagar — a
    baixa é feita pelo `mark_paid` já existente, então marcar pago aqui reflete lá (mesmo registro).

    ── ⚠️ **[Story 8.14] O QUINTO BALDE: "agendadas". Esconder é erro; misturar também** (AC7)

      - agendadas: `status == 'scheduled'`, ordenadas pela **data do débito** (`paid_at`)

    As agendadas saem dos **quatro baldes de vencimento** porque a pergunta da Fila é *"o que eu
    preciso pagar?"* e uma conta agendada **já foi resolvida** — deixá-la em "Hoje" pediria ao dono
    uma ação que ele já tomou. Mas ela **não some da Fila**: some, o dono perde de vista uma saída
    certa de R$ 5.000 e a única tela que responde *"o que sai do meu caixa nos próximos 30 dias"*
    passa a mentir por omissão.

    O balde novo ordena pela **data do débito**, não por `due_date`: o dono quer saber *quando o
    dinheiro sai*, e numa agendada essas duas datas são diferentes por construção.

    Calculado **na leitura**, como os outros quatro — nenhum job, nenhum cron. O worker do AC10 é
    cosmética de status, não pré-requisito desta lista.

    Isolamento por RLS (sem filtro manual de tenant_id — Regra de Ouro nº 1); `tenant_id` fica na
    assinatura por consistência com os demais serviços do módulo e para o teste rls_e2e."""
    today = today or datetime.now(UTC).date()
    d7 = today + timedelta(days=7)
    d30 = today + timedelta(days=30)
    rows = list(
        db.scalars(
            select(Payable).where(Payable.status == STATUS_OPEN).order_by(Payable.due_date)
        ).all()
    )
    atrasados: list[Payable] = []
    hoje: list[Payable] = []
    prox7: list[Payable] = []
    prox30: list[Payable] = []
    for p in rows:
        if p.due_date < today:
            atrasados.append(p)
        elif p.due_date == today:
            hoje.append(p)
        elif p.due_date <= d7:  # today < due_date <= today+7
            prox7.append(p)
        elif p.due_date <= d30:  # today+7 < due_date <= today+30
            prox30.append(p)
        # due_date > today+30 → fora da fila (não é "próximo")

    # [8.14] Query própria: os cinco baldes não ordenam pela mesma coluna (`due_date` × `paid_at`),
    # exatamente como `receipts.list_candidates` já resolve com duas queries em vez de um ORDER BY
    # composto. **Sem janela de 30 dias aqui de propósito:** um débito agendado para daqui a 60 dias
    # é um compromisso assumido, não uma previsão — escondê-lo recriaria a omissão que o AC combate.
    agendadas = list(
        db.scalars(
            select(Payable)
            .where(Payable.status == STATUS_SCHEDULED)
            .order_by(Payable.paid_at)
        ).all()
    )

    summary = PaymentQueueSummary(
        atrasados_count=len(atrasados),
        atrasados_cents=sum(p.amount_cents for p in atrasados),
        hoje_count=len(hoje),
        hoje_cents=sum(p.amount_cents for p in hoje),
        proximos_7_dias_count=len(prox7),
        proximos_7_dias_cents=sum(p.amount_cents for p in prox7),
        proximos_30_dias_count=len(prox30),
        proximos_30_dias_cents=sum(p.amount_cents for p in prox30),
        agendadas_count=len(agendadas),
        agendadas_cents=sum(p.amount_cents for p in agendadas),
    )
    return PaymentQueueOut(
        atrasados=[payable_out(p, today) for p in atrasados],
        hoje=[payable_out(p, today) for p in hoje],
        proximos_7_dias=[payable_out(p, today) for p in prox7],
        proximos_30_dias=[payable_out(p, today) for p in prox30],
        agendadas=[payable_out(p, today) for p in agendadas],
        summary=summary,
    )
