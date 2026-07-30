"""Regras da conta bancária: CRUD + conta primária + **saldo derivado** (Story 8.2).

**Isolamento:** por RLS, e só por RLS — nenhuma query aqui filtra `tenant_id` à mão (Regra de Ouro
nº 1 do `CLAUDE.md`: defesa-em-profundidade foi considerada e REJEITADA para não criar o padrão
"algumas queries filtram, outras não", onde esquecer uma vira vazamento). Cross-tenant cai em
`db.get(...) is None` → 404 fail-closed, nunca 403 (403 confirmaria a existência da linha).

**Sem FK dura** entre entidades financeiras (padrão do projeto: `charges.client_id`,
`payables.cost_center_id`): a referência é solta e a integridade é validada no service. Quando a
Story 8.3 criar `bank_transactions.bank_account_id`, ela valida a conta chamando `get_account` —
não declara `ForeignKey`.

**O saldo é derivado, nunca materializado** (design §3.1). Não existe coluna de saldo em
`bank_accounts` e não pode passar a existir; ver o aviso (b) na docstring de `models.py`.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.bank.models import (
    KIND_INVESTMENT,
    KIND_PLATFORM_WALLET,
    KINDS,
    BankAccount,
)
from app.modules.bank.schemas import BankAccountCreate, BankAccountUpdate

_DUPLICATE_MSG = (
    "Já existe uma conta com esta agência e número neste banco. "
    "Edite a conta existente em vez de cadastrar de novo — duas contas para o mesmo número "
    "produziriam divergência crônica na conferência."
)


class BankError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _today() -> date:
    """Hoje em UTC — mesma âncora do Cockpit e da Projeção (`datetime.now(UTC).date()`).

    Para o Brasil (UTC−3) a data UTC nunca fica ATRÁS da local, então a guarda de "data futura"
    é, no pior caso, mais permissiva por algumas horas — nunca bloqueia o usuário de informar o
    dia de hoje, que é o erro que doeria. A dívida geral de fuso por tenant está registrada no
    `CLAUDE.md` §6.1 e não é resolvida aqui.
    """
    return datetime.now(UTC).date()


def _validate_kind(kind: str) -> str:
    if kind == KIND_PLATFORM_WALLET:
        raise BankError(
            "A Carteira e1p não pode ser cadastrada como conta bancária. O saldo da Carteira é "
            "derivado das suas vendas (com split), não de um extrato — somar os dois como se "
            "fossem a mesma coisa é justamente o erro que este módulo existe para impedir.",
            422,
        )
    if kind not in KINDS:
        raise BankError(
            f"Tipo de conta inválido: '{kind}'. Use um de: {', '.join(KINDS)}.", 422
        )
    return kind


def _validate_opening_date(opening_date: date) -> date:
    if opening_date > _today():
        raise BankError(
            "A data de abertura não pode ser futura — ela é o dia em que você conferiu o saldo "
            "no app do banco.",
            422,
        )
    return opening_date


# ── Leitura ──────────────────────────────────────────────────────────────────────────────────


def get_account(db: Session, account_id: str) -> BankAccount:
    acc = db.get(BankAccount, account_id)
    if acc is None:
        # Cross-tenant também cai aqui: a RLS esconde a linha → db.get devolve None → 404
        # (fail-closed, mesmo padrão do resto do projeto: 404, não 403).
        raise BankError("Conta bancária não encontrada", 404)
    return acc


def list_accounts(db: Session, *, include_archived: bool = False) -> list[BankAccount]:
    """Contas do tenant, ordenadas por nome. Arquivadas ficam FORA por default.

    Mesmo contrato de `chart_of_accounts.list_accounts`: a conta arquivada continua existindo (o
    histórico de movimentos depende dela), mas some das superfícies do dia a dia.
    """
    stmt = select(BankAccount).order_by(BankAccount.name)
    if not include_archived:
        stmt = stmt.where(BankAccount.archived_at.is_(None))
    return list(db.scalars(stmt).all())


def primary_account(db: Session) -> BankAccount | None:
    """A conta primária ATIVA do tenant, se houver (a Onda 6 — payout — consome isto).

    Devolve `None` de forma explícita quando não há: arquivar a primária **não** elege sucessora
    em silêncio (AC7). Escolher a conta de destino do dinheiro do usuário sem ele pedir é o tipo
    de "ajuda" que só se descobre quando o dinheiro já foi para o lugar errado.
    """
    stmt = (
        select(BankAccount)
        .where(BankAccount.is_primary.is_(True), BankAccount.archived_at.is_(None))
        .order_by(BankAccount.name)
    )
    return db.scalars(stmt).first()


# ── Saldo derivado (design §3.1 / assinaturas canônicas §3.1.1) ──────────────────────────────


def _movements_sum(db: Session, *, bank_account_id: str, until: date | None = None) -> int:
    """PONTO DE EXTENSÃO da Story 8.3 — hoje devolve sempre 0.

    Nesta story `bank_transactions` **não existe**, então o saldo derivado é exatamente o saldo de
    abertura. A Story 8.3 substitui o corpo desta função (e só dela) por:

        SUM(bank_transactions.amount_cents)
        WHERE bank_account_id = :bank_account_id
          AND posted_at > <opening_date da conta>   -- movimento anterior já está no saldo de
                                                    -- abertura; contá-lo dobraria o valor
          AND (:until IS NULL OR posted_at <= :until)   -- `until` é DATE e INCLUSIVO
          AND status <> 'ignored'

    **A assinatura PÚBLICA (`derived_balance`) não muda** — é isso que permite que 8.5/8.7/8.8
    sejam escritas contra o contrato antes de existir um único movimento. Esta função é privada;
    a 8.3 pode acrescentar parâmetros internos (ex.: receber o `opening_date` já carregado para
    evitar uma releitura) à vontade.
    """
    return 0


def _movements_sums(
    db: Session, *, bank_account_ids: Sequence[str], until: date | None = None
) -> dict[str, int]:
    """Versão em LOTE de `_movements_sum` — hoje devolve `{}` (nenhum movimento existe).

    Story 8.3: um `GROUP BY bank_account_id` com as mesmas condições de `_movements_sum`, numa
    única query. É o que dá sentido ao "uma passada" de `derived_balances_as_of`. Conta sem
    movimento simplesmente não aparece no dicionário (o chamador usa `.get(id, 0)`).
    """
    return {}


def derived_balance(db: Session, *, bank_account_id: str, until: date | None = None) -> int:
    """Saldo derivado de UMA conta numa data (design §3.1). Centavos.

        saldo = opening_balance_cents + SUM(movimentos até `until`)

    `until` é um `date` (nunca `datetime`) e é **INCLUSIVO**; `None` = todo o histórico conhecido.
    Enquanto a Story 8.3 não existir, o resultado é o próprio `opening_balance_cents`.

    Esta é a **única** implementação da fórmula da §3.1 no repositório inteiro. Uma segunda torna a
    Regra dos Planos §1.3a inauditável — se aparecer, o `dedup-checker` deve reprovar.

    Conta inexistente (ou de outro tenant, escondida pela RLS) → `BankError` 404.
    """
    acc = get_account(db, bank_account_id)
    return acc.opening_balance_cents + _movements_sum(
        db, bank_account_id=acc.id, until=until
    )


def derived_balances_as_of(
    db: Session, *, as_of: date | None = None, include_archived: bool = False
) -> dict[str, int]:
    """Saldo de TODAS as contas numa **data comum** (`as_of`), em uma passada. `{id: centavos}`.

    ⛔ **PROIBIDA na conferência (design §5.1 / Story 8.5).** Lá cada conta tem a **sua própria**
    data de referência — o `reference_date` do checkpoint daquela conta —, e um `as_of` comum
    compararia o saldo do banco de uma data com o saldo do sistema de outra, que é o erro clássico
    desta classe de relatório e que o service da 8.5 deve **recusar**. A conferência usa laço de
    `derived_balance` com o `until` de cada conta; o custo é N queries sob índice para uma empresa
    de 1 pessoa com um punhado de contas, ou seja, ruído.

    ✅ **Use para:** a tela de lista "Contas & Saldos" (Story 8.7), onde a data é uma só porque o
    usuário quer o saldo de hoje de tudo; e como base de `active_balance_total` (Story 8.8).

    O nome carrega o `as_of` de propósito (ratificação D-4): a versão anterior se chamava
    `derived_balances` e diferia de `derived_balance` por **um `s` final**, sendo a função errada
    para o trabalho da conferência. O sintoma de errar era uma divergência **falsa, silenciosa e
    plausível** — o relatório não quebraria, mentiria um número.
    """
    accounts = list_accounts(db, include_archived=include_archived)
    return _balances_for(db, accounts, until=as_of)


def active_balance_total(
    db: Session,
    *,
    until: date | None = None,
    exclude_kinds: Iterable[str] = (KIND_INVESTMENT,),
) -> int:
    """Σ dos saldos derivados das contas ATIVAS, excluindo `investment` por default. Centavos.

    É a parcela "no banco" que a Story 8.8 soma ao `available_cents` da Carteira sob
    `ORIGEM_MISTO` — somando sim, mas com as duas parcelas **rotuladas** na UI: somar é correto
    (é tudo dinheiro do usuário), esconder a composição nunca é.

    Aplicação (`kind='investment'`) fica de fora por default porque dinheiro aplicado não é caixa
    disponível para pagar a conta de amanhã (design §6.1). Contas arquivadas nunca entram.
    """
    excluded = set(exclude_kinds)
    accounts = [a for a in list_accounts(db) if a.kind not in excluded]
    return sum(_balances_for(db, accounts, until=until).values())


def _balances_for(
    db: Session, accounts: Sequence[BankAccount], *, until: date | None
) -> dict[str, int]:
    """`{id: saldo}` para um conjunto já carregado de contas — UMA consulta de movimentos."""
    sums = _movements_sums(db, bank_account_ids=[a.id for a in accounts], until=until)
    return {a.id: a.opening_balance_cents + sums.get(a.id, 0) for a in accounts}


# ── Escrita ──────────────────────────────────────────────────────────────────────────────────


def _clear_other_primaries(db: Session, *, keep_id: str | None) -> None:
    """Desmarca `is_primary` de todas as contas do tenant, exceto `keep_id`. Sem commit.

    Percorre as linhas em Python (e não um `UPDATE ... WHERE`) porque são poucas por tenant e
    assim as instâncias já carregadas na sessão ficam consistentes — evitando o clássico "o objeto
    na memória diz uma coisa, o banco diz outra" logo antes de um `refresh`.
    """
    stmt = select(BankAccount).where(BankAccount.is_primary.is_(True))
    for other in db.scalars(stmt).all():
        if other.id != keep_id:
            other.is_primary = False


def create_account(
    db: Session, *, tenant_id: str, actor: str, data: BankAccountCreate
) -> BankAccount:
    """Cria a conta. A PRIMEIRA conta ativa do tenant nasce primária (AC7).

    `opening_balance_cents` pode ser NEGATIVO (conta no limite / cheque especial) — não há guarda
    de sinal aqui de propósito.
    """
    kind = _validate_kind(data.kind)
    opening_date = _validate_opening_date(data.opening_date)

    acc = BankAccount(
        tenant_id=tenant_id,
        name=data.name,
        kind=kind,
        institution=data.institution,
        institution_code=data.institution_code,
        branch=data.branch,
        number=data.number,
        holder_document=data.holder_document,
        pix_key=data.pix_key,
        opening_balance_cents=data.opening_balance_cents,
        opening_date=opening_date,
        # Sem primária ativa (tenant novo, ou a anterior foi arquivada) → esta assume.
        is_primary=primary_account(db) is None,
    )
    db.add(acc)
    try:
        # ⚠️ `flush` ANTES do `audit.record`: `id` tem default Python-side (`_uuid`), que só é
        # aplicado no INSERT — sem o flush, `acc.id` ainda é None e a entrada de auditoria nasceria
        # com `target=''`, ou seja, um rastro que não aponta para nada. (O mesmo padrão em
        # `chart_of_accounts.create_account` grava o target vazio; achado registrado, correção lá
        # é fora do escopo desta story.)
        db.flush()
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="bank.account.create", target=acc.id
        )
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BankError(_DUPLICATE_MSG, 409) from e
    db.refresh(acc)
    return acc


def update_account(
    db: Session, *, account_id: str, tenant_id: str, actor: str, data: BankAccountUpdate
) -> BankAccount:
    """Edita a conta. `is_primary=True` troca a primária na MESMA transação (AC7).

    `archived_at` não é editável por aqui (arquivar tem rota própria, com auditoria própria).
    """
    acc = get_account(db, account_id)

    if data.kind is not None:
        acc.kind = _validate_kind(data.kind)
    if data.opening_date is not None:
        acc.opening_date = _validate_opening_date(data.opening_date)
    for field in (
        "name",
        "institution",
        "institution_code",
        "branch",
        "number",
        "holder_document",
        "pix_key",
        "opening_balance_cents",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(acc, field, value)

    if data.is_primary is not None:
        if data.is_primary:
            if acc.archived_at is not None:
                raise BankError("Conta arquivada não pode ser a conta principal", 422)
            _clear_other_primaries(db, keep_id=acc.id)
            acc.is_primary = True
        else:
            # Desmarcar explicitamente é permitido: "nenhuma conta primária" é um estado válido
            # (é onde o tenant fica ao arquivar a primária) e não elegemos sucessora em silêncio.
            acc.is_primary = False

    audit.record(db, tenant_id=tenant_id, actor=actor, action="bank.account.update", target=acc.id)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BankError(_DUPLICATE_MSG, 409) from e
    db.refresh(acc)
    return acc


def set_primary(db: Session, *, account_id: str, tenant_id: str, actor: str) -> BankAccount:
    """Marca esta conta como primária e desmarca as demais — **num commit só**.

    Se a troca fosse em dois commits, uma falha no meio deixaria o tenant com duas primárias (ou
    nenhuma), e o consumidor da Onda 6 (payout) escolheria a conta de destino no par ou ímpar.
    """
    acc = get_account(db, account_id)
    if acc.archived_at is not None:
        raise BankError("Conta arquivada não pode ser a conta principal", 422)
    _clear_other_primaries(db, keep_id=acc.id)
    acc.is_primary = True
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.account.set_primary", target=acc.id
    )
    db.commit()
    db.refresh(acc)
    return acc


def archive_account(
    db: Session, *, account_id: str, tenant_id: str, actor: str
) -> BankAccount:
    """Arquiva (lógico): seta `archived_at`, NÃO deleta a linha — conta encerrada não pode levar o
    histórico de movimentos junto (design §2.1). Idempotente: rearquivar mantém o carimbo original.

    Se era a primária, o tenant fica **sem** primária — nenhuma sucessora é eleita em silêncio.
    """
    acc = get_account(db, account_id)
    if acc.archived_at is None:
        acc.archived_at = datetime.now(UTC)
        acc.is_primary = False
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="bank.account.archive", target=acc.id
        )
        db.commit()
        db.refresh(acc)
    return acc
