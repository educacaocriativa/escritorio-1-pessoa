"""Conta, movimento e saldo declarado — entidades de NEGÓCIO (RLS). O **plano 3** do dinheiro.

`BankAccount` (Story 8.2) é a conta; `BankTransaction` (Story 8.3) é a linha de extrato;
`BankBalanceCheckpoint` (Story 8.4) é a **verdade externa** do saldo num dia. Cada uma tem a sua
própria docstring com as invariantes que a mantêm correta — leia a do modelo que você vai mexer,
além destes três avisos, que valem para o módulo inteiro:

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
    # O ATO de declarar, ao lado do VALOR declarado acima. São dois eixos, não um campo achatado
    # (Story 8.21): sem esta coluna, "informei zero" e "não informei nada" são a MESMA linha, e a
    # Projeção afirma runway sobre um saldo que ninguém informou.
    #   True  → `opening_balance_cents` é uma AFIRMAÇÃO do dono.
    #   False → o dono disse que NÃO SABE; o valor fica `0` e é PLACEHOLDER, não afirmação.
    # ⚠️ Sem `default=` do lado Python de propósito: quem constrói precisa DECLARAR. O
    # `server_default` da migration 0074 existiu só para as linhas legadas e foi derrubado no mesmo
    # passo — se ficasse, todo INSERT que omitisse a coluna gravaria "eu sei o saldo" em silêncio,
    # que é o defeito que esta coluna existe para matar.
    opening_balance_is_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
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


# ── Vocabulário de `source` — a ORIGEM da linha de extrato (design §2.2, Onda 2 §3.1) ─────────
# Só `manual` era escrito na Onda 1. Os demais estão declarados porque o vocabulário da coluna é
# fechado no design e declará-los custa zero — descobrir depois que era fechado custa uma migration.
SOURCE_MANUAL = "manual"      # lançado à mão pelo usuário (Story 8.3)
SOURCE_OFX = "ofx"            # importado de arquivo OFX (Onda 4)
SOURCE_CSV = "csv"            # importado de CSV (Onda 4)
SOURCE_PAYABLE = "payable"    # NOVO (Story 8.9) — baixa de Contas a Pagar
SOURCE_CHARGE = "charge"      # NOVO (Story 8.9) — recebimento fora do trilho
SOURCE_TRANSFER = "transfer"  # perna de transferência entre contas do usuário (Story 8.18)
SOURCE_YIELD = "yield"        # rendimento de aplicação (Onda 2b)
SOURCE_PAYOUT = "payout"      # payout da Carteira e1p caindo no banco (Onda 3)

# ⚠️ **OS DOIS CONJUNTOS — e a regra normativa que eles instituem (Onda 2 §3.1, Story 8.9 AC3).**
#
# A partir da Story 8.9, **nenhuma regra deste repositório é escrita contra um valor SOLTO de
# `source`**: toda regra é escrita contra `SOURCES_SISTEMA` ou `SOURCES_EXTERNA`. A pergunta que os
# dois conjuntos respondem é única e limpa — *"o e1p conhece o lançamento de negócio que corresponde
# a esta linha?"* — e acrescentar uma origem nova passa a ser **uma entrada numa tupla**, sem que
# nenhuma regra mude.
#
# **Por que a disciplina do conjunto é obrigatória aqui, e não estilo.** `source` mistura DOIS
# eixos: `manual|ofx|csv` são **portas de entrada** e `payable|charge|transfer|yield|payout` são
# **origens de lançamento**. A mistura nasceu no design-mãe §2.2 e foi para produção na migration
# 0059 — e ela **NÃO será consertada** (Onda 2 §3.1): consertar exige reescrever uma coluna com dado
# em produção, sob `FORCE ROW LEVEL SECURITY` (a armadilha da 0046), para benefício conceitual e
# zero benefício de usuário. O que impede a mancha de INFECTAR o resto é exatamente a regra acima:
# ninguém pergunta *"`source == 'ofx'`?"*, todo mundo pergunta *"`source in SOURCES_EXTERNA`?"*.
#
# ⚠️ Corolário que a §4.2.0 do design da Onda 2 grava em pedra: **não existe um booleano
# `permite_futuro` decidido pelo chamador.** Um booleano é o parâmetro que alguém passa `True` no
# caminho manual, um dia, por conveniência — e nenhum gate de AST o pega, porque não há import
# envolvido. O eixo já existe e é `source`. Um eixo, uma pergunta.
SOURCES_SISTEMA: tuple[str, ...] = (
    SOURCE_PAYABLE,
    SOURCE_CHARGE,
    SOURCE_TRANSFER,
    SOURCE_YIELD,
    SOURCE_PAYOUT,
)
SOURCES_EXTERNA: tuple[str, ...] = (SOURCE_MANUAL, SOURCE_OFX, SOURCE_CSV)

# DERIVADA da união, nunca uma terceira lista escrita à mão: uma lista manual permitiria um valor
# novo entrar em um conjunto e sumir do outro em silêncio (`test_sources_particionam_o_vocabulario`
# em `tests/test_money_planes.py` prova união == SOURCES e interseção == vazio).
SOURCES: tuple[str, ...] = SOURCES_EXTERNA + SOURCES_SISTEMA

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


# ── Vocabulário de `operation_nature` — SUGERIDO, jamais enum fechado (Story 8.17) ────────────
#
# **A pergunta que este campo responde: *"para que serve este movimento?"*** — e ele é um RÓTULO,
# nunca um fato de dinheiro: não entra em nenhuma fórmula de saldo, não muda `derived_balance`, não
# muda a divergência da conferência (Story 8.17 AC9).
#
# ⚠️ **Este vocabulário NÃO é validado, e a diferença para `KINDS` é deliberada — leia o aviso (c)
# da docstring do módulo antes de "harmonizar".** `kind` de conta tem COMPORTAMENTO associado
# (`investment` sai do caixa; `platform_wallet` é recusado), então é validado. Aqui é o oposto:
# mesmo padrão de `investment_accounts.kind` e `cost_centers.kind` — **texto curto validado por
# tamanho** (`String(24)`, mais o `max_length` do schema de entrada), com a lista abaixo servindo de
# **sugestão na UI**. A API aceita qualquer texto que caiba.
#
# **Por que a válvula de texto livre é obrigatória** (design Onda 2 §7(a), design-mãe §7.2 D8):
#
#     *"O extrato está cheio de coisas que não imaginamos (estorno de tarifa, crédito de convênio,
#     débito de seguro, cashback). Recusar um fato bancário legítimo porque ele não está na lista
#     recria a incompletude que a onda combate."*
#
# Uma story futura que transformar isto num `Enum`/`CheckConstraint` — ou que fizer o service
# recusar valor fora da lista — quebra o AC3 da 8.17 e reintroduz exatamente aquela incompletude.
#
# `tarifa_bancaria` é o ÚNICO valor novo da Story 8.17; os outros três já eram vocabulário do
# design-mãe §7.2 (que também lista `receita_servico`, `receita_produto`, `despesa_operacional`,
# `pro_labore`, `aporte_socio`, `distribuicao_lucro`, `emprestimo`, `estorno` — fora da curadoria
# da 8.17 de propósito: a lista da UI é CURTA, e "Outro (descreva)" cobre o resto).
OPERATION_NATURE_TARIFA = "tarifa_bancaria"          # tarifa, juros, taxa de TED (NOVO na 8.17)
OPERATION_NATURE_TRIBUTO = "tributo"                 # IOF, imposto
OPERATION_NATURE_TRANSFERENCIA = "transferencia_propria"  # entre contas do próprio dono
OPERATION_NATURE_RECEITA_FINANCEIRA = "receita_financeira"  # rendimento

# A lista **sugerida** na UI, nesta ordem. `bank/router.py` NÃO a valida e o service NÃO a impõe:
# quem a consome é o `<select>` do formulário (`apps/web/.../contas.ts`), e o pareamento entre as
# duas listas tem teste (`test_bank_contagem_dupla.py::test_vocabulario_sugerido_bate_com_a_ui`).
OPERATION_NATURES: tuple[str, ...] = (
    OPERATION_NATURE_TARIFA,
    OPERATION_NATURE_TRIBUTO,
    OPERATION_NATURE_TRANSFERENCIA,
    OPERATION_NATURE_RECEITA_FINANCEIRA,
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
        # ÚNICO **PARCIAL** — a garantia de idempotência da Regra da Origem (Onda 2 §3.2,
        # Story 8.9 AC2). **É ESTE ÍNDICE, e não o `dedup_hash`, que impede o movimento de existir
        # duas vezes:** preencher a conta duas vezes, reprocessar a mesma baixa ou um retry de
        # request esbarram aqui, no banco, fail-closed, no espírito da RLS.
        #
        # ⚠️ **Sobre o `WHERE origin_id IS NOT NULL` — e uma correção ao texto da Story 8.9.** A
        # AC2 justifica a cláusula dizendo que *"sem ela, todo movimento manual colidiria com todo
        # outro movimento manual"*. **Isso é falso**, e o próprio design da Onda 2 escreve o motivo
        # duas páginas antes, ao rejeitar a coluna `leg`: **no Postgres, `NULL` é distinto de
        # `NULL` em índice único por padrão** (idem no SQLite). Duas linhas com `origin_id IS NULL`
        # conviveriam num índice TOTAL — a cláusula não é o que as salva.
        #
        # O que a cláusula faz de verdade, e por que ela fica:
        #   (1) **tamanho e intenção** — o índice carrega só as linhas de origem de sistema, que
        #       são a minoria, em vez de uma entrada por movimento do tenant (mesmo raciocínio do
        #       `ix_bank_transactions_status`, parcial pelo mesmo motivo);
        #   (2) **não depender do comportamento de `NULL`** — a convivência de dois movimentos
        #       externos passa a ser ESTRUTURAL (eles nem estão no índice) em vez de depender de
        #       `NULLS DISTINCT`, que é o default do Postgres mas é **configurável desde o PG15**
        #       (`NULLS NOT DISTINCT`). Uma "melhoria" futura que ligasse isso quebraria o
        #       lançamento manual em silêncio.
        # **Consequência para quem testa:** nenhum teste de COMPORTAMENTO distingue o índice
        # parcial do total — os dois se comportam igual hoje. A guarda contra a remoção da cláusula
        # é ESTRUTURAL (`test_indice_de_origem_e_parcial`), e é assim de propósito.
        #
        # `tenant_id` PRIMEIRO pelo mesmo motivo dos outros três índices únicos deste módulo:
        # índice único é GLOBAL e não respeita RLS. Sem ele, o tenant B receberia uma violação
        # inexplicável por causa de um dado do tenant A — bug **e** vazamento de existência (a
        # lição que `uq_bank_accounts_tenant_ident` já pagou na Story 8.2).
        Index(
            "uq_bank_transactions_origin",
            "tenant_id",
            "source",
            "origin_id",
            unique=True,
            postgresql_where=text("origin_id IS NOT NULL"),
            sqlite_where=text("origin_id IS NOT NULL"),
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
    # Vocabulário `SOURCES`. `create_transaction` fixa `manual` — a API **não** aceita `source` do
    # cliente (8.3 AC6): quem escolhe a origem é o caminho de código, nunca o payload. A partir da
    # Story 8.9, os valores de `SOURCES_SISTEMA` são escritos por **uma única função do
    # repositório**, `bank/origin.py::sync_origin_movement`. `String(16)` continua servindo:
    # `"payable"` (7) e `"charge"` (6) cabem — **sem migration de tipo**.
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # ── A CHAVE DE ORIGEM (Story 8.9, Onda 2 §3.2) ───────────────────────────────────────────
    # **INVARIANTE DA ORIGEM (normativa, testada nas DUAS direções):**
    #     `source ∈ SOURCES_SISTEMA` ⟺ `origin_id IS NOT NULL`.
    # Aplicada no **service** (`origin.sync_origin_movement`), não por `CheckConstraint` — padrão
    # do projeto: integridade no service, onde ela pode explicar. Testar só um sentido deixaria
    # passar exatamente o estado que a importação da Onda 4 vai criar por acidente (linha externa
    # com `origin_id` preenchido), por isso `test_origem_do_sistema_sempre_tem_origin_id` verifica
    # os dois.
    #
    # ⚠️ **`origin_id` é a CHAVE DE ORIGEM, NÃO "o id do lançamento"** (ratificação §C-3.3). Para
    # origem de **perna única** (`payable`, `charge`, `yield`, `payout`) ela **é** o id do
    # lançamento; para origem de **múltiplas pernas** é `f"{id}:{perna}"` — hoje só `transfer`, com
    # `out`/`in` (Story 8.18). O que ela garante é a unicidade da **unidade de sincronização**, e a
    # unidade de sincronização de uma transferência é a PERNA, não a transferência; o pareamento
    # entre as pernas é trabalho de `transfer_id`, logo acima.
    #
    # ⚠️ **`VARCHAR(64)` e não 36, por assimetria de custo — não por conforto.** `uuid4` (36) +
    # `":out"` (4) = 40, e o vocabulário de perna pode crescer. Em Postgres `VARCHAR(n)` é
    # armazenamento **variável** (64 e 36 custam o mesmo em disco; o `n` é restrição, não reserva),
    # enquanto errar para menos custa `ALTER COLUMN` sobre tabela com dado sob `FORCE ROW LEVEL
    # SECURITY` — a armadilha da 0046, que o ADR 0003 nomeia como o único ponto desse tipo do
    # épico. `test_origin_id_cabe_na_coluna` reprova em CI, e não no `ALTER COLUMN`, a origem de
    # várias pernas que não couber.
    #
    # **Regra de autoridade (Onda 2 §3.3):** `bank_transactions.bank_account_id` é **DERIVADA** de
    # `payables.bank_account_id`/`charges.bank_account_id` (a decisão autoritativa do usuário) pelo
    # sincronizador, e é escrita por **nenhum outro caminho**. Se o cache de leitura
    # (`payable.bank_transaction_id`) divergir do movimento cujo `origin_id = payable.id`, **quem
    # manda é o `origin_id`**.
    origin_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
    transfer_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
    # Vocabulário `STATUSES`. Ver invariante (d).
    status: Mapped[str] = mapped_column(String(16), default=STATUS_UNMATCHED, nullable=False)
    # Por que o usuário mandou ignorar. Texto livre curto — vira a explicação na conferência.
    ignored_reason: Mapped[str] = mapped_column(String(120), default="", nullable=False)


# ── Vocabulário de `kind` da TRANSFERÊNCIA — do módulo `bank`, e só dele (Story 8.18) ─────────
#
# ⚠️ **Este vocabulário NÃO referencia o módulo de investimentos, e a ausência é o AC5 inteiro.**
# (O caminho de import dele não aparece escrito em lugar nenhum deste módulo — nem em prosa: o gate
# por TEXTO CRU o pega em qualquer posição, e essa é a metade que pega a fuga por `importlib`.)
# `investment_in`/`investment_out` descrevem *para onde o dinheiro do dono foi* — uma conta
# bancária dele com `kind='investment'` —, não um produto financeiro com rentabilidade. A faceta de
# produto (`investment_accounts`, `principal_cents` derivado, `register_yield`) é **Onda 2b**, e é
# lá que mora o único backfill do épico. Transferir para uma `bank_account` de aplicação **já
# funciona** desde a Onda 1: o dinheiro se move e os dois saldos derivados batem.
#
# O gate estrutural `test_bank_transfers_nao_importa_investments` (varredura AST, em
# `tests/test_money_planes.py`) reprova o dia em que alguém "ligar" os dois por conveniência.
#
# Validado por LISTA no service, como `KINDS` de conta e ao contrário de `operation_nature`: este
# campo tem comportamento associado (`investment_in` é o que a UI usa para avisar que o valor sai do
# "Disponível como caixa"), então um valor fora do vocabulário seria um comportamento não decidido.
# A coluna continua `VARCHAR(20)` (não é enum no banco) para que crescer o vocabulário não exija
# migration — a validação mora no service, onde ela pode explicar o porquê ao usuário.
TRANSFER_KIND_OWN = "own_transfer"          # entre duas contas correntes/poupança/caixa do dono
TRANSFER_KIND_INVESTMENT_IN = "investment_in"    # o dinheiro foi PARA uma conta de aplicação
TRANSFER_KIND_INVESTMENT_OUT = "investment_out"  # o dinheiro VOLTOU de uma conta de aplicação

TRANSFER_KINDS: tuple[str, ...] = (
    TRANSFER_KIND_OWN,
    TRANSFER_KIND_INVESTMENT_IN,
    TRANSFER_KIND_INVESTMENT_OUT,
)


class BankTransfer(Base, TenantMixin, TimestampMixin):
    """*"Movi R$ X da minha conta A para a minha conta B em tal dia."* **Plano 3** (Story 8.18).

    É o **lançamento**; as duas linhas de extrato que ele produz são `BankTransaction` com
    `source='transfer'`, `origin_id = f"{transfer.id}:out"` / `f"{transfer.id}:in"` e
    `transfer_id = transfer.id`. Quem as escreve é `bank/origin.py::sync_origin_movement`, em
    **duas chamadas**, na mesma transação — nunca esta classe, nunca um `setattr` direto.

    Quatro invariantes:

    **(a) A Regra da NEUTRALIDADE — transferência não é receita nem despesa.** Ela é
    **exclusivamente** evento do plano 3: nunca cria, altera ou baixa `Charge`, `Payable` ou
    `Transaction`, e por isso **não aparece** na DRE, na Lucratividade nem na Projeção como entrada
    ou saída. Isto é verdadeiro **por construção** (`dre.py` agrega exatamente essas três tabelas e
    `bank_transfers` não é nenhuma delas) — e mesmo assim tem teste nomeado,
    `test_transferencia_nao_altera_dre`, porque a garantia é a **invariante, não o nome**: o dia em
    que alguém "melhorar" a DRE para incluir uma quarta fonte, o teste é o que avisa.

    **(b) `amount_cents` é SEMPRE POSITIVO — o sinal vive nas pernas.** Guardar o sinal aqui seria a
    terceira convenção de sinal do repositório (a DRE tem a dela, `bank_transactions` tem a dela) e
    a pergunta *"o negativo aqui significa 'saiu de A' ou 'a transferência foi invertida'?"* não tem
    resposta escrita em lugar nenhum. Guarda no service (`create_transfer`), não `CheckConstraint`.

    **(c) As duas pernas são ESPELHO deste lançamento.** Apagar a transferência apaga as duas
    (`delete_transfer`, sob a mesma guarda de linha puramente sintética da 8.12); corrigir não
    existe — apagar e recriar é barato aqui, ao contrário de `payables`/`charges`, porque **nenhum
    evento de Agenda está envolvido**. E as pernas **não** são editáveis nem ignoráveis pela tela de
    movimentos: elas herdam a guarda da Regra da Origem (d), escrita contra `SOURCES_SISTEMA`.

    **(d) Nenhuma coluna de saldo, aqui como em `bank_accounts`.** O saldo é derivado dos
    movimentos, sempre (design §3.1). Uma transferência **redistribui** saldo entre contas; o total
    das contas elegíveis não muda. Quando o destino é `kind='investment'`, o *"Disponível como
    caixa"* **cai** — e isso é correto: o dinheiro deixou de ser caixa.

    **Referências soltas, sem FK dura** (`from_account_id`, `to_account_id`): padrão do projeto
    (`charges.client_id`, `payables.cost_center_id`) — a integridade é validada no service, sob RLS.
    Uma FK entre tabelas com RLS `FORCE` cria caminhos de erro difíceis de diagnosticar quando a GUC
    não está setada.

    Herda `TenantMixin` — é o que dá a coluna `tenant_id` que a RLS usa **e** a purga automática na
    exclusão de conta (`platform.service._business_table_names` descobre subclasses dinamicamente).
    """

    __tablename__ = "bank_transfers"

    __table_args__ = (
        # Só leitura: *"o que passou por esta conta?"*. `tenant_id` primeiro porque índice é global
        # e não respeita RLS — mesmo raciocínio dos índices únicos deste módulo.
        Index(
            "ix_bank_transfers_accounts",
            "tenant_id",
            "from_account_id",
            "to_account_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Conta de ORIGEM: é dela que sai a perna `:out`, com valor NEGATIVO.
    from_account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Conta de DESTINO: é nela que entra a perna `:in`, com valor POSITIVO.
    to_account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Ver invariante (b): SEMPRE POSITIVO. Centavos, BigInteger.
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # `Date`, JAMAIS `DateTime` (design §3.3) — a mesma disciplina de `BankTransaction.posted_at`.
    posted_at: Mapped[date] = mapped_column(Date, nullable=False)
    # Vocabulário `TRANSFER_KINDS`, validado no service. Ver o bloco acima.
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # O que o dono escreveu. Vira `raw_description` das DUAS pernas (elas são espelho).
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


# ── Vocabulário de `origin` — o **EIXO B** da procedência (design §1.3.1) ─────────────────────
#
# A pergunta que este eixo responde: *"por qual PORTA este saldo EXTERNO entrou no e1p?"*
# Sufixo de campo de API: `*_fonte`. Este é o vocabulário CANÔNICO do eixo B, e ele mora aqui — ao
# lado da coluna `bank_balance_checkpoints.origin` que descreve — enquanto o **eixo A** (`*_origem`
# ∈ `plataforma|banco|misto|indisponivel`, a pergunta *"de qual PLANO de dinheiro o número vem?"*)
# mora em `app/core/money_planes.py`.
#
# ⚠️ **Os dois eixos NUNCA se traduzem um no outro.** A ratificação da @architect (D-3) removeu da
# Story 8.4 uma camada que mapeava `origin='manual'` → `ORIGEM_DECLARADO`; essa tradução foi
# apontada como **a prova** de que havia dois conceitos achatados num campo só. `declarado` e
# `extrato` estão REVOGADOS como valores de `*_origem`; a Story 8.5 lê `origin` **direto**, sem
# traduzir. Consequência boa: na Onda 3, ZERO mudança de vocabulário — `ofx` já existe aqui.
ORIGIN_MANUAL = "manual"  # o usuário olhou o app do banco e digitou o número (o ÚNICO desta onda)
# RESERVADO para a Onda 3: o `<LEDGERBAL>` do arquivo OFX importado. **Ninguém escreve nele hoje** —
# a API recusa com 422 (AC3) e `import_batch_id` nasce sempre NULL. Declarar custa zero; descobrir
# depois que o vocabulário era fechado custa uma migration.
ORIGIN_OFX = "ofx"

ORIGINS: tuple[str, ...] = (ORIGIN_MANUAL, ORIGIN_OFX)


class BankBalanceCheckpoint(Base, TenantMixin, TimestampMixin):
    """*"O saldo desta conta, no FIM deste dia, era X."* A **verdade externa** (Story 8.4).

    Três avisos, e o terceiro é o mais importante do épico inteiro:

    **(a) É esta tabela que torna a conferência possível SEM IMPORTAÇÃO NENHUMA** (design §2.4). Ela
    é a "Opção B" do estudo antecedente (saldo declarado) preservada dentro do desenho maior em vez
    de descartada, e é por causa dela que a Onda 1 entrega valor sozinha, antes de qualquer parser
    existir. O custo para o usuário é o menor de todo o épico: ~1 vez por mês, 5 segundos,
    **confirmando** um número que já está na tela do app do banco — dentro do teto de simplicidade
    do design §0 (*"o e1p pode pedir que o usuário CONFIRME um número; não que ele CONSTRUA um
    número"*). O contraste deliberado é a Onda 3, onde baixar e subir o OFX é reconhecido no próprio
    design como *"o pedido mais caro"*.

    **(b) `reference_date` é O FIM DAQUELE DIA.** É um `Date` (jamais `DateTime`, design §2.4 e
    `CLAUDE.md` §6.0) e a comparação da conferência (Story 8.5) é, obrigatoriamente,
    `latest_checkpoint(..., on_or_before=D)` × `derived_balance(..., until=D)` com **o mesmo `D`**,
    onde `D` é o `reference_date` do checkpoint encontrado — nunca "hoje", nunca o fim do período
    pedido. `until` de `derived_balance` também é inclusivo, então as duas janelas coincidem por
    construção. Comparar saldos apurados em datas diferentes é o erro clássico desta classe de
    relatório, e o design §5.1 manda **recusar**, não arredondar.

    **(c) O checkpoint NUNCA corrige o saldo derivado.** O saldo do sistema é derivado dos
    movimentos (`opening_balance_cents + SUM(amount_cents)`, design §3.1); este número é a verdade
    externa. Os dois existem para serem **comparados**, jamais reconciliados automaticamente. Se
    algum dia alguém fizer o checkpoint ajustar o saldo — por um "movimento de ajuste" automático,
    que é a "melhoria" bem-intencionada mais provável aqui —, a divergência iria a zero **por
    construção** e o produto perderia a única coisa que está vendendo: a capacidade de dizer
    **quanto** está faltando (`|divergencia_cents|` por conta é a métrica primária do epic §3.1).
    Corolário: nada aqui materializa saldo. Esta tabela **não é cache de saldo** — é registro de uma
    declaração, com data e autor. A defesa permanente contra essa boa intenção é o teste nomeado
    `test_checkpoint_nao_altera_saldo_derivado`.

    **Por que existe um checkpoint por CONTA e não um "saldo declarado do tenant"** (epic §9 F3): a
    topologia real do usuário é corrente + poupança + aplicação, possivelmente em bancos diferentes.
    Três contas divergindo +R$ 1.200, −R$ 900 e +R$ 40 dão +R$ 340 consolidado, que *parece saudável
    e esconde dois problemas* — por isso a conferência é **por conta**, e um consolidado só existe
    acompanhado da decomposição (epic §3.2).

    **`origin` na constraint única não é redundância:** o mesmo dia pode ter um checkpoint `manual`
    **e** um `ofx`, porque são dois fatos independentes (e divergirem entre si já é informação: ou o
    usuário digitou errado, ou o arquivo é de outro período). Ver `ORIGINS` acima e o desempate
    determinístico documentado em `service.latest_checkpoint`.

    **Referências soltas, sem FK dura** (`bank_account_id`, `import_batch_id`): padrão do projeto —
    a integridade é validada no service, sob RLS.
    """

    __tablename__ = "bank_balance_checkpoints"

    # ÚNICO **total** (não parcial). `tenant_id` PRIMEIRO porque índice único é GLOBAL e não
    # respeita RLS — sem ele o tenant B levaria um 409 por causa de um dado do tenant A (bug **e**
    # vazamento de existência), mesmo raciocínio de `BankAccount`/`BankTransaction`.
    # ⚠️ Declarado também AQUI, e não só na migration: a suíte unitária cria o schema com
    # `Base.metadata.create_all` em SQLite (`tests/conftest.py`), e sem esta declaração o caminho de
    # redeclaração (AC4) e a corrida de `IntegrityError` não seriam exercidos fora do Postgres.
    __table_args__ = (
        Index(
            "uq_bank_checkpoint_day",
            "tenant_id",
            "bank_account_id",
            "reference_date",
            "origin",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Referência SOLTA — validada no service via `get_account` (404 fail-closed pela RLS).
    bank_account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Ver aviso (b): **`Date`, jamais `DateTime`**. Não "melhore" para TIMESTAMP em story nenhuma.
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    # PODE ser negativo (conta no limite / cheque especial) — sem default e sem guarda de sinal.
    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Vocabulário `ORIGINS` (eixo B). Validado no service; nesta onda só `manual` é aceito.
    origin: Mapped[str] = mapped_column(String(12), nullable=False)
    # Sempre NULL nesta onda — só a importação da Onda 3 preenche.
    import_batch_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
    # `user_id` de quem declarou. Nullable porque a linha `ofx` da Onda 3 não terá autor humano.
    created_by: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
