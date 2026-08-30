"""Transcrição de voz (Groq, Whisper) — segundo ponto único de acesso a um provedor de IA,
irmão de `core/ai.py` (Anthropic). A API de mensagens da Anthropic não aceita áudio como
entrada; transcrição exige um provedor de STT dedicado. Provedores diferentes, formas de
cobrança diferentes (segundos de áudio, não tokens) — misturar as duas chaves num módulo só
criaria acoplamento sem ganho. Ver
docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md.

REGRA: mesma obrigatoriedade do item 1 do docstring de `core/ai.py` — `db` e `tenant_id` são
OBRIGATÓRIOS, para que seja estruturalmente impossível chamar a Groq sem contabilizar (ledger
`ai_usage`, `provider='groq'`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai_usage

logger = logging.getLogger("e1p.transcription")

_MODELO = "whisper-large-v3"
_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

_EXT_POR_MIME = {
    "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/wav": ".wav",
}


def _nome_do_arquivo(mime_type: str) -> str:
    """A Groq espelha a API da OpenAI/Whisper, que infere o container do áudio pela EXTENSÃO do
    nome do arquivo — um nome sem extensão pode ser rejeitado. Notas de voz do WhatsApp via
    Baileys/Evolution são sempre `audio/ogg`; qualquer mime não reconhecido cai no mesmo default,
    porque é a extensão real do formato que quase sempre chega aqui."""
    base = (mime_type or "").split(";")[0].strip()
    return "audio" + _EXT_POR_MIME.get(base, ".ogg")


@dataclass
class TranscriptionResult:
    text: str
    audio_seconds: float


def _response_body(exc: Exception) -> str:
    """O corpo da resposta que a Groq devolveu junto com o erro — mesma disciplina de
    `core/whatsapp/providers/evolution.py::_response_body`: o status sozinho não diagnostica
    nada, o corpo geralmente já diz o motivo."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return "(sem resposta HTTP)"
    try:
        return resp.text[:400]
    except Exception:  # noqa: BLE001 — diagnóstico nunca pode virar a causa de outra falha
        return "(corpo ilegível)"


def transcribe(
    db: Session, *, tenant_id: str, audio_bytes: bytes, mime_type: str,
    user_id: str | None = None,
) -> TranscriptionResult | None:
    """Transcreve um áudio via Groq. **Nunca levanta** — devolve `None` em qualquer falha (sem
    `GROQ_API_KEY`, erro HTTP, erro de rede, transcrição vazia), para o chamador decidir a
    desculpa que manda ao dono. O áudio em si nunca é persistido — só esta chamada síncrona.
    """
    if not settings.groq_api_key:
        return None

    try:
        resp = httpx.post(
            _URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            files={
                "file": (
                    _nome_do_arquivo(mime_type), audio_bytes,
                    mime_type or "application/octet-stream",
                ),
            },
            data={"model": _MODELO, "response_format": "verbose_json"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        # A leitura do payload mora DENTRO do try de propósito: um 200 com corpo em formato
        # inesperado (não é dict, `duration` não é numérico) é falha de terceiro do mesmo jeito
        # que um erro HTTP — `.get` em algo que não é dict levanta AttributeError, `float()` em
        # algo não numérico levanta ValueError/TypeError, e a promessa "nunca levanta" da
        # assinatura não pode depender do corpo estar no formato certo.
        texto = (payload.get("text") or "").strip()
        duracao = payload.get("duration")
        if not texto or duracao is None:
            logger.warning(
                "[transcription] resposta 200 da Groq sem texto ou duração utilizável "
                "(texto=%r, duration=%r)", texto, duracao,
            )
            return None
        audio_seconds = float(duracao)
    except Exception as exc:  # noqa: BLE001 — provedor externo, nunca derruba quem chamou
        logger.exception(
            "[transcription] falha ao transcrever áudio via Groq (corpo: %s)",
            _response_body(exc),
        )
        return None

    ai_usage.record(
        db, tenant_id=tenant_id, task="vima.transcricao", model=_MODELO, provider="groq",
        audio_seconds=audio_seconds, user_id=user_id,
    )
    return TranscriptionResult(text=texto, audio_seconds=audio_seconds)
