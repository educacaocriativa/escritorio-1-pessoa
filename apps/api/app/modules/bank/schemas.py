"""Schemas da conta bancária (Story 8.2).

**Nenhum saldo trafega sem procedência** (Regra dos Planos §1.3c): todo campo que carrega saldo tem
um irmão `*_origem` preenchido com uma constante de `app.core.money_planes` — nunca uma string
literal solta. Aqui a origem é sempre `ORIGEM_BANCO`, porque o número vem do plano 3.
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
    # leitura por `service.derived_balance`. Enquanto `bank_transactions` não existir (Story 8.3),
    # ele é igual a `opening_balance_cents`.
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
