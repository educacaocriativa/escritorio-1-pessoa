"""Rotas do módulo bancário: contas (8.2), movimentos (8.3) e saldos declarados (8.4).

Sem `DELETE` em conta nem em movimento — de propósito. Conta encerrada é **arquivada** (AC2 da 8.2)
e movimento errado é **editado ou ignorado** (AC6 da 8.3): o histórico é o produto, e apagar
destruiria justamente a evidência que torna o saldo conferível. O **checkpoint** é a única exceção
(`DELETE /bank/checkpoints/{id}`) — ele não tem histórico dependente; ver o porquê em
`service.delete_checkpoint`.

**Vocabulário voltado ao usuário:** *"saldo desta conta no fim do dia"*, dentro do menu
**"Contas & Saldos"** (design §5.4). O rótulo *"conciliação bancária"* é **proibido** pelo epic §2.1
— ele descreve um trabalho de contador, e este produto pede 5 segundos de confirmação por mês.

Toda rota usa `get_tenant_db` (RLS). Este módulo **não** entra na allowlist de
`tests/test_tenancy_guard.py`: não existe superfície pública aqui, e não deve passar a existir.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_BANCO
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.bank import reconciliation, service, transfers
from app.modules.bank.models import (
    BankAccount,
    BankBalanceCheckpoint,
    BankTransaction,
    BankTransfer,
)
from app.modules.bank.schemas import (
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
    BankBalanceOut,
    BankTransactionCreate,
    BankTransactionOut,
    BankTransactionUpdate,
    BankTransferCreate,
    BankTransferOut,
    CheckpointCreate,
    CheckpointOut,
    CicloDaConferenciaOut,
    CiclosDaConferenciaOut,
    ConferenciaContaOut,
    ConferenciaReportOut,
    ContaForaDaBandaOut,
    IgnoreRequest,
)
from app.modules.settings.service import hoje_do_tenant

router = APIRouter(prefix="/bank", tags=["bank"])

_guard = require_module("bank")


def _out(
    a: BankAccount,
    saldo_derivado_cents: int,
    agendado: service.AgendadoDaConta | None = None,
) -> BankAccountOut:
    """`BankAccount` → `BankAccountOut`, com o saldo corrente e o agendado (Story 8.14 AC13).

    `agendado=None` significa *"esta conta não tem movimento futuro"* e vira `(0, 0)` — nunca
    "não sei". O default existe só para a rota de **criação**, onde a conta acabou de nascer e
    não pode ter movimento nenhum, muito menos futuro; todas as demais passam o valor real.
    """
    agendado = agendado or service.AgendadoDaConta(saida_cents=0, entrada_cents=0)
    return BankAccountOut(
        id=a.id,
        name=a.name,
        kind=a.kind,
        institution=a.institution,
        institution_code=a.institution_code,
        branch=a.branch,
        number=a.number,
        holder_document=a.holder_document,
        pix_key=a.pix_key,
        opening_balance_cents=a.opening_balance_cents,
        opening_balance_is_known=a.opening_balance_is_known,
        opening_date=a.opening_date,
        is_primary=a.is_primary,
        archived_at=a.archived_at,
        saldo_derivado_cents=saldo_derivado_cents,
        # Constante do vocabulário do eixo A (`app.core.money_planes`) — nunca a string "banco"
        # escrita à mão. Todo saldo declara o plano de onde vem (Regra dos Planos §1.3c).
        # ⚠️ **Story 8.21 — a procedência é o que diz "não sei", nunca o número.** Conta cujo saldo
        # de abertura o dono NÃO declarou tem um derivado que parte de um `0` placeholder: o número
        # existe e continua visível (princípio da Onda 0 — suprimir a afirmação, nunca o número),
        # mas afirmá-lo como vindo do plano `banco` seria a mesma mentira da Projeção, uma camada
        # acima. Anular `saldo_derivado_cents` está fora de questão: seria propagar `None` pela
        # âncora da fórmula do §3.1, que é justamente o desenho que a @architect rejeitou.
        saldo_derivado_origem=service.origem_do_saldo_derivado(a),
        # Story 8.14 — o que já tem dia marcado e ainda não aconteceu. Os dois em MÓDULO, com o
        # irmão de procedência: nenhum saldo trafega sem plano declarado (Regra dos Planos §1.3c).
        agendado_saida_cents=agendado.saida_cents,
        agendado_entrada_cents=agendado.entrada_cents,
        agendado_origem=ORIGEM_BANCO,
        created_at=a.created_at,
    )


def _agendado_de(db: Session, acc: BankAccount) -> service.AgendadoDaConta:
    """O agendado de UMA conta — o helper das rotas de conta única (Story 8.14).

    Existe para que as quatro rotas de CRUD chamem **a mesma** função em lote que a lista chama,
    com uma conta só, em vez de nascer uma variante "para uma conta" que divergiria da outra.
    """
    return service.agendado_sums(db, accounts=[acc])[acc.id]


def _tx_out(t: BankTransaction) -> BankTransactionOut:
    return BankTransactionOut(
        id=t.id,
        bank_account_id=t.bank_account_id,
        posted_at=t.posted_at,
        amount_cents=t.amount_cents,
        raw_description=t.raw_description,
        user_description=t.user_description,
        # A regra de exibição resolvida UMA vez, aqui — a UI da 8.7 não a reimplementa.
        description=t.user_description or t.raw_description,
        counterparty_name=t.counterparty_name,
        counterparty_document=t.counterparty_document,
        operation_nature=t.operation_nature,
        source=t.source,
        # Story 8.18 — o pareamento das pernas irmãs. `None` em toda origem de perna única.
        transfer_id=t.transfer_id,
        status=t.status,
        ignored_reason=t.ignored_reason,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _cp_out(c: BankBalanceCheckpoint) -> CheckpointOut:
    return CheckpointOut(
        id=c.id,
        bank_account_id=c.bank_account_id,
        reference_date=c.reference_date,
        balance_cents=c.balance_cents,
        # Eixo A (plano) do saldo declarado — constante do vocabulário de `app.core.money_planes`,
        # nunca a string "banco" à mão. O saldo que o usuário leu no app do banco é plano 3, e é
        # por os dois números serem do MESMO plano que compará-los na 8.5 faz sentido.
        balance_origem=ORIGEM_BANCO,
        # Eixo B (porta de entrada) do mesmo saldo. Não se traduz no eixo A — design §1.3.1.
        origin=c.origin,
        created_by=c.created_by,
        created_at=c.created_at,
    )


def _err(e: service.BankError) -> HTTPException:
    """`detail` estruturado quando o erro é ACIONÁVEL; string em todo o resto.

    Mesmo contrato de `payables.router._err` — **um** formato de erro acionável no repositório, não
    dois: `{"detail": {"acao": ..., "mensagem": ...}}`, com `acao` e os dados **dentro** de
    `detail`. Dois formatos obrigariam a UI a saber, por rota, onde procurar o `acao`.
    """
    return HTTPException(status_code=e.status_code, detail=e.detail or str(e))


# ── O 409 acionável da guarda de contagem dupla (Story 8.17 AC5/AC8) ─────────────────────────
#
# ⚠️ **É AQUI que o id opaco vira vocabulário de negócio, e não no service.** `bank/service.py` não
# pode nomear a entidade do outro módulo (nem em nome de campo — achado A-2 da ratificação §C-5.3);
# a **rota** pode, porque o que ela monta é o payload HTTP que a tela consome. O
# `DuplicataCandidato` entra opaco e sai traduzido.
ACAO_BAIXAR_PAYABLE = "baixar_payable"


def _brl(cents: int) -> str:
    """Centavos → "R$ 1.234,56". Cópia deliberada da fórmula de `core/boleto._brl`.

    **Não** importamos aquela: `core/boleto` carrega o `fpdf` no import, e puxar um gerador de PDF
    para dentro do caminho de erro de um lançamento manual é peso sem motivo. A dívida de
    consolidar as ~9 formatações de moeda do repositório está registrada (`contas.ts`) e não é
    desta story.
    """
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _erro_de_duplicata(e: service.DuplicataDePagamento) -> HTTPException:
    """A **redação da escolha**, num lugar só (AC8: *"a mensagem é do backend"*).

    A tela mostra esta frase como veio e oferece as duas ações — *"dar baixa nessa conta"* (o
    movimento nasce sozinho, pela Regra da Origem) e *"é outro pagamento"* (reenvia com
    `confirmar_avulso=true`) —, **sem** pré-selecionar nenhuma e **sem** perder o que foi digitado:
    um 409 que apaga o formulário treina o usuário a marcar "é outro pagamento" sem ler.

    ⚠️ A frase diz *"com vencimento em"* e não *"vencendo em"* de propósito: o candidato pode estar
    **pago** (a janela de ±3 dias cobre os dois estados), e "vencendo" descreveria errado uma conta
    que já foi paga.
    """
    c = e.candidato
    quem = f" ({c.descricao})" if c.descricao else ""
    mensagem = (
        f"Existe uma conta a pagar de {_brl(c.valor_cents)} com vencimento em "
        f"{c.data.strftime('%d/%m')}{quem}. Quer dar baixa nela — o movimento nasce sozinho — ou "
        "este é outro pagamento?"
    )
    return HTTPException(
        status_code=e.status_code,
        detail={
            "acao": ACAO_BAIXAR_PAYABLE,
            # O id opaco do DTO, traduzido para o vocabulário de quem consome o payload.
            "payable_id": c.referencia_id,
            "mensagem": mensagem,
        },
    )


@router.get("/accounts", response_model=list[BankAccountOut])
def list_accounts(
    include_archived: bool = Query(default=False),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[BankAccountOut]:
    """Lista as contas com o saldo derivado de HOJE (uma data só para todas).

    Este é o consumidor legítimo de `derived_balances_as_of` (design §3.1.1): tela de lista, data
    comum. A conferência (Story 8.5) **não** pode usar essa função — ver a docstring dela.

    ⚠️ **Esta frase já estava escrita aqui antes de ser verdade.** Até a Story 8.10, `as_of=None`
    significava "sem limite superior" e a rota devolvia o saldo de *todo o histórico*, futuro
    incluído — a docstring dizia "HOJE" e o código não fazia isso. Hoje a chamada abaixo continua
    idêntica e passou a cumprir o que estava escrito, porque **o default mudou de significado**.
    Não "conserte" isto passando `SEM_CORTE`: esta tela é a superfície corrente por excelência.
    """
    accounts = service.list_accounts(db, include_archived=include_archived)
    # Duas leituras baratas (as contas + os saldos em lote) em vez de 1 + N: a partir da Story 8.3
    # cada `derived_balance` avulso custaria um `SUM` próprio, e é esse N+1 que a função em lote
    # existe para evitar.
    balances = service.derived_balances_as_of(db, include_archived=include_archived)
    # Story 8.14 — o agendado sai da MESMA lista, em duas agregacoes constantes (nunca uma por
    # conta): `agendado_sums` existe pelo mesmo motivo que `derived_balances_as_of`.
    agendados = service.agendado_sums(db, accounts=accounts)
    return [
        _out(a, balances.get(a.id, a.opening_balance_cents), agendados.get(a.id))
        for a in accounts
    ]


@router.post("/accounts", response_model=BankAccountOut, status_code=201)
def create_account(
    data: BankAccountCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    try:
        acc = service.create_account(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
        # Sem `agendado`: a conta nasce nesta chamada e nao pode ter movimento nenhum,
        # muito menos futuro. E o unico caminho em que o `(0, 0)` do default e um FATO.
        return _out(acc, service.derived_balance(db, bank_account_id=acc.id))
    except service.BankError as e:
        raise _err(e) from e


@router.get("/accounts/{account_id}", response_model=BankAccountOut)
def get_account(
    account_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    try:
        acc = service.get_account(db, account_id)
        return _out(
            acc, service.derived_balance(db, bank_account_id=acc.id), _agendado_de(db, acc)
        )
    except service.BankError as e:
        raise _err(e) from e


@router.patch("/accounts/{account_id}", response_model=BankAccountOut)
def update_account(
    account_id: str,
    data: BankAccountUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    try:
        acc = service.update_account(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
        return _out(
            acc, service.derived_balance(db, bank_account_id=acc.id), _agendado_de(db, acc)
        )
    except service.BankError as e:
        raise _err(e) from e


@router.post("/accounts/{account_id}/set-primary", response_model=BankAccountOut)
def set_primary(
    account_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    """Elege a conta principal — o destino do payout da Carteira (Onda 3).

    ⚠️ **O service existe desde a Story 8.7 e ficou sem porta até aqui.** Ele foi escrito
    explicitamente para este consumidor (*"senão o consumidor da Onda 6 (payout) escolheria a conta
    de destino no par ou ímpar"*, na docstring de `service.set_primary`), mas nenhuma rota o
    alcançava: o dono via o selo "principal" na tela e não tinha como atribuí-lo. A Onda 3 é a
    primeira que **depende** disso — o 409 do saque manda o dono definir a conta principal —, e por
    isso é ela que abre a porta. Sem esta rota aquela frase apontaria para uma ação inexistente.
    """
    try:
        acc = service.set_primary(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id
        )
        return _out(
            acc, service.derived_balance(db, bank_account_id=acc.id), _agendado_de(db, acc)
        )
    except service.BankError as e:
        raise _err(e) from e


@router.post("/accounts/{account_id}/archive", response_model=BankAccountOut)
def archive_account(
    account_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    try:
        acc = service.archive_account(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id
        )
        return _out(
            acc, service.derived_balance(db, bank_account_id=acc.id), _agendado_de(db, acc)
        )
    except service.BankError as e:
        raise _err(e) from e


@router.get("/accounts/{account_id}/balance", response_model=BankBalanceOut)
def account_balance(
    account_id: str,
    until: date | None = Query(default=None),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankBalanceOut:
    """Saldo derivado desta conta até `until` (inclusivo). **Sem `until` = até HOJE** (Story 8.10).

    `until` volta no payload: um saldo sem a data em que foi apurado é um número que não dá para
    conferir — e conferir é o produto (design §5.1). Desde a 8.10 esse campo **nunca mais vem
    `null`**, porque não existe mais resposta desta rota sem data de corte.

    ⚠️ **O que volta é a data EFETIVAMENTE usada, não o `until` cru da query.** As duas coisas
    divergem exatamente no caso em que o campo importa — a chamada sem `until` —, e devolver o cru
    ali faria o payload dizer *"não sei em que data isto foi apurado"* sobre um número que foi
    apurado numa data muito específica. É o defeito que o campo existe para impedir.

    O corte é resolvido **uma vez** e passado explicitamente para o saldo, de modo que o número e a
    data do mesmo payload venham do mesmo relógio (ver `service.resolve_until`).
    """
    corte = service.resolve_until(until, hoje_do_tenant(db))
    try:
        # Story 8.21 — a conta é carregada aqui (e não só o número) porque a PROCEDÊNCIA depende
        # dela: as duas rotas que expõem saldo derivado precisam dizer "não sei" pelo mesmo
        # critério, senão a mesma conta sairia `banco` numa e `indisponivel` na outra.
        acc = service.get_account(db, account_id)
        saldo = service.derived_balance(db, bank_account_id=account_id, until=corte)
    except service.BankError as e:
        raise _err(e) from e
    return BankBalanceOut(
        saldo_derivado_cents=saldo,
        saldo_derivado_origem=service.origem_do_saldo_derivado(acc),
        until=corte,
    )


# ── Movimentos (Story 8.3) ───────────────────────────────────────────────────────────────────


@router.post(
    "/accounts/{account_id}/transactions", response_model=BankTransactionOut, status_code=201
)
def create_transaction(
    account_id: str,
    data: BankTransactionCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    """Lança um movimento MANUAL nesta conta. A conta vem do path; `source` é fixado no service.

    **409 acionável** quando a saída manual casa com uma conta a pagar em valor e janela (Story
    8.17 AC5) — ver `_erro_de_duplicata`. Reenviar com `confirmar_avulso=true` passa.
    """
    try:
        tx = service.create_transaction(
            db,
            bank_account_id=account_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            data=data,
        )
    # ANTES do `except BankError` genérico: `DuplicataDePagamento` é subclasse dele, e a ordem
    # invertida faria o 409 acionável sair como string solta (a UI voltaria a adivinhar por
    # substring, que é como um contrato de erro deixa de ser contrato).
    except service.DuplicataDePagamento as e:
        raise _erro_de_duplicata(e) from e
    except service.BankError as e:
        raise _err(e) from e
    return _tx_out(tx)


@router.get("/transactions", response_model=list[BankTransactionOut])
def list_transactions(
    bank_account_id: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    # Repetível (`?status=unmatched&status=partial`): é o formato que a Story 8.5 precisa para
    # pedir "o que ainda não bateu" numa chamada só.
    status: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[BankTransactionOut]:
    """Movimentos do tenant, `posted_at` desc. `start`/`end` são inclusivos nas duas pontas."""
    try:
        rows = service.list_transactions(
            db,
            bank_account_id=bank_account_id,
            start=start,
            end=end,
            statuses=status,
            limit=limit,
            offset=offset,
        )
    except service.BankError as e:
        raise _err(e) from e
    return [_tx_out(t) for t in rows]


@router.get("/transactions/{transaction_id}", response_model=BankTransactionOut)
def get_transaction(
    transaction_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    try:
        return _tx_out(service.get_transaction(db, transaction_id))
    except service.BankError as e:
        raise _err(e) from e


@router.patch("/transactions/{transaction_id}", response_model=BankTransactionOut)
def update_transaction(
    transaction_id: str,
    data: BankTransactionUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    """Corrige data, valor ou rótulo. `raw_description` NÃO é editável (invariante do modelo)."""
    try:
        tx = service.update_transaction(
            db,
            transaction_id=transaction_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            data=data,
        )
    except service.BankError as e:
        raise _err(e) from e
    return _tx_out(tx)


@router.post("/transactions/{transaction_id}/ignore", response_model=BankTransactionOut)
def ignore_transaction(
    transaction_id: str,
    data: IgnoreRequest | None = None,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    """Tira do saldo sem apagar. Idempotente. Corpo opcional (`{"reason": "..."}`)."""
    try:
        tx = service.ignore_transaction(
            db,
            transaction_id=transaction_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            reason=(data.reason if data else ""),
        )
    except service.BankError as e:
        raise _err(e) from e
    return _tx_out(tx)


@router.post("/transactions/{transaction_id}/unignore", response_model=BankTransactionOut)
def unignore_transaction(
    transaction_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransactionOut:
    """Devolve ao saldo (`ignored` → `unmatched`). Idempotente."""
    try:
        tx = service.unignore_transaction(
            db, transaction_id=transaction_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.BankError as e:
        raise _err(e) from e
    return _tx_out(tx)


# ── Transferência entre contas próprias (Story 8.18) ─────────────────────────────────────────
#
# ⚠️ **O `DELETE` daqui é a SEGUNDA exceção do módulo** (a primeira é o checkpoint), e o porquê está
# em `transfers.delete_transfer`: sem ele, a única correção de uma transferência errada seria a
# contrapartida que o design §4.5 rejeita nominalmente. Ele não contradiz o "sem DELETE de
# movimento" do topo deste arquivo — as pernas continuam não sendo apagáveis **por elas mesmas**;
# quem as apaga é o lançamento que as gerou (Regra da Origem (c): o movimento é espelho).
#
# **Não existe `PATCH` de transferência**, e a ausência é decisão: corrigir é apagar e recriar, o
# que é barato aqui (duas linhas puramente sintéticas, nenhum evento de Agenda envolvido).


def _transfer_out(t: BankTransfer) -> BankTransferOut:
    return BankTransferOut(
        id=t.id,
        from_account_id=t.from_account_id,
        to_account_id=t.to_account_id,
        amount_cents=t.amount_cents,
        posted_at=t.posted_at,
        kind=t.kind,
        description=t.description,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.post("/transfers", response_model=BankTransferOut, status_code=201)
def create_transfer(
    data: BankTransferCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransferOut:
    """Registra que dinheiro foi de uma conta sua para outra.

    Gera **as duas pernas**, num commit só.

    **Não é receita nem despesa** (Regra da Neutralidade): a DRE, a Lucratividade e a Projeção não
    se movem por causa dela. O que muda são os saldos derivados das duas contas — e, quando o
    destino é uma conta de aplicação, o *"Disponível como caixa"* cai, porque o dinheiro deixou de
    ser caixa.

    As duas contas vêm no CORPO (e não no path) porque nenhuma das duas é "a conta desta rota": a
    operação é sobre o par. `posted_at` futuro é **422** — ver `transfers._validate_nao_futura`.
    """
    try:
        t = transfers.create_transfer(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    except service.BankError as e:
        raise _err(e) from e
    return _transfer_out(t)


@router.get("/transfers", response_model=list[BankTransferOut])
def list_transfers(
    bank_account_id: str | None = Query(
        default=None, description="Casa os DOIS lados: origem ou destino."
    ),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[BankTransferOut]:
    """Transferências do tenant, `posted_at` desc. `start`/`end` inclusivos nas duas pontas."""
    rows = transfers.list_transfers(
        db,
        bank_account_id=bank_account_id or None,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    return [_transfer_out(t) for t in rows]


@router.get("/transfers/{transfer_id}", response_model=BankTransferOut)
def get_transfer(
    transfer_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankTransferOut:
    try:
        return _transfer_out(transfers.get_transfer(db, transfer_id))
    except service.BankError as e:
        raise _err(e) from e


@router.delete("/transfers/{transfer_id}", status_code=204)
def delete_transfer(
    transfer_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    """Desfaz a transferência: o lançamento **e as duas pernas** somem juntos. Ver o service."""
    try:
        transfers.delete_transfer(
            db, transfer_id=transfer_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.BankError as e:
        raise _err(e) from e
    return Response(status_code=204)


# ── Saldos declarados (Story 8.4) ────────────────────────────────────────────────────────────


@router.post(
    "/accounts/{account_id}/checkpoints", response_model=CheckpointOut, status_code=201
)
def declare_balance(
    account_id: str,
    data: CheckpointCreate,
    response: Response,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CheckpointOut:
    """Informa o saldo desta conta **no fim** do dia `reference_date`.

    **201** quando é a primeira declaração daquele dia; **200** quando corrige uma existente — o
    mesmo dia declarado de novo **corrige**, nunca conflita (AC4): quem digitou o número errado
    precisa de um gesto para arrumar, não de um ciclo apagar→recriar.

    Este número **não** altera o saldo que o e1p calculou; ele é a verdade externa contra a qual
    esse saldo é medido. A comparação entre os dois é a Story 8.5.
    """
    try:
        cp, criado = service.declare_balance(
            db,
            bank_account_id=account_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            data=data,
        )
    except service.BankError as e:
        raise _err(e) from e
    if not criado:
        response.status_code = 200
    return _cp_out(cp)


@router.get("/accounts/{account_id}/checkpoints", response_model=list[CheckpointOut])
def list_checkpoints(
    account_id: str,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[CheckpointOut]:
    """Saldos já informados desta conta, do mais recente para o mais antigo.

    Só a lista dos fatos declarados — **sem** histórico ou gráfico de saldo (fora do escopo,
    epic §6) e **sem** divergência (é a Story 8.5, que tem a banda de tolerância e a decomposição
    por conta que um número solto aqui não teria).
    """
    try:
        # A conta é validada mesmo numa leitura: pedir os saldos de uma conta que não existe (ou é
        # de outro tenant) tem que ser 404, não uma lista vazia — vazio significaria "esta conta
        # nunca teve saldo informado", que é uma afirmação diferente e enganosa.
        service.get_account(db, account_id)
        rows = service.list_checkpoints(
            db, bank_account_id=account_id, start=start, end=end, limit=limit, offset=offset
        )
    except service.BankError as e:
        raise _err(e) from e
    return [_cp_out(c) for c in rows]


@router.get("/checkpoints/{checkpoint_id}", response_model=CheckpointOut)
def get_checkpoint(
    checkpoint_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CheckpointOut:
    try:
        return _cp_out(service.get_checkpoint(db, checkpoint_id))
    except service.BankError as e:
        raise _err(e) from e


@router.delete("/checkpoints/{checkpoint_id}", status_code=204)
def delete_checkpoint(
    checkpoint_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    """Remove uma declaração indevida. Único `DELETE` do módulo `bank`.

    O porquê de ele ser a exceção está em `service.delete_checkpoint`.
    """
    try:
        service.delete_checkpoint(
            db, checkpoint_id=checkpoint_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.BankError as e:
        raise _err(e) from e
    return Response(status_code=204)


# ── Conferência, bloco 1 (Story 8.5) ─────────────────────────────────────────────────────────


def _conferencia_conta_out(c: reconciliation.ConferenciaConta) -> ConferenciaContaOut:
    return ConferenciaContaOut(
        bank_account_id=c.bank_account_id,
        bank_account_name=c.bank_account_name,
        bank_account_kind=c.bank_account_kind,
        saldo_banco_cents=c.saldo_banco_cents,
        saldo_banco_origem=c.saldo_banco_origem,
        saldo_banco_fonte=c.saldo_banco_fonte,
        saldo_banco_data=c.saldo_banco_data,
        saldo_sistema_cents=c.saldo_sistema_cents,
        saldo_sistema_origem=c.saldo_sistema_origem,
        divergencia_cents=c.divergencia_cents,
        dentro_da_tolerancia=c.dentro_da_tolerancia,
        tolerancia_cents=c.tolerancia_cents,
        dias_desde_ultima_conferencia=c.dias_desde_ultima_conferencia,
        movimentos_ignorados=c.movimentos_ignorados,
        movimentos_no_periodo=c.movimentos_no_periodo,
        valor_movimentado_cents=c.valor_movimentado_cents,
        notes=c.notes,
    )


def _conferencia_out(r: reconciliation.ConferenciaReport) -> ConferenciaReportOut:
    """Dataclass → schema, campo a campo (padrão de `_projection_out`).

    Sem `model_validate(dataclass)` de propósito: a conversão explícita é o lugar onde um campo novo
    do serviço aparece como erro de compilação mental em vez de sumir em silêncio do contrato HTTP —
    e num relatório de saldos "sumir em silêncio" é justamente como um campo `*_origem` deixaria de
    ser entregue sem ninguém perceber (Regra dos Planos §1.3c).
    """
    return ConferenciaReportOut(
        start=r.start,
        end=r.end,
        contas=[_conferencia_conta_out(c) for c in r.contas],
        total_divergencia_cents=r.total_divergencia_cents,
        contas_avaliadas=r.contas_avaliadas,
        contas_sem_checkpoint=r.contas_sem_checkpoint,
        contas_fora_da_banda=[
            ContaForaDaBandaOut(
                bank_account_id=f.bank_account_id,
                bank_account_name=f.bank_account_name,
                divergencia_cents=f.divergencia_cents,
                tolerancia_cents=f.tolerancia_cents,
            )
            for f in r.contas_fora_da_banda
        ],
        notes=r.notes,
        # Story 8.16 — os termos da pré-condição do gate. ANOTAM, nunca subtraem: nenhum campo de
        # divergência acima é recalculado por causa deles.
        lancamentos_sem_conta_informada=r.lancamentos_sem_conta_informada,
        valor_sem_conta_informada_cents=r.valor_sem_conta_informada_cents,
        rendimentos_sem_perna_bancaria=r.rendimentos_sem_perna_bancaria,
        valor_rendimentos_sem_perna_cents=r.valor_rendimentos_sem_perna_cents,
    )


@router.get("/reconciliation-report", response_model=ConferenciaReportOut)
def reconciliation_report(
    start: date = Query(..., description="Início do período (data de calendário), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de calendário), YYYY-MM-DD"),
    bank_account_id: str | None = Query(
        default=None, description="Confere só esta conta. Omitir = todas as contas ativas."
    ),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ConferenciaReportOut:
    """*"Meu saldo bate?"* — a divergência entre o banco e o e1p, **por conta**. SOMENTE LEITURA.

    Não escreve nada: nenhum saldo é declarado, nenhum movimento é criado, editado ou baixado,
    nenhum `status` é recalculado. Chamar esta rota duas vezes deixa o banco de dados idêntico.

    **A comparação é na data do CHECKPOINT de cada conta**, não em `end` e não hoje: para cada uma,
    o saldo que o banco atesta (o último saldo informado dentro do período) é comparado com o saldo
    derivado **naquela mesma data**. Comparar saldos apurados em datas diferentes acusaria como furo
    tudo o que aconteceu no meio — e por isso contas diferentes podem ter datas de referência
    diferentes no mesmo relatório.

    **`indisponivel` é resposta legítima, não um erro, e tem DOIS motivos** (Story 8.20): a conta
    não teve saldo informado no período, **ou** o saldo informado é da própria data de abertura da
    conta, em que a comparação seria tautológica — os dois vêm com
    `saldo_banco_origem='indisponivel'` e `divergencia_cents=null` (o discriminador é
    `saldo_banco_data`, preenchido só no segundo, e a nota **da conta** diz qual é). O e1p **diz que
    não sabe** em vez de comparar contra zero, que inventaria uma divergência inteira com cara de
    fato.

    **O consolidado nunca vem sozinho:** `total_divergencia_cents` cobre só as contas avaliáveis e
    viaja sempre com `contas` e `contas_fora_da_banda` (epic §3.2).

    **Os contadores da pré-condição do gate ANOTAM, nunca subtraem** (Story 8.16):
    `lancamentos_sem_conta_informada` e `rendimentos_sem_perna_bancaria` dizem o que o e1p sabe que
    ainda **não** virou movimento bancário no período, e `notes` traz a frase de cada termo não-zero
    nomeando a onda que o fecha. Nenhum deles altera `divergencia_cents`, `tolerancia_cents`,
    `dentro_da_tolerancia`, `total_divergencia_cents` ou `contas_fora_da_banda`.

    `end < start` → 422. `bank_account_id` inexistente ou de outro tenant → 404 fail-closed.
    """
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    # `?bank_account_id=` (string vazia) == "todas as contas": normaliza para None em vez de virar
    # um filtro que casa zero contas — mesmo tratamento de `cost_center_id` no
    # `financial_intelligence/router.py`.
    bank_account_id = bank_account_id or None
    try:
        report = reconciliation.reconciliation_report(
            db, start=start, end=end, bank_account_id=bank_account_id
        )
    except service.BankError as e:
        raise _err(e) from e
    return _conferencia_out(report)


@router.get("/reconciliation-cycles", response_model=CiclosDaConferenciaOut)
def reconciliation_cycles(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CiclosDaConferenciaOut:
    """*"Este número já vale?"* — um mês por linha, com o volume que produziu cada um. READ-ONLY.

    A rota acima responde *"está batendo?"*. Esta responde a outra pergunta, que decide as ondas
    seguintes do épico: se o número daquele mês pode ser **lido** como medida do furo, ou se ele
    ainda mede a própria incompletude do sistema.

    **Sem parâmetro de período, de propósito.** O ciclo é o mês de calendário no fuso do tenant, e
    fronteira escolhível permitiria selecionar a janela que produz o número desejado — a régua
    andando junto com o que ela mede, que é o que a banda fixa da Regra 7 existe para impedir.

    **Derivado na leitura, nunca gravado.** Roda o relatório de conferência uma vez por mês. Um
    lançamento retroativo muda **legitimamente** a leitura de um ciclo passado; um valor congelado
    passaria a discordar do recalculado, e seriam duas verdades sobre a mesma divergência.

    **Sem conta bancária cadastrada, `ciclos` vem vazio** — não com um ciclo corrente de conteúdo
    nulo, que seria a condição (a) da legibilidade violada pela porta dos fundos.

    ⚠️ **ANOTA, NUNCA SUBTRAI:** nada aqui recalcula divergência, tolerância ou banda.
    """
    return CiclosDaConferenciaOut(
        ciclos=[
            CicloDaConferenciaOut(
                ano_mes=c.ano_mes,
                start=c.start,
                end=c.end,
                fechado=c.fechado,
                legivel=c.legivel,
                motivo_nao_legivel=c.motivo_nao_legivel,
                total_divergencia_cents=c.total_divergencia_cents,
                contas_avaliadas=c.contas_avaliadas,
                contas_sem_checkpoint=c.contas_sem_checkpoint,
                movimentos_no_periodo=c.movimentos_no_periodo,
                valor_movimentado_cents=c.valor_movimentado_cents,
            )
            for c in reconciliation.ciclos_da_conferencia(db)
        ]
    )
