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


class NucleoEventoIn(BaseModel):
    """Corpo de `POST /dna/nucleo/{evento}`.

    `exibidas` é o **denominador VISTO** e só faz sentido no `open` — o `abandon` manda `{}`. Por
    isso o campo é opcional no schema e a obrigatoriedade é decidida por evento no router: um
    `int` obrigatório aqui recusaria o `abandon`, e um default `0` gravaria "vi zero perguntas",
    que é afirmação falsa em vez de campo ausente.
    """

    exibidas: int | None = None


def to_out(pergunta: catalog.Pergunta) -> PerguntaOut:
    return PerguntaOut(
        key=pergunta.key,
        classe=pergunta.classe,
        eixo=pergunta.eixo,
        texto=pergunta.texto,
        formato=pergunta.formato,
        opcoes=[OpcaoOut(rotulo=o.rotulo, valor=o.valor) for o in pergunta.opcoes],
    )
