"""Contrato HTTP do DNA.

A pergunta viaja INTEIRA para o front (texto e opções), em vez de o front ter uma cópia do
catálogo: duas cópias divergem no primeiro ajuste de texto, e a versão errada é sempre a que o
dono está lendo.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.modules.dna import catalog


class OpcaoOut(BaseModel):
    rotulo: str
    valor: Any | None


class PerguntaOut(BaseModel):
    key: str
    classe: str
    eixo: str
    texto: str
    formato: str
    opcoes: list[OpcaoOut]


class RespostaIn(BaseModel):
    valor: Any | None = None
    source: str


class PularIn(BaseModel):
    source: str


def to_out(pergunta: catalog.Pergunta) -> PerguntaOut:
    return PerguntaOut(
        key=pergunta.key,
        classe=pergunta.classe,
        eixo=pergunta.eixo,
        texto=pergunta.texto,
        formato=pergunta.formato,
        opcoes=[OpcaoOut(rotulo=o.rotulo, valor=o.valor) for o in pergunta.opcoes],
    )
