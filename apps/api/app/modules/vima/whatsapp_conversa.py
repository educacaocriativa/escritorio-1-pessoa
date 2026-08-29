"""Vima por WhatsApp: quando o dono manda mensagem pro PRÓPRIO número conectado (self-chat,
Evolution), essa mensagem vira pergunta à Vima em vez de virar mensagem de CRM — em TEXTO
(`responder`) ou em ÁUDIO transcrito (`responder_audio`).

Ver docs/superpowers/specs/2026-08-28-vima-canal-whatsapp-design.md (texto) e
docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md (voz).
"""
from __future__ import annotations

import logging
import time

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
) -> None:
    """O dono perguntou algo em TEXTO na self-chat — responde pelo MESMO canal. Ver `_responder`
    para o mecanismo compartilhado com `responder_audio`."""
    _responder(
        db, tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id, texto=texto,
        profile=profile,
    )


def responder_audio(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, audio_bytes: bytes,
    audio_mime_type: str, profile,
) -> None:
    """O dono mandou uma NOTA DE VOZ na self-chat — transcreve (Groq) e segue o MESMO caminho de
    `responder`: a transcrição vira o `texto` que alimenta `pergunta.responder`, e a resposta
    final ECOA o que foi entendido (`🎤 "..."`), porque o dono nunca vê a transcrição em lugar
    nenhum — sem o eco, um erro de transcrição vira resposta certa pra pergunta errada, sem
    nenhuma pista do porquê. Ver docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md.

    Checa `_ja_processada` ANTES de transcrever — evita pagar a Groq de novo numa reentrega de
    webhook que a checagem de dentro de `_responder` também pegaria, só que depois do gasto.
    """
    if _ja_processada(wa_message_id):
        return  # reentrega do webhook — já respondida (ou já falhou e já pedimos desculpa)

    resultado = transcription.transcribe(
        db, tenant_id=tenant_id, audio_bytes=audio_bytes, mime_type=audio_mime_type,
    )
    if resultado is None:
        _marcar_processada(wa_message_id)
        whatsapp.send_text(
            to=phone, text="Não consegui entender o áudio — tenta de novo em instantes.",
            profile=profile,
        )
        return

    _responder(
        db, tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id, texto=resultado.text,
        profile=profile, eco=f'🎤 "{resultado.text}" — ',
    )


def _responder(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, texto: str, profile,
    eco: str = "",
) -> None:
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
        return  # reentrega do webhook — já respondida
    _marcar_processada(wa_message_id)

    user = _usuario_do_telefone(db, tenant_id, phone)
    if user is None:
        # Defensivo: o chamador já confirmou que o telefone é de um usuário ativo
        # (`_e_telefone_da_equipe`), mas não há garantia atômica entre a checagem e aqui —
        # melhor desistir em silêncio do que estourar.
        logger.warning("[vima] self-chat sem usuário correspondente: tenant=%s", tenant_id)
        return

    chave = _chave(tenant_id, phone)

    try:
        resultado = pergunta_service.responder(
            db, user=scheduler.como_ator(user), pergunta=texto, historico=_historico(chave),
        )
    except Exception:  # noqa: BLE001 — falha nunca fica muda (ver docstring)
        logger.exception("[vima] falha ao responder pergunta via WhatsApp self-chat")
        db.rollback()
        whatsapp.send_text(
            to=phone, text="Não consegui responder agora — tenta de novo em instantes.",
            profile=profile,
        )
        return

    _guardar_turno(chave, "usuario", texto)
    _guardar_turno(chave, "vima", resultado.texto)
    whatsapp.send_text(to=phone, text=f"{eco}{resultado.texto}", profile=profile)
