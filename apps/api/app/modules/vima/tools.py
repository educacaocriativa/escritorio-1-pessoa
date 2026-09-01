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
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.core.tz import day_window_utc, tenant_zone
from app.modules.agenda import service as agenda_service
from app.modules.agenda.models import (
    KIND_ATENDIMENTO,
    KIND_AUDIENCIA,
    KIND_BLOQUEIO,
    KIND_LEMBRETE,
    KIND_REUNIAO,
    AgendaEvent,
)
from app.modules.agenda.schemas import EventCreate
from app.modules.crm import service as crm_service
from app.modules.crm import timeline as crm_timeline
from app.modules.financial_intelligence import projection as projection_service
from app.modules.juridico import service as juridico_service
from app.modules.marketing import service as marketing_service
from app.modules.payables import service as payables_service
from app.modules.receivables import service as receivables_service
from app.modules.settings.service import hoje_do_tenant, tenant_timezone
from app.modules.stock import service as stock_service
from app.modules.vima import absences
from app.modules.vima.permissions import pode_ver


def _consultar_recebiveis(
    db: Session, _user: CurrentUser, _entrada: dict[str, Any],
) -> dict[str, Any]:
    return receivables_service.summary(db)


def _consultar_pagaveis(
    db: Session, _user: CurrentUser, _entrada: dict[str, Any],
) -> dict[str, Any]:
    return payables_service.summary(db)


def _consultar_projecao_caixa(
    db: Session, _user: CurrentUser, _entrada: dict[str, Any],
) -> dict[str, Any]:
    return asdict(projection_service.cash_projection(db))


# Tipos que fazem sentido nascer de uma conversa — exclui prazo/cobranca_*/google, derivados
# de outro módulo ou de sync externo.
_TIPOS_CRIAVEIS_POR_CHAT = {
    KIND_ATENDIMENTO, KIND_REUNIAO, KIND_AUDIENCIA, KIND_BLOQUEIO, KIND_LEMBRETE,
}
_DURACAO_PADRAO = timedelta(hours=1)
# Mensagem idêntica nas três ferramentas de escrita — extraída para não triplicar o texto.
_ERRO_CONFIRMACAO = (
    "peça a confirmação explícita do dono antes de chamar esta ferramenta de novo "
    "com confirmado=true"
)


def _evento_json(e: AgendaEvent) -> dict[str, Any]:
    """Serialização compartilhada entre `consultar_agenda` e as ferramentas de escrita — o `id`
    é o que permite à Claude referenciar de volta, numa chamada seguinte, um evento achado por
    consulta (`cancelar_compromisso`/`remarcar_compromisso` operam por `event_id`)."""
    return {
        "id": e.id,
        "titulo": e.title,
        "inicio": _aware(e.starts_at).isoformat(),
        "fim": _aware(e.ends_at).isoformat(),
        "dia_inteiro": e.all_day,
        "status": e.status,
        "tipo": e.kind,
    }


def _combinar_utc(dia: date, hora: time, tz_name: str) -> datetime:
    """Combina uma data-calendário e uma hora de parede NO FUSO do tenant, convertidas para
    UTC — mesma disciplina de `day_window_utc`, mas para um instante específico em vez da
    meia-noite do dia."""
    return datetime.combine(dia, hora, tzinfo=tenant_zone(tz_name)).astimezone(UTC)


def _consultar_agenda(
    db: Session, _user: CurrentUser, entrada: dict[str, Any],
) -> dict[str, Any]:
    tz = tenant_timezone(db)
    inicio = date.fromisoformat(entrada["data_inicio"])
    fim = date.fromisoformat(entrada.get("data_fim") or entrada["data_inicio"])
    janela_inicio, _ = day_window_utc(inicio, tz)
    _, janela_fim = day_window_utc(fim, tz)
    eventos = agenda_service.list_events(
        db, start=janela_inicio, end=janela_fim, exclude_cancelled=True, limit=50,
    )
    return {"eventos": [_evento_json(e) for e in eventos]}


def _criar_compromisso(
    db: Session, user: CurrentUser, entrada: dict[str, Any],
) -> dict[str, Any]:
    # Confirmação ANTES do tipo (mesma ordem de cancelar/remarcar): uma chamada não confirmada
    # com tipo inválido deve pedir confirmação, não reprovar o tipo — nudge o modelo para o
    # reparo certo (peça confirmação de novo) em vez de um erro que ele pode tentar "consertar"
    # trocando o tipo por conta própria.
    if not entrada.get("confirmado"):
        return {"erro": _ERRO_CONFIRMACAO}

    tipo = entrada["tipo"]
    if tipo not in _TIPOS_CRIAVEIS_POR_CHAT:
        raise ValueError(f"tipo inválido para criar por chat: {tipo}")

    tz = tenant_timezone(db)
    dia = date.fromisoformat(entrada["data"])
    starts_at = _combinar_utc(dia, time.fromisoformat(entrada["hora_inicio"]), tz)
    if entrada.get("hora_fim"):
        ends_at = _combinar_utc(dia, time.fromisoformat(entrada["hora_fim"]), tz)
    else:
        ends_at = starts_at + _DURACAO_PADRAO
    if ends_at <= starts_at:
        raise ValueError("hora_fim deve ser depois de hora_inicio")

    client_id = None
    nome_cliente = entrada.get("cliente")
    cliente_nao_encontrado = False
    if nome_cliente:
        clientes = crm_service.list_clients(db, search=nome_cliente, limit=1)
        if clientes:
            client_id = clientes[0].id
        else:
            cliente_nao_encontrado = True

    evento, conflitos = agenda_service.create_event(
        db, tenant_id=user.tenant_id, actor=user.user_id, by_ai=True,
        data=EventCreate(
            title=entrada["titulo"], kind=tipo, starts_at=starts_at, ends_at=ends_at,
            location=entrada.get("local") or "", source="vima", client_id=client_id,
        ),
    )
    resultado: dict[str, Any] = {
        "compromisso": _evento_json(evento),
        "conflitos": [_evento_json(c) for c in conflitos],
    }
    if cliente_nao_encontrado:
        resultado["aviso"] = (
            f"cliente '{nome_cliente}' não encontrado no cadastro; criado sem vínculo"
        )
    return resultado


def _cancelar_compromisso(
    db: Session, user: CurrentUser, entrada: dict[str, Any]
) -> dict[str, Any]:
    if not entrada.get("confirmado"):
        return {"erro": _ERRO_CONFIRMACAO}
    # Mesma restrição de tipo de `criar_compromisso` (Regra de Ouro nº 3 / achado da revisão
    # final): sem isto, `consultar_agenda` devolve eventos de QUALQUER tipo e a Vima podia
    # cancelar um prazo jurídico ou uma cobrança por chat — pior que criar, já que cancelar é
    # terminal (STATUS_CANCELLED não sai de TERMINAL_STATUSES). Busca o evento ANTES de cancelar
    # para checar o tipo — uma query a mais, aceitável pela correção que ela compra.
    evento = agenda_service.get_event(db, entrada["event_id"])
    if evento.kind not in _TIPOS_CRIAVEIS_POR_CHAT:
        raise ValueError(f"tipo não editável por chat: {evento.kind}")
    evento = agenda_service.cancel_event(
        db, event_id=entrada["event_id"], tenant_id=user.tenant_id, actor=user.user_id,
        by_ai=True,
    )
    return {"compromisso": _evento_json(evento)}


def _remarcar_compromisso(
    db: Session, user: CurrentUser, entrada: dict[str, Any]
) -> dict[str, Any]:
    if not entrada.get("confirmado"):
        return {"erro": _ERRO_CONFIRMACAO}

    evento_atual = agenda_service.get_event(db, entrada["event_id"])
    # Mesma restrição de tipo de `cancelar_compromisso`/`criar_compromisso` — reusa o evento já
    # buscado para calcular `duracao_original`, sem query extra.
    if evento_atual.kind not in _TIPOS_CRIAVEIS_POR_CHAT:
        raise ValueError(f"tipo não editável por chat: {evento_atual.kind}")
    duracao_original = evento_atual.ends_at - evento_atual.starts_at

    tz = tenant_timezone(db)
    dia = date.fromisoformat(entrada["nova_data"])
    novo_inicio = _combinar_utc(dia, time.fromisoformat(entrada["nova_hora_inicio"]), tz)
    if entrada.get("nova_hora_fim"):
        novo_fim = _combinar_utc(dia, time.fromisoformat(entrada["nova_hora_fim"]), tz)
    else:
        novo_fim = novo_inicio + duracao_original
    if novo_fim <= novo_inicio:
        raise ValueError("nova_hora_fim deve ser depois de nova_hora_inicio")

    evento, conflitos = agenda_service.reschedule_event(
        db, event_id=entrada["event_id"], tenant_id=user.tenant_id, actor=user.user_id,
        starts_at=novo_inicio, ends_at=novo_fim, by_ai=True,
    )
    return {
        "compromisso": _evento_json(evento),
        "conflitos": [_evento_json(c) for c in conflitos],
    }


def _consultar_cliente(
    db: Session, _user: CurrentUser, entrada: dict[str, Any],
) -> dict[str, Any]:
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


def _aware(dt: datetime) -> datetime:
    # SQLite devolve sem fuso; a comparação é sempre em UTC (mesma convenção de vima/service.py).
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _consultar_clientes_recentes(
    db: Session, _user: CurrentUser, entrada: dict[str, Any],
) -> dict[str, Any]:
    limite = int(entrada.get("limite") or 5)
    clientes = crm_service.list_recent_clients(db, limit=200)
    dias = entrada.get("dias")
    if dias:
        corte = datetime.now(UTC) - timedelta(days=int(dias))
        clientes = [c for c in clientes if _aware(c.created_at) >= corte]
    return {
        "clientes": [
            {
                "id": c.id,
                "nome": c.name,
                "telefone": c.phone,
                "tags": c.tags,
                "origem": c.source,
                "entrou_em": c.created_at.isoformat(),
            }
            for c in clientes[:limite]
        ]
    }


def _consultar_documentos_juridicos(
    db: Session, _user: CurrentUser, entrada: dict[str, Any],
) -> dict[str, Any]:
    client_id = None
    if entrada.get("cliente"):
        clientes = crm_service.list_clients(db, search=entrada["cliente"], limit=1)
        if not clientes:
            return {"documentos": []}
        client_id = clientes[0].id
    documentos = juridico_service.list_documents(db, client_id=client_id)
    dias = entrada.get("dias")
    if dias:
        limite = datetime.now(UTC) - timedelta(days=int(dias))
        documentos = [d for d in documentos if _aware(d.created_at) >= limite]
    return {
        "documentos": [
            {
                "titulo": d.title,
                "skill": d.skill,
                "categoria": d.category,
                "cliente": juridico_service.client_name(db, d.client_id),
                "gerado_em": d.created_at.isoformat(),
                "status": d.status,
            }
            for d in documentos[:20]
        ]
    }


def _consultar_campanhas_marketing(
    db: Session, _user: CurrentUser, entrada: dict[str, Any],
) -> dict[str, Any]:
    campanhas = marketing_service.list_carousels(db)
    dias = entrada.get("dias")
    if dias:
        limite = datetime.now(UTC) - timedelta(days=int(dias))
        campanhas = [c for c in campanhas if _aware(c.created_at) >= limite]
    return {
        "campanhas": [
            {
                "tema": c.topic,
                "plataforma": c.platform,
                "status": c.status,
                "gerado_em": c.created_at.isoformat(),
            }
            for c in campanhas[:20]
        ]
    }


def _consultar_estoque_baixo(
    db: Session, _user: CurrentUser, _entrada: dict[str, Any],
) -> dict[str, Any]:
    itens = stock_service.low_stock(db)
    return {
        "itens": [
            {
                "nome": i.name,
                "quantidade": i.quantity,
                "minimo": i.min_quantity,
                "unidade": i.unit,
            }
            for i in itens
        ]
    }


def _consultar_item_estoque(
    db: Session, _user: CurrentUser, entrada: dict[str, Any],
) -> dict[str, Any]:
    nome = entrada["nome"].strip().lower()
    itens = [
        i for i in stock_service.list_items(db, only_active=True) if nome in i.name.lower()
    ]
    return {
        "itens": [
            {
                "nome": i.name,
                "quantidade": i.quantity,
                "minimo": i.min_quantity,
                "unidade": i.unit,
                "baixo": i.quantity <= i.min_quantity,
            }
            for i in itens
        ]
    }


def _consultar_clientes_atencao(
    db: Session, _user: CurrentUser, _entrada: dict[str, Any],
) -> dict[str, Any]:
    agora = datetime.now(UTC)
    hoje = hoje_do_tenant(db, now=agora)
    ausencias = absences.clientes_em_atencao(db, hoje=hoje, agora=agora)
    return {
        "clientes_em_atencao": [
            {
                "descricao": a.title,
                "tipo": a.kind,
                "dias": a.dias,
                "cliente_id": a.client_id,
            }
            for a in ausencias
        ]
    }


@dataclass
class Ferramenta:
    nome: str
    # Nome de módulo em `User.allowed_modules` — decide se a Claude VÊ esta ferramenta.
    modulo: str
    # Schema no formato de tool-use da Anthropic (`name`/`description`/`input_schema`).
    definicao: dict[str, Any]
    # `user` existe para as ferramentas de ESCRITA carimbarem tenant_id/actor — as de leitura
    # ignoram (mesma convenção de parâmetro não usado do resto do arquivo: `_user`).
    executar: Callable[[Session, CurrentUser, dict[str, Any]], dict[str, Any]]


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
        nome="criar_compromisso",
        modulo="agenda",
        definicao={
            "name": "criar_compromisso",
            "description": (
                "Cria um novo compromisso na agenda. SÓ chame com confirmado=true depois que o "
                "dono confirmar explicitamente os detalhes numa mensagem anterior — antes "
                "disso, resuma o que você entendeu e peça a confirmação em texto."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Título do compromisso."},
                    "tipo": {
                        "type": "string",
                        "enum": ["atendimento", "reuniao", "audiencia", "bloqueio", "lembrete"],
                        "description": "Tipo do compromisso.",
                    },
                    "data": {"type": "string", "description": "Data no formato AAAA-MM-DD."},
                    "hora_inicio": {"type": "string", "description": "Hora de início, HH:MM."},
                    "hora_fim": {
                        "type": "string",
                        "description": (
                            "Hora de término, HH:MM. Se omitida, dura 1h. (mesmo dia de data — "
                            "não representa compromissos que atravessam a meia-noite)"
                        ),
                    },
                    "cliente": {
                        "type": "string",
                        "description": "Nome ou parte do nome do cliente, se houver um vinculado.",
                    },
                    "local": {"type": "string", "description": "Local do compromisso, se houver."},
                    "confirmado": {
                        "type": "boolean",
                        "description": (
                            "true SOMENTE depois que o dono confirmou explicitamente numa "
                            "mensagem anterior."
                        ),
                    },
                },
                "required": ["titulo", "tipo", "data", "hora_inicio", "confirmado"],
            },
        },
        executar=_criar_compromisso,
    ),
    Ferramenta(
        nome="cancelar_compromisso",
        modulo="agenda",
        definicao={
            "name": "cancelar_compromisso",
            "description": (
                "Cancela um compromisso existente. Use consultar_agenda primeiro para achar o "
                "event_id certo. SÓ chame com confirmado=true depois que o dono confirmar "
                "explicitamente qual compromisso cancelar numa mensagem anterior."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Id do compromisso, obtido via consultar_agenda.",
                    },
                    "confirmado": {
                        "type": "boolean",
                        "description": (
                            "true SOMENTE depois que o dono confirmou explicitamente numa "
                            "mensagem anterior."
                        ),
                    },
                },
                "required": ["event_id", "confirmado"],
            },
        },
        executar=_cancelar_compromisso,
    ),
    Ferramenta(
        nome="remarcar_compromisso",
        modulo="agenda",
        definicao={
            "name": "remarcar_compromisso",
            "description": (
                "Muda a data/hora de um compromisso existente. Use consultar_agenda primeiro "
                "para achar o event_id certo. SÓ chame com confirmado=true depois que o dono "
                "confirmar explicitamente o novo horário numa mensagem anterior."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Id do compromisso, obtido via consultar_agenda.",
                    },
                    "nova_data": {"type": "string", "description": "Nova data, AAAA-MM-DD."},
                    "nova_hora_inicio": {
                        "type": "string", "description": "Nova hora de início, HH:MM.",
                    },
                    "nova_hora_fim": {
                        "type": "string",
                        "description": (
                            "Nova hora de término, HH:MM. Se omitida, preserva a duração "
                            "original. (mesmo dia de nova_data — não representa compromissos "
                            "que atravessam a meia-noite)"
                        ),
                    },
                    "confirmado": {
                        "type": "boolean",
                        "description": (
                            "true SOMENTE depois que o dono confirmou explicitamente numa "
                            "mensagem anterior."
                        ),
                    },
                },
                "required": ["event_id", "nova_data", "nova_hora_inicio", "confirmado"],
            },
        },
        executar=_remarcar_compromisso,
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
    Ferramenta(
        nome="consultar_clientes_recentes",
        modulo="crm",
        definicao={
            "name": "consultar_clientes_recentes",
            "description": (
                "Lista os clientes mais recentemente adicionados ao CRM, do mais novo para o "
                "mais antigo, com nome, telefone, tags, origem e quando entraram. Use para "
                "perguntas como 'qual foi o último contato/cliente que entrou no CRM' (omita "
                "'dias' e olhe o primeiro da lista) ou 'quem entrou ontem/essa semana' "
                "(use 'dias': 1 para ontem, 7 para essa semana)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "dias": {
                        "type": "integer",
                        "description": (
                            "Só considera clientes entrados nos últimos N dias. Omita para não "
                            "filtrar por data."
                        ),
                    },
                    "limite": {
                        "type": "integer",
                        "description": (
                            "Quantos clientes retornar, do mais novo para o mais antigo. "
                            "Padrão 5."
                        ),
                    },
                },
            },
        },
        executar=_consultar_clientes_recentes,
    ),
    Ferramenta(
        nome="consultar_documentos_juridicos",
        modulo="juridico",
        definicao={
            "name": "consultar_documentos_juridicos",
            "description": (
                "Lista documentos jurídicos já gerados (petições, contratos, pareceres etc.), "
                "opcionalmente filtrados por cliente (nome ou parte dele) e/ou por quantos dias "
                "atrás foram gerados. Use para perguntas como 'que documentos jurídicos eu já "
                "gerei para o cliente X?' ou 'quais documentos foram gerados essa semana?'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "cliente": {
                        "type": "string",
                        "description": "Nome ou parte do nome do cliente, se a busca for por ele.",
                    },
                    "dias": {
                        "type": "integer",
                        "description": (
                            "Só considera documentos gerados nos últimos N dias. Omita para não "
                            "filtrar por data."
                        ),
                    },
                },
            },
        },
        executar=_consultar_documentos_juridicos,
    ),
    Ferramenta(
        nome="consultar_campanhas_marketing",
        modulo="marketing",
        definicao={
            "name": "consultar_campanhas_marketing",
            "description": (
                "Lista carrosséis/campanhas de marketing já gerados (tema, plataforma, status), "
                "opcionalmente só os dos últimos N dias. Use para perguntas sobre que campanhas "
                "de marketing foram criadas recentemente e sobre qual tema."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "dias": {
                        "type": "integer",
                        "description": (
                            "Só considera campanhas geradas nos últimos N dias. Omita para não "
                            "filtrar por data."
                        ),
                    },
                },
            },
        },
        executar=_consultar_campanhas_marketing,
    ),
    Ferramenta(
        nome="consultar_estoque_baixo",
        modulo="stock",
        definicao={
            "name": "consultar_estoque_baixo",
            "description": (
                "Lista os itens de estoque cuja quantidade já caiu para o mínimo configurado ou "
                "abaixo dele. Use para perguntas como 'o que está com estoque baixo?'."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        executar=_consultar_estoque_baixo,
    ),
    Ferramenta(
        nome="consultar_item_estoque",
        modulo="stock",
        definicao={
            "name": "consultar_item_estoque",
            "description": (
                "Busca item(ns) de estoque pelo nome (ou parte dele) e devolve quantidade atual, "
                "mínimo configurado e se está baixo. Use para perguntas sobre quanto tem em "
                "estoque de um item específico."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string", "description": "Nome ou parte do nome do item."},
                },
                "required": ["nome"],
            },
        },
        executar=_consultar_item_estoque,
    ),
    Ferramenta(
        nome="consultar_clientes_atencao",
        modulo="comercial",
        definicao={
            "name": "consultar_clientes_atencao",
            "description": (
                "Lista clientes que precisam de atenção agora: conversa de WhatsApp que "
                "escreveu e ainda não foi respondida, contato que sumiu (sem falar há muitos "
                "dias) ou negociação parada na mesma etapa do funil há tempo demais. Use para "
                "perguntas como 'qual cliente precisa de atenção hoje?', 'estou deixando "
                "alguém esperando?' ou 'algum contato sumiu?'."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        executar=_consultar_clientes_atencao,
    ),
]


def ferramentas_disponiveis(user: CurrentUser) -> list[Ferramenta]:
    """As ferramentas que este usuário PODE VER — o filtro decide o que a Claude enxerga, não o
    que ela esconde depois de já ter visto."""
    return [f for f in FERRAMENTAS if pode_ver(user, f.modulo)]


def executar(db: Session, user: CurrentUser, nome: str, entrada: dict[str, Any]) -> str:
    """Executa uma ferramenta pelo nome, respeitando a MESMA lista que foi oferecida à Claude.

    Nunca deixa uma exceção subir crua: o loop de tool-use precisa de um `tool_result` sempre,
    mesmo quando a consulta/escrita falha — a Claude é instruída (ver `vima/pergunta.py`) a
    dizer que não conseguiu, nunca a inventar (Artigo IV, No Invention). Erro de domínio
    (`AgendaError`) e de formato (`ValueError`) chegam com a mensagem REAL — a genérica é só
    para o que não se sabe explicar.
    """
    disponiveis = {f.nome: f for f in ferramentas_disponiveis(user)}
    ferramenta = disponiveis.get(nome)
    if ferramenta is None:
        return json.dumps({"erro": "ferramenta indisponível para este usuário"})
    try:
        resultado = ferramenta.executar(db, user, entrada)
    except (agenda_service.AgendaError, ValueError) as exc:
        # Defesa em profundidade: nenhum caminho hoje deixa a sessão suja neste ponto (todo
        # `raise` acontece antes de qualquer mutação), mas a sessão sobrevive a até 6 turnos de
        # tool-use (`ai.complete_with_tools`'s `max_tool_turns`) — um autoflush futuro não deve
        # arriscar commitar estado parcial de uma escrita que falhou no meio.
        db.rollback()
        return json.dumps({"erro": str(exc)})
    except Exception:  # noqa: BLE001 — tool_result sempre existe; a Claude decide o que dizer.
        db.rollback()
        return json.dumps({"erro": "não foi possível consultar isso agora"})
    return json.dumps(resultado, default=str, ensure_ascii=False)
