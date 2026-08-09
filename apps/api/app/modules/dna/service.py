"""Escrita e leitura crua do DNA. A validação contra o catálogo mora aqui.

A coluna `value` é JSON frouxo de propósito — o formato é decidido pelo catálogo, e é aqui que
o catálogo é cobrado. Sem esta porta estreita, o JSON vira depósito de qualquer coisa e o
resolver quebra na leitura, longe de quem escreveu.

Este módulo NÃO é puro: carimba `answered_at` com o instante. Carimbar INSTANTE é legítimo;
derivar QUE DIA É HOJE é o que o gate de `test_fuso_do_tenant.py` proíbe — e essa derivação
mora em `cadencia.py`, que recebe `hoje` por parâmetro.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.dna import catalog
from app.modules.dna.models import DnaAnswer


class DnaError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def responder(
    db: Session,
    *,
    tenant_id: str,
    key: str,
    valor: Any,
    user_id: str | None,
    source: str,
) -> DnaAnswer:
    """Grava a resposta, validando contra o catálogo. Commita."""
    pergunta = _pergunta(key)
    _validar(pergunta, valor)
    return _gravar(db, tenant_id=tenant_id, key=key, valor=valor, user_id=user_id, source=source)


def pular(
    db: Session, *, tenant_id: str, key: str, user_id: str | None, source: str
) -> DnaAnswer:
    """Registra que o dono viu e pulou. `value` nulo é o registro — não é linha ausente."""
    _pergunta(key)
    return _gravar(db, tenant_id=tenant_id, key=key, valor=None, user_id=user_id, source=source)


def respostas(db: Session) -> dict[str, Any]:
    """Só o que foi de fato respondido. Puladas ficam de fora."""
    return {
        linha.question_key: linha.value
        for linha in db.scalars(select(DnaAnswer)).all()
        if linha.value is not None
    }


def linhas(db: Session) -> dict[str, DnaAnswer]:
    """Todas as linhas, inclusive as puladas — é o que a cadência precisa ver."""
    return {linha.question_key: linha for linha in db.scalars(select(DnaAnswer)).all()}


def _pergunta(key: str) -> catalog.Pergunta:
    pergunta = catalog.POR_KEY.get(key)
    if pergunta is None:
        raise DnaError(f"a pergunta '{key}' não existe no catálogo", status_code=404)
    return pergunta


def _validar(pergunta: catalog.Pergunta, valor: Any) -> None:
    if pergunta.formato == catalog.FORMATO_TEXTO:
        if not isinstance(valor, str):
            raise DnaError(f"'{pergunta.key}' espera texto")
        if len(valor) > catalog.MAX_TEXTO:
            raise DnaError(
                f"texto longo demais ({len(valor)} caracteres, máximo {catalog.MAX_TEXTO})"
            )
        return

    permitidos = {o.valor for o in pergunta.opcoes}

    if pergunta.formato == catalog.FORMATO_MULTIPLA:
        if not isinstance(valor, list):
            raise DnaError(f"'{pergunta.key}' espera uma lista")
        invalidos = [v for v in valor if v not in permitidos]
        if invalidos:
            raise DnaError(f"{invalidos} não está entre as opções de '{pergunta.key}'")
        return

    if valor not in permitidos:
        raise DnaError(f"'{valor}' não está entre as opções de '{pergunta.key}'")


def _gravar(
    db: Session, *, tenant_id: str, key: str, valor: Any, user_id: str | None, source: str
) -> DnaAnswer:
    """Upsert por `(tenant, pergunta)` — a unique constraint da migration é o que o garante."""
    linha = db.scalar(select(DnaAnswer).where(DnaAnswer.question_key == key))
    if linha is None:
        linha = DnaAnswer(tenant_id=tenant_id, question_key=key)
        db.add(linha)
    linha.value = valor
    linha.answered_at = datetime.now(UTC)
    linha.answered_by = user_id
    linha.source = source
    db.commit()
    db.refresh(linha)
    return linha
