"""Schemas da conta bancária (Story 8.2) e do movimento bancário (Story 8.3).

**Nenhum saldo trafega sem procedência** (Regra dos Planos §1.3c): todo campo que carrega saldo tem
um irmão `*_origem` preenchido com uma constante de `app.core.money_planes` — nunca uma string
literal solta. Aqui a origem é sempre `ORIGEM_BANCO`, porque o número vem do plano 3.

⚠️ `BankTransactionOut.amount_cents` **não** é um saldo e por isso não tem `*_origem`: é o valor de
UM movimento, não o resultado de uma soma. A regra §1.3c fala de campos que carregam saldo — quem
carrega saldo neste módulo é `saldo_derivado_cents`, e ele declara.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.core.money_planes import ORIGEM_BANCO
from app.core.validators import validate_document


def _digits_or_empty(v: str | None) -> str | None:
    """CPF/CNPJ do TITULAR — opcional. Normaliza para só-dígitos e valida quando informado.

    ⚠️ **DESVIO DOCUMENTADO da Task 5 da story 8.2** (registrado no Dev Agent Record). A story
    mandava validar *"só tamanho/normalização de dígitos, sem dígito verificador"*, com a
    justificativa de que o DV é *"a dívida global já registrada no `CLAUDE.md` §6.1"* e que
    resolvê-la aqui *"criaria inconsistência com o resto do produto"*. **A premissa está
    desatualizada:** `app/core/validators.py` já implementa CPF/CNPJ com dígito verificador e é
    usado por `auth`, `crm`, `contracts` e `platform` — validar só o tamanho aqui produziria
    exatamente a inconsistência que a instrução queria evitar. Seguimos o padrão real do projeto
    (mesmo formato opcional de `crm.schemas.ClientCreate.document`); a nota do `CLAUDE.md` §6.1 é
    que está velha, e corrigi-la é fora do escopo desta story.
    """
    if v is None or not v.strip():
        return ""
    return validate_document(v)


def _strip(v: str | None) -> str | None:
    return v.strip() if v is not None else None


class BankAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Validado contra `models.KINDS` no SERVICE (não aqui): `platform_wallet` precisa de uma
    # mensagem de 422 PRÓPRIA, explicando a Regra dos Planos, e não do erro genérico do Pydantic.
    kind: str = Field(max_length=16)
    institution: str = Field(default="", max_length=120)
    institution_code: str = Field(default="", max_length=8)
    branch: str = Field(default="", max_length=16)
    number: str = Field(default="", max_length=32)
    holder_document: str = Field(default="", max_length=20)
    pix_key: str = Field(default="", max_length=140)
    # PODE ser negativo: conta no limite / cheque especial é saldo de partida legítimo.
    opening_balance_cents: int = 0
    opening_date: date

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

    @field_validator("institution", "institution_code", "branch", "number", "pix_key", "kind")
    @classmethod
    def _text(cls, v: str) -> str:
        return v.strip()

    @field_validator("holder_document")
    @classmethod
    def _holder_document(cls, v: str) -> str:
        return _digits_or_empty(v) or ""


class BankAccountUpdate(BaseModel):
    """Edição parcial — `None` significa "não altera" em todos os campos.

    `archived_at` **não** é editável por aqui (AC2): arquivar é uma operação própria
    (`POST /bank/accounts/{id}/archive`), com auditoria, e desarquivar não existe de propósito.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, max_length=16)
    institution: str | None = Field(default=None, max_length=120)
    institution_code: str | None = Field(default=None, max_length=8)
    branch: str | None = Field(default=None, max_length=16)
    number: str | None = Field(default=None, max_length=32)
    holder_document: str | None = Field(default=None, max_length=20)
    pix_key: str | None = Field(default=None, max_length=140)
    opening_balance_cents: int | None = None
    opening_date: date | None = None
    is_primary: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ser vazio")
        return v

    @field_validator("institution", "institution_code", "branch", "number", "pix_key", "kind")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _strip(v)

    @field_validator("holder_document")
    @classmethod
    def _holder_document(cls, v: str | None) -> str | None:
        return _digits_or_empty(v)


class BankAccountOut(BaseModel):
    id: str
    name: str
    kind: str
    institution: str
    institution_code: str
    branch: str
    number: str
    holder_document: str
    pix_key: str
    opening_balance_cents: int
    opening_date: date
    is_primary: bool
    archived_at: datetime | None
    # Saldo DERIVADO (design §3.1) — não existe coluna de saldo; este número é calculado a cada
    # leitura por `service.derived_balance`: `opening_balance_cents` + Σ dos movimentos posteriores
    # à data de abertura que não estejam ignorados (Story 8.3).
    saldo_derivado_cents: int
    # Procedência OBRIGATÓRIA do saldo acima (Regra dos Planos §1.3c). Sempre `ORIGEM_BANCO`: este
    # número vem do plano 3, jamais da Carteira.
    saldo_derivado_origem: str = ORIGEM_BANCO
    created_at: datetime


class BankBalanceOut(BaseModel):
    """Resposta de `GET /bank/accounts/{id}/balance`.

    `until` é a data de corte usada (inclusiva) — `None` significa "sem corte" (todo o histórico).
    Ela é devolvida no payload porque a Story 8.5 compara saldos **na mesma data**, e um saldo sem
    a data em que foi apurado é um número que não dá para conferir.
    """

    saldo_derivado_cents: int
    saldo_derivado_origem: str = ORIGEM_BANCO
    until: date | None


# ── Movimento bancário (Story 8.3) ───────────────────────────────────────────────────────────


class BankTransactionCreate(BaseModel):
    """Lançamento MANUAL de um movimento. A conta vem do PATH, nunca do corpo.

    `source` **não** existe aqui de propósito (AC6): quem escolhe a origem da linha é o caminho de
    código (`SOURCE_MANUAL`, fixado no service), nunca o cliente. Se o payload pudesse dizer
    `source='ofx'`, a coluna deixaria de significar "de onde este dado veio" — e é ela que a
    auditoria usa para separar o que o banco disse do que o usuário digitou.

    `description` alimenta `raw_description`, que é **imutável** a partir daí (invariante (c) do
    modelo). Toda edição posterior vai em `user_description`.
    """

    posted_at: date
    # COM SINAL: + entrada, − saída. `0` é recusado com 422 no service (invariante (b) do modelo).
    amount_cents: int
    # Vira `raw_description` (TEXT, sem limite de tamanho no banco) e congela.
    description: str = Field(default="")
    # Contraparte informável à mão (§7). Os demais campos de contraparte (`pix_end_to_end_id`,
    # `fiscal_document_ref`) só são preenchidos por importação/conciliação e não entram aqui.
    counterparty_name: str = Field(default="", max_length=160)
    counterparty_document: str = Field(default="", max_length=20)
    operation_nature: str | None = Field(default=None, max_length=24)

    @field_validator("description", "counterparty_name")
    @classmethod
    def _text(cls, v: str) -> str:
        return v.strip()

    @field_validator("operation_nature")
    @classmethod
    def _nature(cls, v: str | None) -> str | None:
        return _strip(v) or None

    @field_validator("counterparty_document")
    @classmethod
    def _counterparty_document(cls, v: str) -> str:
        """Mesma validação de `holder_document` (dígito verificador, via `core/validators`).

        ⚠️ **A Onda 3 NÃO deve reusar esta validação para dado importado.** Aqui o documento é
        digitado por quem está olhando para o comprovante e um erro de digitação vale um 422; num
        arquivo do banco, um CPF malformado é o que o banco mandou — recusar a linha por causa dele
        perderia a evidência, que é justo o que a importação existe para preservar.
        """
        return _digits_or_empty(v) or ""


class BankTransactionUpdate(BaseModel):
    """Edição parcial — `None` significa "não altera".

    **Três campos, e mais nada** (AC4/AC6). Ausentes de propósito, com guarda redundante no service
    para o caso de alguém acrescentá-los aqui sem ler:
    - `raw_description`: imutável, é a prova documental (invariante (c) do modelo);
    - `source`, `dedup_hash`, `fitid`: descrevem a PROCEDÊNCIA da linha, que o usuário não escolhe;
    - `status`: só `ignore`/`unignore` a escrevem nesta onda (invariante (d) do modelo).

    Um movimento `ignored` **pode** ser editado: corrigir e depois reativar é o caminho normal.
    """

    posted_at: date | None = None
    amount_cents: int | None = None
    user_description: str | None = None

    @field_validator("user_description")
    @classmethod
    def _user_description(cls, v: str | None) -> str | None:
        return _strip(v)


class IgnoreRequest(BaseModel):
    """Corpo de `POST /bank/transactions/{id}/ignore`. `reason` é opcional."""

    reason: str = Field(default="", max_length=120)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return v.strip()


class BankTransactionOut(BaseModel):
    """Movimento como a API o devolve.

    `description` é a **derivação pronta** `user_description or raw_description` — entregue além
    dos dois campos crus para que a UI (Story 8.7) não reimplemente a regra e as duas
    implementações não divirjam depois (Dev Notes da 8.3).

    **Colunas da tabela que NÃO entram neste contrato agora**, e por quê: `fitid`, `dedup_hash`,
    `balance_after_cents`, `import_batch_id` e `transfer_id` são criadas pela migration desta story
    porque a Onda 3/4 depende delas (design §7.3), mas nesta onda **nenhum caminho de código as
    escreve** e nenhum consumidor as lê — são NULL/derivadas por construção. Quem passar a
    populá-las define o contrato de saída delas, com uma pergunta a mais no caso de
    `balance_after_cents`: por carregar um saldo (o que o banco reportou após o movimento), ela
    precisa nascer com o irmão `*_origem` da Regra dos Planos §1.3c. Expor um campo de saldo agora,
    sempre nulo e sem procedência, seria justamente o contra-exemplo que essa regra procura.
    """

    id: str
    bank_account_id: str
    posted_at: date
    # COM SINAL (+ entrada / − saída). NÃO é saldo — ver a nota no topo do módulo.
    amount_cents: int
    # O que o banco/usuário disse, congelado. Nunca muda depois da criação.
    raw_description: str
    # O rótulo editável.
    user_description: str
    # `user_description or raw_description` — a regra de exibição, já resolvida.
    description: str
    counterparty_name: str
    counterparty_document: str
    operation_nature: str | None
    # Sempre `manual` nesta onda; existe no contrato porque a UI da 8.7 precisa distinguir o que foi
    # digitado do que veio de arquivo assim que a Onda 3 existir.
    source: str
    status: str
    ignored_reason: str
    created_at: datetime
    updated_at: datetime
