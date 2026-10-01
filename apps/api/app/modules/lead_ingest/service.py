"""Ingestão de leads com atribuição: o site empurra PESSOAS, o e1p absorve (spec §6.2).

Uma chamada de `ingest`, na ordem:

1. **Reivindica a chave** (`registro.reivindicar`). Repetida e concluída → no-op (HTTP 200).
2. **Resolve o contato.** Evento de ENTRADA (lead, carrinho, compra) passa por
   `crm.absorb_lead` com `source="api"` — a porta única de lead, com a dedup de sempre (telefone
   normalizado, depois e-mail). Evento de PÓS-VENDA (renovação, reembolso, chargeback,
   cancelamento) de quem já existe NÃO passa: `absorb_lead` reabre card em coluna terminal, e um
   reembolso tiraria do Ganho quem comprou — o contrário da spec ("não movem o card").
3. **Soma tags** sem duplicar e sem estourar o limite do CRM; o que sobrar fica registrado.
4. **Grava o fato** na timeline (`module="comercial"`), com a atribuição no corpo.
5. **Fecha.** `compra_aprovada` leva o card ao Ganho (coluna `is_won`) no mesmo commit.
6. **Inscreve no funil do evento** (`config.funil_do_evento`), se não houver jornada viva nele.

`absorb_lead` commita no meio (é assim que ele é, e os outros chamadores dependem disso): a
reivindicação entra no MESMO commit do contato, e tags + fato + conclusão no seguinte. Ver a
docstring de `models.LeadIngestRecord` sobre a retomada quando o processo cai entre os dois.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import audit, facts
from app.core.facts import (
    COM_ASSINATURA_CANCELADA,
    COM_ASSINATURA_RENOVADA,
    COM_CARRINHO_ABANDONADO,
    COM_COMPRA_APROVADA,
    COM_COMPRA_CONTESTADA,
    COM_COMPRA_REEMBOLSADA,
    COM_LEAD_RECEBIDO,
)
from app.modules.crm import service as crm_service
from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.funnels import automation, engine
from app.modules.funnels.service import FunnelError
from app.modules.lead_ingest import config
from app.modules.lead_ingest import registro as registro_service
from app.modules.lead_ingest.schemas import Contato, IngestIn
from app.modules.lead_ingest.tags import somar_tags
from app.modules.settings import service as settings_service
from app.modules.settings.models import TenantProfile

ATOR = "integracao:lead_ingest"

logger = logging.getLogger("e1p.lead_ingest")

KIND_POR_EVENTO = {
    "lead": COM_LEAD_RECEBIDO,
    "carrinho_abandonado": COM_CARRINHO_ABANDONADO,
    "compra_aprovada": COM_COMPRA_APROVADA,
    "renovacao": COM_ASSINATURA_RENOVADA,
    "reembolso": COM_COMPRA_REEMBOLSADA,
    "chargeback": COM_COMPRA_CONTESTADA,
    "cancelamento": COM_ASSINATURA_CANCELADA,
}

# Título FIXO por evento: o plano e a origem vêm do site e vão no corpo. Interpolar texto de
# fora no título arriscaria a guarda de dinheiro de `facts.record` (um plano com "R$" viraria
# `FactError` → 500 → reenvio eterno da fila do site).
TITULO_POR_EVENTO = {
    "lead": "Deixou o contato no site",
    "carrinho_abandonado": "Abandonou o carrinho",
    "compra_aprovada": "Compra aprovada",
    "renovacao": "Assinatura renovada",
    "reembolso": "Compra reembolsada",
    "chargeback": "Chargeback na compra",
    "cancelamento": "Assinatura cancelada",
}

# `<produto>:<sufixo>` (spec §6.2). Cancelamento não é reembolso: tag própria.
SUFIXO_DE_PRODUTO = {
    "reembolso": "reembolso",
    "chargeback": "chargeback",
    "cancelamento": "cancelou",
}


@dataclass(frozen=True)
class ResultadoIngest:
    processado: bool  # False = chave já processada (no-op, HTTP 200)
    contato_id: str | None


def ingest(db: Session, *, tenant_id: str, dados: IngestIn) -> ResultadoIngest:
    """Processa um evento do site. A sessão já vem RLS-escopada no tenant DO TOKEN."""
    # Lido ANTES da reivindicação: `get_profile` commita quando cria o perfil, e um commit no
    # meio publicaria a reivindicação antes de existir contato.
    perfil = settings_service.get_profile(db, tenant_id)
    # Semeia as etapas e COMMITA antes da reivindicação: o seed pode dar rollback (corrida) e
    # levaria junto a chave reivindicada. Depois daqui `absorb_lead` não semeia mais nada.
    crm_service.ensure_stages(db, tenant_id)
    registro = registro_service.reivindicar(
        db,
        tenant_id=tenant_id,
        chave=dados.chave_idempotencia,
        evento=dados.evento,
        ocorrido_em=dados.ocorrido_em,
        payload=dados.model_dump(mode="json"),
    )
    if registro is None:
        return ResultadoIngest(
            processado=False,
            contato_id=registro_service.contato_da_chave(db, chave=dados.chave_idempotencia),
        )

    contato = _resolve_contato(db, tenant_id=tenant_id, dados=dados)

    # `absorb_lead` pode ter commitado, e o commit solta o FOR UPDATE da reivindicação: neste
    # intervalo a linha está visível, sem conclusão e sem trava. Retoma a trava agora e relê o
    # estado (populate_existing): se uma retentativa concorrente concluiu nesse meio-tempo, não
    # escreve nada de novo.
    registro = registro_service._buscar(db, chave=dados.chave_idempotencia, travar=True)
    if registro is None or registro.concluido_em is not None:
        return ResultadoIngest(
            processado=False, contato_id=registro.client_id if registro else contato.id
        )

    novas = list(dados.tags)
    prefixo = config.produto(perfil)
    sufixo = SUFIXO_DE_PRODUTO.get(dados.evento)
    if prefixo and sufixo:
        novas.append(f"{prefixo}:{sufixo}")
    contato.tags, descartadas = somar_tags(contato.tags, novas)

    facts.record(
        db,
        tenant_id=tenant_id,
        module="comercial",
        kind=KIND_POR_EVENTO[dados.evento],
        title=TITULO_POR_EVENTO[dados.evento],
        actor=ATOR,
        body=_corpo(dados, descartadas),
        client_id=contato.id,
        subject_type="lead_ingest",
        subject_id=registro.id,
        occurred_at=dados.ocorrido_em,
    )
    registro_service.concluir(registro, client_id=contato.id, tags_descartadas=descartadas)
    audit.record(
        db, tenant_id=tenant_id, actor=ATOR, action="lead_ingest.process", target=registro.id
    )
    _fechar(db, tenant_id=tenant_id, evento=dados.evento, contato=contato)
    _inscrever_no_funil(
        db, tenant_id=tenant_id, perfil=perfil, evento=dados.evento, contato_id=contato.id
    )
    return ResultadoIngest(processado=True, contato_id=contato.id)


def _resolve_contato(db: Session, *, tenant_id: str, dados: IngestIn) -> Client:
    contato = dados.contato
    if dados.evento not in config.EVENTOS_DE_ENTRADA:
        existente = crm_service.find_lead(db, phone=contato.telefone, email=contato.email)
        if existente is not None:
            return existente
    cliente, _novo = crm_service.absorb_lead(
        db,
        tenant_id=tenant_id,
        actor=ATOR,
        data=ClientCreate(
            name=_nome(contato), email=contato.email, phone=contato.telefone, source="api"
        ),
        # O funil é decidido pelo EVENTO, não pelo caminho automático do `source`.
        auto_enroll=False,
    )
    return cliente


def _nome(contato: Contato) -> str:
    """Kiwify e formulário mandam nome; carrinho abandonado às vezes não. O card precisa de um."""
    return (contato.nome or contato.email or contato.telefone or "")[:255]


def _corpo(dados: IngestIn, descartadas: list[str]) -> str:
    """A atribuição completa e o pedido — SEM valores (invariante 2 de `core/facts.py`).

    O fato não guarda dinheiro: o valor da venda mora no registro bruto
    (`lead_ingest_records.payload`) e, na origem, na Kiwify. Filtra por SUFIXO (`*_centavos`),
    em qualquer nível, e não por nome: `Pedido` e `Toque` aceitam campos extras, e um
    `taxa_centavos` que o site passe a mandar amanhã não pode entrar pela porta dos fundos.
    """
    return json.dumps(
        {
            "evento": dados.evento,
            "chave_idempotencia": dados.chave_idempotencia,
            "atribuicao": _sem_valores(dados.atribuicao.model_dump(mode="json")),
            "pedido": _sem_valores(
                dados.pedido.model_dump(mode="json") if dados.pedido is not None else None
            ),
            "tags_descartadas": descartadas,
        },
        ensure_ascii=False,
        indent=2,
    )


def _sem_valores(valor):
    """Remove, em qualquer profundidade, as chaves `*_centavos`."""
    if isinstance(valor, dict):
        return {k: _sem_valores(v) for k, v in valor.items() if not k.endswith("_centavos")}
    if isinstance(valor, list):
        return [_sem_valores(v) for v in valor]
    return valor


def _fechar(db: Session, *, tenant_id: str, evento: str, contato: Client) -> None:
    """Commita o que está pendente; em `compra_aprovada`, junto com a ida ao Ganho.

    `move_client` commita a sessão inteira: tags, fato e conclusão do registro entram no MESMO
    commit da mudança de etapa, e o aviso de "movido para Ganho" (notifications) só sai depois
    dele. Reembolso, chargeback e cancelamento NÃO movem o card (spec §6.2): a venda aconteceu,
    e o que mudou depois fica em tag e fato, não apagado.
    """
    if evento != "compra_aprovada":
        db.commit()
        return
    ganho = next((s for s in crm_service.ensure_stages(db, tenant_id) if s.is_won), None)
    if ganho is None:
        logger.warning(
            "[lead_ingest] tenant=%s sem coluna de Ganho ativa; compra registrada sem mover o "
            "card %s",
            tenant_id, contato.id,
        )
        db.commit()
        return
    if contato.stage_id == ganho.id:
        db.commit()
        return
    crm_service.move_client(
        db, client_id=contato.id, tenant_id=tenant_id, actor=ATOR, by_ai=False,
        stage_id=ganho.id,
    )


def _inscrever_no_funil(
    db: Session, *, tenant_id: str, perfil: TenantProfile, evento: str, contato_id: str
) -> None:
    """Funil por evento (spec §6.4). Melhor esforço: o lead já está commitado.

    Mesma contenção do caminho automático (`automation.on_client_returned`): quem já anda no
    funil não recomeça do zero porque o site mandou outro evento.
    """
    funil_id = config.funil_do_evento(perfil, evento)
    if not funil_id or automation.jornada_viva(db, funnel_id=funil_id, client_id=contato_id):
        return
    try:
        engine.enroll(
            db, tenant_id=tenant_id, actor=ATOR, funnel_id=funil_id, client_id=contato_id
        )
    except FunnelError:
        # Funil apagado, vazio ou sem entrada: não pode virar 500 — o site reenviaria e
        # receberia 200 (chave concluída), e a inscrição continuaria sem acontecer em silêncio.
        logger.warning(
            "[lead_ingest] inscrição falhou tenant=%s funil=%s evento=%s cliente=%s",
            tenant_id, funil_id, evento, contato_id,
        )
