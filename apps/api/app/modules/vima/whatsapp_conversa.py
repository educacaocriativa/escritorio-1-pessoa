"""Vima por WhatsApp: quando o dono manda mensagem pro PRÓPRIO número conectado (self-chat,
Evolution), essa mensagem vira pergunta à Vima em vez de virar mensagem de CRM — em TEXTO
(`responder`) ou em ÁUDIO transcrito (`responder_audio`).

Ver docs/superpowers/specs/2026-08-28-vima-canal-whatsapp-design.md (texto) e
docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md (voz).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import transcription, whatsapp
from app.core.phone import normalize_br
from app.modules.auth.models import User
from app.modules.vima import pergunta as pergunta_service
from app.modules.vima import scheduler

logger = logging.getLogger("e1p.vima")

# Poucos minutos — o suficiente para uma sequência natural de perguntas, curto o bastante para
# nunca virar "histórico permanente" (decisão da spec: zero persistência).
TTL_CONTEXTO_SEGUNDOS = 5 * 60
TTL_DEDUP_SEGUNDOS = 5 * 60

# Em processo — não sobrevive a reiniciar, não é compartilhado entre réplicas. Aceito para a
# escala atual (ver spec); Redis é o próximo passo se um dia isso incomodar de verdade.
_HISTORICO: dict[str, list[tuple[float, pergunta_service.Turno]]] = {}
_VISTAS: dict[str, float] = {}

# Última resposta que A PRÓPRIA VIMA mandou para cada telefone, por (texto, expira). A Evolution
# está inscrita em MESSAGES_UPSERT e ecoa de volta toda mensagem que o produto manda (mesmo
# mecanismo do eco em `whatsapp_inbox.service.ingest_webhook_payload`) — numa self-chat, esse eco
# tem `from_me=True` igual a uma pergunta real do dono, e chega com um `wa_message_id` NOVO
# (`_VISTAS` não pega, pois não é reentrega do MESMO evento). Sem esta guarda, o eco bate na
# mesma condição de roteamento e vira "pergunta nova": a Vima responde à própria resposta, que
# ecoa de novo, indefinidamente (achado ao vivo em produção, 2026-08-31).
_ULTIMAS_RESPOSTAS: dict[str, tuple[str, float]] = {}


@dataclass(frozen=True)
class Resultado:
    """O que de fato foi perguntado e respondido — `whatsapp_inbox.service.ingest_webhook_payload`
    usa isto pra gravar a troca em `whatsapp_messages` (a self-chat não passa pelo caminho normal
    de gravação, ver comentário lá). `None` em vez deste tipo significa "nada de novo aconteceu":
    reentrega do mesmo `wa_message_id`, eco da própria resposta da Vima, ou telefone sem usuário
    correspondente — nenhum desses é uma pergunta de verdade, e gravar criaria ruído ou duplicata
    na conversa."""

    pergunta: str
    resposta: str


def _chave(tenant_id: str, phone: str) -> str:
    return f"{tenant_id}:{normalize_br(phone) or phone}"


def _ja_processada(wa_message_id: str) -> bool:
    expira = _VISTAS.get(wa_message_id)
    return expira is not None and expira > time.monotonic()


def _marcar_processada(wa_message_id: str) -> None:
    _VISTAS[wa_message_id] = time.monotonic() + TTL_DEDUP_SEGUNDOS
    if len(_VISTAS) > 1000:  # limpeza oportunista — sem isso o dict cresce sem limite
        agora = time.monotonic()
        for chave in [k for k, exp in _VISTAS.items() if exp <= agora]:
            del _VISTAS[chave]


def _historico(chave: str) -> list[pergunta_service.Turno]:
    agora = time.monotonic()
    vivos = [(exp, t) for exp, t in _HISTORICO.get(chave, []) if exp > agora]
    _HISTORICO[chave] = vivos
    return [t for _, t in vivos]


def _guardar_turno(chave: str, papel: str, texto: str) -> None:
    expira = time.monotonic() + TTL_CONTEXTO_SEGUNDOS
    _HISTORICO.setdefault(chave, []).append(
        (expira, pergunta_service.Turno(papel=papel, texto=texto))
    )


def _e_eco_da_propria_resposta(chave: str, texto: str) -> bool:
    registrada = _ULTIMAS_RESPOSTAS.get(chave)
    if registrada is None:
        return False
    texto_anterior, expira = registrada
    return expira > time.monotonic() and texto_anterior == texto


def _marcar_resposta_enviada(chave: str, texto: str) -> None:
    _ULTIMAS_RESPOSTAS[chave] = (texto, time.monotonic() + TTL_DEDUP_SEGUNDOS)


def _usuario_do_telefone(db: Session, tenant_id: str, phone: str) -> User | None:
    """O mesmo casamento por telefone normalizado que `vima.scheduler.responder_optin` já faz
    para o toque no botão do briefing — reusa `scheduler.usuarios_ativos` (pública desde a
    tarefa anterior) em vez de reescrever a consulta pela terceira vez (a primeira é
    `whatsapp_inbox.service._e_telefone_da_equipe`, que fica como está: devolve só `bool` e
    não precisa da linha inteira)."""
    chave = normalize_br(phone)
    if chave is None:
        return None
    return next(
        (
            u for u in scheduler.usuarios_ativos(db, tenant_id)
            if u.phone and normalize_br(u.phone) == chave
        ),
        None,
    )


def responder(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, texto: str, profile,
) -> Resultado | None:
    """O dono perguntou algo em TEXTO na self-chat — responde pelo MESMO canal. Ver `_responder`
    para o mecanismo compartilhado com `responder_audio`."""
    return _responder(
        db, tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id, texto=texto,
        profile=profile,
    )


def responder_audio(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, audio_bytes: bytes,
    audio_mime_type: str, profile,
) -> Resultado | None:
    """O dono mandou uma NOTA DE VOZ na self-chat — transcreve (Groq) e segue o MESMO caminho de
    `responder`: a transcrição vira o `texto` que alimenta `pergunta.responder`, e a resposta
    final ECOA o que foi entendido (`🎤 "..."`), porque o dono nunca vê a transcrição em lugar
    nenhum — sem o eco, um erro de transcrição vira resposta certa pra pergunta errada, sem
    nenhuma pista do porquê. Ver docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md.

    Checa `_ja_processada` ANTES de transcrever — evita pagar a Groq de novo numa reentrega de
    webhook que a checagem de dentro de `_responder` também pegaria, só que depois do gasto.

    Resolve o usuário pelo telefone ANTES de transcrever — só para poder passar `user_id` ao
    ledger da Groq (`transcription.transcribe`); note que `_responder` resolve o MESMO usuário de
    novo logo em seguida (consulta duplicada, aceita deliberadamente: mais barata que restruturar
    a assinatura de `_responder` ou seus testes existentes). Se ninguém bater aqui, a transcrição
    ainda roda (só o ledger fica sem `user_id`) — quem desiste em silêncio por telefone sem
    usuário é `_responder`, não este ponto.

    Faz `db.commit()` logo após uma transcrição BEM-SUCEDIDA (antes de `_responder`) para isolar
    a cobrança da Groq — que já aconteceu e já custou dinheiro — de uma falha posterior em
    `pergunta.responder`: sem esse commit, o `db.rollback()` de dentro do except de `_responder`
    apagaria a linha do ledger já gravada por `transcribe()`, mesmo a chamada à Groq tendo
    genuinamente ocorrido. Seguro neste modelo de transação: o loop do webhook em
    `whatsapp_inbox/service.py` já commita POR MENSAGEM (ver comentário "CRÍTICO" lá), então um
    commit mais cedo dentro dessa mesma unidade de trabalho é só um subconjunto do que já
    acontece, não um risco novo.
    """
    if _ja_processada(wa_message_id):
        return None  # reentrega do webhook — já respondida (ou já falhou e já pedimos desculpa)

    user = _usuario_do_telefone(db, tenant_id, phone)
    transcrito = transcription.transcribe(
        db, tenant_id=tenant_id, audio_bytes=audio_bytes, mime_type=audio_mime_type,
        user_id=user.id if user else None,
    )
    if transcrito is None:
        _marcar_processada(wa_message_id)
        desculpa = "Não consegui entender o áudio — tenta de novo em instantes."
        whatsapp.send_text(to=phone, text=desculpa, profile=profile)
        # `pergunta` fica com um rótulo, não a transcrição — não há transcrição nenhuma pra
        # gravar (é justamente isso que falhou). Ainda assim vira uma linha na conversa: sem
        # ela, a desculpa apareceria sozinha, sem contexto do que a originou.
        return Resultado(pergunta="[áudio não reconhecido]", resposta=desculpa)

    db.commit()  # isola a cobrança da Groq (já ocorrida) de uma falha posterior em _responder

    return _responder(
        db, tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id, texto=transcrito.text,
        profile=profile, eco=f'🎤 "{transcrito.text}" — ',
    )


def _responder(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, texto: str, profile,
    eco: str = "",
) -> Resultado | None:
    """O mecanismo compartilhado por `responder` (texto) e `responder_audio` (voz, já
    transcrita): resolve o usuário, chama `pergunta.responder`, grava o turno no cache e manda a
    resposta pelo mesmo canal — com `eco` prefixado quando a pergunta veio de áudio.

    NÃO commita: roda dentro da transação-por-mensagem do `ingest`, que decide quando commitar
    (mesmo padrão de `vima.scheduler.responder_optin`).

    Nunca deixa uma falha muda: qualquer erro no meio do caminho ainda tenta mandar uma resposta
    de desculpa pelo mesmo canal — `whatsapp.send_text` nunca levanta (fire-and-forget por
    contrato), então essa tentativa é sempre segura.
    """
    if _ja_processada(wa_message_id):
        return None  # reentrega do webhook — já respondida
    _marcar_processada(wa_message_id)

    chave = _chave(tenant_id, phone)
    if _e_eco_da_propria_resposta(chave, texto):
        # O eco (ver `_ULTIMAS_RESPOSTAS`) da resposta que A PRÓPRIA VIMA acabou de mandar —
        # não é pergunta nova, e respondê-lo criaria um loop infinito de auto-resposta.
        logger.info(
            "[vima] eco da própria resposta ignorado: tenant=%s wa_message_id=%s",
            tenant_id, wa_message_id,
        )
        return None

    user = _usuario_do_telefone(db, tenant_id, phone)
    if user is None:
        # Defensivo: o chamador já confirmou que o telefone é de um usuário ativo
        # (`_e_telefone_da_equipe`), mas não há garantia atômica entre a checagem e aqui —
        # melhor desistir em silêncio do que estourar.
        logger.warning("[vima] self-chat sem usuário correspondente: tenant=%s", tenant_id)
        return None

    try:
        resposta = pergunta_service.responder(
            db, user=scheduler.como_ator(user), pergunta=texto, historico=_historico(chave),
        )
    except Exception:  # noqa: BLE001 — falha nunca fica muda (ver docstring)
        logger.exception("[vima] falha ao responder pergunta via WhatsApp self-chat")
        db.rollback()
        desculpa = "Não consegui responder agora — tenta de novo em instantes."
        whatsapp.send_text(to=phone, text=desculpa, profile=profile)
        return Resultado(pergunta=texto, resposta=desculpa)

    _guardar_turno(chave, "usuario", texto)
    _guardar_turno(chave, "vima", resposta.texto)
    resposta_final = f"{eco}{resposta.texto}"
    _marcar_resposta_enviada(chave, resposta_final)
    whatsapp.send_text(to=phone, text=resposta_final, profile=profile)
    logger.info(
        "[vima] self-chat respondida: tenant=%s wa_message_id=%s", tenant_id, wa_message_id,
    )
    return Resultado(pergunta=texto, resposta=resposta_final)
