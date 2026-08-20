"""Contrato da busca global."""
from __future__ import annotations

from pydantic import BaseModel


class SearchItemOut(BaseModel):
    id: str
    title: str
    subtitle: str
    #: Caminho pronto para o router do front. Quem decide para onde o resultado leva é o backend,
    #: no registro — a tela não remonta rota a partir do tipo.
    route: str
    #: Só em `depth=deep`: na camada rasa não há corpo de onde extrair trecho.
    snippet: str | None = None


class SearchGroupOut(BaseModel):
    type: str
    has_more: bool
    #: Só em `depth=deep`. Contar na camada rasa custaria oito `count()` por tecla — e `has_more`
    #: não tem como mentir sobre um número que não anuncia (spec §6.1).
    total: int | None = None
    items: list[SearchItemOut]


class SearchOut(BaseModel):
    groups: list[SearchGroupOut]
