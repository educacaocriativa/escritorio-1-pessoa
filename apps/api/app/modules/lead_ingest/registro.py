"""Reivindicar e concluir uma chave de idempotência (ver `models.LeadIngestRecord`)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.lead_ingest.models import LeadIngestRecord


def _consulta(chave: str, *, travar: bool = False):
    # Sem filtro de tenant: a sessão já vem RLS-escopada (Regra de Ouro nº 1).
    consulta = select(LeadIngestRecord).where(LeadIngestRecord.chave_idempotencia == chave)
    if not travar:
        return consulta
    # `populate_existing`: se a linha já está no identity map da sessão, o FOR UPDATE traz o
    # estado atual do banco em vez do cacheado (um `concluido_em=None` velho reprocessaria).
    return consulta.with_for_update().execution_options(populate_existing=True)


def _buscar(db: Session, *, chave: str, travar: bool = False) -> LeadIngestRecord | None:
    """`travar=True` toma FOR UPDATE: duas retomadas simultâneas não passam juntas."""
    return db.scalar(_consulta(chave, travar=travar))


def reivindicar(
    db: Session,
    *,
    tenant_id: str,
    chave: str,
    evento: str,
    ocorrido_em: datetime,
    payload: dict,
) -> LeadIngestRecord | None:
    """Devolve a linha a processar, ou `None` se a chave já foi (ou está sendo) processada.

    Linha existente SEM `concluido_em` é devolvida para retomada (ver a docstring do modelo),
    sob `FOR UPDATE`: a segunda retomada concorrente espera a primeira commitar e então
    enxerga `concluido_em` preenchido.
    A trava vale até o próximo commit: quem commitar no meio (ex.: `absorb_lead`) deve retomá-la
    com `_buscar(..., travar=True)` e reler `concluido_em` antes de escrever.
    **NÃO commita**: a reivindicação só fica visível para as outras requisições junto com o
    primeiro commit de quem chamou.
    """
    existente = _buscar(db, chave=chave, travar=True)
    if existente is not None:
        return None if existente.concluido_em is not None else existente
    novo = LeadIngestRecord(
        tenant_id=tenant_id, chave_idempotencia=chave, evento=evento,
        ocorrido_em=ocorrido_em, payload=payload,
    )
    db.add(novo)
    try:
        db.flush()
    except IntegrityError:
        # Outra requisição com a MESMA chave inseriu primeiro. No Postgres, este flush ficou
        # parado no índice único até ela commitar — e então falhou. Quem chegou depois não
        # tem efeito nenhum: responde "já processado".
        db.rollback()
        return None
    return novo


def concluir(
    registro: LeadIngestRecord, *, client_id: str, tags_descartadas: list[str]
) -> None:
    """Marca como processada. **NÃO commita**: entra no commit das tags, do fato e da etapa."""
    registro.client_id = client_id
    registro.tags_descartadas = list(tags_descartadas)
    registro.concluido_em = datetime.now(UTC)


def contato_da_chave(db: Session, *, chave: str) -> str | None:
    existente = _buscar(db, chave=chave)
    return existente.client_id if existente is not None else None
