"""Orquestra o loop de pergunta-e-resposta da Vima (`POST /vima/pergunta`).

Sem persistência: o histórico da conversa vive só no que o front reenvia a cada pergunta (ver
spec `docs/superpowers/specs/2026-08-28-vima-pergunte-design.md`). Um contexto reversível mascara
a pergunta e CADA resultado de ferramenta antes da Claude; argumentos e resposta final são
resolvidos somente dentro da nossa infraestrutura (Regra de Ouro nº 2).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit
from app.core.anonymizer import AnonymizationContext
from app.core.tenancy import CurrentUser
from app.modules.auth.models import Tenant, User
from app.modules.crm import service as crm_service
from app.modules.vima import tools

_SYSTEM = (
    "Você é a Vima, a assistente do dono deste negócio dentro do e1p. Responda perguntas sobre "
    "o negócio SOMENTE com base no que as ferramentas devolverem — nunca invente um número, uma "
    "data ou um nome. Se não tiver uma ferramenta que responda a pergunta, diga isso claramente "
    "em vez de adivinhar. Responda em português do Brasil, direto e sem rodeios.\n\n"
    "Antes de criar, cancelar ou remarcar um compromisso na agenda, resuma em texto o que você "
    "entendeu (o quê, quando, com quem) e peça confirmação explícita do dono. SÓ chame "
    "criar_compromisso, cancelar_compromisso ou remarcar_compromisso com confirmado=true depois "
    "que o dono confirmar claramente numa mensagem seguinte — nunca no mesmo turno em que ele "
    "pediu. Para cancelar ou remarcar, use consultar_agenda primeiro para achar o compromisso "
    "certo; se houver mais de um compatível, pergunte qual antes de agir."
)

_NAME_CONNECTORS = {"da", "das", "de", "do", "dos", "e"}


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
    privacy = AnonymizationContext()
    texto_inicial = _com_historico(pergunta, historico)
    texto_inicial = privacy.mask_literals(
        texto_inicial, _nomes_conhecidos(db, user), label="PESSOA"
    )
    seguro = privacy.mask(texto_inicial)

    def _executar(nome: str, entrada: dict) -> str:
        # A entrada da ferramenta chega da Claude ainda MASCARADA (o texto que ela viu é
        # `seguro`) — sem desmascarar aqui, um placeholder como `[FONE_1]` num título/local de
        # `criar_compromisso` seria PERSISTIDO PERMANENTEMENTE em `agenda_events`, ao contrário
        # da resposta final (que já é desmascarada abaixo). Mesmo `mapa` usado para a resposta.
        entrada_real = privacy.unmask(entrada)
        resultado_real = tools.executar(db, user, nome, entrada_real)
        return privacy.mask_tool_result(resultado_real)

    resultado = ai.complete_with_tools(
        db=db, tenant_id=user.tenant_id, task="vima.pergunta", system=_SYSTEM,
        user_message=seguro, tools=definicoes, executar_ferramenta=_executar,
        user_id=user.user_id,
    )
    texto = privacy.unmask(resultado.text)
    audit.record(
        db, tenant_id=user.tenant_id, actor="ai", action="vima.pergunta.respondida",
        target="", is_ai=True,
    )
    return Resposta(texto=texto, por_ia=True)


def _nomes_conhecidos(db: Session, user: CurrentUser) -> list[str]:
    """Vocabulário determinístico para tirar nomes da pergunta antes da primeira chamada.

    NER não oferece garantia suficiente para privacidade. Os nomes já conhecidos pelo produto
    vêm das tabelas locais e a RLS limita os clientes ao tenant da sessão.
    """
    nomes: list[str] = []
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is not None:
        nomes.append(tenant.legal_name)
    nomes.extend(db.scalars(select(User.name).where(User.tenant_id == user.tenant_id)).all())

    offset = 0
    while True:
        pagina = crm_service.list_clients(db, limit=500, offset=offset)
        nomes.extend(cliente.name for cliente in pagina)
        if len(pagina) < 500:
            break
        offset += len(pagina)

    # Também protege menções pelo primeiro/último nome ("fale com João"), sem mascarar
    # conectores portugueses que aparecem naturalmente em qualquer pergunta.
    componentes = {
        parte
        for nome in nomes
        for parte in nome.split()
        if len(parte) >= 3 and parte.casefold() not in _NAME_CONNECTORS
    }
    return nomes + list(componentes)


def _com_historico(pergunta: str, historico: list[Turno]) -> str:
    if not historico:
        return pergunta
    linhas = [f"{'Dono' if t.papel == 'usuario' else 'Vima'}: {t.texto}" for t in historico]
    linhas.append(f"Dono: {pergunta}")
    return "\n".join(linhas)
