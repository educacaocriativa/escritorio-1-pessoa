"""Conta bancária — entidade de NEGÓCIO (RLS), Story 8.2. O **plano 3** do dinheiro.

Três avisos que a próxima pessoa a mexer aqui precisa ler antes de mudar qualquer coisa:

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

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, String, text
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
