"""Orquestra o loop de pergunta-e-resposta da Vima (`POST /vima/pergunta`).

Sem persistência: o histórico da conversa vive só no que o front reenvia a cada pergunta (ver
spec `docs/superpowers/specs/2026-08-28-vima-pergunte-design.md`). A pergunta do dono e os
resultados das ferramentas chegam à Claude SEM anonimização de nome — extensão explícita do
risco aceito pelo fundador em 2026-07-11 para o Diagnóstico Financeiro (CLAUDE.md §6.1). PII
ESTRUTURAL (CPF/CNPJ/e-mail/telefone) continua mascarada, como em qualquer outra chamada de IA
(Regra de Ouro nº 2) — só o texto INICIAL passa pelo anonimizador; os resultados de ferramenta
não são mascarados (decisão da spec).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit
from app.core.anonymizer import anonymizer
from app.core.tenancy import CurrentUser
from app.modules.vima import tools

_SYSTEM = (
    "Você é a Vima, a assistente do dono deste negócio dentro do e1p. Responda perguntas sobre "
    "o negócio SOMENTE com base no que as ferramentas devolverem — nunca invente um número, uma "
    "data ou um nome. Se não tiver uma ferramenta que responda a pergunta, diga isso claramente "
    "em vez de adivinhar. Responda em português do Brasil, direto e sem rodeios."
)


@dataclass
class Turno:
    papel: str  # "usuario" | "vima"
    texto: str


@dataclass
class Resposta:
    texto: str
    por_ia: bool


def responder(db: Session, *, user: CurrentUser, pergunta: str, historico: list[Turno]) -> Resposta:
    if not settings.anthropic_api_key:
        return Resposta(
            texto="A Vima está sem acesso à IA agora — pergunte de novo mais tarde.",
            por_ia=False,
        )

    definicoes = [f.definicao for f in tools.ferramentas_disponiveis(user)]
    seguro, mapa = anonymizer.mask(_com_historico(pergunta, historico))

    def _executar(nome: str, entrada: dict) -> str:
        return tools.executar(db, user, nome, entrada)

    resultado = ai.complete_with_tools(
        db=db, tenant_id=user.tenant_id, task="vima.pergunta", system=_SYSTEM,
        user_message=seguro, tools=definicoes, executar_ferramenta=_executar,
        user_id=user.user_id,
    )
    texto = anonymizer.unmask(resultado.text, mapa)
    audit.record(
        db, tenant_id=user.tenant_id, actor="ai", action="vima.pergunta.respondida",
        target="", is_ai=True,
    )
    return Resposta(texto=texto, por_ia=True)


def _com_historico(pergunta: str, historico: list[Turno]) -> str:
    if not historico:
        return pergunta
    linhas = [f"{'Dono' if t.papel == 'usuario' else 'Vima'}: {t.texto}" for t in historico]
    linhas.append(f"Dono: {pergunta}")
    return "\n".join(linhas)
