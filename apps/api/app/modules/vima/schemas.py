"""Contrato HTTP do briefing.

`linhas` sai junto com `texto` de propósito. O texto é a narração — boa para ler, ruim para
programar contra; as linhas são o payload determinístico que a IA apenas reescreveu. A tela da
Onda 4 renderiza o texto, e um cliente que precise agir sobre um item (marcar como resolvido,
abrir o contato) tem a estrutura sem ter que fazer parsing de prosa.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.modules.vima.models import Briefing


class LinhaOut(BaseModel):
    secao: str
    module: str
    texto: str


class BriefingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference_date: date
    texto: str
    # Se a narração veio da IA ou do template. A UI usa para rotular o rastro (Regra de Ouro
    # nº 3) — sem chave configurada o briefing sai íntegro, e dizer "escrito pela IA" ali seria
    # falso.
    por_ia: bool
    # `True` = nada ACONTECEU na janela. Pendência e tendência podem existir mesmo assim.
    vazio: bool
    excedente: int
    linhas: list[LinhaOut]
    read_at: datetime | None
    created_at: datetime


def to_out(briefing: Briefing) -> BriefingOut:
    dados = _payload(briefing)
    return BriefingOut(
        id=briefing.id,
        reference_date=briefing.reference_date,
        texto=briefing.texto,
        por_ia=briefing.por_ia,
        vazio=briefing.vazio,
        excedente=int(dados.get("excedente") or 0),
        linhas=[LinhaOut(**linha) for linha in dados.get("linhas") or []],
        read_at=briefing.read_at,
        created_at=briefing.created_at,
    )


def _payload(briefing: Briefing) -> dict:
    """Payload ilegível não derruba a leitura: o texto narrado continua entregue."""
    try:
        dados = json.loads(briefing.payload)
    except (TypeError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}
