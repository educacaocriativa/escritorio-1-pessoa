"""Conta bancária e movimento bancário — entidades de NEGÓCIO (RLS). O **plano 3** do dinheiro.

`BankAccount` (Story 8.2) é a conta; `BankTransaction` (Story 8.3) é a linha de extrato. Cada uma
tem a sua própria docstring com as invariantes que a mantêm correta — leia a do modelo que você vai
mexer, além destes três avisos, que valem para o módulo inteiro:

**(a) Este é o plano 3 — nunca some com o plano 1 sem rótulo.** Os três planos de dinheiro
(design `controle-bancario-design.md` §1.1) são: **plataforma** (`transactions`,
`platform_earnings` — dinheiro no trilho e1p, split 40/30/20), **negócio** (`charges`, `payables` —
direitos e obrigações, dinheiro de ninguém ainda) e **bancário** (esta tabela + `bank_transactions`
— o dinheiro que está de fato no banco do usuário). A **Regra dos Planos** (§1.3a) proíbe que
nenhum cálculo de saldo bancário leia `transactions` e que nenhum cálculo de saldo de carteira leia
`bank_transactions`, e que as duas somas ocupem o mesmo campo numérico. O bug que originou o Epic 8
foi exatamente isso: a Projeção de Caixa usava `wallet.available_cents` como se fosse o saldo do
banco. `apps/api/tests/test_money_planes.py` transforma a regra em teste executável — inclusive a
direção de import permitida (§1.3b: `bank` **pode** importar `wallet`; `wallet` **nunca** importa
`bank`).

**(b) O saldo é DERIVADO — materializá-lo está PROIBIDO pelo design §3.1.** Repare que não existe
coluna de saldo nesta tabela, e isso é deliberado: `opening_balance_cents` é o **ponto de partida**
(o número que o usuário confirma olhando o app do banco, porque banco brasileiro só entrega ~60 dias
de extrato), não o saldo. O saldo vem de `service.derived_balance`. Um saldo materializado pode
divergir dos próprios movimentos, e aí existem dois números e nenhuma forma de saber qual está
certo — pagaríamos com a única propriedade que este produto está vendendo: que o número é
conferível. Se um dia a performance doer (~40 movimentos/mês, ~5.000 em dez anos por conta, sob
índice — não vai), a resposta é um **checkpoint de corte** movendo `opening_date` para frente, que é
auditável, nunca uma coluna de saldo.

**(c) `kind` aqui é VALIDADO — ao contrário dos outros `kind` do projeto, e de propósito.**
`investment_accounts.kind` (Story 5.6) e `cost_centers.kind` (Story 5.5) são texto livre porque são
rótulos informativos. Este **tem comportamento associado**: a Story 8.8 exclui `investment` do saldo
de caixa (`service.active_balance_total`) e `platform_wallet` é recusado pela API (AC4). Uma story
futura que "harmonize" este campo com os outros quebra as duas regras de uma vez. A coluna continua
`VARCHAR(16)` (não é enum no banco) para que crescer o vocabulário não exija migration — a validação
mora no service, onde ela pode explicar o porquê ao usuário.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# ── Vocabulário de `kind` ────────────────────────────────────────────────────────────────────
# Os QUATRO valores que a API aceita (design §2.1). `KINDS` é a fonte da validação no service.
KIND_CHECKING = "checking"      # conta corrente
KIND_SAVINGS = "savings"        # poupança
KIND_INVESTMENT = "investment"  # aplicação (excluída do "no banco" pela Story 8.8)
KIND_CASH = "cash"              # dinheiro em espécie / "caixinha" (tipicamente sem `number`)

KINDS: tuple[str, ...] = (KIND_CHECKING, KIND_SAVINGS, KIND_INVESTMENT, KIND_CASH)

# ⚠️ RESERVADO, **fora** de `KINDS` de propósito — a API recusa com 422 (AC4).
# Design §2.1: modelar a Carteira e1p como uma conta bancária unificaria a visão de "onde está meu
# dinheiro" e por isso é tentador; o design REJEITA fazer isso agora porque criaria um caminho em
# que somar plano 1 com plano 3 é fácil (violação da Regra dos Planos §1.3a). O valor fica no
# vocabulário para o dia em que houver payout real (Onda 6) — *"até lá, ninguém escreve nele"*.
# Reservar custa zero; descobrir depois que o vocabulário era fechado custa uma migration.
KIND_PLATFORM_WALLET = "platform_wallet"


class BankAccount(Base, TenantMixin, TimestampMixin):
    __tablename__ = "bank_accounts"

    # Índice único PARCIAL: identidade bancária única por tenant QUANDO informada. `tenant_id` é a
    # primeira coluna porque índice único é global e não respeita RLS (design §2.1).
    # ⚠️ `sqlite_where` é obrigatório junto do `postgresql_where`: a suíte unitária cria o schema
    # com `Base.metadata.create_all` em SQLite (`tests/conftest.py`). Sem ele o índice nasceria
    # TOTAL no SQLite e o teste "duas contas sem número convivem" passaria/falharia conforme o
    # banco — verde por engano num, vermelho inexplicável no outro.
    __table_args__ = (
        Index(
            "uq_bank_accounts_tenant_ident",
            "tenant_id",
            "institution_code",
            "branch",
            "number",
            unique=True,
            postgresql_where=text("number <> ''"),
            sqlite_where=text("number <> ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Como o usuário chama a conta ("Itaú PJ", "Aplicação CDB", "Caixinha").
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Ver aviso (c) da docstring do módulo: validado no service contra KINDS.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Identidade bancária (tudo opcional — default ''): nome do banco, COMPE/ISPB (<BANKID> do OFX),
    # agência, conta (<ACCTID>), CPF/CNPJ do titular (§7 rastreabilidade) e chave Pix.
    institution: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    institution_code: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    branch: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    number: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    holder_document: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    pix_key: Mapped[str] = mapped_column(String(140), default="", nullable=False)
    # PONTO DE PARTIDA do saldo derivado — NÃO é o saldo. Ver aviso (b). Pode ser NEGATIVO (conta
    # no limite / cheque especial). Centavos, BigInteger (Regra de Ouro: dinheiro nunca é float).
    opening_balance_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # A partir de quando o e1p conhece esta conta. Movimento anterior a esta data NÃO entra no
    # saldo derivado (a fórmula do design §3.1 é `posted_at > opening_date`) — ele já está DENTRO
    # do `opening_balance_cents`, e contá-lo de novo seria dobrar o valor.
    opening_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Conta padrão de débito/crédito. No máximo UMA ativa por tenant — invariante mantida pelo
    # service (`set_primary`/`archive_account`), não pelo banco: uma constraint parcial
    # `UNIQUE (tenant_id) WHERE is_primary` obrigaria a ordenar os UPDATEs para não colidir no meio
    # da troca, e o ganho é nulo num campo que só o service escreve.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Arquivar, NUNCA deletar (design §2.1, padrão de `chart_accounts`): conta encerrada não pode
    # levar o histórico de movimentos junto — a auditoria é o produto.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )


# ── Vocabulário de `source` — a ORIGEM da linha de extrato (design §2.2) ──────────────────────
# Só `manual` é escrito na Onda 1. Os demais estão declarados porque o vocabulário da coluna é
# fechado no design e declará-los custa zero — descobrir depois que era fechado custa uma migration.
SOURCE_MANUAL = "manual"      # lançado à mão pelo usuário (Story 8.3 — o ÚNICO desta onda)
SOURCE_OFX = "ofx"            # importado de arquivo OFX (Onda 3)
SOURCE_CSV = "csv"            # importado de CSV (Onda 3)
SOURCE_TRANSFER = "transfer"  # perna de transferência entre contas do usuário (Onda 6)
SOURCE_YIELD = "yield"        # rendimento de aplicação (Onda 6)
SOURCE_PAYOUT = "payout"      # payout da Carteira e1p caindo no banco (Onda 6)

SOURCES: tuple[str, ...] = (
    SOURCE_MANUAL,
    SOURCE_OFX,
    SOURCE_CSV,
    SOURCE_TRANSFER,
    SOURCE_YIELD,
    SOURCE_PAYOUT,
)

# ── Vocabulário de `status` — o estado de CONCILIAÇÃO do movimento (design §2.2) ──────────────
# ⚠️ Ver o aviso (d) na docstring de `BankTransaction`: nesta onda só `unmatched` e `ignored` são
# escritos. `partial`/`matched` pertencem ao `_refresh_status` da conciliação (Onda 4).
STATUS_UNMATCHED = "unmatched"  # nasce assim: nenhum lançamento do e1p foi vinculado a ele
STATUS_PARTIAL = "partial"      # vinculado parcialmente (Onda 4)
STATUS_MATCHED = "matched"      # totalmente conciliado (Onda 4)
STATUS_IGNORED = "ignored"      # o usuário disse "isto não deve contar" — FORA do saldo derivado

STATUSES: tuple[str, ...] = (
    STATUS_UNMATCHED,
    STATUS_PARTIAL,
    STATUS_MATCHED,
    STATUS_IGNORED,
)


class BankTransaction(Base, TenantMixin, TimestampMixin):
    """Uma linha de extrato bancário (Story 8.3). **Plano 3.**

    Quatro invariantes. Quebrar qualquer uma delas quebra o produto em silêncio — nenhuma dá erro
    na hora, todas dão um número errado depois:

    **(a) Plano 3 — nunca somar com `transactions`/`wallet` sem rótulo.** Ver o aviso (a) na
    docstring do módulo e a Regra dos Planos §1.3a, que `tests/test_money_planes.py` transforma em
    teste executável. Nenhum cálculo de saldo bancário lê `transactions`; nenhum cálculo de saldo de
    carteira lê esta tabela; as duas somas nunca ocupam o mesmo campo numérico.

    **(b) `amount_cents` é ASSINADO, e o sinal é INTERNO a esta tabela.** `+` = crédito (entrada),
    `−` = débito (saída); o saldo é `SUM(amount_cents)` puro, sem `CASE`. ⚠️ Este sinal **não** segue
    a convenção canônica da DRE (*"o sinal vem da tabela de origem"* — `dre.py`), porque lá cada
    origem é uma tabela de mão única (`charges` entra, `payables` sai) e aqui **uma mesma tabela**
    carrega os dois. Mesmo cuidado que as docstrings de `payables`/`receivables` têm com
    caixa×competência: a regra está escrita onde o leitor está prestes a errar. `amount_cents == 0`
    é recusado com 422 pelo service — movimento de valor zero não é um fato do extrato, é um erro
    de digitação, e entraria no saldo somando nada e na conferência ocupando uma linha.

    **(c) `raw_description` é IMUTÁVEL.** É a prova documental do que o banco disse (design §2.2).
    Na Onda 3 ela guarda o `<MEMO>`/`<NAME>` cru do arquivo; no lançamento manual guarda o texto que
    o usuário digitou — **mesma coluna, mesma regra**, para que o comportamento não divergisse por
    origem justo quando importado e manual passassem a conviver na mesma tela. Toda reclassificação
    (do usuário hoje, da IA na Onda 4, sempre com confirmação) vai em `user_description`. O que a UI
    exibe é `user_description or raw_description`, e `BankTransactionOut.description` já entrega
    essa derivação pronta para a regra não ser reimplementada em dois lugares.

    **(d) `status` é a ÚNICA materialização deliberada deste design (§2.2), e a disciplina de quem
    pode escrevê-la é o que a mantém correta.** Ela é derivável de `bank_reconciliations`, e mesmo
    assim é materializada porque a conferência precisa varrer "tudo que não bateu" por um índice
    parcial. Nesta onda **só** `service.ignore_transaction`/`unignore_transaction` a escrevem
    (`unmatched` ⇄ `ignored`); `partial` e `matched` pertencem ao `_refresh_status` do service de
    conciliação (Onda 4), chamado em toda mutação de vínculo, na mesma transação. Escrevê-los de
    qualquer outro lugar quebra a invariante sem nenhum sintoma imediato.

    **Referências soltas, sem FK dura:** `bank_account_id`, `import_batch_id` e `transfer_id` são
    referências sem `ForeignKey`, padrão do projeto (`charges.client_id`,
    `payables.cost_center_id`) — a integridade é validada no service, sob RLS. Uma FK entre tabelas
    com RLS `FORCE` cria caminhos de erro difíceis de diagnosticar quando a GUC não está setada.

    ⚠️ **PII de terceiro:** `raw_description`, `counterparty_name` e `counterparty_document`
    descrevem quem pagou/recebeu — gente que **nunca contratou com a e1p**. A partir da Onda 3/4
    esses campos só podem chegar ao Claude via `core/anonymizer` (Regra de Ouro nº 2, REQ-18,
    design §7.4). Nenhuma chamada de IA existe nesta story; o aviso mora aqui porque é esta story
    que **cria as colunas**.
    """

    __tablename__ = "bank_transactions"

    # ⚠️ `sqlite_where` é obrigatório junto do `postgresql_where`, pelo mesmo motivo já documentado
    # em `BankAccount`: a suíte unitária cria o schema com `Base.metadata.create_all` em SQLite
    # (`tests/conftest.py`) e um índice parcial declarado só para Postgres nasceria TOTAL lá —
    # divergência de schema entre o banco que os testes exercitam e o que a produção roda.
    __table_args__ = (
        # O índice de trabalho: toda leitura é "os movimentos DESTA conta NESTA janela".
        Index(
            "ix_bank_transactions_account_date",
            "tenant_id",
            "bank_account_id",
            "posted_at",
        ),
        # PARCIAL: a conferência só varre o que não bateu, então o índice não carrega o passado
        # já conciliado (design §2.2) — é justo essa parte que cresce sem parar.
        Index(
            "ix_bank_transactions_status",
            "tenant_id",
            "status",
            postgresql_where=text("status <> 'matched'"),
            sqlite_where=text("status <> 'matched'"),
        ),
        # ÚNICO. `tenant_id` PRIMEIRO porque índice único é GLOBAL e não respeita RLS — sem ele o
        # tenant B levaria um 409 por causa de um dado do tenant A (bug **e** vazamento de
        # existência). Ver `service._manual_dedup_hash` para a variante usada no manual.
        Index(
            "uq_bank_transactions_dedup",
            "tenant_id",
            "bank_account_id",
            "dedup_hash",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Referência SOLTA — sem FK dura (ver a docstring acima). Validada no service via `get_account`.
    bank_account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # `Date`, JAMAIS `DateTime` (design §3.3). Extrato bancário brasileiro é por dia; guardar hora
    # só convidaria a conversão UTC↔local que fez eventos sumirem da Agenda (`CLAUDE.md` §6.0). Ali
    # a lição foi aprendida na comparação; aqui ela é aplicada na ORIGEM: o tipo não permite o erro.
    # **Não "melhore" isto para TIMESTAMP em nenhuma story futura.**
    posted_at: Mapped[date] = mapped_column(Date, nullable=False)
    # Ver invariante (b). Sem `CheckConstraint` de propósito: a guarda de `!= 0` mora no service,
    # onde ela pode explicar ao usuário o que fazer — padrão do projeto (integridade no service).
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Ver invariante (c) — IMUTÁVEL depois de criada.
    raw_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    user_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # <FITID> do OFX: NULL no manual e no CSV. Guardado p/ diagnóstico e p/ detectar reciclagem de
    # FITID por banco (Onda 3). Criado agora porque acrescentá-lo depois custaria uma migration
    # sobre tabela com dado (design §7.3).
    fitid: Mapped[str | None] = mapped_column(String(255), default=None, nullable=True)
    # Mecanismo UNIVERSAL de idempotência (§4.4) — CSV não tem FITID, manual não tem. NOT NULL, logo
    # a primeira linha já precisa de valor: ver `service._manual_dedup_hash`.
    dedup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Saldo após o movimento, quando o arquivo do banco trouxer (Onda 3). Sempre NULL no manual.
    balance_after_cents: Mapped[int | None] = mapped_column(
        BigInteger, default=None, nullable=True
    )
    # Contraparte (§7, rastreabilidade tributária) — todos opcionais. Ver o aviso de PII acima.
    counterparty_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    counterparty_document: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    pix_end_to_end_id: Mapped[str | None] = mapped_column(
        String(40), default=None, nullable=True
    )
    operation_nature: Mapped[str | None] = mapped_column(
        String(24), default=None, nullable=True
    )
    fiscal_document_ref: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True
    )
    # Vocabulário `SOURCES`. Nesta onda SEMPRE `manual`, fixado no service — a API **não** aceita
    # `source` do cliente (AC6): quem escolhe a origem é o caminho de código, nunca o payload.
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    import_batch_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
    transfer_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
    # Vocabulário `STATUSES`. Ver invariante (d).
    status: Mapped[str] = mapped_column(String(16), default=STATUS_UNMATCHED, nullable=False)
    # Por que o usuário mandou ignorar. Texto livre curto — vira a explicação na conferência.
    ignored_reason: Mapped[str] = mapped_column(String(120), default="", nullable=False)
