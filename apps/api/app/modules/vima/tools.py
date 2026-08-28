"""Ferramentas de leitura que a Vima oferece à Claude no loop de `POST /vima/pergunta`.

Cada ferramenta é um wrapper fino sobre um serviço determinístico que já existe — a Claude
escolhe QUAL consultar, nunca calcula o número ela mesma (mesma disciplina de
`vima/absences.py`: "a IA só NARRA, nunca origina número"). O filtro de permissão decide quais
ferramentas a Claude sequer VÊ, não quais respostas aparecem depois de já vistas — mesmo
princípio de `vima/service.gerar_ou_ler` para o briefing.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.core.tz import day_window_utc
from app.modules.agenda import service as agenda_service
from app.modules.crm import service as crm_service
from app.modules.crm import timeline as crm_timeline
from app.modules.financial_intelligence import projection as projection_service
from app.modules.payables import service as payables_service
from app.modules.receivables import service as receivables_service
from app.modules.settings.service import tenant_timezone
from app.modules.vima.permissions import pode_ver


def _consultar_recebiveis(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:
    return receivables_service.summary(db)


def _consultar_pagaveis(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:
    return payables_service.summary(db)


def _consultar_projecao_caixa(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:
    return asdict(projection_service.cash_projection(db))


def _consultar_agenda(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:
    tz = tenant_timezone(db)
    inicio = date.fromisoformat(entrada["data_inicio"])
    fim = date.fromisoformat(entrada.get("data_fim") or entrada["data_inicio"])
    janela_inicio, _ = day_window_utc(inicio, tz)
    _, janela_fim = day_window_utc(fim, tz)
    eventos = agenda_service.list_events(
        db, start=janela_inicio, end=janela_fim, exclude_cancelled=True, limit=50,
    )
    return {
        "eventos": [
            {
                "titulo": e.title,
                "inicio": e.starts_at.isoformat(),
                "fim": e.ends_at.isoformat(),
                "dia_inteiro": e.all_day,
                "status": e.status,
                "tipo": e.kind,
            }
            for e in eventos
        ]
    }


def _consultar_cliente(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:
    nome = entrada["nome"]
    clientes = crm_service.list_clients(db, search=nome, limit=5)
    resultado = []
    for cliente in clientes:
        entradas, _ = crm_timeline.build(db, client_id=cliente.id, limit=1)
        ultima = entradas[0] if entradas else None
        resultado.append({
            "id": cliente.id,
            "nome": cliente.name,
            "telefone": cliente.phone,
            "tags": cliente.tags,
            "origem": cliente.source,
            "ultima_interacao": (
                {"titulo": ultima["title"], "quando": ultima["at"].isoformat()}
                if ultima else None
            ),
        })
    return {"clientes": resultado}


@dataclass
class Ferramenta:
    nome: str
    # Nome de módulo em `User.allowed_modules` — decide se a Claude VÊ esta ferramenta.
    modulo: str
    # Schema no formato de tool-use da Anthropic (`name`/`description`/`input_schema`).
    definicao: dict[str, Any]
    executar: Callable[[Session, dict[str, Any]], dict[str, Any]]


FERRAMENTAS: list[Ferramenta] = [
    Ferramenta(
        nome="consultar_recebiveis",
        modulo="receivables",
        definicao={
            "name": "consultar_recebiveis",
            "description": (
                "Resumo do que o dono tem a RECEBER de clientes: total em aberto, vencido, já "
                "recebido, e as contagens de cada um. Use para perguntas sobre dinheiro a "
                "receber."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        executar=_consultar_recebiveis,
    ),
    Ferramenta(
        nome="consultar_pagaveis",
        modulo="payables",
        definicao={
            "name": "consultar_pagaveis",
            "description": (
                "Resumo do que o dono tem a PAGAR: total em aberto, vencido, da semana, do mês, "
                "já pago no mês. Use para perguntas sobre dinheiro a pagar ou despesas."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        executar=_consultar_pagaveis,
    ),
    Ferramenta(
        nome="consultar_projecao_caixa",
        modulo="financial_intelligence",
        definicao={
            "name": "consultar_projecao_caixa",
            "description": (
                "Projeção de caixa em 30/60/90 dias e o runway (quantos dias o caixa aguenta no "
                "ritmo atual de gasto). Use para perguntas sobre quanto tempo o caixa aguenta ou "
                "como vai ficar o saldo."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        executar=_consultar_projecao_caixa,
    ),
    Ferramenta(
        nome="consultar_agenda",
        modulo="agenda",
        definicao={
            "name": "consultar_agenda",
            "description": (
                "Compromissos da agenda entre duas datas (inclusive). Use para perguntas sobre "
                "o que o dono tem marcado num dia ou período."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "data_inicio": {
                        "type": "string",
                        "description": "Data no formato AAAA-MM-DD.",
                    },
                    "data_fim": {
                        "type": "string",
                        "description": (
                            "Data final no formato AAAA-MM-DD. Se omitida, usa a mesma de "
                            "data_inicio."
                        ),
                    },
                },
                "required": ["data_inicio"],
            },
        },
        executar=_consultar_agenda,
    ),
    Ferramenta(
        nome="consultar_cliente",
        modulo="crm",
        definicao={
            "name": "consultar_cliente",
            "description": (
                "Busca cliente(s) pelo nome (ou parte dele) e devolve contato, tags, origem e a "
                "última interação registrada. Use para perguntas sobre um cliente específico."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string", "description": "Nome ou parte do nome do cliente."},
                },
                "required": ["nome"],
            },
        },
        executar=_consultar_cliente,
    ),
]


def ferramentas_disponiveis(user: CurrentUser) -> list[Ferramenta]:
    """As ferramentas que este usuário PODE VER — o filtro decide o que a Claude enxerga, não o
    que ela esconde depois de já ter visto."""
    return [f for f in FERRAMENTAS if pode_ver(user, f.modulo)]


def executar(db: Session, user: CurrentUser, nome: str, entrada: dict[str, Any]) -> str:
    """Executa uma ferramenta pelo nome, respeitando a MESMA lista que foi oferecida à Claude.

    Nunca deixa uma exceção subir crua: o loop de tool-use precisa de um `tool_result` sempre,
    mesmo quando a consulta falha — a Claude é instruída (ver `vima/pergunta.py`) a dizer que
    não conseguiu, nunca a inventar (Artigo IV, No Invention).
    """
    disponiveis = {f.nome: f for f in ferramentas_disponiveis(user)}
    ferramenta = disponiveis.get(nome)
    if ferramenta is None:
        return json.dumps({"erro": "ferramenta indisponível para este usuário"})
    try:
        resultado = ferramenta.executar(db, entrada)
    except Exception:  # noqa: BLE001 — tool_result sempre existe; a Claude decide o que dizer.
        return json.dumps({"erro": "não foi possível consultar isso agora"})
    return json.dumps(resultado, default=str, ensure_ascii=False)
