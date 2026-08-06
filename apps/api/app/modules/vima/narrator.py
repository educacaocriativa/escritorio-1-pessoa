"""Narra o payload já composto. A IA entra SÓ AQUI e SÓ DEPOIS de tudo estar calculado.

Mesmo fluxo obrigatório de `financial_intelligence/ai_narrator.py`:
  1. Monta o texto-fonte a partir do `Payload`.
  2. `anonymizer.mask` — Regra de Ouro nº 2.
  3. `ai.complete`.
  4. `anonymizer.unmask` — os valores reais voltam LOCALMENTE, nunca no Claude.

Degradação graciosa: sem `ANTHROPIC_API_KEY` (ou em qualquer erro), devolve o MESMO payload
renderizado por template. O briefing continua íntegro, só deixa de ser conversado — e nesse
caso NÃO grava rastro de IA, porque não houve IA.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit
from app.core.anonymizer import anonymizer
from app.modules.vima.composer import (
    SECAO_ACONTECEU,
    SECAO_NUMEROS,
    SECAO_PENDENTE,
    Payload,
)

logger = logging.getLogger("e1p.vima")

_SYSTEM = (
    "Você é a Vima, assistente de um profissional autônomo brasileiro. "
    "Recebe um briefing JÁ CALCULADO por um motor determinístico, dividido em ACONTECEU, "
    "PENDENTE e NÚMEROS. Reescreva em português do Brasil, em tom direto e caloroso, "
    "como quem atualiza um sócio que acabou de acordar. No máximo 3 parágrafos curtos.\n"
    "REGRAS ABSOLUTAS: use SOMENTE os fatos, números, nomes e datas presentes no texto — "
    "NUNCA invente nada. Mantenha os marcadores entre colchetes (ex.: [FONE_1]) EXATAMENTE "
    "como estão. NUNCA sugira uma ação que não esteja no texto. NUNCA reordene por "
    "importância: a ordem recebida já é a ordem certa."
)


@dataclass(frozen=True)
class Narracao:
    texto: str
    por_ia: bool


def render_template(payload: Payload, nome_do_usuario: str) -> str:
    """O fallback. Mesmo conteúdo, sem prosa."""
    partes = [f"Bom dia, {nome_do_usuario}."]
    for secao in (SECAO_ACONTECEU, SECAO_PENDENTE, SECAO_NUMEROS):
        linhas = [linha for linha in payload.linhas if linha.secao == secao]
        if not linhas:
            continue
        partes.append(f"\n{secao}")
        partes.extend(f"  • {linha.texto}" for linha in linhas)
    if payload.excedente:
        partes.append(f"\n… e mais {payload.excedente} coisas antes disso.")
    return "\n".join(partes)


def narrar(
    db: Session, *, tenant_id: str, payload: Payload, nome_do_usuario: str
) -> Narracao:
    fonte = render_template(payload, nome_do_usuario)
    if not settings.anthropic_api_key:
        return Narracao(texto=fonte, por_ia=False)

    seguro, mapa = anonymizer.mask(fonte)
    try:
        resposta = ai.complete(system=_SYSTEM, user_message=seguro, max_tokens=1500)
    except Exception:  # noqa: BLE001 — a IA nunca derruba o briefing: cai no template.
        logger.exception("Narração da Vima falhou; caindo no template")
        return Narracao(texto=fonte, por_ia=False)

    texto = anonymizer.unmask(resposta.text, mapa)
    # Regra de Ouro nº 3: houve ação REAL de IA → grava o rastro. Sem commit: quem chama
    # decide o momento, e o rastro pertence à mesma transação que grava o briefing.
    audit.record(
        db, tenant_id=tenant_id, actor="ai", action="vima.briefing.narrado",
        target="", is_ai=True,
    )
    return Narracao(texto=texto, por_ia=True)
