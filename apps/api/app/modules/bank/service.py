"""Regras do módulo bancário: contas + conta primária + **saldo derivado** (Story 8.2) e os
**movimentos** que fazem esse saldo se mover (Story 8.3).

**Isolamento:** por RLS, e só por RLS — nenhuma query aqui filtra `tenant_id` à mão (Regra de Ouro
nº 1 do `CLAUDE.md`: defesa-em-profundidade foi considerada e REJEITADA para não criar o padrão
"algumas queries filtram, outras não", onde esquecer uma vira vazamento). Cross-tenant cai em
`db.get(...) is None` → 404 fail-closed, nunca 403 (403 confirmaria a existência da linha).

**Sem FK dura** entre entidades financeiras (padrão do projeto: `charges.client_id`,
`payables.cost_center_id`): a referência é solta e a integridade é validada no service —
`bank_transactions.bank_account_id` é validada chamando `get_account`, sem `ForeignKey`.

**O saldo é derivado, nunca materializado** (design §3.1). Não existe coluna de saldo em
`bank_accounts` e não pode passar a existir; ver o aviso (b) na docstring de `models.py`. A soma
dos movimentos tem **uma** implementação (`_movements_sums`) e é ela que aplica o
`status <> 'ignored'` — quem consome o saldo não refiltra.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.db.base import _uuid
from app.modules.bank.models import (
    KIND_INVESTMENT,
    KIND_PLATFORM_WALLET,
    KINDS,
    SOURCE_MANUAL,
    STATUS_IGNORED,
    STATUS_UNMATCHED,
    STATUSES,
    BankAccount,
    BankTransaction,
)
from app.modules.bank.schemas import (
    BankAccountCreate,
    BankAccountUpdate,
    BankTransactionCreate,
    BankTransactionUpdate,
)

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


def _movements_sums(
    db: Session, *, accounts: Sequence[BankAccount], until: date | None = None
) -> dict[str, int]:
    """Σ dos movimentos de cada conta, em **UMA** query. `{bank_account_id: centavos}`.

    Esta é a **única** implementação da soma de movimentos do repositório (Story 8.3 preencheu o
    ponto de extensão que a 8.2 deixou). `_movements_sum` delega para cá em vez de repetir o
    `WHERE`: duas cópias da mesma fórmula divergiriam no dia em que uma delas ganhasse uma condição
    — e o sintoma seria um saldo que muda conforme a tela que o pede.

        SUM(amount_cents)
        WHERE bank_account_id = :conta
          AND posted_at > <opening_date DAQUELA conta>  -- movimento anterior já está DENTRO do
                                                        -- opening_balance_cents; contá-lo de novo
                                                        -- dobraria o valor
          AND (:until IS NULL OR posted_at <= :until)    -- `until` é DATE e INCLUSIVO
          AND status <> 'ignored'                        -- AC5: ignorar TIRA do saldo

    ⚠️ **O filtro `status <> 'ignored'` mora AQUI, dentro do saldo** — é contrato para as Stories
    8.5 e 8.7: quem consome o saldo derivado **não** refiltra. Ter o filtro em dois lugares é ter
    dois lugares para divergirem.

    A cláusula de conta é um `OR` de pares `(conta, opening_date)` em vez de um `IN (...)` porque
    cada conta tem a **sua** data de corte. Ainda é uma query só — a alternativa (`GROUP BY` com
    `IN` e filtro de data em Python) leria linhas que o índice já sabe descartar, e a alternativa
    "uma query por conta" seria o N+1 que `derived_balances_as_of` existe para evitar.

    Conta sem movimento simplesmente não aparece no dicionário; o chamador usa `.get(id, 0)`.
    """
    if not accounts:
        return {}

    escopo = or_(
        *[
            and_(
                BankTransaction.bank_account_id == a.id,
                BankTransaction.posted_at > a.opening_date,
            )
            for a in accounts
        ]
    )
    stmt = (
        select(
            BankTransaction.bank_account_id,
            func.coalesce(func.sum(BankTransaction.amount_cents), 0),
        )
        .where(escopo, BankTransaction.status != STATUS_IGNORED)
        .group_by(BankTransaction.bank_account_id)
    )
    if until is not None:
        stmt = stmt.where(BankTransaction.posted_at <= until)
    return {account_id: int(total or 0) for account_id, total in db.execute(stmt).all()}


def _movements_sum(db: Session, *, account: BankAccount, until: date | None = None) -> int:
    """Σ dos movimentos de UMA conta. Delega para `_movements_sums` — ver a fórmula lá.

    Recebe a `BankAccount` já carregada (e não o id) porque a soma precisa do `opening_date` dela;
    a assinatura é privada e a 8.2 explicitamente autorizou mudá-la para evitar a releitura.
    """
    return _movements_sums(db, accounts=[account], until=until).get(account.id, 0)


def derived_balance(db: Session, *, bank_account_id: str, until: date | None = None) -> int:
    """Saldo derivado de UMA conta numa data (design §3.1). Centavos.

        saldo = opening_balance_cents + SUM(movimentos até `until`)

    `until` é um `date` (nunca `datetime`) e é **INCLUSIVO**. `until=None` significa **sem limite
    superior**: o saldo atual completo, incluindo movimento com data futura se algum existir (hoje
    o service recusa lançar no futuro, mas o saldo não depende dessa guarda para estar correto).
    A conferência da Story 8.5 **sempre** passa `until` = a data de referência do checkpoint, porque
    comparar saldos apurados em datas diferentes é o erro que o design §5.1 manda recusar.

    Movimentos com `status='ignored'` ficam **de fora** — o filtro é aplicado aqui dentro e quem
    consome não refiltra (ver `_movements_sums`).

    Esta é a **única** implementação da fórmula da §3.1 no repositório inteiro. Uma segunda torna a
    Regra dos Planos §1.3a inauditável — se aparecer, o `dedup-checker` deve reprovar.

    Conta inexistente (ou de outro tenant, escondida pela RLS) → `BankError` 404.
    """
    acc = get_account(db, bank_account_id)
    return acc.opening_balance_cents + _movements_sum(db, account=acc, until=until)


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
    """`{id: saldo}` para um conjunto já carregado de contas — UMA consulta de movimentos.

    Conta **sem movimento nenhum** aparece no dicionário com o saldo de abertura: o `GROUP BY` de
    `_movements_sums` sozinho a omitiria (erro clássico), e é o laço sobre `accounts` — não sobre o
    resultado da query — que garante isso.
    """
    sums = _movements_sums(db, accounts=accounts, until=until)
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


# ── Movimento bancário (Story 8.3) ───────────────────────────────────────────────────────────
#
# **Lançar, editar e ignorar. Nada além disso — e nenhum `DELETE`** (AC6): o par editar/ignorar já
# cobre o erro de digitação e o lançamento indevido, e apagar destruiria a auditoria, que é o
# produto. Um movimento ignorado sai do saldo mas continua visível, com o motivo do lado.


def _manual_dedup_hash(bank_account_id: str, transaction_id: str) -> str:
    """`sha256("{conta}|manual|{id}")` — a variante de `dedup_hash` do lançamento MANUAL (§4.4).

    A coluna é `NOT NULL` e carrega a constraint única `(tenant_id, bank_account_id, dedup_hash)`,
    então a primeira linha inserida já precisa de um valor — mesmo numa story que, por escopo, não
    faz deduplicação nenhuma (epic §6: *"Não inclui: … dedup por `fitid`/`dedup_hash`"*).

    **Por que chavear no próprio UUID da linha.** A variante canônica sem FITID do design §4.4 é
    `sha256("{conta}|c|{posted_at}|{amount}|{normaliza(descrição)}|{ordinal_no_dia}")` e depende do
    ordinal calculado contra o que já existe no banco naquele dia — implementá-la aqui seria
    construir metade do pipeline de importação numa story delimitada como "sem parser". Chavear no
    UUID é único por construção, satisfaz o `NOT NULL` e garante o comportamento que importa desde
    já: **dois lançamentos manuais idênticos no mesmo dia** (dois Pix de R$ 50 para a mesma pessoa)
    **são dois movimentos**, nunca um. Colidir ali seria um furo criado pelo próprio sistema — o
    risco exato que o design §4.4 alerta.

    **Consequência para quem implementar a Onda 3:** um movimento manual nunca colide com uma linha
    importada, e vice-versa. O encontro entre os dois é resolvido pelo passo de **enriquecimento
    antes de inserir** (design §4.5), que é semântico (mesma conta, mesmo valor, `posted_at` em ±3
    dias) — o hash **não** vai ajudar a casar manual × importado. E não tente "harmonizar" as
    variantes retroativamente: reescrever `dedup_hash` de linhas existentes é migration com backfill
    sob FORCE RLS, a armadilha da `0046`.

    ⚠️ Não é `core.security.hash_token`, apesar de ser o mesmo sha256. Aquele helper existe para
    que um SEGREDO não fique em claro no banco, e a evolução natural dele é virar um KDF com sal —
    o que aqui reescreveria a semântica da constraint única em silêncio. Mesma primitiva, contratos
    diferentes.
    """
    return hashlib.sha256(
        f"{bank_account_id}|{SOURCE_MANUAL}|{transaction_id}".encode()
    ).hexdigest()


def _validate_amount(amount_cents: int) -> int:
    if amount_cents == 0:
        raise BankError(
            "O valor do movimento não pode ser zero. Use um valor positivo para entrada "
            "(crédito) e negativo para saída (débito).",
            422,
        )
    return amount_cents


def _validate_posted_at(posted_at: date, account: BankAccount) -> date:
    """As duas guardas de data do lançamento. Ambas 422, ambas com o porquê na mensagem.

    1. **`posted_at > opening_date`** — a fórmula do saldo derivado (design §3.1) só soma movimento
       POSTERIOR à data de abertura, porque tudo até ali já está dentro de `opening_balance_cents`.
       Aceitar a data e não somar o movimento seria pior do que recusar: a linha existiria, o saldo
       não mudaria, e ninguém entenderia por quê.
    2. **Não futura** — extrato bancário é fato passado. Data futura é erro de digitação (ano
       errado é o caso comum), e um movimento no futuro entra no saldo de `until=None` e some do
       saldo de hoje, o que aparece como divergência inexplicável na conferência da 8.5.
    """
    if posted_at <= account.opening_date:
        raise BankError(
            f"A data do movimento precisa ser posterior a {account.opening_date.isoformat()}, "
            "a data de abertura desta conta no e1p. O saldo de abertura já contempla tudo o que "
            "aconteceu até aquele dia — lançar antes disso contaria o mesmo dinheiro duas vezes.",
            422,
        )
    if posted_at > _today():
        raise BankError(
            "A data do movimento não pode ser futura: o extrato registra o que já aconteceu.",
            422,
        )
    return posted_at


def _validate_statuses(statuses: Sequence[str]) -> tuple[str, ...]:
    invalidos = [s for s in statuses if s not in STATUSES]
    if invalidos:
        raise BankError(
            f"Status inválido: {', '.join(invalidos)}. Use um de: {', '.join(STATUSES)}.", 422
        )
    return tuple(statuses)


def get_transaction(db: Session, transaction_id: str) -> BankTransaction:
    """404 fail-closed — cross-tenant cai aqui pela RLS (a linha não existe para quem pergunta)."""
    tx = db.get(BankTransaction, transaction_id)
    if tx is None:
        raise BankError("Movimento bancário não encontrado", 404)
    return tx


def list_transactions(
    db: Session,
    *,
    bank_account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    statuses: Sequence[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BankTransaction]:
    """Movimentos do tenant, do mais recente para o mais antigo. Paginação OBRIGATÓRIA.

    `start`/`end` são datas de calendário e **inclusivas** nas duas pontas — `posted_at` é `DATE`,
    então não existe aritmética de fuso em lugar nenhum deste caminho (design §3.3).

    A ordenação desempata por `created_at` desc: dois movimentos no mesmo dia (o caso do AC7) sem
    desempate sairiam em ordem indefinida, e uma lista que muda de ordem entre dois `GET` iguais
    quebra a paginação em silêncio — a linha que estava no fim da página 1 reaparece no topo da 2.

    Paginação obrigatória é padrão do projeto desde a correção de QA da Agenda (`CLAUDE.md`):
    `limit` é grampeado em [1, 500] em vez de rejeitado, mesmo contrato de
    `payables.list_payables`.
    """
    limit = max(1, min(limit, 500))
    stmt = select(BankTransaction).order_by(
        BankTransaction.posted_at.desc(), BankTransaction.created_at.desc()
    )
    if bank_account_id:
        stmt = stmt.where(BankTransaction.bank_account_id == bank_account_id)
    if start is not None:
        stmt = stmt.where(BankTransaction.posted_at >= start)
    if end is not None:
        stmt = stmt.where(BankTransaction.posted_at <= end)
    if statuses:
        stmt = stmt.where(BankTransaction.status.in_(_validate_statuses(statuses)))
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


def create_transaction(
    db: Session,
    *,
    bank_account_id: str,
    tenant_id: str,
    actor: str,
    data: BankTransactionCreate,
) -> BankTransaction:
    """Lança um movimento MANUAL na conta. `source` é fixado aqui, nunca vem do payload.

    Validações, todas antes de qualquer escrita: conta existe e é visível (404 fail-closed pela
    RLS), conta **não arquivada** (422 — lançar movimento NOVO numa conta encerrada é quase sempre
    a conta errada selecionada), valor `!= 0` (422) e as duas guardas de data de
    `_validate_posted_at` (422). Note a assimetria deliberada com `update_transaction`, que
    **aceita** editar movimento de conta arquivada: encerrar a conta impede lançar história nova,
    não impede corrigir a história que já estava lá.

    ⚠️ **Desvio documentado do contrato tabelado na story:** a story lista
    `create_transaction(db, *, tenant_id, actor, data)` — sem a conta —, mas a rota que o mesmo
    AC6 fixa recebe a conta no PATH (`POST /bank/accounts/{id}/transactions`). Como
    `BankTransactionCreate` não tem (nem deve ter) `bank_account_id`, a conta entra como parâmetro
    nomeado. É uma ADIÇÃO, não uma quebra: qualquer chamador precisa informar a conta de todo
    jeito, e `update_transaction` já recebe o `transaction_id` do mesmo jeito. Pôr o id no corpo
    criaria duas fontes de verdade para a mesma informação, com a pergunta "qual vence?" a ser
    respondida em 8.7.
    """
    acc = get_account(db, bank_account_id)
    if acc.archived_at is not None:
        raise BankError(
            "Esta conta está arquivada e não recebe lançamentos novos. Se ela voltou a ser usada, "
            "cadastre-a de novo com o saldo de abertura do dia.",
            422,
        )
    amount_cents = _validate_amount(data.amount_cents)
    posted_at = _validate_posted_at(data.posted_at, acc)

    # O id é gerado AQUI (e não pelo default do modelo, que só é aplicado no INSERT) porque o
    # `dedup_hash` é chaveado nele: sem isso seria preciso inserir, ler o id de volta e dar um
    # UPDATE — três idas ao banco e uma janela em que a coluna NOT NULL não teria valor.
    transaction_id = _uuid()
    tx = BankTransaction(
        id=transaction_id,
        tenant_id=tenant_id,
        bank_account_id=acc.id,
        posted_at=posted_at,
        amount_cents=amount_cents,
        # Congela AQUI e nunca mais muda (invariante (c) do modelo).
        raw_description=data.description,
        user_description="",
        fitid=None,
        dedup_hash=_manual_dedup_hash(acc.id, transaction_id),
        counterparty_name=data.counterparty_name,
        counterparty_document=data.counterparty_document,
        operation_nature=data.operation_nature,
        source=SOURCE_MANUAL,
        status=STATUS_UNMATCHED,
    )
    db.add(tx)
    # `flush` ANTES do `audit.record`, mesmo padrão de `create_account`: garante que a linha entrou
    # (a constraint única de dedupe fala aqui) antes de gravar um rastro que a afirma.
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transaction.create", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx


def update_transaction(
    db: Session,
    *,
    transaction_id: str,
    tenant_id: str,
    actor: str,
    data: BankTransactionUpdate,
) -> BankTransaction:
    """Corrige um movimento: **só** `posted_at`, `amount_cents` e `user_description`.

    Um movimento `ignored` pode ser editado — corrigir e depois reativar (`unignore`) é o caminho
    normal de quem ignorou por engano. Movimento de conta **arquivada** também pode: ver a nota de
    assimetria em `create_transaction`.

    A guarda contra editar `raw_description`/`source`/`dedup_hash`/`status`/`fitid` é dupla, de
    propósito: os campos não existem em `BankTransactionUpdate` **e** esta função só toca nos três
    campos permitidos, um a um, sem nenhum `setattr` genérico sobre `data.model_dump()`. Um laço
    genérico transformaria "acrescentar um campo ao schema" em "tornar esse campo editável" sem que
    ninguém precisasse decidir isso — que é exatamente como uma coluna imutável deixa de ser.
    """
    tx = get_transaction(db, transaction_id)

    if data.posted_at is not None:
        # Revalida contra a conta ATUAL do movimento (a conta não muda: não há rota para movê-lo).
        tx.posted_at = _validate_posted_at(data.posted_at, get_account(db, tx.bank_account_id))
    if data.amount_cents is not None:
        tx.amount_cents = _validate_amount(data.amount_cents)
    if data.user_description is not None:
        tx.user_description = data.user_description

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transaction.update", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx


def ignore_transaction(
    db: Session, *, transaction_id: str, tenant_id: str, actor: str, reason: str = ""
) -> BankTransaction:
    """Tira o movimento do saldo derivado sem apagá-lo. **Idempotente.**

    "Ignorar" é o que o usuário faz com um lançamento que existe no extrato mas não deveria contar
    para ele. A linha continua visível, com o motivo do lado — o oposto de um `DELETE`, que sumiria
    com a evidência e deixaria o saldo mudado sem explicação.

    Já ignorado → no-op silencioso (não re-grava o motivo, não gera segunda auditoria): a resposta é
    a mesma, que é o que idempotente significa para quem chamou duas vezes por causa de um clique
    duplo.
    """
    tx = get_transaction(db, transaction_id)
    if tx.status == STATUS_IGNORED:
        return tx
    tx.status = STATUS_IGNORED
    tx.ignored_reason = reason[:120]
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transaction.ignore", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx


def unignore_transaction(
    db: Session, *, transaction_id: str, tenant_id: str, actor: str
) -> BankTransaction:
    """Devolve o movimento ao saldo (`ignored` → `unmatched`) e limpa o motivo. **Idempotente.**

    Existe porque `ignore` sem volta transformaria um clique errado em dado permanentemente fora do
    saldo — e não há `DELETE` para desfazer. Volta sempre para `unmatched`, nunca para `partial`/
    `matched`: reconstruir o estado de conciliação é trabalho do `_refresh_status` da Onda 4, e
    chutá-lo aqui seria escrever na invariante (d) do modelo de fora do dono dela.
    """
    tx = get_transaction(db, transaction_id)
    if tx.status != STATUS_IGNORED:
        return tx
    tx.status = STATUS_UNMATCHED
    tx.ignored_reason = ""
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transaction.unignore", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx
