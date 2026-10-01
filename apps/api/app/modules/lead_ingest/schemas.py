"""Contrato de `POST /public/ingest/leads` — spec §6.1, CONGELADO.

O site codifica contra este formato EM PARALELO: renomear campo, evento ou código de status aqui
quebra o outro lado sem nenhum teste deste repositório ficar vermelho. Mudança de contrato é
mudança de spec primeiro.

O que é tolerado de propósito, para que uma variação inofensiva do site não vire 422 — e 422 é
erro PERMANENTE para a fila do site, que desiste de reenviar:
- `""` em nome/e-mail/telefone vale como ausente;
- `Toque` e `Pedido` aceitam campos extras (o site captura `gbraid`/`wbraid`, spec §5.1, e o
  contrato só lista `gclid`/`fbclid`);
- campos desconhecidos na raiz (inclusive um `tenant_id`) são IGNORADOS — o tenant vem do token.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

Evento = Literal[
    "lead",
    "carrinho_abandonado",
    "compra_aprovada",
    "renovacao",
    "reembolso",
    "chargeback",
    "cancelamento",
]
Situacao = Literal["resolvida", "apenas_kiwify", "sem_origem"]

# Teto anti-abuso do corpo. Os limites do CONTATO (50 tags de 40 caracteres) são aplicados na
# soma, com descarte registrado — ver `lead_ingest/tags.py`.
TagIn = Annotated[str, Field(max_length=200)]


class Contato(BaseModel):
    nome: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    telefone: str | None = Field(default=None, max_length=32)

    @field_validator("nome", "email", "telefone", mode="before")
    @classmethod
    def _vazio_e_ausente(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def _email_ou_telefone(self) -> Contato:
        if not self.email and not self.telefone:
            raise ValueError("contato exige e-mail ou telefone")
        return self


class Toque(BaseModel):
    model_config = ConfigDict(extra="allow")

    utm_source: str | None = Field(default=None, max_length=500)
    utm_medium: str | None = Field(default=None, max_length=500)
    utm_campaign: str | None = Field(default=None, max_length=500)
    utm_content: str | None = Field(default=None, max_length=500)
    utm_term: str | None = Field(default=None, max_length=500)
    gclid: str | None = Field(default=None, max_length=500)
    fbclid: str | None = Field(default=None, max_length=500)
    landing_path: str | None = Field(default=None, max_length=500)
    referrer_host: str | None = Field(default=None, max_length=255)
    ocorrido_em: datetime | None = None


class Atribuicao(BaseModel):
    situacao: Situacao
    primeiro_toque: Toque | None = None
    ultimo_toque: Toque | None = None


class Pedido(BaseModel):
    model_config = ConfigDict(extra="allow")

    provedor: str = Field(min_length=1, max_length=40)
    order_id: str = Field(min_length=1, max_length=120)
    plano: str | None = Field(default=None, max_length=80)
    periodo: str | None = Field(default=None, max_length=40)
    valor_bruto_centavos: int | None = Field(default=None, ge=0)
    valor_liquido_centavos: int | None = Field(default=None, ge=0)


class IngestIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    evento: Evento
    chave_idempotencia: str = Field(min_length=1, max_length=200)
    ocorrido_em: AwareDatetime
    contato: Contato
    tags: list[TagIn] = Field(default_factory=list, max_length=100)
    atribuicao: Atribuicao
    # Só nos eventos de venda (spec §6.1); opcional em todos, sem exigência por evento.
    pedido: Pedido | None = None


class IngestOut(BaseModel):
    """Corpo da resposta. O contrato do site depende só do STATUS; isto é para diagnóstico."""

    resultado: Literal["processado", "ja_processado"]
    contato_id: str | None
